package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type emptyInput struct{}
type instanceInput struct {
	InstanceID string `json:"instance_id" jsonschema:"Required desktop ID"`
}
type operationInput struct {
	OperationID string `json:"operation_id"`
}
type createInput struct {
	CreateRequest
	IdempotencyKey string `json:"idempotency_key" jsonschema:"Stable retry key for this provisioning request"`
}
type actionInput struct {
	InstanceID string `json:"instance_id"`
	Action     string `json:"action" jsonschema:"start, stop, restart, or remove (retains storage)"`
}
type commandInput struct {
	InstanceID     string   `json:"instance_id"`
	Argv           []string `json:"argv"`
	Cwd            string   `json:"cwd,omitempty"`
	Root           string   `json:"root,omitempty" jsonschema:"projects or desktop; defaults to projects"`
	TimeoutSeconds int      `json:"timeout_seconds,omitempty"`
}
type jobInput struct {
	InstanceID string `json:"instance_id"`
	JobID      string `json:"job_id"`
}
type outputInput struct {
	InstanceID string `json:"instance_id"`
	JobID      string `json:"job_id"`
	Stream     string `json:"stream" jsonschema:"stdout or stderr"`
	Cursor     int64  `json:"cursor,omitempty"`
}

// The SDK's localhost check cannot recognize a loopback Tailscale reverse
// proxy. Our outer handler validates the exact public/listen Host and Origin
// before principal resolution or MCP handling, independent of proxy headers.
func (s *Server) mcpHandler() http.Handler {
	return mcp.NewStreamableHTTPHandler(func(r *http.Request) *mcp.Server {
		p, ok := r.Context().Value(principalKey{}).(principal)
		if !ok {
			return nil
		}
		server := mcp.NewServer(&mcp.Implementation{Name: "vibestack-runner", Version: api.Version}, nil)
		mcpTool(server, s, p, "host_inspect", "Inspect host capacity, approved templates, desktops and storage.", func(v emptyInput) (string, string, any, string, error) { return "GET", APIRoot + "/host", nil, "", nil })
		mcpTool(server, s, p, "templates_list", "List approved templates and broker limits.", func(v emptyInput) (string, string, any, string, error) { return "GET", APIRoot, nil, "", nil })
		mcpTool(server, s, p, "instances_list", "List accessible desktops, password status and human setup URLs.", func(v emptyInput) (string, string, any, string, error) {
			return "GET", APIRoot + "/instances", nil, "", nil
		})
		mcpTool(server, s, p, "instance_inspect", "Inspect one desktop. Linux credentials are configured by a human, outside MCP.", func(v instanceInput) (string, string, any, string, error) {
			return "GET", instancePath(v.InstanceID), nil, "", validMCPID(v.InstanceID)
		})
		mcpTool(server, s, p, "instance_create", "Provision an approved desktop; returns a durable operation ID. Poll operation_get. Never submit passwords.", func(v createInput) (string, string, any, string, error) {
			return "POST", APIRoot + "/instances", v.CreateRequest, v.IdempotencyKey, nil
		})
		mcpTool(server, s, p, "instance_action", "Start, stop, restart or remove a desktop. Returns a durable operation ID; removal retains volumes.", func(v actionInput) (string, string, any, string, error) {
			if v.Action != "start" && v.Action != "stop" && v.Action != "restart" && v.Action != "remove" {
				return "", "", nil, "", errors.New("unsupported lifecycle action")
			}
			return "POST", instancePath(v.InstanceID) + "/" + v.Action, map[string]any{}, "", validMCPID(v.InstanceID)
		})
		mcpTool(server, s, p, "operation_get", "Poll a durable provisioning or lifecycle operation.", func(v operationInput) (string, string, any, string, error) {
			return "GET", APIRoot + "/operations/" + url.PathEscape(v.OperationID), nil, "", validMCPID(v.OperationID)
		})
		mcpTool(server, s, p, "workspace_command", "Submit argv to a selected desktop; returns a durable job ID. Poll workspace_job.", func(v commandInput) (string, string, any, string, error) {
			if v.Root == "" {
				v.Root = "projects"
			}
			if v.TimeoutSeconds == 0 {
				v.TimeoutSeconds = 30
			}
			return "POST", instancePath(v.InstanceID) + "/workspace" + api.WorkspaceAPI + "/commands", map[string]any{"argv": v.Argv, "cwd": v.Cwd, "root": v.Root, "timeout_seconds": v.TimeoutSeconds}, "", validMCPID(v.InstanceID)
		})
		mcpTool(server, s, p, "workspace_job", "Inspect a job on the explicitly selected desktop.", func(v jobInput) (string, string, any, string, error) {
			if err := validMCPID(v.JobID); err != nil {
				return "", "", nil, "", err
			}
			return "GET", instancePath(v.InstanceID) + "/workspace" + api.WorkspaceAPI + "/jobs/" + v.JobID, nil, "", validMCPID(v.InstanceID)
		})
		mcpTool(server, s, p, "workspace_output", "Read one bounded page of job output; continue with next_cursor.", func(v outputInput) (string, string, any, string, error) {
			if validMCPID(v.JobID) != nil || (v.Stream != "stdout" && v.Stream != "stderr") || v.Cursor < 0 {
				return "", "", nil, "", errors.New("invalid job output selection")
			}
			return "GET", instancePath(v.InstanceID) + "/workspace" + api.WorkspaceAPI + "/jobs/" + v.JobID + "/output?stream=" + v.Stream + "&cursor=" + fmt.Sprint(v.Cursor), nil, "", validMCPID(v.InstanceID)
		})
		mcpTool(server, s, p, "workspace_screenshot", "Capture the selected desktop as a bounded PNG image.", func(v instanceInput) (string, string, any, string, error) {
			return "POST", instancePath(v.InstanceID) + "/workspace" + api.WorkspaceAPI + "/screenshot", map[string]any{}, "", validMCPID(v.InstanceID)
		})
		return server
	}, &mcp.StreamableHTTPOptions{Stateless: true, JSONResponse: true, DisableLocalhostProtection: true, MaxRequestBodyBytes: 1 << 20, PropagateRequestCancellation: true})
}
func instancePath(id string) string { return APIRoot + "/instances/" + url.PathEscape(id) }
func validMCPID(id string) error {
	if !idPattern.MatchString(id) {
		return errors.New("a valid explicit ID is required")
	}
	return nil
}

