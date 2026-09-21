package providers

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// Run only in a clean, network-disabled probe container. Do not run this
// against a developer's existing provider home or account.
func TestPinnedCodexHandshakeWithoutAccount(t *testing.T) {
	if os.Getenv("VIBESTACK_PROVIDER_PROBE_DISPOSABLE") != "1" {
		t.Skip("requires the explicit disposable provider-probe environment")
	}
	binary := os.Getenv("VIBESTACK_CODEX_TEST_BINARY")
	if !filepath.IsAbs(binary) {
		t.Fatal("requires an absolute pinned test executable")
	}
	cmd := exec.Command(binary, "app-server", "--listen", "stdio://")
	cmd.Dir = t.TempDir()
	cmd.Stderr = io.Discard
	in, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	out, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal("pinned provider could not start")
	}
	t.Cleanup(func() { cmd.Process.Kill(); cmd.Wait() })
	c := newRPC(in, out)
	t.Cleanup(func() { c.stop(ErrDisconnected) })
	_, err = c.call(deadline(t), "initialize", map[string]any{"clientInfo": map[string]string{"name": "vibestack-protocol-probe", "version": "1"}, "capabilities": map[string]bool{"experimentalApi": false}})
	if err != nil {
		t.Fatal("pinned provider initialization failed")
	}
	if err := c.notify(deadline(t), "initialized", map[string]any{}); err != nil {
		t.Fatal(err)
	}
	value, err := c.call(deadline(t), "account/read", map[string]bool{"refreshToken": false})
	if err != nil {
		t.Fatal("pinned provider account-state method failed")
	}
	var state struct {
		RequiresAuth bool            `json:"requiresOpenaiAuth"`
		Account      json.RawMessage `json:"account"`
	}
	if json.Unmarshal(value, &state) != nil || !state.RequiresAuth || (len(state.Account) != 0 && string(state.Account) != "null") {
		t.Fatal("clean fixture did not report missing human authentication")
	}
	t.Log("real pinned stdio handshake and absent-account state passed without a model call")
}

func TestPinnedProductionAdaptersWithoutAccount(t *testing.T) {
	if os.Getenv("VIBESTACK_PROVIDER_PROBE_DISPOSABLE") != "1" {
		t.Skip("requires a clean disposable container")
	}
	for _, provider := range []string{"codex", "opencode"} {
		t.Run(provider, func(t *testing.T) {
			variable := "VIBESTACK_CODEX_TEST_BINARY"
			if provider == "opencode" {
				variable = "VIBESTACK_OPENCODE_TEST_BINARY"
			}
			binary := os.Getenv(variable)
			if !filepath.IsAbs(binary) {
				t.Fatal("absolute pinned executable required")
			}
			ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
			defer cancel()
			var adapter agentRuntime
			var err error
			if provider == "codex" {
				adapter, err = startCodex(ctx, binary, t.TempDir())
			} else {
				adapter, err = startOpenCode(ctx, binary, t.TempDir())
			}
			if err != nil {
				t.Fatal("production adapter startup failed:", err)
			}
			defer adapter.Close()
			state, err := adapter.Status(ctx)
			if err != nil {
				t.Fatal("native status failed:", err)
			}
			if provider == "codex" {
				if state.Authentication != "needs_sign_in" || len(state.Models) != 0 {
					t.Fatal("clean Codex account was not absent")
				}
			} else {
				r := adapter.(*openCodeRuntime)
				request, _ := http.NewRequestWithContext(ctx, "GET", r.origin+"/global/health", nil)
				response, err := r.client.Do(request)
				if err != nil {
					t.Fatal("unauthenticated probe failed")
				}
				response.Body.Close()
				if response.StatusCode != 401 {
					t.Fatal("OpenCode private listener accepted an unauthenticated caller")
				}
				if len(state.Models) == 0 {
					t.Fatal("expected the pinned runtime's built-in model catalog")
				}
				project := t.TempDir()
				session, err := r.Create(ctx, project, state.Models[0].ID)
				if err != nil {
					t.Fatal("real native session creation failed:", err)
				}
				if err = r.Resume(ctx, session, project, state.Models[0].ID); err != nil {
					t.Fatal("real native session resume failed:", err)
				}
				var saved struct {
					Permission []struct {
						Permission string `json:"permission"`
						Pattern    string `json:"pattern"`
						Action     string `json:"action"`
					} `json:"permission"`
				}
				if err = r.request(ctx, "GET", "/session/"+session, project, nil, &saved); err != nil {
					t.Fatal(err)
				}
				if len(saved.Permission) != 1 || saved.Permission[0].Permission != "*" || saved.Permission[0].Pattern != "*" || saved.Permission[0].Action != "ask" {
					t.Fatal("session did not retain explicit human approval policy")
				}
			}
			t.Log("exact native adapter startup, safe status and private transport passed without a model call")
		})
	}
}
