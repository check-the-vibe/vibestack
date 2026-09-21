package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func trustedServer(t *testing.T) (*Server, *Store) {
	t.Helper()
	store, err := OpenStore(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	cfg := DefaultConfig()
	cfg.AuthenticationMode = AuthTrustedTailnet
	cfg.PublicURL = "https://runner.example"
	return NewServer(cfg, store, nil), store
}
func TestSharedAuthorityAndModeTransitions(t *testing.T) {
	s, store := trustedServer(t)
	ctx := context.Background()
	id := s.sharedPrincipal
	if id == "" || s.authError != nil {
		t.Fatal("missing shared principal")
	}
	if again, err := store.ConfigureAuthentication(ctx, AuthTrustedTailnet); err != nil || again != id {
		t.Fatal("shared principal changed")
	}
	i := api.Instance{ID: strings.Repeat("a", 32), Name: "shared", Owner: id, Ports: map[string]int{}, URLs: map[string]string{}, CreatedAt: nowISO(), UpdatedAt: nowISO()}
	if err := store.CreateInstance(ctx, i, "data", "projects", map[string]any{}); err != nil {
		t.Fatal(err)
	}
	for _, credential := range []string{"", "untrusted-device-label"} {
		response := runnerRequest(t, s, "GET", APIRoot+"/instances", credential, nil)
		if response.Code != 200 || !strings.Contains(response.Body.String(), i.ID) {
			t.Fatal("independent client cannot see shared desktop", response.Body.String())
		}
	}
	first := runnerRequest(t, s, "POST", APIRoot+"/drives", "", map[string]string{"name": "shared-files"})
	second := runnerRequest(t, s, "GET", APIRoot+"/drives", "other-device", nil)
	if first.Code != 201 || !strings.Contains(second.Body.String(), "shared-files") {
		t.Fatal("storage namespace differs")
	}
	if _, err := store.ConfigureAuthentication(ctx, AuthPaired); err == nil {
		t.Fatal("mode switch adopted resources")
	}
	if r := runnerRequest(t, s, "POST", APIRoot+"/pairing/requests", "", map[string]any{}); r.Code != 404 {
		t.Fatal("trusted pairing enabled")
	}
	discovery := runnerRequest(t, s, "GET", api.DiscoveryPath, "", nil)
	if !strings.Contains(discovery.Body.String(), `"authentication_mode":"trusted-tailnet"`) || strings.Contains(discovery.Body.String(), `"pairing"`) {
		t.Fatal("wrong discovery")
	}
}
func TestLegacyPairedRegistryCannotBecomeTrusted(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.RequestPairing(context.Background(), "device", []string{"instances:read", "instances:write"}); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ConfigureAuthentication(context.Background(), AuthTrustedTailnet); err == nil {
		t.Fatal("legacy registry adopted")
	}
	if _, err := store.ConfigureAuthentication(context.Background(), AuthPaired); err != nil {
		t.Fatal(err)
	}
}
func TestMCPIndependentClientAndSourceBoundary(t *testing.T) {
	s, _ := trustedServer(t)
	host := httptest.NewServer(s.HTTP.Handler)
	defer host.Close()
	s.Config.Listen = strings.TrimPrefix(host.URL, "http://")
	ctx := context.Background()
	client := mcp.NewClient(&mcp.Implementation{Name: "independent-test", Version: "1"}, nil)
	session, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: host.URL + "/mcp"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	list, err := session.ListTools(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(list.Tools) != 11 {
		t.Fatalf("tools=%d", len(list.Tools))
	}
	for _, tool := range list.Tools {
		if strings.Contains(tool.Name, "password") {
			t.Fatal("MCP password exposed")
		}
	}
	result, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "instances_list", Arguments: map[string]any{}})
	if err != nil || result.IsError {
		t.Fatalf("tool failed: %v %+v", err, result)
	}
	result, err = session.CallTool(ctx, &mcp.CallToolParams{Name: "workspace_command", Arguments: map[string]any{"instance_id": strings.Repeat("a", 32), "argv": []string{"true"}}})
	if err != nil || !result.IsError {
		t.Fatal("unavailable instance was accepted", err)
	}
	for _, test := range []struct {
		host, origin string
		status       int
	}{
		{s.Config.Listen, s.Config.PublicURL, 200},
		{"evil.example", s.Config.PublicURL, 421},
		{s.Config.Listen, "https://evil.example", 403},
		{"runner.example:9999", "", 421},
		{"runner.example", "https://runner.example:9999", 403},
	} {
		body := []byte(`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`)
		r := httptest.NewRequest("POST", host.URL+"/mcp", bytes.NewReader(body))
		r.Host = test.host
		r.Header.Set("Origin", test.origin)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Accept", "application/json, text/event-stream")
		w := httptest.NewRecorder()
		s.HTTP.Handler.ServeHTTP(w, r)
		if w.Code != test.status {
			t.Fatalf("host=%s origin=%s: %d %s", test.host, test.origin, w.Code, w.Body.String())
		}
	}
}
func TestPasswordValidationAndUnavailableManager(t *testing.T) {
	s, store := trustedServer(t)
	i := api.Instance{ID: strings.Repeat("b", 32), Name: "desktop", Owner: s.sharedPrincipal, Ports: map[string]int{}, URLs: map[string]string{}, CreatedAt: nowISO(), UpdatedAt: nowISO()}
	if err := store.CreateInstance(context.Background(), i, "d", "p", map[string]any{}); err != nil {
		t.Fatal(err)
	}
	for _, value := range []string{"", strings.Repeat(" ", 20), strings.Repeat("x", 257), strings.Repeat("x", 15) + "\n"} {
		w := runnerRequest(t, s, http.MethodPost, instancePath(i.ID)+"/password", "", map[string]string{"password": value})
		if w.Code != 400 {
			t.Fatalf("policy status %d", w.Code)
		}
	}
	secret, _ := randomID()
	w := runnerRequest(t, s, "POST", instancePath(i.ID)+"/password", "", map[string]string{"password": secret})
	if w.Code != 503 || strings.Contains(w.Body.String(), secret) {
		t.Fatal("unsafe helper failure")
	}
	ops, _ := store.OperationsOwned(context.Background(), i.Owner)
	raw, _ := json.Marshal(ops)
	if strings.Contains(string(raw), secret) || len(ops) > 0 {
		t.Fatal("password persisted")
	}
}

