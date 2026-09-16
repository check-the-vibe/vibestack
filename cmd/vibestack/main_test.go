package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

func TestInstancesUpdateAcceptsDocumentedIDBeforeFlags(t *testing.T) {
	var received map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != api.RunnerAPI+"/instances/alpha-id/update" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		if got := r.Header.Get("Idempotency-Key"); got != "update-alpha-v1" {
			t.Errorf("unexpected idempotency key %q", got)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer test-credential" {
			t.Errorf("unexpected authorization header %q", got)
		}
		if err := json.NewDecoder(r.Body).Decode(&received); err != nil {
			t.Errorf("decode request: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"operation":{"id":"0123456789abcdef0123456789abcdef","kind":"update","status":"queued"}}`))
	}))
	defer server.Close()

	client, err := api.NewClient(server.URL, "test-credential", "")
	if err != nil {
		t.Fatal(err)
	}
	profile := api.Profile{Kind: "runner"}
	err = instances(context.Background(), client, profile, []string{
		"update", "alpha-id",
		"--template", "accepted",
		"--idempotency-key", "update-alpha-v1",
		"--memory-bytes", "1073741824",
	}, globalOptions{json: true})
	if err != nil {
		t.Fatal(err)
	}
	if received["template"] != "accepted" {
		t.Fatalf("unexpected request body %#v", received)
	}
	resources, ok := received["resources"].(map[string]any)
	if !ok || resources["memory_bytes"] != float64(1073741824) {
		t.Fatalf("unexpected resource body %#v", received)
	}
}
