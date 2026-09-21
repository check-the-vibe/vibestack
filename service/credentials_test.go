package service

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func testStore(t *testing.T) (*Store, string) {
	t.Helper()
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	s, err := NewStore(root)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s, root
}

func issue(t *testing.T, s *Store, owner bool, caps ...string) (Credential, string) {
	t.Helper()
	c, token, err := s.Issue("test client", owner, caps, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	return c, token
}

func TestCredentialsPersistWithoutPlaintextAndRevokeAcrossStores(t *testing.T) {
	s, root := testStore(t)
	c, token := issue(t, s, true)
	data, err := os.ReadFile(filepath.Join(root, "service-credentials.json"))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), token) || c.Hash != "" {
		t.Fatal("credential plaintext/hash leaked through public delivery metadata")
	}
	other, err := NewStore(root)
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	if other.Identity != s.Identity {
		t.Fatal("identity changed on restart")
	}
	p, err := other.Authenticate(token)
	if err != nil || !p.Owner || p.InstanceID != s.Identity {
		t.Fatalf("persisted auth: %v %v", p, err)
	}
	if err := s.Revoke(c.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := other.Authenticate(token); !errors.Is(err, ErrUnauthenticated) {
		t.Fatalf("revocation not applied: %v", err)
	}
	if _, err := other.authenticateDigest(p.digest); !errors.Is(err, ErrUnauthenticated) {
		t.Fatalf("session bypassed revocation: %v", err)
	}
	list, err := s.List()
	if err != nil || len(list) != 1 || list[0].Hash != "" || list[0].RevokedAt == 0 {
		t.Fatalf("unsafe list: %v", err)
	}
}

func TestCredentialInstanceExpiryAndCapabilityGrants(t *testing.T) {
	s, _ := testStore(t)
	other, _ := testStore(t)
	_, token := issue(t, s, false, "workspaceStatus")
	p, err := s.Authenticate(token)
	if err != nil {
		t.Fatal(err)
	}
	if !p.Allows("workspaceStatus", false) || p.Allows("submitArgvCommand", false) || p.Allows("workspaceStatus", true) {
		t.Fatal("capability or owner grant escaped")
	}
	if _, err := other.Authenticate(token); !errors.Is(err, ErrUnauthenticated) {
		t.Fatalf("accepted other instance token: %v", err)
	}
	s.now = func() time.Time { return time.Now().Add(2 * time.Hour) }
	if _, err := s.Authenticate(token); !errors.Is(err, ErrUnauthenticated) {
		t.Fatalf("accepted expired token: %v", err)
	}
}

func TestLegacyClientsRemainWorkspaceOnlyAndObserveRotation(t *testing.T) {
	s, root := testStore(t)
	legacyToken := strings.Repeat("l", 43)
	if err := os.WriteFile(filepath.Join(root, "automation.token"), []byte(legacyToken+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	p, err := s.Authenticate(legacyToken)
	if err != nil || p.Owner || !p.Allows("submitArgvCommand", false) {
		t.Fatalf("legacy auth: %v", err)
	}
	if err := os.WriteFile(filepath.Join(root, "automation.token"), []byte(strings.Repeat("n", 43)+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.authenticateDigest(p.digest); !errors.Is(err, ErrUnauthenticated) {
		t.Fatal("legacy rotation did not invalidate session")
	}
	token := "vsw_" + strings.Repeat("b", 64)
	client := map[string]any{"id": strings.Repeat("a", 32), "credential_hash": tokenDigest(token), "permissions": []string{"workspace"}, "revoked_at": nil}
	write := func() {
		t.Helper()
		data, _ := json.Marshal(map[string]any{"version": 1, "clients": []any{client}})
		if err := os.WriteFile(filepath.Join(root, "client-credentials.json"), data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	write()
	p, err = s.Authenticate(token)
	if err != nil || p.Owner {
		t.Fatalf("paired auth: %v", err)
	}
	client["revoked_at"] = time.Now().Unix()
	write()
	if _, err := s.Authenticate(token); !errors.Is(err, ErrUnauthenticated) {
		t.Fatal("paired revocation ignored")
	}
}

func TestCredentialFilesRejectUnsafeModesLinksAndMalformedState(t *testing.T) {
	for _, mode := range []string{"permissions", "symlink", "hardlink", "malformed", "directory"} {
		t.Run(mode, func(t *testing.T) {
			s, root := testStore(t)
			_, token := issue(t, s, false)
			name := filepath.Join(root, "service-credentials.json")
			switch mode {
			case "permissions":
				if err := os.Chmod(name, 0644); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.Rename(name, name+".original"); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(name+".original", name); err != nil {
					t.Fatal(err)
				}
			case "hardlink":
				if err := os.Link(name, name+".copy"); err != nil {
					t.Fatal(err)
				}
			case "malformed":
				if err := os.WriteFile(name, []byte("{"), 0600); err != nil {
					t.Fatal(err)
				}
			case "directory":
				if err := os.Remove(name); err != nil {
					t.Fatal(err)
				}
				if err := os.Mkdir(name, 0700); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := s.Authenticate(token); !errors.Is(err, ErrUnsafeState) {
				t.Fatalf("unsafe state accepted: %v", err)
			}
		})
	}
}

func TestConcurrentIssuanceDoesNotLoseCredentials(t *testing.T) {
	s, root := testStore(t)
	other, err := NewStore(root)
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			store := s
			if i%2 == 0 {
				store = other
			}
			if _, _, err := store.Issue("concurrent", false, nil, time.Hour); err != nil {
				t.Error(err)
			}
		}(i)
	}
	wg.Wait()
	list, err := s.List()
	if err != nil || len(list) != 20 {
		t.Fatalf("lost credentials: count=%d error=%v", len(list), err)
	}
}
