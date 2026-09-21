package service

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	clientapi "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

type fixture struct {
	server        *Server
	store         *Store
	public, state string
	calls         atomic.Int32
	received      chan *http.Request
}

func serviceFixture(t *testing.T) *fixture {
	t.Helper()
	s, root := testStore(t)
	if err := os.WriteFile(filepath.Join(root, "automation.token"), []byte(strings.Repeat("i", 43)+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	f := &fixture{store: s, public: t.TempDir(), state: root, received: make(chan *http.Request, 128)}
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.calls.Add(1)
		f.received <- r.Clone(r.Context())
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"status":"ready"}`))
	}))
	t.Cleanup(backend.Close)
	server, err := NewServer(Config{Store: s, StaticRoot: f.public, PublicURL: "https://workspace.example", AutomationURL: backend.URL, ControlURL: backend.URL, SetupURL: backend.URL})
	if err != nil {
		t.Fatal(err)
	}
	f.server = server
	t.Cleanup(func() { server.Close() })
	return f
}

func request(s *Server, method, path, token, body string, headers map[string]string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, "http://localhost"+path, strings.NewReader(body))
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	for k, v := range headers {
		r.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}

func TestEveryLegacyRouteRequiresAuthenticationBeforeBackend(t *testing.T) {
	f := serviceFixture(t)
	for _, route := range f.server.operations {
		path := strings.NewReplacer("{id}", strings.Repeat("a", 32), "{code}", "ABCD-EFGH", "{service}", "x11vnc", "{operation}", "start", "{path}", "demo.txt").Replace(route.Path)
		response := request(f.server, route.Method, path, "", "{}", nil)
		if response.Code != 401 {
			t.Errorf("%s %s: got %d", route.Method, path, response.Code)
		}
	}
	for _, path := range []string{"/mcp", "/api/v1/capabilities", "/api/v1/unknown", "/setup/api/unknown"} {
		if w := request(f.server, "GET", path, "", "", nil); w.Code != 401 {
			t.Errorf("%s status %d", path, w.Code)
		}
	}
	if f.calls.Load() != 0 {
		t.Fatal("anonymous request reached backend")
	}
	w := request(f.server, "GET", "/api/v1/automation", "", "", nil)
	var body map[string]any
	if json.Unmarshal(w.Body.Bytes(), &body) != nil || body["code"] != "unauthorized" || body["error"].(map[string]any)["code"] != "unauthenticated" {
		t.Fatal("legacy error code or new envelope was lost")
	}
}

func TestProxyRequestIDIsBoundedAndCorrelatesAcrossTheAdapter(t *testing.T) {
	f := serviceFixture(t)
	_, token := issue(t, f.store, false)
	id := strings.Repeat("a", 32)
	r := httptest.NewRequest("GET", "http://localhost/api/v1/status", nil)
	r.RemoteAddr = "127.0.0.1:12345"
	r.Header.Set("Authorization", "Bearer "+token)
	r.Header.Set("X-Request-ID", id)
	w := httptest.NewRecorder()
	f.server.ServeHTTP(w, r)
	backend := <-f.received
	if w.Header().Get("X-Request-ID") != id || backend.Header.Get("X-Request-ID") != id {
		t.Fatal("proxy correlation lost")
	}
	r.RemoteAddr = "192.0.2.1:12345"
	w = httptest.NewRecorder()
	f.server.ServeHTTP(w, r)
	if w.Header().Get("X-Request-ID") == id {
		t.Fatal("non-proxy request ID trusted")
	}
}

func TestAuthenticationAndTargetFailuresHaveNoSideEffects(t *testing.T) {
	f := serviceFixture(t)
	c, token := issue(t, f.store, false, "workspaceStatus")
	other, _ := testStore(t)
	_, foreign := issue(t, other, false)
	for _, tc := range []struct {
		name, method, path, token string
		headers                   map[string]string
		status                    int
	}{
		{"invalid", "GET", "/api/v1/status", strings.Repeat("x", 43), nil, 401},
		{"foreign instance credential", "GET", "/api/v1/status", foreign, nil, 401},
		{"missing grant", "POST", "/api/v1/automation/commands", token, nil, 403},
		{"owner required", "POST", "/setup/api/password", token, nil, 403},
		{"wrong target", "GET", "/api/v1/status", token, map[string]string{"X-VibeStack-Expected-Instance": strings.Repeat("f", 32)}, 409},
		{"forged identity", "POST", "/setup/api/password", "", map[string]string{"X-Forwarded-User": "owner", "X-VibeStack-Principal": "owner"}, 401},
		{"wrong origin", "GET", "/api/v1/status", token, map[string]string{"Origin": "https://attacker.example"}, 403},
		{"cross site", "POST", "/api/v1/automation/commands", token, map[string]string{"Sec-Fetch-Site": "cross-site"}, 403},
		{"query credential", "GET", "/api/v1/status?token=hidden", token, nil, 400},
	} {
		t.Run(tc.name, func(t *testing.T) {
			w := request(f.server, tc.method, tc.path, tc.token, "{}", tc.headers)
			if w.Code != tc.status {
				t.Fatalf("status %d: %s", w.Code, w.Body.String())
			}
		})
	}
	if err := f.store.Revoke(c.ID); err != nil {
		t.Fatal(err)
	}
	if w := request(f.server, "GET", "/api/v1/status", token, "", nil); w.Code != 401 {
		t.Fatalf("revoked status %d", w.Code)
	}
	if f.calls.Load() != 0 {
		t.Fatal("denied request reached backend")
	}
}

func TestCompatibilityUsesInternalCredentialsAndDropsIdentityHeaders(t *testing.T) {
	f := serviceFixture(t)
	_, token := issue(t, f.store, false)
	w := request(f.server, "POST", "/api/v1/automation/commands", token, `{"argv":["/usr/bin/true"]}`, map[string]string{"Content-Type": "application/json", "Origin": "http://localhost", "Cookie": "external=secret", "X-Forwarded-User": "owner", "X-Forwarded-Host": "attacker.example"})
	if w.Code != 200 {
		t.Fatalf("status %d: %s", w.Code, w.Body.String())
	}
	r := <-f.received
	if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("i", 43) {
		t.Fatal("internal credential was not used")
	}
	for _, name := range []string{"Cookie", "Origin", "X-Forwarded-User", "X-Forwarded-Host"} {
		if r.Header.Get(name) != "" {
			t.Errorf("forwarded %s", name)
		}
	}
	if strings.Contains(w.Body.String(), token) || w.Header().Get("X-VibeStack-Instance-ID") != f.store.Identity {
		t.Fatal("unsafe result or missing instance")
	}
}

func TestBrowserSessionCSRFAndRevocation(t *testing.T) {
	f := serviceFixture(t)
	c, token := issue(t, f.store, true)
	w := request(f.server, "POST", "/auth/session", token, "", nil)
	if w.Code != 200 {
		t.Fatalf("session status %d: %s", w.Code, w.Body.String())
	}
	var result struct {
		CSRF string `json:"csrf"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	cookies := w.Result().Cookies()
	if len(cookies) != 1 || !cookies[0].HttpOnly || !cookies[0].Secure || cookies[0].SameSite != http.SameSiteStrictMode || cookies[0].Domain != "" {
		t.Fatal("unsafe session cookie")
	}
	headers := map[string]string{"Cookie": cookies[0].Name + "=" + cookies[0].Value}
	if w := request(f.server, "POST", "/setup/api/install", "", "{}", headers); w.Code != 401 {
		t.Fatal("missing CSRF accepted")
	}
	if f.calls.Load() != 0 {
		t.Fatal("CSRF bypass executed")
	}
	headers["X-VibeStack-CSRF"] = result.CSRF
	if w := request(f.server, "POST", "/setup/api/install", "", "{}", headers); w.Code != 200 {
		t.Fatalf("valid session rejected %d", w.Code)
	}
	if err := f.store.Revoke(c.ID); err != nil {
		t.Fatal(err)
	}
	if w := request(f.server, "POST", "/setup/api/install", "", "{}", headers); w.Code != 401 {
		t.Fatal("session survived credential revocation")
	}
	if f.calls.Load() != 1 {
		t.Fatal("revoked session reached backend")
	}
}

func TestLimitsAndUnknownRoutesDoNotFallThrough(t *testing.T) {
	f := serviceFixture(t)
	_, token := issue(t, f.store, true)
	for _, tc := range []struct {
		method, path, body string
		status             int
	}{
		{"POST", "/api/v1/diagnostics/events", strings.Repeat("x", 4097), 413},
		{"POST", "/setup/api/install", strings.Repeat("x", 65537), 413},
		{"POST", "/api/v1/automation/commands", strings.Repeat("x", (1<<20)+4097), 413},
		{"GET", "/api/v1/unknown", "", 404},
		{"GET", "/setup/api/unknown", "", 404},
		{"POST", "/api/v1/status", "{}", 404},
	} {
		w := request(f.server, tc.method, tc.path, token, tc.body, nil)
		if w.Code != tc.status {
			t.Errorf("%s %s = %d: %s", tc.method, tc.path, w.Code, w.Body.String())
		}
	}
	if f.calls.Load() != 0 {
		t.Fatal("invalid request reached backend")
	}
}

func TestStaticPublishBoundaryAndFilteredDiscovery(t *testing.T) {
	f := serviceFixture(t)
	for name, content := range map[string]string{"hello.txt": "published", ".env": "private", "credentials.json": "private"} {
		if err := os.WriteFile(filepath.Join(f.public, name), []byte(content), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Mkdir(filepath.Join(f.public, "directory"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(f.state, "identity"), filepath.Join(f.public, "escape.txt")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(".env", filepath.Join(f.public, "hidden.txt")); err != nil {
		t.Fatal(err)
	}
	if w := request(f.server, "GET", "/hello.txt", "", "", nil); w.Code != 200 || w.Body.String() != "published" {
		t.Fatal("published file unavailable")
	}
	for _, path := range []string{"/.env", "/credentials.json", "/directory", "/escape.txt", "/hidden.txt", "/%2eenv", "/missing"} {
		if w := request(f.server, "GET", path, "", "", nil); w.Code != 404 {
			t.Errorf("%s: %d", path, w.Code)
		}
	}
	if w := request(f.server, "PUT", "/hello.txt", "", "changed", nil); w.Code != 405 {
		t.Fatal("static write allowed")
	}
	_, token := issue(t, f.store, false, "workspaceStatus")
	w := request(f.server, "GET", "/api/v1/capabilities", token, "", nil)
	var listing struct {
		Capabilities []struct {
			ID string `json:"id"`
		} `json:"capabilities"`
	}
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &listing) != nil || len(listing.Capabilities) != 1 || listing.Capabilities[0].ID != "workspaceStatus" {
		t.Fatalf("grant-filtered listing failed: %s", w.Body.String())
	}
	w = request(f.server, "GET", "/.well-known/vibestack", "", "", nil)
	if w.Code != 200 || strings.Contains(w.Body.String(), "workspaceStatus") || strings.Contains(w.Body.String(), token) || strings.Contains(w.Body.String(), f.state) {
		t.Fatal("anonymous discovery leaked private inventory")
	}
}

func TestExistingClientCanDiscoverAndUseToken(t *testing.T) {
	f := serviceFixture(t)
	_, token := issue(t, f.store, false)
	server := httptest.NewServer(f.server)
	defer server.Close()
	client, err := clientapi.NewClient(server.URL, token, "")
	if err != nil {
		t.Fatal(err)
	}
	discovery, err := client.Discover(t.Context())
	if err != nil || discovery.Identity != f.store.Identity {
		t.Fatalf("legacy discovery: %v", err)
	}
	var status map[string]any
	if _, err := client.JSON(t.Context(), http.MethodGet, "/api/v1/status", nil, &status, true, nil); err != nil || status["status"] != "ready" {
		t.Fatalf("legacy authenticated call failed: %v", err)
	}
	response, err := http.Get(server.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	io.Copy(io.Discard, response.Body)
	if response.StatusCode != 200 {
		t.Fatal("health check failed")
	}
}
