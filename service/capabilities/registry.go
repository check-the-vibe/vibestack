// Package capabilities defines trusted, compiled workspace extensions. It has
// no HTTP listener, credential issuer, dynamic loader or independent identity.
package capabilities

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"reflect"
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/check-the-vibe/vibestack/contracts"
	"github.com/google/jsonschema-go/jsonschema"
)

type Principal interface {
	Allows(id string, owner bool) bool
}
type Handler func(context.Context, Principal, json.RawMessage) (any, error)
type Definition struct {
	ContractVersion int             `json:"contract_version"`
	ID              string          `json:"id"`
	Description     string          `json:"description"`
	Permission      string          `json:"permission"`
	Effect          string          `json:"effect"`
	Retry           string          `json:"retry"`
	TimeoutMS       int             `json:"timeout_ms"`
	RequestBytes    int64           `json:"request_bytes"`
	ResponseBytes   int64           `json:"response_bytes"`
	InputSchema     json.RawMessage `json:"input_schema"`
	OutputSchema    json.RawMessage `json:"output_schema"`
	REST            struct {
		Method string `json:"method"`
		Path   string `json:"path"`
	} `json:"rest"`
	MCPPolicy string `json:"mcp_policy"`
}
type Registration struct {
	Definition json.RawMessage
	Handle     Handler
}
type Entry struct {
	Definition    Definition
	input, output *jsonschema.Resolved
	handle        Handler
}
type Registry struct {
	entries map[string]*Entry
	slots   chan struct{}
}

type Failure struct{ Code string }

func (f *Failure) Error() string { return f.Message() }
func Fail(code string) *Failure {
	switch code {
	case "invalid_input", "forbidden", "not_found", "limit_exceeded", "busy", "timeout", "cancelled", "unavailable", "precondition_failed", "conflict":
		return &Failure{code}
	default:
		return &Failure{"internal_error"}
	}
}
func (f *Failure) Status() int {
	switch f.Code {
	case "invalid_input":
		return 400
	case "forbidden":
		return 403
	case "not_found":
		return 404
	case "precondition_failed":
		return 412
	case "conflict":
		return 409
	case "limit_exceeded":
		return 413
	case "busy":
		return 429
	case "unavailable":
		return 503
	case "timeout":
		return 504
	case "cancelled":
		return 408
	default:
		return 500
	}
}
func (f *Failure) Message() string {
	switch f.Code {
	case "invalid_input":
		return "Input does not match the capability schema."
	case "forbidden":
		return "This capability requires a different grant."
	case "not_found":
		return "The requested capability or resource is unavailable."
	case "precondition_failed":
		return "The resource changed; inspect it before retrying."
	case "conflict":
		return "The operation conflicts with current workspace state; inspect it before retrying."
	case "limit_exceeded":
		return "The declared request or result limit was exceeded."
	case "busy":
		return "The dispatcher is at capacity; no handler was started."
	case "unavailable":
		return "A required local service is unavailable; inspect state before retrying."
	case "timeout":
		return "The deadline expired; inspect state before retrying a mutation."
	case "cancelled":
		return "The request ended; inspect state before retrying a mutation."
	default:
		return "The capability could not return a valid result."
	}
}
func (f *Failure) Retryable() bool { return f.Code == "busy" }

// ResolveSchema never loads a remote schema. It is shared by the definition,
// dispatcher and MCP adapters so registration fails before accepting traffic.
func ResolveSchema(raw []byte) (*jsonschema.Resolved, error) {
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil, err
	}
	if err := inspectSchema(value, 0); err != nil {
		return nil, err
	}
	var schema jsonschema.Schema
	if err := json.Unmarshal(raw, &schema); err != nil {
		return nil, err
	}
	return schema.Resolve(&jsonschema.ResolveOptions{ValidateDefaults: true})
}
func inspectSchema(value any, depth int) error {
	if depth > 32 {
		return errors.New("schema nesting exceeds 32")
	}
	switch v := value.(type) {
	case map[string]any:
		for k, child := range v {
			if k == "$ref" || k == "$dynamicRef" {
				ref, ok := child.(string)
				if !ok || !strings.HasPrefix(ref, "#") {
					return errors.New("schema references must be local")
				}
			}
			if err := inspectSchema(child, depth+1); err != nil {
				return err
			}
		}
	case []any:
		for _, child := range v {
			if err := inspectSchema(child, depth+1); err != nil {
				return err
			}
		}
	}
	return nil
}

var routePath = regexp.MustCompile(`^/api/v1/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$`)

