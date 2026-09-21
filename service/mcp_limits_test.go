package service

import (
	"context"
	"encoding/json"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/check-the-vibe/vibestack/internal/mcpwire"
	"github.com/check-the-vibe/vibestack/service/capabilities"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// These framing checks use the real HTTP handler in memory; no local backend
// or listening socket is needed before dispatch is admitted.
func framingService(t *testing.T, options ...func(*Config)) *Server {
	t.Helper()
	store, _ := testStore(t)
	cfg := Config{Store: store, StaticRoot: t.TempDir(), ProjectsRoot: t.TempDir(), AutomationURL: "http://127.0.0.1:1", ControlURL: "http://127.0.0.1:1", SetupURL: "http://127.0.0.1:1"}
	for _, option := range options {
		option(&cfg)
	}
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { server.Close() })
	return server
}

func TestWorkspaceMCPRejectsOversizedRPCIdentityBeforeDispatch(t *testing.T) {
	var dispatched atomic.Int32
	server := framingService(t, func(c *Config) { c.Audit = func(AuditEvent) { dispatched.Add(1) } })
	_, token := issue(t, server.cfg.Store, false, "project_summary")
	for _, id := range []string{strings.Repeat("x", 8192), strings.Repeat("<", 64)} {
		body := `{"jsonrpc":"2.0","id":"do-not-reflect-` + id + `","method":"tools/call","params":{"name":"project_summary","arguments":{"project":"missing"}}}`
		w := request(server, "POST", "/mcp", token, body, map[string]string{"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
		if w.Code != 413 || w.Body.Len() > 1024 || strings.Contains(w.Body.String(), "do-not-reflect") || !strings.Contains(w.Body.String(), "limit_exceeded") {
			t.Fatal("oversized RPC identity bypassed the framing budget")
		}
	}
	if dispatched.Load() != 0 {
		t.Fatal("invalid frame reached a capability")
	}
}

func TestWorkspaceMCPReservesSpaceForJSONRPCFraming(t *testing.T) {
	const id = "framing_budget"
	var definition map[string]any
	json.Unmarshal(capabilities.Builtins(nil)[0].Definition, &definition)
	definition["id"], definition["response_bytes"] = id, mcpwire.FrameBytes
	definition["rest"] = map[string]string{"method": "POST", "path": "/api/v1/framing-budget"}
	definition["output_schema"] = map[string]any{"type": "object", "additionalProperties": false, "required": []string{"payload"}, "properties": map[string]any{"payload": map[string]any{"type": "string", "maxLength": mcpwire.FrameBytes}}}
	d, _ := json.Marshal(definition)
	// Find a payload whose two copies fit the outer limit alone but leave too
	// little room for the permitted request ID and JSON-RPC wrapper.
	envelope, _ := json.Marshal(map[string]any{"instance_id": strings.Repeat("a", 32), "request_id": strings.Repeat("b", 32), "capability": id, "result": map[string]string{"payload": ""}})
	sample, _ := json.Marshal(&mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: string(envelope)}}, StructuredContent: json.RawMessage(envelope)})
	payload := strings.Repeat("x", (mcpwire.FrameBytes-128-len(sample))/2)
	server := framingService(t, func(c *Config) {
		c.Capabilities = []capabilities.Registration{{Definition: d, Handle: func(context.Context, capabilities.Principal, json.RawMessage) (any, error) {
			return map[string]string{"payload": payload}, nil
		}}}
	})
	_, token := issue(t, server.cfg.Store, false, id)
	body := `{"jsonrpc":"2.0","id":"` + strings.Repeat("z", mcpwire.IDBytes-2) + `","method":"tools/call","params":{"name":"` + id + `","arguments":{"project":"missing"}}}`
	w := request(server, "POST", "/mcp", token, body, map[string]string{"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
	if w.Code != 200 || w.Body.Len() > 2048 || !strings.Contains(w.Body.String(), `"isError":true`) || !strings.Contains(w.Body.String(), "limit_exceeded") {
		t.Fatal("serialized tool result did not reserve framing space")
	}
}
