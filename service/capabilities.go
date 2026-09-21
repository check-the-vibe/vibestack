package service

import (
	"context"
	"encoding/json"
	"errors"
	"mime"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/check-the-vibe/vibestack/service/capabilities"
)

type AuditEvent struct {
	RequestID  string `json:"request_id"`
	InstanceID string `json:"instance_id"`
	Capability string `json:"capability"`
	Outcome    string `json:"outcome"`
	DurationMS int64  `json:"duration_ms"`
}

func (s *Server) registerCapabilities() error {
	// A missing projects mount is reported by the capability, not a false static
	// readiness failure. Runtime configuration supplies the actual /projects.
	if s.cfg.ProjectsRoot != "" {
		root, err := os.OpenRoot(s.cfg.ProjectsRoot)
		if err != nil {
			return errors.New("projects root unavailable")
		}
		s.projects = root
	}
	workspace, workspaceIDs := s.workspaceRegistrations()
	registrations := append(capabilities.Builtins(s.projects), workspace...)
	registrations = append(registrations, s.providerRegistrations()...)
	registrations = append(registrations, s.cfg.Capabilities...)
	var ids, routes []string
	for _, route := range s.operations {
		// Only the explicit compiled adapters share an existing operation ID.
		// User registrations still cannot replace either adapter or legacy IDs.
		if !workspaceIDs[route.ID] {
			ids = append(ids, route.ID)
		}
		routes = append(routes, route.Method+" "+route.Path)
	}
	registry, err := capabilities.New(registrations, ids, routes)
	if err != nil {
		return err
	}
	s.registry = registry
	s.mux.HandleFunc("POST /api/v1/capabilities/{capability}/invoke", s.authorized("", false, func(w http.ResponseWriter, r *http.Request) {
		s.invokeCapability(w, r, r.PathValue("capability"), false)
	}))
	s.mux.HandleFunc("GET /api/capabilities.openapi.json", s.authorized("", false, s.capabilitySchema))
	for _, definition := range registry.Definitions(Principal{Owner: true}) {
		// ServeMux detects overlapping method/path patterns. Return a startup error
		// instead of accepting a partial extension set or shadowing an old handler.
		if err := s.registerCapabilityRoute(definition); err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) registerCapabilityRoute(d capabilities.Definition) (err error) {
	defer func() {
		if recover() != nil {
			err = errors.New("capability conflicts with an existing route")
		}
	}()
	s.mux.HandleFunc(d.REST.Method+" "+d.REST.Path, s.authorized(d.ID, d.Permission == "owner", func(w http.ResponseWriter, r *http.Request) { s.invokeCapability(w, r, d.ID, true) }))
	return nil
}

func (s *Server) invokeCapability(w http.ResponseWriter, r *http.Request, id string, friendly bool) {
	started := time.Now()
	outcome := "internal_error"
	defer func() {
		if s.cfg.Audit != nil {
			name := id
			if !capabilityID.MatchString(name) {
				name = "unknown"
			}
			s.cfg.Audit(AuditEvent{RequestID: w.Header().Get("X-Request-ID"), InstanceID: s.cfg.Store.Identity, Capability: name, Outcome: outcome, DurationMS: time.Since(started).Milliseconds()})
		}
	}()
	fail := func(f *capabilities.Failure) {
		outcome = f.Code
		if f.Retryable() {
			w.Header().Set("Retry-After", "1")
		}
		s.failure(w, f.Status(), f.Code, f.Message(), f.Retryable())
	}
	entry, ok := s.registry.Entry(id)
	if !ok {
		fail(capabilities.Fail("not_found"))
		return
	}
	p := r.Context().Value(principalKey).(Principal)
	if !p.Allows(id, entry.Definition.Permission == "owner") {
		fail(capabilities.Fail("forbidden"))
		return
	}
	var raw json.RawMessage
	if friendly && (r.Method == "GET" || r.Method == "HEAD") {
		var failure *capabilities.Failure
		raw, failure = entry.HTTPInput(r)
		if failure != nil {
			fail(failure)
			return
		}
	} else {
		contentType, _, contentTypeErr := mime.ParseMediaType(r.Header.Get("Content-Type"))
		if r.URL.RawQuery != "" || contentTypeErr != nil || contentType != "application/json" {
			fail(capabilities.Fail("invalid_input"))
			return
		}
		data, err := readBounded(r.Body, entry.Definition.RequestBytes)
		if err != nil {
			fail(capabilities.Fail("limit_exceeded"))
			return
		}
		raw = data
	}
	encoded, failure := s.dispatchCapability(r.Context(), p, id, raw, w.Header().Get("X-Request-ID"))
	if failure != nil {
		fail(failure)
		return
	}
	outcome = "ok"
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(200)
	if r.Method != "HEAD" {
		w.Write(append(encoded, '\n'))
	}
}

// Both transports call this dispatcher. Adapters only decode their framing;
// grants, schemas, handler deadlines, capacity and output validation live here.
func (s *Server) dispatchCapability(ctx context.Context, p Principal, id string, raw json.RawMessage, requestID string) (json.RawMessage, *capabilities.Failure) {
	result, failure := s.registry.Execute(context.WithValue(ctx, workspaceRequestIDKey, requestID), p, id, raw)
	if failure != nil {
		return nil, failure
	}
	envelope := map[string]any{"instance_id": p.InstanceID, "request_id": requestID, "capability": id, "result": result}
	encoded, err := json.Marshal(envelope)
	if err != nil {
		return nil, capabilities.Fail("internal_error")
	}
	entry, _ := s.registry.Entry(id)
	if int64(len(encoded)) > entry.Definition.ResponseBytes {
		return nil, capabilities.Fail("limit_exceeded")
	}
	return encoded, nil
}

func capabilityEnvelopeSchema(d capabilities.Definition) map[string]any {
	return map[string]any{"type": "object", "additionalProperties": false,
		"required":   []string{"instance_id", "request_id", "capability", "result"},
		"properties": map[string]any{"instance_id": map[string]string{"type": "string"}, "request_id": map[string]string{"type": "string"}, "capability": map[string]string{"const": d.ID}, "result": d.OutputSchema}}
}

func (s *Server) capabilityCatalog(w http.ResponseWriter, r *http.Request) {
	p := r.Context().Value(principalKey).(Principal)
	list := []map[string]any{}
	for _, definition := range s.registry.Definitions(p) {
		state, next := "unavailable", "This capability's policy excludes MCP; use its authorized REST route."
		if workspaceMCPEnabled(definition) {
			state, next = "implemented", "Call the named MCP tool or the REST invocation route."
		}
		list = append(list, map[string]any{"id": definition.ID, "definition": definition, "rest": "implemented", "web": "implemented", "cli": "implemented", "cli_command": "capability call " + definition.ID + " --input FILE", "mcp": state, "next_action": next})
	}
	for _, route := range s.operations {
		if _, registered := s.registry.Entry(route.ID); registered {
			continue
		}
		if p.Allows(route.ID, route.Owner) {
			list = append(list, map[string]any{"id": route.ID, "method": route.Method, "path": route.Path, "rest": "implemented", "web": "implemented", "mcp": "unavailable", "next_action": "Use the authenticated compatibility route; generic invocation is not registered for this legacy operation yet."})
		}
	}
	s.json(w, 200, map[string]any{"instance_id": s.cfg.Store.Identity, "capabilities": list})
}

func (s *Server) capabilitySchema(w http.ResponseWriter, r *http.Request) {
	p := r.Context().Value(principalKey).(Principal)
	paths := map[string]any{}
	for _, d := range s.registry.Definitions(p) {
		operation := map[string]any{"operationId": d.ID, "description": d.Description, "security": []any{map[string]any{"workspaceBearer": []any{}}}, "responses": map[string]any{"200": map[string]any{"description": "Capability envelope", "content": map[string]any{"application/json": map[string]any{"schema": capabilityEnvelopeSchema(d)}}}}}
		if d.REST.Method == "GET" || d.REST.Method == "HEAD" {
			var schema struct {
				Properties map[string]json.RawMessage `json:"properties"`
				Required   []string                   `json:"required"`
			}
			json.Unmarshal(d.InputSchema, &schema)
			params := []any{}
			for name, field := range schema.Properties {
				required := false
				for _, key := range schema.Required {
					required = required || name == key
				}
				params = append(params, map[string]any{"name": name, "in": "query", "required": required, "schema": field})
			}
			operation["parameters"] = params
		} else {
			operation["requestBody"] = map[string]any{"required": true, "content": map[string]any{"application/json": map[string]any{"schema": d.InputSchema}}}
		}
		methods, ok := paths[d.REST.Path].(map[string]any)
		if !ok {
			methods = map[string]any{}
			paths[d.REST.Path] = methods
		}
		methods[strings.ToLower(d.REST.Method)] = operation
	}
	s.json(w, 200, map[string]any{"openapi": "3.1.0", "info": map[string]string{"title": "VibeStack registered capabilities", "version": "1"}, "paths": paths, "components": map[string]any{"securitySchemes": map[string]any{"workspaceBearer": map[string]string{"type": "http", "scheme": "bearer"}}}})
}