func TestMCPPairedAuthorizationAndOwnerIsolation(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	cfg := DefaultConfig()
	cfg.PublicURL = "https://runner.example"
	s := NewServer(cfg, store, nil)
	token, _ := randomID()
	owner := strings.Repeat("d", 32)
	_, err = store.db.Exec(`INSERT INTO clients(id,label,permissions_json,credential_hash,created_at) VALUES(?,?,?,?,?)`, owner, "test", `["instances:read","instances:write"]`, HashCredential(token), nowISO())
	if err != nil {
		t.Fatal(err)
	}
	other := api.Instance{ID: strings.Repeat("e", 32), Name: "private", Owner: strings.Repeat("f", 32), Ports: map[string]int{}, URLs: map[string]string{}, CreatedAt: nowISO(), UpdatedAt: nowISO()}
	if err := store.CreateInstance(context.Background(), other, "d", "p", map[string]any{}); err != nil {
		t.Fatal(err)
	}
	call := func(credential string) *httptest.ResponseRecorder {
		body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"instance_inspect","arguments":{"instance_id":"` + other.ID + `"}}}`
		r := httptest.NewRequest("POST", "https://runner.example/mcp", strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Accept", "application/json, text/event-stream")
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		w := httptest.NewRecorder()
		s.HTTP.Handler.ServeHTTP(w, r)
		return w
	}
	if w := call(""); w.Code != 401 {
		t.Fatal("missing MCP credential accepted")
	}
	if w := call(token); w.Code != 200 || !strings.Contains(w.Body.String(), `"isError":true`) || strings.Contains(w.Body.String(), `"name":"private"`) {
		t.Fatal("cross-owner MCP access accepted", w.Body.String())
	}
	if err := store.RevokeClient(context.Background(), owner); err != nil {
		t.Fatal(err)
	}
	if w := call(token); w.Code != 401 {
		t.Fatal("revoked MCP credential accepted")
	}
}
