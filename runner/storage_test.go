package runner

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

func storageTestStore(t *testing.T) (*Store, string, string) {
	t.Helper()
	s, err := OpenStore(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	a := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	b := "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	for _, id := range []string{a, b} {
		_, err = s.db.Exec(`INSERT INTO clients VALUES(?,?,?,?,?,NULL)`, id, id, `["instances:read","instances:write"]`, HashCredential(id), nowISO())
		if err != nil {
			t.Fatal(err)
		}
	}
	return s, a, b
}
func TestDriveOwnershipLeaseAtomicityAndRetention(t *testing.T) {
	s, a, b := storageTestStore(t)
	ctx := context.Background()
	first, err := s.RegisterDrive(ctx, "projects", a, "volume", "")
	if err != nil {
		t.Fatal(err)
	}
	second, err := s.RegisterDrive(ctx, "files", a, "volume", "")
	if err != nil {
		t.Fatal(err)
	}
	if err := s.validateSelection(ctx, StorageSelection{ProjectDrive: first.ID}, b); err == nil {
		t.Fatal("cross-owner drive accepted")
	}
	v := StorageSelection{ProjectDrive: first.ID, FileDrives: []Attachment{{DriveID: second.ID, Name: "files"}}}
	if err := s.acquireDrives(ctx, "one", v); err != nil {
		t.Fatal(err)
	}
	if err := s.acquireDrives(ctx, "two", StorageSelection{ProjectDrive: second.ID}); err == nil {
		t.Fatal("active writable drive shared")
	}
	if err := s.releaseDrives(ctx, "one"); err != nil {
		t.Fatal(err)
	}
	if err := s.acquireDrives(ctx, "two", v); err != nil {
		t.Fatal(err)
	}
	if values, err := s.Drives(ctx, a); err != nil || len(values) != 2 {
		t.Fatalf("drive retention failed: %v", err)
	}
	for _, files := range [][]Attachment{{{DriveID: first.ID, Name: "same"}}, {{DriveID: second.ID, Name: "../escape"}}, {{DriveID: second.ID, Name: "projects"}}} {
		if err := s.validateSelection(ctx, StorageSelection{ProjectDrive: first.ID, FileDrives: files}, a); err == nil {
			t.Fatal("invalid mount accepted")
		}
	}
}
func TestEnvironmentOwnershipRedactionAndRuntimeProtection(t *testing.T) {
	s, a, b := storageTestStore(t)
	ctx := context.Background()
	secret := "private-test-value-never-report"
	v, err := s.AddEnvironment(ctx, "tools", a, map[string]string{"SERVICE_TOKEN": secret})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.environmentValues(ctx, v.ID, b); err == nil {
		t.Fatal("cross-owner environment read")
	}
	list, err := s.Environments(ctx, a)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(list)
	if strings.Contains(string(raw), secret) || !strings.Contains(string(raw), "SERVICE_TOKEN") {
		t.Fatal("unsafe environment report")
	}
	for _, key := range []string{"HOME", "VIBESTACK_ALLOWED_HOSTS", "VIBESTACK_API_TOKEN", "LD_PRELOAD", "BASH_ENV", "PYTHONPATH", "XDG_RUNTIME_DIR", "NODE_OPTIONS"} {
		if _, err := s.AddEnvironment(ctx, "blocked", a, map[string]string{key: secret}); err == nil || strings.Contains(err.Error(), secret) {
			t.Fatalf("unsafe key %s", key)
		}
	}
	cfg := DefaultConfig()
	cfg.PublicURL = "https://runner.example"
	server := NewServer(cfg, s, nil)
	result := runnerRequest(t, server, "GET", APIRoot+"/environment-sets", a, nil)
	if result.Code != 200 || strings.Contains(result.Body.String(), secret) {
		t.Fatal("unsafe API metadata")
	}
	result = runnerRequest(t, server, "POST", APIRoot+"/environment-sets", a, map[string]any{"name": "invalid", "values": map[string]string{"HOME": secret}})
	if result.Code != 409 || strings.Contains(result.Body.String(), secret) {
		t.Fatal("unsafe environment error")
	}
	result = runnerRequest(t, server, "POST", APIRoot+"/drives", a, map[string]string{"name": "evil", "source": "/root"})
	if result.Code != 400 {
		t.Fatal("remote path registration accepted")
	}
}
func TestLegacyVolumesMigrateWithoutMovingContents(t *testing.T) {
	s, a, _ := storageTestStore(t)
	ctx := context.Background()
	now := nowISO()
	i := api.Instance{ID: "cccccccccccccccccccccccccccccccc", Name: "legacy", Owner: a, Template: "desktop", ImageDigest: "sha256:test", DesiredState: "stopped", ObservedState: "stopped", CreatedAt: now, UpdatedAt: now}
	if err := s.CreateInstance(ctx, i, "legacy-data-volume", "legacy-projects-volume", map[string]any{}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`DELETE FROM metadata WHERE key='storage_migrated'`); err != nil {
		t.Fatal(err)
	}
	if err := s.migrateStorage(); err != nil {
		t.Fatal(err)
	}
	if err := s.migrateStorage(); err != nil {
		t.Fatal(err)
	}
	v, err := s.Selection(ctx, i.ID)
	if err != nil {
		t.Fatal(err)
	}
	d, err := s.drive(ctx, v.ProjectDrive, a)
	if err != nil || d.Source != "legacy-projects-volume" {
		t.Fatal("migration changed volume")
	}
	if err := s.MarkRemoved(ctx, i.ID); err != nil {
		t.Fatal(err)
	}
	drives, err := s.Drives(ctx, a)
	if err != nil || len(drives) != 2 {
		t.Fatal("remove lost drives")
	}
}
func TestDriveFolderValidationAndOverlap(t *testing.T) {
	s, a, _ := storageTestStore(t)
	ctx := context.Background()
	root := t.TempDir()
	folder := filepath.Join(root, "projects")
	if err := os.Mkdir(folder, 0700); err != nil {
		t.Fatal(err)
	}
	d, err := s.RegisterDrive(ctx, "host-projects", a, "bind", folder)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(d)
	if strings.Contains(string(raw), folder) {
		t.Fatal("host path leaked")
	}
	child := filepath.Join(folder, "child")
	os.Mkdir(child, 0700)
	if _, err := s.RegisterDrive(ctx, "overlap", a, "bind", child); err == nil {
		t.Fatal("overlapping folder accepted")
	}
	alias := filepath.Join(root, "alias")
	os.Symlink(folder, alias)
	if _, err := validateDriveFolder(alias); err == nil {
		t.Fatal("symlink alias accepted")
	}
	for _, path := range []string{"/", "/home", "/home/jarvis", "/etc", "/tmp", "/proc", "relative", "/tmp/../tmp"} {
		if _, err := validateDriveFolder(path); err == nil {
			t.Fatalf("unsafe folder accepted: %s", path)
		}
	}
}
func TestBrokerGuideUsesConfiguredOriginAndSafeDisclosure(t *testing.T) {
	s, _, _ := storageTestStore(t)
	cfg := DefaultConfig()
	cfg.PublicURL = "https://runner.example:10443"
	server := NewServer(cfg, s, nil)
	r := runnerRequest(t, server, "GET", "/AGENTS.md", "", nil)
	if r.Code != 200 || !strings.Contains(r.Body.String(), cfg.PublicURL) || !strings.Contains(r.Body.String(), "explicitly fetch") || !strings.Contains(r.Body.String(), "/snapshot") {
		t.Fatal("incomplete broker guide")
	}
	for _, path := range []string{"/host", "/drives", "/snapshots", "/environment-sets"} {
		r := runnerRequest(t, server, "GET", APIRoot+path, "", nil)
		if r.Code != 401 {
			t.Fatal("unauthenticated storage metadata exposed")
		}
	}
}

func TestPurgedDriveRegistrationIsNotResurrectedOnOpen(t *testing.T) {
	s, a, _ := storageTestStore(t)
	ctx := context.Background()
	i := api.Instance{ID: "dddddddddddddddddddddddddddddddd", Name: "retained", Owner: a, CreatedAt: nowISO(), UpdatedAt: nowISO()}
	if err := s.CreateInstance(ctx, i, "retained-data", "retained-projects", map[string]any{}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`DELETE FROM metadata WHERE key='storage_migrated'`); err != nil {
		t.Fatal(err)
	}
	if err := s.migrateStorage(); err != nil {
		t.Fatal(err)
	}
	if err := s.MarkRemoved(ctx, i.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`DELETE FROM drives WHERE id=?`, i.ID+"-projects"); err != nil {
		t.Fatal(err)
	}
	if err := s.migrateStorage(); err != nil {
		t.Fatal(err)
	}
	if _, err := s.drive(ctx, i.ID+"-projects", a); err == nil {
		t.Fatal("purged drive resurrected")
	}
}
