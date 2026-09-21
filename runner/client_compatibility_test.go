package runner

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type compatibilityAuth struct{ token string }

func (a compatibilityAuth) RoundTrip(r *http.Request) (*http.Response, error) {
	r = r.Clone(r.Context())
	if a.token != "" {
		r.Header.Set("Authorization", "Bearer "+a.token)
	}
	return http.DefaultTransport.RoundTrip(r)
}

// Acceptance supplies the actual pinned historical/current CLI executables.
// The runner has no Docker manager in this fixture and cannot mutate a host.
func TestHistoricalCLIWithPrivateRunner(t *testing.T) {
	old, current := os.Getenv("VIBESTACK_LEGACY_CLI"), os.Getenv("VIBESTACK_COMPAT_CURRENT_CLI")
	if old == "" || current == "" {
		t.Skip("requires explicit historical and current native CLI paths")
	}
	if !filepath.IsAbs(old) || !filepath.IsAbs(current) {
		t.Fatal("CLI fixtures must be absolute paths")
	}
	for _, mode := range []string{AuthPaired, AuthTrustedTailnet} {
		t.Run(mode, func(t *testing.T) {
			state := filepath.Join(t.TempDir(), "state")
			store, err := OpenStore(state)
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			cfg := DefaultConfig()
			cfg.AuthenticationMode = mode
			server := NewServer(cfg, store, nil)
			owner, credential := server.sharedPrincipal, ""
			if mode == AuthPaired {
				owner = strings.Repeat("a", 32)
				credential, err = randomID()
				if err != nil {
					t.Fatal(err)
				}
				_, err = store.db.Exec(`INSERT INTO clients(id,label,permissions_json,credential_hash,created_at) VALUES(?,?,?,?,?)`, owner, "compatibility fixture", `["instances:read","instances:write"]`, HashCredential(credential), nowISO())
				if err != nil {
					t.Fatal(err)
				}
			}
			instance := api.Instance{ID: strings.Repeat("b", 32), Name: "compatibility-fixture", Owner: owner, Ports: map[string]int{}, URLs: map[string]string{}, CreatedAt: nowISO(), UpdatedAt: nowISO()}
			if err := store.CreateInstance(context.Background(), instance, "fixture-data", "fixture-projects", map[string]any{}); err != nil {
				t.Fatal(err)
			}
			identity, err := store.Identity(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			profileFile := filepath.Join(t.TempDir(), "profiles.json")
			for round := 0; round < 2; round++ {
				if round == 1 {
					store, err = OpenStore(state)
					if err != nil {
						t.Fatal(err)
					}
					defer store.Close()
					server = NewServer(cfg, store, nil)
				}
				host := httptest.NewServer(server.HTTP.Handler)
				defer host.Close()
				server.Config.Listen = strings.TrimPrefix(host.URL, "http://")
				server.Config.PublicURL = host.URL
				gotIdentity, err := store.Identity(context.Background())
				if err != nil || gotIdentity != identity {
					t.Fatal("runner identity changed across reopen")
				}
				profiles := api.ProfileFile{Version: 1, Profiles: map[string]api.Profile{"fixture": {Name: "fixture", Kind: "runner", AuthenticationMode: mode, Identity: identity, URL: host.URL, Credential: credential}}}
				data, _ := json.Marshal(profiles)
				if err := os.WriteFile(profileFile, data, 0600); err != nil {
					t.Fatal(err)
				}
				for _, binary := range []string{old, current} {
					ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
					command := exec.CommandContext(ctx, binary, "--profile", "fixture", "--json", "instances", "list")
					command.Env = []string{"PATH=" + os.Getenv("PATH"), "VIBESTACK_CONFIG=" + profileFile}
					output, err := command.Output()
					cancel()
					if err != nil || credential != "" && strings.Contains(string(output), credential) {
						t.Fatal("historical/current runner CLI failed or disclosed its fixture credential")
					}
					var value struct {
						Instances []api.Instance `json:"instances"`
					}
					if json.Unmarshal(output, &value) != nil || len(value.Instances) != 1 || value.Instances[0].ID != instance.ID {
						t.Fatal("runner CLI lost its owned resource across restart")
					}
				}
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				client := mcp.NewClient(&mcp.Implementation{Name: "runner-compatibility", Version: "1"}, nil)
				session, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: host.URL + "/mcp", MaxRetries: -1, DisableStandaloneSSE: true, HTTPClient: &http.Client{Timeout: 5 * time.Second, Transport: compatibilityAuth{credential}}}, nil)
				if err != nil {
					cancel()
					t.Fatal("private runner MCP connection failed")
				}
				value, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "instances_list", Arguments: map[string]any{}})
				if err != nil || value.IsError {
					t.Fatal("private runner MCP operation failed")
				}
				session.Close()
				cancel()
				host.Close()
				store.Close()
			}
		})
	}
}
