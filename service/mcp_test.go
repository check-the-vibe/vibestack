package service

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/check-the-vibe/vibestack/service/capabilities"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type mcpAuthTransport struct{ token, instance string }

func (a mcpAuthTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	r = r.Clone(r.Context())
	r.Header.Set("Authorization", "Bearer "+a.token)
	r.Header.Set("X-VibeStack-Expected-Instance", a.instance)
	return http.DefaultTransport.RoundTrip(r)
}

func connectMCP(t *testing.T, server *Server, token string) *mcp.ClientSession {
	t.Helper()
	host := httptest.NewServer(server)
	t.Cleanup(host.Close)
	client := mcp.NewClient(&mcp.Implementation{Name: "vibestack-go-acceptance", Version: "1"}, nil)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	session, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: host.URL + "/mcp", MaxRetries: -1, DisableStandaloneSSE: true,
		HTTPClient: &http.Client{Timeout: 10 * time.Second, Transport: mcpAuthTransport{token, server.cfg.Store.Identity}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil)
	if err != nil {
		t.Fatalf("MCP connection failed: %v", err)
	}
	t.Cleanup(func() { session.Close() })
	return session
}

func TestWorkspaceMCPGoClientAndRESTParity(t *testing.T) {
	f := serviceFixture(t)
	credential, token := issue(t, f.store, false, "project_summary")
	session := connectMCP(t, f.server, token)
	list, err := session.ListTools(context.Background(), nil)
	if err != nil || len(list.Tools) != 1 || list.Tools[0].Name != "project_summary" || !list.Tools[0].Annotations.ReadOnlyHint {
		t.Fatalf("unexpected MCP tools: %v", err)
	}
	result, err := session.CallTool(context.Background(), &mcp.CallToolParams{Name: "project_summary", Arguments: map[string]any{"project": "missing"}})
	if err != nil || result.IsError {
		t.Fatalf("registered MCP call failed: %v", err)
	}
	encoded, _ := json.Marshal(result.StructuredContent)
	var envelope map[string]any
	if json.Unmarshal(encoded, &envelope) != nil || envelope["instance_id"] != f.store.Identity || envelope["capability"] != "project_summary" {
		t.Fatal("MCP lost canonical envelope")
	}
	w := request(f.server, "POST", "/api/v1/project-summary", token, `{"project":"missing"}`, map[string]string{"Content-Type": "application/json"})
	var rest map[string]any
	json.Unmarshal(w.Body.Bytes(), &rest)
	a, _ := json.Marshal(envelope["result"])
	b, _ := json.Marshal(rest["result"])
	if w.Code != 200 || string(a) != string(b) || !identifier.MatchString(envelope["request_id"].(string)) {
		t.Fatal("REST/MCP result or identity differs")
	}
	bad, err := session.CallTool(context.Background(), &mcp.CallToolParams{Name: "project_summary", Arguments: map[string]any{"project": "../data", "secret": "do-not-echo"}})
	if err != nil || !bad.IsError {
		t.Fatal("invalid MCP input reached handler")
	}
	raw, _ := json.Marshal(bad)
	if strings.Contains(string(raw), "do-not-echo") || !strings.Contains(string(raw), "invalid_input") {
		t.Fatal("unsafe or incorrect MCP failure")
	}
	if err := f.store.Revoke(credential.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := session.ListTools(context.Background(), nil); err == nil {
		t.Fatal("existing MCP client survived credential revocation")
	}
	if f.calls.Load() != 0 {
		t.Fatal("workspace MCP reached legacy/host backend")
	}
}

func TestWorkspaceMCPAdmissionDenials(t *testing.T) {
	f := serviceFixture(t)
	_, token := issue(t, f.store, false, "project_summary")
	other, _ := testStore(t)
	_, foreign := issue(t, other, false)
	body := `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`
	for _, tc := range []struct {
		name, token, header, value string
		status                     int
	}{
		{"missing", "", "", "", 401},
		{"invalid", "invalid", "", "", 401},
		{"foreign", foreign, "", "", 401},
		{"origin", token, "Origin", "https://attacker.example", 403},
		{"forged", "", "X-VibeStack-Principal", "owner", 401},
		{"wrong instance", token, "X-VibeStack-Expected-Instance", strings.Repeat("f", 32), 409},
		{"session only", "", "Mcp-Session-Id", "stolen-session", 401},
		{"unexpected session", token, "Mcp-Session-Id", "stolen-session", 400},
		{"unexpected replay", token, "Last-Event-ID", "replay", 400},
	} {
		t.Run(tc.name, func(t *testing.T) {
			headers := map[string]string{"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
			if tc.header != "" {
				headers[tc.header] = tc.value
			}
			w := request(f.server, "POST", "/mcp", tc.token, body, headers)
			if w.Code != tc.status || (w.Code == 401 && !strings.HasPrefix(w.Header().Get("WWW-Authenticate"), "Bearer ")) {
				t.Fatalf("incorrect admission status %d", w.Code)
			}
		})
	}
	f.store.now = func() time.Time { return time.Now().Add(2 * time.Hour) }
	if w := request(f.server, "POST", "/mcp", token, body, nil); w.Code != 401 {
		t.Fatal("expired token was accepted")
	}
	if f.calls.Load() != 0 {
		t.Fatal("denied MCP request reached a backend")
	}
}

func TestWorkspaceMCPChangedGrantsAndHumanPolicies(t *testing.T) {
	var calls atomic.Int32
	registrations := []capabilities.Registration{}
	for _, policy := range []string{"human-only", "owner-opt-in"} {
		definition := capabilities.Builtins(nil)[0].Definition
		var d map[string]any
		json.Unmarshal(definition, &d)
		id := strings.ReplaceAll(policy, "-", "_")
		d["id"], d["mcp_policy"] = id, policy
		d["rest"] = map[string]string{"method": "POST", "path": "/api/v1/" + id}
		raw, _ := json.Marshal(d)
		registrations = append(registrations, capabilities.Registration{Definition: raw, Handle: func(context.Context, capabilities.Principal, json.RawMessage) (any, error) {
			calls.Add(1)
			return nil, nil
		}})
	}
	f := serviceFixture(t, func(c *Config) { c.Capabilities = registrations })
	_, owner := issue(t, f.store, true)
	session := connectMCP(t, f.server, owner)
	list, err := session.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatal("owner tool discovery failed")
	}
	for _, name := range []string{"human_only", "owner_opt_in", "instances_list", "instance_create", "readWorkspaceClipboard", "writeWorkspaceClipboard", "addWorkspaceSSHKey", "removeWorkspaceSSHKey", "listWorkspaceSSHKeys", "listWorkspaceClients", "setLinuxPassword"} {
		for _, tool := range list.Tools {
			if tool.Name == name {
				t.Fatal("excluded tool advertised")
			}
		}
		if result, err := session.CallTool(context.Background(), &mcp.CallToolParams{Name: name, Arguments: map[string]any{"project": "missing"}}); err == nil && !result.IsError {
			t.Fatal("excluded tool executed")
		}
	}
	credential, token := issue(t, f.store, false, "project_summary")
	changed := connectMCP(t, f.server, token)
	if err := f.store.locked(func() error {
		state, err := f.store.load()
		if err != nil {
			return err
		}
		for i := range state.Credentials {
			if state.Credentials[i].ID == credential.ID {
				state.Credentials[i].Capabilities = []string{"workspaceStatus"}
			}
		}
		return f.store.save(state)
	}); err != nil {
		t.Fatal(err)
	}
	list, err = changed.ListTools(context.Background(), nil)
	if err != nil || len(list.Tools) != 1 || list.Tools[0].Name != "workspaceStatus" {
		t.Fatal("old connection retained changed grants")
	}
	if result, err := changed.CallTool(context.Background(), &mcp.CallToolParams{Name: "project_summary", Arguments: map[string]any{"project": "missing"}}); err == nil && !result.IsError {
		t.Fatal("removed grant executed through old client")
	}
	if calls.Load() != 0 || f.calls.Load() != 0 {
		t.Fatal("denied calls had side effects")
	}
}

func TestWorkspaceMCPTypeScriptClient(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("Node unavailable; full image acceptance requires the independent TypeScript client")
	}
	if _, err := os.Stat("../node_modules/@modelcontextprotocol/sdk/package.json"); err != nil {
		t.Skip("run npm ci; full image acceptance requires the independent TypeScript client")
	}
	f := serviceFixture(t)
	_, token := issue(t, f.store, false, "project_summary")
	path := filepath.Join(t.TempDir(), "client.token")
	if err := os.WriteFile(path, []byte(token), 0600); err != nil {
		t.Fatal(err)
	}
	host := httptest.NewServer(f.server)
	defer host.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, node, "../tests/mcp-client-check.mjs")
	cmd.Env = append(os.Environ(), "VIBESTACK_MCP_BASE_URL="+host.URL, "VIBESTACK_MCP_CREDENTIAL_FILE="+path, "VIBESTACK_MCP_EXPECTED_INSTANCE="+f.store.Identity)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("independent TypeScript client failed: %s", output)
	} else {
		t.Log(strings.TrimSpace(string(output)))
	}
}

