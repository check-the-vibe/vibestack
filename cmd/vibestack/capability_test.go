package main

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

func TestGenericCapabilityUsesCurrentServerRegistryWithoutReplay(t *testing.T) {
	var calls int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Header.Get("Authorization") != "Bearer fixture" || r.Header.Get("X-VibeStack-Expected-Instance") != strings.Repeat("a", 32) {
			t.Error("missing credential or workspace pin")
		}
		if r.URL.Path == "/api/v1/capabilities" || r.URL.Path == "/api/capabilities.openapi.json" {
			io.WriteString(w, `{"capabilities":[{"id":"user_added"}]}`)
			return
		}
		if r.Method != "POST" || r.URL.Path != "/api/v1/capabilities/user_added/invoke" {
			t.Error("wrong generic invocation")
		}
		data, _ := io.ReadAll(r.Body)
		if string(data) != `{"value":1,"value":2}` {
			t.Error("duplicate-key evidence was changed before server validation")
		}
		w.WriteHeader(409)
		io.WriteString(w, `{"request_id":"fixture-request","error":{"code":"conflict","message":"Changed before commit.","retryable":false}}`)
	}))
	defer server.Close()
	client, _ := api.NewClient(server.URL, "fixture", "")
	client.ExpectedIdentity = strings.Repeat("a", 32)
	profile := api.Profile{Kind: "workspace"}
	for _, action := range []string{"list", "schema"} {
		if err := capabilityCommand(context.Background(), client, profile, []string{action}, globalOptions{}); err != nil {
			t.Fatal(err)
		}
	}
	input := filepath.Join(t.TempDir(), "input.json")
	os.WriteFile(input, []byte(`{"value":1,"value":2}`), 0600)
	err := capabilityCommand(context.Background(), client, profile, []string{"call", "user_added", "--input", input}, globalOptions{})
	var remote *api.HTTPError
	if !errors.As(err, &remote) || remote.Code != "conflict" || remote.RequestID != "fixture-request" || remote.Retryable || calls != 3 {
		t.Fatalf("unexpected conflict/replay: calls=%d err=%v", calls, err)
	}
	for _, args := range [][]string{{"call", "../escape"}, {"call", "user_added", "unexpected"}} {
		if capabilityCommand(context.Background(), client, profile, args, globalOptions{}) == nil {
			t.Fatal("invalid CLI accepted")
		}
	}
	if calls != 3 {
		t.Fatal("invalid input reached server")
	}
}

func TestCapabilityInputRejectsNonObjectsAndSpecialFiles(t *testing.T) {
	file := filepath.Join(t.TempDir(), "input")
	client, _ := api.NewClient("https://unused.example", "fixture", "")
	for _, input := range []string{"[]", "null", "{} {}", ""} {
		os.WriteFile(file, []byte(input), 0600)
		if capabilityCommand(context.Background(), client, api.Profile{Kind: "workspace"}, []string{"call", "example", "--input", file}, globalOptions{}) == nil {
			t.Fatal("bad input accepted")
		}
	}
	fifo := filepath.Join(t.TempDir(), "fifo")
	if err := syscall.Mkfifo(fifo, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readInputFile(fifo, 32); err == nil {
		t.Fatal("FIFO accepted")
	}
	os.WriteFile(file, []byte(strings.Repeat("x", 33)), 0600)
	if _, err := readInputFile(file, 32); err == nil {
		t.Fatal("oversized file accepted")
	}
}
