package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/check-the-vibe/vibestack/internal/providers"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type fixtureProviders struct {
	providerManager
	calls atomic.Int32
}

func (f *fixtureProviders) Close()                     {}
func (f *fixtureProviders) Catalog() []providers.State { return []providers.State{} }
func (f *fixtureProviders) Activate(id string) (providers.State, error) {
	f.calls.Add(1)
	return providers.State{Definition: providers.Definition{ID: id}, Models: []providers.Model{}, Phase: "active"}, nil
}
func (f *fixtureProviders) OpenApp(context.Context, string) error { f.calls.Add(1); return nil }
func (f *fixtureProviders) Approve(context.Context, string, string, string, bool) error {
	f.calls.Add(1)
	return providers.ErrConflict
}

func TestProviderOperationsShareAuthenticationSchemaAndHumanPolicy(t *testing.T) {
	f := serviceFixture(t)
	backend := &fixtureProviders{}
	f.server.providers = backend
	for _, operation := range f.server.providerOperations() {
		method := operation.method
		if method == "" {
			method = "POST"
		}
		w := request(f.server, method, operation.path, "", "{}", nil)
		if w.Code != 401 {
			t.Fatalf("anonymous provider route %s: %d", operation.id, w.Code)
		}
	}
	_, owner := issue(t, f.store, true)
	_, ordinary := issue(t, f.store, false)
	_, limited := issue(t, f.store, false, "listProviders")
	headers := map[string]string{"Content-Type": "application/json"}
	for _, test := range []struct {
		path, token, body string
		status            int
	}{
		{"/api/v1/providers/activate", limited, `{"provider":"codex"}`, 403},
		{"/api/v1/providers/activate", ordinary, `{"provider":"arbitrary"}`, 400},
		{"/api/v1/providers/activate", ordinary, `{"provider":"codex","installer":"https://untrusted.invalid/install.sh"}`, 400},
		{"/api/v1/capabilities/activateProvider/invoke", ordinary, `{"provider":"codex","argv":["unexpected"]}`, 400},
		{"/api/v1/providers/open-app", ordinary, `{"provider":"codex"}`, 403},
		{"/api/v1/providers/activate", ordinary, `{"provider":"codex"}`, 200},
	} {
		w := request(f.server, "POST", test.path, test.token, test.body, headers)
		if w.Code != test.status {
			t.Fatalf("provider request status %d, wanted %d", w.Code, test.status)
		}
	}
	if backend.calls.Load() != 1 {
		t.Fatal("denied request reached provider manager")
	}
	session := connectMCP(t, f.server, owner)
	list, err := session.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, tool := range list.Tools {
		if tool.Name == "openProviderApp" || tool.Name == "answerProviderApproval" {
			t.Fatal("human-only provider action exposed to MCP")
		}
		if tool.Name == "activateProvider" {
			found = true
		}
	}
	if !found {
		t.Fatal("provider activation absent from shared MCP registry")
	}
	result, err := session.CallTool(context.Background(), &mcp.CallToolParams{Name: "activateProvider", Arguments: map[string]any{"provider": "codex", "url": "http://attacker.invalid"}})
	if err != nil || !result.IsError || backend.calls.Load() != 1 {
		t.Fatal("MCP bypassed the same input schema")
	}
	result, err = session.CallTool(context.Background(), &mcp.CallToolParams{Name: "activateProvider", Arguments: map[string]any{"provider": "codex"}})
	if err != nil || result.IsError || backend.calls.Load() != 2 {
		t.Fatal("valid MCP activation did not reach the shared manager")
	}
}

func TestProviderInstallUsesFixedCatalogAndObservesDurableCompletion(t *testing.T) {
	var installs atomic.Int32
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.Method + " " + r.URL.Path {
		case "GET /api/state":
			if installs.Load() == 0 {
				w.Write([]byte(`{"state_valid":true,"installed":[],"job":{"running":false}}`))
			} else {
				w.Write([]byte(`{"state_valid":true,"installed":["codex-cli"],"job":{"running":false,"ok":true}}`))
			}
		case "POST /api/install":
			var body struct {
				Components []string `json:"components"`
			}
			if json.NewDecoder(r.Body).Decode(&body) != nil || len(body.Components) != 1 || body.Components[0] != "codex-cli" {
				t.Error("unexpected installer input")
			}
			installs.Add(1)
			w.Write([]byte(`{"ok":true}`))
		default:
			t.Error("unexpected provider backend path")
			w.WriteHeader(404)
		}
	}))
	defer backend.Close()
	f := serviceFixture(t, func(c *Config) { c.SetupURL = backend.URL })
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := f.server.installProviderComponent(ctx, "codex-cli"); err != nil {
		t.Fatal(err)
	}
	if err := f.server.installProviderComponent(ctx, "codex-cli"); err != nil {
		t.Fatal(err)
	}
	if installs.Load() != 1 {
		t.Fatal("installed component was installed again")
	}
	if err := f.server.installProviderComponent(ctx, strings.Repeat("x", 10)); err == nil {
		t.Fatal("unknown component accepted")
	}
}