func New(registrations []Registration, reservedIDs []string, reservedRoutes []string) (*Registry, error) {
	if len(registrations) > 128 {
		return nil, errors.New("at most 128 capabilities may be registered")
	}
	metadataBytes := 0
	for _, registration := range registrations {
		metadataBytes += len(registration.Definition)
	}
	if metadataBytes > 1<<20 {
		return nil, errors.New("combined capability definitions exceed 1 MiB")
	}
	metadata, err := ResolveSchema(contracts.CapabilityDefinition)
	if err != nil {
		return nil, errors.New("capability contract is invalid")
	}
	r := &Registry{entries: map[string]*Entry{}, slots: make(chan struct{}, 32)}
	reserved := http.NewServeMux()
	ids, routes := map[string]bool{}, map[string]bool{}
	for _, id := range reservedIDs {
		ids[id] = true
	}
	for _, route := range reservedRoutes {
		routes[route] = true
		reserved.HandleFunc(strings.ReplaceAll(route, "{path}", "{path...}"), func(http.ResponseWriter, *http.Request) {})
	}
	for _, registration := range registrations {
		if len(registration.Definition) > 128<<10 || registration.Handle == nil {
			return nil, errors.New("capability definition or handler missing")
		}
		var value any
		if json.Unmarshal(registration.Definition, &value) != nil || metadata.Validate(value) != nil {
			return nil, errors.New("invalid capability metadata")
		}
		var d Definition
		if json.Unmarshal(registration.Definition, &d) != nil {
			return nil, errors.New("invalid capability definition")
		}
		if ids[d.ID] {
			return nil, fmt.Errorf("duplicate or reserved capability ID: %s", d.ID)
		}
		// Custom routes are literal JSON operations. Parameter/raw aliases are
		// implemented by explicit compatibility adapters, never inferred from input.
		if !routePath.MatchString(d.REST.Path) || d.REST.Path == "/api/v1/capabilities" || strings.HasPrefix(d.REST.Path, "/api/v1/capabilities/") {
			return nil, fmt.Errorf("reserved or non-literal capability route: %s", d.ID)
		}
		pattern := d.REST.Method + " " + d.REST.Path
		_, reservedPattern := reserved.Handler(&http.Request{Method: d.REST.Method, URL: &url.URL{Path: d.REST.Path}})
		if routes[pattern] || reservedPattern != "" {
			return nil, fmt.Errorf("duplicate or reserved capability route: %s", d.ID)
		}
		input, err := ResolveSchema(d.InputSchema)
		if err != nil {
			return nil, fmt.Errorf("invalid input schema: %s", d.ID)
		}
		var inputObject map[string]json.RawMessage
		json.Unmarshal(d.InputSchema, &inputObject)
		if _, ok := inputObject["additionalProperties"]; !ok {
			return nil, fmt.Errorf("declare unknown-field policy: %s", d.ID)
		}
		if d.REST.Method == "GET" || d.REST.Method == "HEAD" {
			if d.Effect != "read" {
				return nil, fmt.Errorf("safe HTTP methods require a read capability: %s", d.ID)
			}
			var query struct {
				Properties map[string]struct {
					Type string `json:"type"`
				} `json:"properties"`
			}
			if json.Unmarshal(d.InputSchema, &query) != nil {
				return nil, fmt.Errorf("query properties must declare scalar types: %s", d.ID)
			}
			for _, field := range query.Properties {
				switch field.Type {
				case "string", "boolean", "integer", "number":
				default:
					return nil, fmt.Errorf("query properties must declare scalar types: %s", d.ID)
				}
			}
		}
		output, err := ResolveSchema(d.OutputSchema)
		if err != nil {
			return nil, fmt.Errorf("invalid output schema: %s", d.ID)
		}
		if explicitObjectPolicies(input.Schema()) != nil || explicitObjectPolicies(output.Schema()) != nil {
			return nil, fmt.Errorf("every object must declare its unknown-field policy: %s", d.ID)
		}
		ids[d.ID], routes[pattern] = true, true
		r.entries[d.ID] = &Entry{Definition: d, input: input, output: output, handle: registration.Handle}
	}
	return r, nil
}

func explicitObjectPolicies(schema *jsonschema.Schema) error {
	if schema == nil {
		return nil
	}
	if (schema.Type == "object" || slices.Contains(schema.Types, "object")) && schema.AdditionalProperties == nil && schema.UnevaluatedProperties == nil {
		return errors.New("object schema has no unknown-field policy")
	}
	// Traverse schema-typed fields only. Examples/defaults/const values are data,
	// even when their JSON contains a property called "type".
	fields := reflect.ValueOf(schema).Elem()
	for i := 0; i < fields.NumField(); i++ {
		switch child := fields.Field(i).Interface().(type) {
		case *jsonschema.Schema:
			if err := explicitObjectPolicies(child); err != nil {
				return err
			}
		case []*jsonschema.Schema:
			for _, item := range child {
				if err := explicitObjectPolicies(item); err != nil {
					return err
				}
			}
		case map[string]*jsonschema.Schema:
			for _, item := range child {
				if err := explicitObjectPolicies(item); err != nil {
					return err
				}
			}
		}
	}
	return nil
}

