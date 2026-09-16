package runner

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

func testOperation(id, key string) api.Operation {
	now := nowISO()
	return api.Operation{ID: id, Kind: "create", Status: "queued", IdempotencyKey: key, RequestID: "request", CreatedAt: now, UpdatedAt: now}
}

func TestOperationIdempotencyIsScopedToOwnerAndListingDoesNotDeadlock(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	first, duplicate, err := store.CreateOperation(ctx, testOperation("11111111111111111111111111111111", "retry-key"), "owner-a", map[string]string{"name": "one"})
	if err != nil || duplicate {
		t.Fatalf("first operation: duplicate=%v err=%v", duplicate, err)
	}
	_, duplicate, err = store.CreateOperation(ctx, testOperation("22222222222222222222222222222222", "retry-key"), "owner-b", map[string]string{"name": "two"})
	if err != nil || duplicate {
		t.Fatalf("second owner should have an independent key: duplicate=%v err=%v", duplicate, err)
	}
	retried, duplicate, err := store.CreateOperation(ctx, testOperation("33333333333333333333333333333333", "retry-key"), "owner-a", map[string]string{"name": "ignored"})
	if err == nil || duplicate || retried.ID != "" {
		t.Fatalf("mismatched retry should be rejected: %#v duplicate=%v err=%v", retried, duplicate, err)
	}
	retried, duplicate, err = store.CreateOperation(ctx, testOperation("44444444444444444444444444444444", "retry-key"), "owner-a", map[string]string{"name": "one"})
	if err != nil || !duplicate || retried.ID != first.ID {
		t.Fatalf("retry did not return original operation: %#v duplicate=%v err=%v", retried, duplicate, err)
	}
	values, err := store.OperationsOwned(ctx, "owner-a")
	if err != nil || len(values) != 1 || values[0].ID != first.ID {
		t.Fatalf("owned listing: %#v err=%v", values, err)
	}
	all, err := store.Operations(ctx)
	if err != nil || len(all) != 2 {
		t.Fatalf("all listing: %#v err=%v", all, err)
	}
}

func TestRunnerPairingCredentialIsOneTimeAndRevocable(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	ctx := context.Background()
	requested, err := store.RequestPairing(ctx, "agent laptop", []string{"instances:read", "instances:write"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.ApprovePairing(ctx, requested.VerificationCode, true); err != nil {
		t.Fatal(err)
	}
	delivered, err := store.PollPairing(ctx, requested.PairingID, requested.PollingSecret)
	if err != nil || delivered.Credential == "" {
		t.Fatalf("delivery: %#v err=%v", delivered, err)
	}
	clientID, permissions, ok := store.Authenticate(ctx, delivered.Credential)
	if !ok || clientID != delivered.ClientID || len(permissions) != 2 {
		t.Fatalf("authentication: id=%q permissions=%v ok=%v", clientID, permissions, ok)
	}
	if _, err := store.PollPairing(ctx, requested.PairingID, requested.PollingSecret); err == nil {
		t.Fatal("credential was delivered twice")
	}
	if err := store.RevokeClient(ctx, delivered.ClientID); err != nil {
		t.Fatal(err)
	}
	if _, _, ok := store.Authenticate(ctx, delivered.Credential); ok {
		t.Fatal("revoked credential still authenticated")
	}
}

func TestWorkspaceProxyRouteAllowlist(t *testing.T) {
	accepted := [][2]string{
		{"GET", "/api/v1/automation"},
		{"POST", "/api/v1/automation/commands"},
		{"GET", "/api/v1/automation/projects/a.txt"},
		{"PUT", "/api/v1/automation/files/a.bin"},
		{"POST", "/api/v1/services/editor/start"},
	}
	for _, item := range accepted {
		if !allowedWorkspaceRoute(item[0], item[1]) {
			t.Errorf("expected route to be accepted: %v", item)
		}
	}
	for _, item := range [][2]string{{"POST", "/api/v1/automation/pairing/requests"}, {"GET", "/setup/api/state"}, {"GET", "http://attacker/"}, {"DELETE", "/api/v1/automation/files/a"}} {
		if allowedWorkspaceRoute(item[0], item[1]) {
			t.Errorf("expected route to be rejected: %v", item)
		}
	}
}

func TestResourceRequestsAreOperatorBounded(t *testing.T) {
	manager := &Manager{Config: DefaultConfig()}
	if err := manager.validateResources(ResourceRequest{MemoryBytes: manager.Config.MaxMemoryBytes + 1}); err == nil {
		t.Fatal("oversized memory request was accepted")
	}
	if err := manager.validateResources(ResourceRequest{PIDs: 127}); err == nil {
		t.Fatal("undersized PID limit was accepted")
	}
	if err := manager.validateResources(ResourceRequest{}); err != nil {
		t.Fatal(err)
	}
	if err := validateRequestedPorts(map[string]int{"docker": 12345}); err == nil {
		t.Fatal("unknown port purpose was accepted")
	}
	if validIdempotencyKey("line\nbreak") {
		t.Fatal("control-bearing idempotency key was accepted")
	}
}
