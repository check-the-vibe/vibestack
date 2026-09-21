package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

func TestTrustedConnectStoresNoBearerAndDoesNotPair(t *testing.T) {
	t.Setenv("VIBESTACK_CONFIG", filepath.Join(t.TempDir(), "config", "profiles.json"))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != api.DiscoveryPath {
			t.Errorf("unexpected pairing request %s", r.URL.Path)
		}
		json.NewEncoder(w).Encode(map[string]any{"kind": "runner", "identity": strings.Repeat("a", 32), "api_versions": []string{"1"}, "authentication_mode": "trusted-tailnet"})
	}))
	defer server.Close()
	if err := connect(context.Background(), []string{"--url", server.URL, "--name", "shared"}, globalOptions{}); err != nil {
		t.Fatal(err)
	}
	value, err := api.LoadProfiles()
	if err != nil {
		t.Fatal(err)
	}
	p := value.Profiles["shared"]
	if p.AuthenticationMode != "trusted-tailnet" || p.Credential != "" {
		t.Fatal("unsafe trusted profile")
	}
	if err := run([]string{"--profile", "shared", "exec", "--", "true"}); err == nil || !strings.Contains(err.Error(), "--instance") {
		t.Fatal("missing explicit selection accepted")
	}
}
func TestPasswordStdinAndNoAutomaticRetry(t *testing.T) {
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		t.Fatal(err)
	}
	secret := hex.EncodeToString(raw)
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	original := os.Stdin
	os.Stdin = reader
	defer func() { os.Stdin = original; reader.Close() }()
	go func() { writer.Write([]byte(secret + "\n")); writer.Close() }()
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.URL.Path != api.RunnerAPI+"/instances/desktop/password" {
			t.Error("wrong path")
		}
		var body map[string]string
		json.NewDecoder(r.Body).Decode(&body)
		if body["password"] != secret {
			t.Error("stdin changed")
		}
		w.WriteHeader(502)
		json.NewEncoder(w).Encode(map[string]string{"code": "password_completion_uncertain", "message": "Password completion uncertain."})
	}))
	defer server.Close()
	c, _ := api.NewClient(server.URL, "", "")
	c.AuthenticationMode = "trusted-tailnet"
	_, err = submitPassword(context.Background(), c, "desktop", true)
	if err == nil || calls != 1 || strings.Contains(err.Error(), secret) {
		t.Fatal("password was retried or leaked")
	}
}

func TestCreatePasswordIsSeparateAndFailureRetainsDesktop(t *testing.T) {
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		t.Fatal(err)
	}
	secret := hex.EncodeToString(raw)
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	original := os.Stdin
	os.Stdin = reader
	defer func() { os.Stdin = original; reader.Close() }()
	go func() { writer.Write([]byte(secret + "\n")); writer.Close() }()
	calls := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls = append(calls, r.URL.Path)
		switch r.URL.Path {
		case api.RunnerAPI + "/instances":
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			if _, ok := body["password"]; ok {
				t.Error("password in durable create")
			}
			json.NewEncoder(w).Encode(map[string]any{"operation": map[string]string{"id": "op", "instance_id": "retained-desktop", "status": "queued"}})
		case api.RunnerAPI + "/operations/op":
			json.NewEncoder(w).Encode(map[string]any{"operation": map[string]string{"id": "op", "instance_id": "retained-desktop", "status": "succeeded"}})
		case api.RunnerAPI + "/instances/retained-desktop/password":
			var body map[string]string
			json.NewDecoder(r.Body).Decode(&body)
			if body["password"] != secret {
				t.Error("wrong credential input")
			}
			w.WriteHeader(502)
			json.NewEncoder(w).Encode(map[string]string{"message": "helper unavailable"})
		default:
			t.Errorf("unexpected route %s", r.URL.Path)
		}
	}))
	defer server.Close()
	c, _ := api.NewClient(server.URL, "", "")
	c.AuthenticationMode = "trusted-tailnet"
	err = createWithPassword(context.Background(), c, map[string]string{"name": "test", "template": "desktop"}, "key", true, globalOptions{})
	if err == nil || !strings.Contains(err.Error(), "retained-desktop retained") || !strings.Contains(err.Error(), "credential setup incomplete") || strings.Contains(err.Error(), secret) || len(calls) != 3 {
		t.Fatalf("wrong create failure: %v calls=%v", err, calls)
	}
}
