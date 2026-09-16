package vibestack

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestClientURLPolicy(t *testing.T) {
	for _, raw := range []string{"http://example.com", "https://example.com/prefix", "https://user@example.com", "ftp://example.com"} {
		if _, err := NewClient(raw, "", ""); err == nil {
			t.Errorf("unsafe URL was accepted: %s", raw)
		}
	}
	for _, raw := range []string{"http://127.0.0.1:8080", "http://[::1]:8080", "https://workspace.example"} {
		if _, err := NewClient(raw, "", ""); err != nil {
			t.Errorf("valid URL %s: %v", raw, err)
		}
	}
}

func TestCredentialIsNotForwardedAcrossOriginRedirect(t *testing.T) {
	targetHit := false
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		targetHit = true
		if r.Header.Get("Authorization") != "" {
			t.Error("credential reached redirect target")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer target.Close()
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL+"/stolen", http.StatusFound)
	}))
	defer source.Close()
	client, err := NewClient(source.URL, "secret-credential", "")
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.Do(context.Background(), http.MethodGet, "/start", nil, "", true, nil)
	var remote *HTTPError
	if !errors.As(err, &remote) || remote.Status != http.StatusFound {
		t.Fatalf("expected redirect to be returned as an HTTP error, got %v", err)
	}
	if targetHit {
		t.Fatal("cross-origin redirect was followed")
	}
}

func TestProfileFileIsPrivateAndSelectionIsExplicit(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config", "profiles.json")
	t.Setenv("VIBESTACK_CONFIG", path)
	value := ProfileFile{Version: 1, Profiles: map[string]Profile{
		"one": {Name: "one", Kind: "workspace", URL: "https://one.example", Credential: "secret-one"},
		"two": {Name: "two", Kind: "workspace", URL: "https://two.example", Credential: "secret-two"},
	}}
	if err := SaveProfiles(value); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("profile mode=%v err=%v", info.Mode().Perm(), err)
	}
	if _, err := SelectProfile("", "workspace"); err == nil {
		t.Fatal("ambiguous profiles were selected silently")
	}
	selected, err := SelectProfile("two", "workspace")
	if err != nil || selected.URL != "https://two.example" {
		t.Fatalf("explicit selection: %#v err=%v", selected, err)
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadProfiles(); err == nil {
		t.Fatal("world-readable credential file was accepted")
	}
}

func TestSaveProfilesRejectsAnUnsafeContainingDirectory(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "config")
	if err := os.Mkdir(dir, 0755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "profiles.json")
	t.Setenv("VIBESTACK_CONFIG", path)
	value := ProfileFile{Version: 1, Profiles: map[string]Profile{}}
	if err := SaveProfiles(value); err == nil {
		t.Fatal("profile state was written into a group/world-readable directory")
	}
}
