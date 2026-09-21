package service

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/check-the-vibe/vibestack/service/capabilities"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func TestWorkspaceToolCoverageMatchesInventoryAndGrants(t *testing.T) {
	f := serviceFixture(t)
	data, err := os.ReadFile("../contracts/capability-inventory-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var inventory struct {
		Operations []struct{ ID, Authority, Kind, Effect, Retry string }
	}
	if err := json.Unmarshal(data, &inventory); err != nil {
		t.Fatal(err)
	}
	excluded := map[string]bool{"openProviderApp": true, "answerProviderApproval": true, "readWorkspaceClipboard": true, "writeWorkspaceClipboard": true, "listWorkspaceSSHKeys": true, "addWorkspaceSSHKey": true, "removeWorkspaceSSHKey": true, "listWorkspaceClients": true}
	want := map[string]bool{"project_summary": true}
	for _, operation := range inventory.Operations {
		if operation.Authority != "workspace" || operation.Kind != "shared-capability" {
			continue
		}
		entry, ok := f.server.registry.Entry(operation.ID)
		if !ok {
			t.Fatalf("missing compiled adapter %s", operation.ID)
		}
		if entry.Definition.Effect != operation.Effect || entry.Definition.Retry != operation.Retry {
			t.Fatalf("policy drift for %s", operation.ID)
		}
		if !excluded[operation.ID] {
			want[operation.ID] = true
		}
	}
	_, owner := issue(t, f.store, true)
	session := connectMCP(t, f.server, owner)
	list, err := session.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatal("tool discovery failed")
	}
	for _, tool := range list.Tools {
		if !want[tool.Name] {
			t.Fatalf("unexpected tool %s", tool.Name)
		}
		delete(want, tool.Name)
	}
	if len(want) != 0 {
		t.Fatalf("missing tools: %v", want)
	}
	for _, id := range []string{"workspaceStatus", "submitArgvCommand", "writeProjectFile", "captureWorkspaceScreenshot"} {
		_, token := issue(t, f.store, false, id)
		limited := connectMCP(t, f.server, token)
		list, err := limited.ListTools(context.Background(), nil)
		if err != nil || len(list.Tools) != 1 || list.Tools[0].Name != id {
			t.Fatalf("grant filter failed for %s", id)
		}
	}
	if f.calls.Load() != 0 {
		t.Fatal("discovery executed a backend")
	}
}

func TestWorkspaceAdapterArgvDispatchAndDenial(t *testing.T) {
	var calls atomic.Int32
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Path != "/api/v1/automation/commands" || r.Method != "POST" || r.URL.RawQuery != "" {
			t.Error("incorrect backend dispatch")
		}
		if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("i", 43) || !identifier.MatchString(r.Header.Get("X-Request-ID")) {
			t.Error("external credential forwarded or request identity lost")
		}
		var body map[string]any
		json.NewDecoder(r.Body).Decode(&body)
		if len(body) != 3 || body["root"] != "projects" || body["cwd"] != "repo" {
			t.Error("input mapping changed")
		}
		w.WriteHeader(202)
		io.WriteString(w, `{"job":{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"queued"}}`)
	}))
	defer backend.Close()
	f := serviceFixture(t, func(c *Config) { c.AutomationURL = backend.URL })
	_, token := issue(t, f.store, false, "submitArgvCommand")
	_, denied := issue(t, f.store, false, "workspaceStatus")
	body := `{"argv":["/usr/bin/true"],"root":"projects","cwd":"repo"}`
	for _, path := range []string{"/api/v1/operations/submitArgvCommand", "/api/v1/capabilities/submitArgvCommand/invoke"} {
		response := request(f.server, "POST", path, token, body, map[string]string{"Content-Type": "application/json"})
		if response.Code != 200 || !strings.Contains(response.Body.String(), `"job"`) {
			t.Fatalf("REST status %d", response.Code)
		}
	}
	session := connectMCP(t, f.server, token)
	result, err := session.CallTool(context.Background(), &mcp.CallToolParams{Name: "submitArgvCommand", Arguments: json.RawMessage(body)})
	if err != nil || result.IsError {
		t.Fatal("MCP dispatch failed")
	}
	if calls.Load() != 3 {
		t.Fatal("submission replayed or not executed")
	}
	for _, body := range []string{`{"argv":["/usr/bin/true"],"url":"http://attacker.invalid"}`, `{"argv":[],"root":"projects"}`, `{"argv":["/usr/bin/true"],"root":"host"}`} {
		w := request(f.server, "POST", "/api/v1/capabilities/submitArgvCommand/invoke", token, body, map[string]string{"Content-Type": "application/json"})
		if w.Code != 400 {
			t.Fatalf("invalid input status %d", w.Code)
		}
	}
	w := request(f.server, "POST", "/api/v1/capabilities/submitArgvCommand/invoke", denied, body, map[string]string{"Content-Type": "application/json"})
	if w.Code != 403 || calls.Load() != 3 {
		t.Fatal("denied request executed")
	}
}