func (r *Registry) Entry(id string) (*Entry, bool) { e, ok := r.entries[id]; return e, ok }
func (r *Registry) Definitions(p Principal) []Definition {
	out := []Definition{}
	for _, e := range r.entries {
		if p != nil && p.Allows(e.Definition.ID, e.Definition.Permission == "owner") {
			out = append(out, e.Definition)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// Execute invokes the handler at most once. The capacity slot remains occupied
// until even a non-cooperative trusted handler exits, so timeouts cannot spawn
// unbounded background work. Mutations are never replayed by this dispatcher.
func (r *Registry) Execute(ctx context.Context, p Principal, id string, raw json.RawMessage) (json.RawMessage, *Failure) {
	e, ok := r.entries[id]
	if !ok {
		return nil, Fail("not_found")
	}
	if p == nil || !p.Allows(id, e.Definition.Permission == "owner") {
		return nil, Fail("forbidden")
	}
	if int64(len(raw)) > e.Definition.RequestBytes {
		return nil, Fail("limit_exceeded")
	}
	var input any
	if json.Unmarshal(raw, &input) != nil || jsonDepth(input, 0) > 32 || e.input.Validate(input) != nil {
		return nil, Fail("invalid_input")
	}
	if ctx.Err() != nil {
		return nil, Fail("cancelled")
	}
	select {
	case r.slots <- struct{}{}:
	default:
		return nil, Fail("busy")
	}
	ctx, cancel := context.WithTimeout(ctx, time.Duration(e.Definition.TimeoutMS)*time.Millisecond)
	defer cancel()
	type outcome struct {
		data    json.RawMessage
		failure *Failure
	}
	done := make(chan outcome, 1)
	go func() {
		defer func() { <-r.slots }()
		result := outcome{}
		defer func() {
			if recover() != nil {
				result = outcome{failure: Fail("internal_error")}
			}
			done <- result
		}()
		value, err := e.handle(ctx, p, append(json.RawMessage(nil), raw...))
		if err != nil {
			var failure *Failure
			if errors.As(err, &failure) {
				result.failure = Fail(failure.Code)
			} else {
				result.failure = Fail("internal_error")
			}
			return
		}
		encoded, err := json.Marshal(value)
		if err != nil {
			result.failure = Fail("internal_error")
			return
		}
		if int64(len(encoded)) > e.Definition.ResponseBytes {
			result.failure = Fail("limit_exceeded")
			return
		}
		var normalized any
		if json.Unmarshal(encoded, &normalized) != nil || jsonDepth(normalized, 0) > 32 || e.output.Validate(normalized) != nil {
			result.failure = Fail("internal_error")
			return
		}
		result.data = encoded
	}()
	select {
	case <-ctx.Done():
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return nil, Fail("timeout")
		}
		return nil, Fail("cancelled")
	case result := <-done:
		if ctx.Err() != nil {
			if errors.Is(ctx.Err(), context.DeadlineExceeded) {
				return nil, Fail("timeout")
			}
			return nil, Fail("cancelled")
		}
		return result.data, result.failure
	}
}
func jsonDepth(value any, depth int) int {
	if depth > 32 {
		return depth
	}
	max := depth
	switch v := value.(type) {
	case map[string]any:
		for _, c := range v {
			if n := jsonDepth(c, depth+1); n > max {
				max = n
			}
		}
	case []any:
		for _, c := range v {
			if n := jsonDepth(c, depth+1); n > max {
				max = n
			}
		}
	}
	return max
}

// HTTPInput maps a literal friendly GET/HEAD query to its declared scalar
// properties. Other methods carry the same JSON object as the generic POST.
func (e *Entry) HTTPInput(req *http.Request) (json.RawMessage, *Failure) {
	if req.Method != http.MethodGet && req.Method != http.MethodHead {
		return nil, nil
	}
	if req.ContentLength != 0 {
		return nil, Fail("invalid_input")
	}
	var schema struct {
		Properties map[string]struct {
			Type string `json:"type"`
		} `json:"properties"`
	}
	if json.Unmarshal(e.Definition.InputSchema, &schema) != nil {
		return nil, Fail("internal_error")
	}
	result := map[string]any{}
	query, err := url.ParseQuery(req.URL.RawQuery)
	if err != nil {
		return nil, Fail("invalid_input")
	}
	for key, values := range query {
		field, ok := schema.Properties[key]
		if !ok || len(values) != 1 {
			return nil, Fail("invalid_input")
		}
		if field.Type == "string" {
			result[key] = values[0]
			continue
		}
		if field.Type != "boolean" && field.Type != "integer" && field.Type != "number" {
			return nil, Fail("invalid_input")
		}
		var value any
		if err = json.Unmarshal([]byte(values[0]), &value); err != nil {
			return nil, Fail("invalid_input")
		}
		result[key] = value
	}
	raw, err := json.Marshal(result)
	if err != nil {
		return nil, Fail("invalid_input")
	}
	return raw, nil
}