type revokeOnRead struct {
	r      io.Reader
	revoke func()
}

func (r *revokeOnRead) Read(p []byte) (int, error) {
	if r.revoke != nil {
		r.revoke()
		r.revoke = nil
	}
	return r.r.Read(p)
}

func TestWorkspaceMCPReauthenticatesAfterHTTPAdmission(t *testing.T) {
	f := serviceFixture(t)
	credential, token := issue(t, f.store, false, "project_summary")
	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"project_summary","arguments":{"project":"missing"}}}`
	r := httptest.NewRequest("POST", "http://localhost/mcp", &revokeOnRead{r: strings.NewReader(body), revoke: func() {
		if err := f.store.Revoke(credential.ID); err != nil {
			t.Fatal(err)
		}
	}})
	r.Header.Set("Authorization", "Bearer "+token)
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Accept", "application/json, text/event-stream")
	r.Header.Set("Mcp-Protocol-Version", "2025-11-25")
	w := httptest.NewRecorder()
	f.server.ServeHTTP(w, r)
	if !strings.Contains(w.Body.String(), `"isError":true`) || !strings.Contains(w.Body.String(), `"code":"unauthenticated"`) || strings.Contains(w.Body.String(), `"exists"`) {
		t.Fatal("credential revoked after HTTP admission reached execution")
	}
}

func TestWorkspaceMCPCountsTextCopyInResponseBudget(t *testing.T) {
	var definition map[string]any
	json.Unmarshal(capabilities.Builtins(nil)[0].Definition, &definition)
	definition["id"], definition["response_bytes"] = "response_budget", 1024
	definition["rest"] = map[string]string{"method": "POST", "path": "/api/v1/response-budget"}
	definition["output_schema"] = map[string]any{"type": "object", "additionalProperties": false, "required": []string{"text"}, "properties": map[string]any{"text": map[string]any{"type": "string", "maxLength": 700}}}
	raw, _ := json.Marshal(definition)
	var calls atomic.Int32
	f := serviceFixture(t, func(c *Config) {
		c.Capabilities = []capabilities.Registration{{Definition: raw, Handle: func(context.Context, capabilities.Principal, json.RawMessage) (any, error) {
			calls.Add(1)
			return map[string]string{"text": strings.Repeat("payload", 90)}, nil
		}}}
	})
	_, token := issue(t, f.store, false, "response_budget")
	session := connectMCP(t, f.server, token)
	result, err := session.CallTool(context.Background(), &mcp.CallToolParams{Name: "response_budget", Arguments: map[string]any{"project": "missing"}})
	if err != nil || !result.IsError || calls.Load() != 1 {
		t.Fatal("oversized MCP result was returned or replayed")
	}
	data, _ := json.Marshal(result)
	if !strings.Contains(string(data), "limit_exceeded") || strings.Contains(string(data), "payload") || len(data) > 1024 {
		t.Fatal("limit failure was unbounded or disclosed payload")
	}
}