func TestWorkspaceFilePreconditionsBinaryAndSafeErrors(t *testing.T) {
	var calls atomic.Int32
	var status atomic.Int32
	status.Store(200)
	etag := `"sha256-` + strings.Repeat("a", 64) + `"`
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Path != "/api/v1/automation/projects/repo/a #?.bin" || r.URL.RawQuery != "" {
			t.Error("file path escaped incorrectly")
		}
		if code := int(status.Load()); code != 200 {
			w.WriteHeader(code)
			io.WriteString(w, "PRIVATE-ERROR-BODY")
			return
		}
		w.Header().Set("ETag", etag)
		if r.Method == "PUT" {
			if r.Header.Get("If-Match") != etag {
				t.Error("precondition lost")
			}
			body, _ := io.ReadAll(r.Body)
			if string(body) != "\x00binary\xff" {
				t.Error("binary write changed")
			}
			io.WriteString(w, `{"file":{"bytes":8}}`)
			return
		}
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Write([]byte("\x00binary\xff"))
	}))
	defer backend.Close()
	f := serviceFixture(t, func(c *Config) { c.AutomationURL = backend.URL })
	_, token := issue(t, f.store, false, "writeProjectFile", "readProjectFile")
	invoke := func(id string, value map[string]any) *httptest.ResponseRecorder {
		body, _ := json.Marshal(value)
		return request(f.server, "POST", "/api/v1/capabilities/"+id+"/invoke", token, string(body), map[string]string{"Content-Type": "application/json"})
	}
	write := map[string]any{"path": "repo/a #?.bin", "data_base64": base64.StdEncoding.EncodeToString([]byte("\x00binary\xff"))}
	if invoke("writeProjectFile", write).Code != 400 {
		t.Fatal("unconditional write accepted")
	}
	write["if_match"] = "*"
	if invoke("writeProjectFile", write).Code != 400 {
		t.Fatal("wildcard overwrite accepted")
	}
	write["if_match"] = etag
	if invoke("writeProjectFile", write).Code != 200 {
		t.Fatal("conditional write failed")
	}
	write["if_none_match"] = "*"
	if invoke("writeProjectFile", write).Code != 400 {
		t.Fatal("ambiguous preconditions accepted")
	}
	delete(write, "if_none_match")
	for _, path := range []string{"../data/x", "repo/../x", "/absolute", "repo//x", "repo/./x", `repo\x`} {
		write["path"] = path
		if invoke("writeProjectFile", write).Code != 400 {
			t.Fatalf("unsafe file path accepted: %q", path)
		}
	}
	if calls.Load() != 1 {
		t.Fatal("denied writes reached backend")
	}
	read := map[string]any{"path": "repo/a #?.bin"}
	w := invoke("readProjectFile", read)
	if w.Code != 200 || !strings.Contains(w.Body.String(), write["data_base64"].(string)) {
		t.Fatal("binary read changed")
	}
	write["path"] = read["path"]
	for _, code := range []int{412, 409, 503, 307} {
		status.Store(int32(code))
		before := calls.Load()
		w := invoke("writeProjectFile", write)
		if w.Code == 200 || strings.Contains(w.Body.String(), "PRIVATE-ERROR-BODY") || calls.Load() != before+1 {
			t.Fatal("failure disclosed body or replayed mutation")
		}
	}
}

func TestWorkspaceBuiltinIDCannotBeReplaced(t *testing.T) {
	f := serviceFixture(t)
	registrations, _ := f.server.workspaceRegistrations()
	for _, registration := range registrations {
		var d capabilities.Definition
		json.Unmarshal(registration.Definition, &d)
		if d.ID != "workspaceStatus" {
			continue
		}
		cfg := f.server.cfg
		cfg.Capabilities = []capabilities.Registration{registration}
		if server, err := NewServer(cfg); err == nil {
			server.Close()
			t.Fatal("compiled operation was replaced")
		}
	}
}