type boundedResponse struct {
	header   http.Header
	body     bytes.Buffer
	status   int
	overflow bool
}

func (w *boundedResponse) Header() http.Header    { return w.header }
func (w *boundedResponse) WriteHeader(status int) { w.status = status }
func (w *boundedResponse) Write(b []byte) (int, error) {
	if w.body.Len()+len(b) > 16<<20 {
		w.overflow = true
		return len(b), nil
	}
	return w.body.Write(b)
}

// All tools use the same REST dispatch and principal; there is no independent
// MCP ownership logic and no caller-selected proxy URL or Docker command.
func mcpTool[I any](server *mcp.Server, s *Server, p principal, name, description string, route func(I) (string, string, any, string, error)) {
	mcp.AddTool(server, &mcp.Tool{Name: name, Description: description}, func(ctx context.Context, req *mcp.CallToolRequest, input I) (*mcp.CallToolResult, any, error) {
		method, path, body, key, err := route(input)
		if err != nil {
			return nil, nil, err
		}
		raw, err := json.Marshal(body)
		if err != nil {
			return nil, nil, errors.New("invalid request")
		}
		if len(raw) > 1<<20 {
			return nil, nil, errors.New("request too large")
		}
		r, err := http.NewRequestWithContext(ctx, method, path, bytes.NewReader(raw))
		if err != nil {
			return nil, nil, errors.New("invalid request")
		}
		r.Header.Set("Content-Type", "application/json")
		if key != "" {
			r.Header.Set("Idempotency-Key", key)
		}
		w := &boundedResponse{header: make(http.Header), status: 200}
		if err := s.dispatch(w, r, requestID(r), p); err != nil {
			return nil, nil, errors.New(err.Message)
		}
		if w.overflow {
			return nil, nil, errors.New("result exceeds 16 MiB")
		}
		if w.status >= 400 {
			return nil, nil, fmt.Errorf("workspace request failed (HTTP %d)", w.status)
		}
		if strings.HasPrefix(w.header.Get("Content-Type"), "image/png") {
			if !bytes.HasPrefix(w.body.Bytes(), []byte("\x89PNG\r\n\x1a\n")) {
				return nil, nil, errors.New("invalid screenshot")
			}
			return &mcp.CallToolResult{Content: []mcp.Content{&mcp.ImageContent{Data: w.body.Bytes(), MIMEType: "image/png"}}}, nil, nil
		}
		var output any
		if json.Unmarshal(w.body.Bytes(), &output) != nil {
			return nil, nil, errors.New("invalid service response")
		}
		return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: w.body.String()}}, StructuredContent: output}, nil, nil
	})
}
