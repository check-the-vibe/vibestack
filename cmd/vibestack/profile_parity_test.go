package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"
	"time"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/check-the-vibe/vibestack/service"
)

// Run real CLI subprocesses against independent service stores and real compiled
// project_summary handlers. No mocked dispatcher or shared global destination.
func TestConcurrentCLIProfilesKeepWorkspaceAuthority(t *testing.T) {
	profiles := api.ProfileFile{Version: 1, Profiles: map[string]api.Profile{}}
	for i, name := range []string{"alpha", "beta"} {
		state := t.TempDir()
		if err := os.Chmod(state, 0700); err != nil {
			t.Fatal(err)
		}
		store, err := service.NewStore(state)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { store.Close() })
		_, token, err := store.Issue("parity fixture", false, []string{"project_summary"}, time.Hour)
		if err != nil {
			t.Fatal(err)
		}
		projects := t.TempDir()
		project := filepath.Join(projects, "same")
		if err := os.Mkdir(project, 0700); err != nil {
			t.Fatal(err)
		}
		for n := 0; n <= i; n++ {
			if err := os.WriteFile(filepath.Join(project, fmt.Sprintf("file-%d", n)), []byte("fixture"), 0600); err != nil {
				t.Fatal(err)
			}
		}
		server, err := service.NewServer(service.Config{
			Store: store, StaticRoot: t.TempDir(), ProjectsRoot: projects,
			AutomationURL: "http://127.0.0.1:1", ControlURL: "http://127.0.0.1:1", SetupURL: "http://127.0.0.1:1",
		})
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { server.Close() })
		httpServer := httptest.NewServer(server)
		t.Cleanup(httpServer.Close)
		profiles.Profiles[name] = api.Profile{Name: name, Kind: "workspace", URL: httpServer.URL, Identity: store.Identity, Credential: token, AuthenticationMode: "paired"}
	}
	root := t.TempDir()
	config := filepath.Join(root, "private", "profiles.json")
	t.Setenv("VIBESTACK_CONFIG", config)
	if err := api.SaveProfiles(profiles); err != nil {
		t.Fatal(err)
	}
	input := filepath.Join(root, "input.json")
	if err := os.WriteFile(input, []byte(`{"project":"same"}`), 0600); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(root, "vibestack")
	build := exec.Command("go", "build", "-buildvcs=false", "-o", binary, ".")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("CLI fixture build: %s", output)
	}
	invoke := func(profile, capability string) ([]byte, error) {
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		command := exec.CommandContext(ctx, binary, "--profile", profile, "capability", "call", capability, "--input", input)
		command.Env = append(os.Environ(), "VIBESTACK_CONFIG="+config)
		return command.Output()
	}
	var wait sync.WaitGroup
	for i := 0; i < 12; i++ {
		wait.Add(1)
		go func(index int) {
			defer wait.Done()
			name, count := "alpha", 1
			if index%2 == 1 {
				name, count = "beta", 2
			}
			data, err := invoke(name, "project_summary")
			if err != nil {
				t.Errorf("concurrent CLI invocation failed: %v", err)
				return
			}
			var result struct {
				Instance string `json:"instance_id"`
				Result   struct {
					Count int `json:"entry_count"`
				} `json:"result"`
			}
			if json.Unmarshal(data, &result) != nil || result.Instance != profiles.Profiles[name].Identity || result.Result.Count != count {
				t.Error("profile request reached another workspace or lost its result")
			}
		}(i)
	}
	wait.Wait()
	bad := profiles.Profiles["alpha"]
	bad.Name, bad.Identity = "wrong-instance", profiles.Profiles["beta"].Identity
	profiles.Profiles[bad.Name] = bad
	if err := api.SaveProfiles(profiles); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		profile, capability string
		exit                int
	}{
		{"wrong-instance", "project_summary", 6},
		{"alpha", "workspaceStatus", 4},
	} {
		_, err := invoke(tc.profile, tc.capability)
		exit, ok := err.(*exec.ExitError)
		if !ok || exit.ExitCode() != tc.exit {
			t.Errorf("incorrect denied request exit: %v", err)
		}
	}
}
