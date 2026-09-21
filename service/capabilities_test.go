package service

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRegisteredCapabilityRESTAndBrowserShareDispatcher(t *testing.T) {
	var events []AuditEvent
	projects := t.TempDir()
	if err := os.Mkdir(filepath.Join(projects, "demo"), 0700); err != nil {
		t.Fatal(err)
	}
	f := serviceFixture(t, func(c *Config) {
		c.ProjectsRoot = projects
		c.Audit = func(e AuditEvent) { events = append(events, e) }
	})
	credential, token := issue(t, f.store, false, "project_summary")
	headers := map[string]string{"Content-Type": "application/json"}
	for _, path := range []string{"/api/v1/project-summary", "/api/v1/capabilities/project_summary/invoke"} {
		w := request(f.server, "POST", path, token, `{"project":"demo"}`, headers)
		var envelope struct {
			Capability string         `json:"capability"`
			Instance   string         `json:"instance_id"`
			Request    string         `json:"request_id"`
			Result     map[string]any `json:"result"`
		}
		if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &envelope) != nil || envelope.Capability != "project_summary" || envelope.Instance != f.store.Identity || !identifier.MatchString(envelope.Request) || envelope.Result["exists"] != true {
			t.Fatalf("invalid invocation status=%d", w.Code)
		}
	}
	session := request(f.server, "POST", "/auth/session", token, "", nil)
	var value struct {
		CSRF string `json:"csrf"`
	}
	json.Unmarshal(session.Body.Bytes(), &value)
	cookie := session.Result().Cookies()[0]
	browser := map[string]string{"Content-Type": "application/json", "Cookie": cookie.Name + "=" + cookie.Value, "X-VibeStack-CSRF": value.CSRF, "Origin": "http://localhost"}
	if w := request(f.server, "POST", "/api/v1/capabilities/project_summary/invoke", "", `{"project":"demo"}`, browser); w.Code != 200 {
		t.Fatalf("browser status %d", w.Code)
	}
	if len(events) != 3 {
		t.Fatal("missing dispatcher audit")
	}
	for _, e := range events {
		if e.Capability != "project_summary" || e.Outcome != "ok" || !identifier.MatchString(e.RequestID) {
			t.Fatal("incorrect dispatcher metadata")
		}
	}
	if err := f.store.Revoke(credential.ID); err != nil {
		t.Fatal(err)
	}
	if w := request(f.server, "POST", "/api/v1/capabilities/project_summary/invoke", "", `{"project":"demo"}`, browser); w.Code != 401 {
		t.Fatal("revoked browser session executed extension")
	}
	if len(events) != 3 {
		t.Fatal("revoked request reached dispatcher")
	}
}

func TestExtensionMetadataFilteredAndInvalidCallsFail(t *testing.T) {
	f := serviceFixture(t)
	_, token := issue(t, f.store, false, "project_summary")
	_, denied := issue(t, f.store, false, "workspaceStatus")
	for _, path := range []string{"/api/v1/capabilities", "/api/capabilities.openapi.json"} {
		w := request(f.server, "GET", path, token, "", nil)
		if w.Code != 200 || !strings.Contains(w.Body.String(), `"project_summary"`) {
			t.Fatal("registered metadata unavailable")
		}
		w = request(f.server, "GET", path, denied, "", nil)
		if w.Code != 200 || strings.Contains(w.Body.String(), `"project_summary"`) {
			t.Fatal("denied extension metadata disclosed")
		}
	}
	for _, tc := range []struct {
		token, body, ctype string
		status             int
	}{
		{"", `{"project":"demo"}`, "application/json", 401},
		{denied, `{"project":"demo"}`, "application/json", 403},
		{token, `{"project":"../data"}`, "application/json", 400},
		{token, `{"project":"demo","secret":"not-for-logs"}`, "application/json", 400},
		{token, `{"project":"demo"}`, "application/json-invalid", 400},
		{token, strings.Repeat("a", 4097), "application/json", 413},
	} {
		w := request(f.server, "POST", "/api/v1/capabilities/project_summary/invoke", tc.token, tc.body, map[string]string{"Content-Type": tc.ctype})
		if w.Code != tc.status || strings.Contains(w.Body.String(), "not-for-logs") {
			t.Fatalf("boundary status %d expected %d", w.Code, tc.status)
		}
	}
	if f.calls.Load() != 0 {
		t.Fatal("extension request reached legacy backend")
	}
}
