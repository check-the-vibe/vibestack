package runner

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/docker/docker/api/types/mount"
)

type Drive struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Owner     string `json:"owner"`
	Kind      string `json:"kind"`
	Role      string `json:"role"`
	Source    string `json:"-"`
	CreatedAt string `json:"created_at"`
}
type Attachment struct {
	DriveID  string `json:"drive_id"`
	Name     string `json:"name"`
	ReadOnly bool   `json:"read_only"`
}
type StorageSelection struct {
	ProjectDrive   string       `json:"project_drive,omitempty"`
	FileDrives     []Attachment `json:"file_drives,omitempty"`
	EnvironmentSet string       `json:"environment_set,omitempty"`
	StateSeed      string       `json:"state_seed,omitempty"`
}
type EnvironmentSet struct {
	ID   string   `json:"id"`
	Name string   `json:"name"`
	Keys []string `json:"keys"`
}
type Snapshot struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Owner       string `json:"owner"`
	InstanceID  string `json:"instance_id"`
	Volume      string `json:"-"`
	ImageDigest string `json:"image_digest"`
	Flatpak     bool   `json:"flatpak"`
	Status      string `json:"status"`
	CreatedAt   string `json:"created_at"`
}

func (s *Store) migrateStorage() error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	_, err = tx.Exec(`
CREATE TABLE IF NOT EXISTS drives(id TEXT PRIMARY KEY,name TEXT NOT NULL,owner TEXT NOT NULL,kind TEXT NOT NULL,role TEXT NOT NULL,source TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,UNIQUE(owner,name));
CREATE TABLE IF NOT EXISTS instance_storage(instance_id TEXT PRIMARY KEY,selection_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drive_leases(drive_id TEXT PRIMARY KEY,instance_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS environment_sets(id TEXT PRIMARY KEY,name TEXT NOT NULL,owner TEXT NOT NULL,values_json TEXT NOT NULL,UNIQUE(owner,name));
CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,name TEXT NOT NULL,owner TEXT NOT NULL,instance_id TEXT NOT NULL,volume TEXT NOT NULL UNIQUE,image_digest TEXT NOT NULL,flatpak INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(owner,name));
INSERT OR IGNORE INTO drives SELECT id||'-data',name||'-state',owner,'volume','state',data_volume,created_at FROM instances WHERE NOT EXISTS (SELECT 1 FROM metadata WHERE key='storage_migrated');
INSERT OR IGNORE INTO drives SELECT id||'-projects',name||'-projects',owner,'volume','files',projects_volume,created_at FROM instances WHERE NOT EXISTS (SELECT 1 FROM metadata WHERE key='storage_migrated');
INSERT OR IGNORE INTO instance_storage SELECT id,json_object('project_drive',id||'-projects') FROM instances WHERE NOT EXISTS (SELECT 1 FROM metadata WHERE key='storage_migrated');
INSERT OR IGNORE INTO metadata(key,value) VALUES('storage_migrated','1');

`)
	if err != nil {
		return err
	}
	return tx.Commit()
}
func (s *Store) Drives(ctx context.Context, owner string) ([]Drive, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,name,owner,kind,role,source,created_at FROM drives WHERE owner=? ORDER BY name`, owner)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []Drive{}
	for rows.Next() {
		var d Drive
		if err := rows.Scan(&d.ID, &d.Name, &d.Owner, &d.Kind, &d.Role, &d.Source, &d.CreatedAt); err != nil {
			return nil, err
		}
		result = append(result, d)
	}
	return result, rows.Err()
}
func (s *Store) drive(ctx context.Context, id, owner string) (Drive, error) {
	var d Drive
	err := s.db.QueryRowContext(ctx, `SELECT id,name,owner,kind,role,source,created_at FROM drives WHERE id=? AND owner=?`, id, owner).Scan(&d.ID, &d.Name, &d.Owner, &d.Kind, &d.Role, &d.Source, &d.CreatedAt)
	return d, err
}
func (s *Store) RegisterDrive(ctx context.Context, name, owner, kind, source string) (Drive, error) {
	if !validInstanceName(name) || !idPattern.MatchString(owner) {
		return Drive{}, errors.New("invalid drive name or owner")
	}
	var exists int
	if err := s.db.QueryRowContext(ctx, `SELECT (SELECT COUNT(*) FROM clients WHERE id=? AND revoked_at IS NULL) + (SELECT COUNT(*) FROM metadata WHERE key='shared_principal' AND value=? AND EXISTS (SELECT 1 FROM metadata WHERE key='authentication_mode' AND value='trusted-tailnet'))`, owner, owner).Scan(&exists); err != nil || exists != 1 {
		return Drive{}, errors.New("active owner is required")
	}
	id, err := randomID()
	if err != nil {
		return Drive{}, err
	}
	if kind == "volume" {
		source = "vibestack-drive-" + id
	} else if kind == "bind" {
		source, err = validateDriveFolder(source)
		if err != nil {
			return Drive{}, err
		}
	} else {
		return Drive{}, errors.New("invalid drive kind")
	}
	// Reject aliases and overlapping bind roots so IDs cannot bypass writer leases.
	rows, err := s.db.QueryContext(ctx, `SELECT source FROM drives WHERE kind='bind'`)
	if err != nil {
		return Drive{}, err
	}
	for rows.Next() {
		var other string
		if err = rows.Scan(&other); err != nil {
			break
		}
		if kind == "bind" && (withinPath(source, other) || withinPath(other, source)) {
			err = errors.New("drive folder overlaps a registered drive")
			break
		}
	}
	rows.Close()
	if err != nil {
		return Drive{}, err
	}
	d := Drive{ID: id, Name: name, Owner: owner, Kind: kind, Role: "files", Source: source, CreatedAt: nowISO()}
	_, err = s.db.ExecContext(ctx, `INSERT INTO drives VALUES(?,?,?,?,?,?,?)`, d.ID, d.Name, d.Owner, d.Kind, d.Role, d.Source, d.CreatedAt)
	if err != nil {
		return Drive{}, errors.New("drive name or source is already registered")
	}
	return d, nil
}
func withinPath(path, root string) bool {
	return path == root || strings.HasPrefix(path, root+string(filepath.Separator))
}
func validateDriveFolder(path string) (string, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return "", errors.New("drive folder must be a dedicated canonical absolute directory")
	}
	real, err := filepath.EvalSymlinks(path)
	if err != nil || real != path {
		return "", errors.New("drive folder must exist without symlink components")
	}
	info, err := os.Stat(path)
	if err != nil || !info.IsDir() {
		return "", errors.New("drive folder must be a directory")
	}
	for _, root := range []string{"/", "/home", "/tmp", "/mnt", "/srv", "/media"} {
		if path == root {
			return "", errors.New("drive folder is too broad")
		}
	}
	for _, root := range []string{"/etc", "/proc", "/sys", "/dev", "/run", "/var", "/root", "/usr", "/bin", "/sbin", "/boot", "/lib", "/lib64", "/opt"} {
		if withinPath(path, root) {
			return "", errors.New("system folders cannot be registered")
		}
	}
	if strings.HasPrefix(path, "/home/") && len(strings.Split(strings.Trim(path, "/"), "/")) < 3 {
		return "", errors.New("home directories cannot be registered")
	}
	for _, part := range strings.Split(path, "/") {
		if strings.HasPrefix(part, ".") {
			return "", errors.New("hidden or credential folders cannot be registered")
		}
	}
	return path, nil
}
func (s *Store) Selection(ctx context.Context, id string) (StorageSelection, error) {
	var raw string
	err := s.db.QueryRowContext(ctx, `SELECT selection_json FROM instance_storage WHERE instance_id=?`, id).Scan(&raw)
	var v StorageSelection
	if errors.Is(err, sql.ErrNoRows) {
		return v, nil
	}
	if err == nil {
		err = json.Unmarshal([]byte(raw), &v)
	}
	return v, err
}
func (s *Store) validateSelection(ctx context.Context, v StorageSelection, owner string) error {
	seen := map[string]bool{}
	names := map[string]bool{}
	all := append([]Attachment{{DriveID: v.ProjectDrive, Name: "projects"}}, v.FileDrives...)
	if len(all) > 17 {
		return errors.New("at most 16 additional drives are supported")
	}
	for _, a := range all {
		if !validInstanceName(a.Name) || seen[a.DriveID] || names[a.Name] {
			return errors.New("invalid or duplicate drive attachment")
		}
		seen[a.DriveID] = true
		names[a.Name] = true
		d, err := s.drive(ctx, a.DriveID, owner)
		if err != nil || d.Role != "files" {
			return errors.New("file drive is unavailable")
		}
		if d.Kind == "bind" {
			if _, err := validateDriveFolder(d.Source); err != nil {
				return err
			}
		}
	}
	if v.EnvironmentSet != "" {
		if _, err := s.environmentValues(ctx, v.EnvironmentSet, owner); err != nil {
			return errors.New("environment set is unavailable")
		}
	}
	if v.StateSeed != "" {
		snap, err := s.snapshot(ctx, v.StateSeed, owner)
		if err != nil || snap.Status != "ready" {
			return errors.New("state seed is unavailable")
		}
	}
	return nil
}
func (s *Store) saveSelection(ctx context.Context, id string, v StorageSelection) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO instance_storage VALUES(?,?) ON CONFLICT(instance_id) DO UPDATE SET selection_json=excluded.selection_json`, id, encode(v))
	return err
}
func (s *Store) acquireDrives(ctx context.Context, id string, v StorageSelection) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	all := append([]Attachment{{DriveID: v.ProjectDrive}}, v.FileDrives...)
	for _, a := range all {
		if a.ReadOnly {
			continue
		}
		if a.DriveID == "" {
			return errors.New("project drive is required")
		}
		var holder string
		err := tx.QueryRowContext(ctx, `SELECT instance_id FROM drive_leases WHERE drive_id=?`, a.DriveID).Scan(&holder)
		if err == nil && holder != id {
			return errors.New("writable drive is active on another desktop")
		}
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT OR IGNORE INTO drive_leases VALUES(?,?)`, a.DriveID, id); err != nil {
			return err
		}
	}
	return tx.Commit()
}
func (s *Store) releaseDrives(ctx context.Context, id string) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM drive_leases WHERE instance_id=?`, id)
	return err
}
func (s *Store) instanceMounts(ctx context.Context, instance api.Instance, data, projects string) ([]mount.Mount, error) {
	v, err := s.Selection(ctx, instance.ID)
	if err != nil {
		return nil, err
	}
	return s.selectedMounts(ctx, instance, data, projects, v)
}
func (s *Store) selectedMounts(ctx context.Context, instance api.Instance, data, projects string, v StorageSelection) ([]mount.Mount, error) {
	result := []mount.Mount{{Type: mount.TypeVolume, Source: data, Target: "/data"}}
	if v.ProjectDrive == "" {
		return append(result, mount.Mount{Type: mount.TypeVolume, Source: projects, Target: "/projects"}), nil
	}
	all := append([]Attachment{{DriveID: v.ProjectDrive, Name: "projects"}}, v.FileDrives...)
	for i, a := range all {
		d, err := s.drive(ctx, a.DriveID, instance.Owner)
		if err != nil {
			return nil, errors.New("drive is unavailable")
		}
		typ := mount.TypeVolume
		if d.Kind == "bind" {
			typ = mount.TypeBind
		}
		target := "/mnt/drives/" + a.Name
		if i == 0 {
			target = "/projects"
		}
		result = append(result, mount.Mount{Type: typ, Source: d.Source, Target: target, ReadOnly: a.ReadOnly})
	}
	return result, nil
}

var environmentKey = regexp.MustCompile(`^[A-Z][A-Z0-9_]{0,127}$`)

func validateEnvironment(values map[string]string) error {
	if len(values) > 128 {
		return errors.New("too many environment variables")
	}
	total := 0
	for k, v := range values {
		total += len(k) + len(v)
		if !environmentKey.MatchString(k) || strings.ContainsRune(v, 0) || len(v) > 16384 {
			return errors.New("invalid environment variable")
		}
		if strings.HasPrefix(k, "VIBESTACK_") || strings.HasPrefix(k, "LD_") || strings.HasPrefix(k, "PYTHON") || strings.HasPrefix(k, "XDG_") || strings.HasPrefix(k, "DBUS_") {
			return errors.New("runner-controlled environment variable")
		}
		switch k {
		case "HOME", "USER", "LOGNAME", "PATH", "SHELL", "BASH_ENV", "ENV", "DISPLAY", "XAUTHORITY", "SHELLOPTS", "BASHOPTS", "IFS", "TMPDIR", "NODE_OPTIONS", "DOCKER_HOST", "DOCKER_CONFIG", "SSH_AUTH_SOCK":
			return errors.New("runner-controlled environment variable")
		}
	}
	if total > 65536 {
		return errors.New("environment set is too large")
	}
	return nil
}
func (s *Store) AddEnvironment(ctx context.Context, name, owner string, values map[string]string) (EnvironmentSet, error) {
	if !validInstanceName(name) {
		return EnvironmentSet{}, errors.New("invalid environment set name")
	}
	if err := validateEnvironment(values); err != nil {
		return EnvironmentSet{}, err
	}
	id, err := randomID()
	if err != nil {
		return EnvironmentSet{}, err
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO environment_sets VALUES(?,?,?,?)`, id, name, owner, encode(values))
	if err != nil {
		return EnvironmentSet{}, errors.New("environment set name is already used")
	}
	return environmentMetadata(id, name, values), nil
}
func environmentMetadata(id, name string, values map[string]string) EnvironmentSet {
	keys := []string{}
	for k := range values {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return EnvironmentSet{ID: id, Name: name, Keys: keys}
}
func (s *Store) environmentValues(ctx context.Context, id, owner string) (map[string]string, error) {
	var raw string
	err := s.db.QueryRowContext(ctx, `SELECT values_json FROM environment_sets WHERE id=? AND owner=?`, id, owner).Scan(&raw)
	values := map[string]string{}
	if err == nil {
		err = json.Unmarshal([]byte(raw), &values)
	}
	return values, err
}
func (s *Store) Environments(ctx context.Context, owner string) ([]EnvironmentSet, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,name,values_json FROM environment_sets WHERE owner=? ORDER BY name`, owner)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []EnvironmentSet{}
	for rows.Next() {
		var id, name, raw string
		if err := rows.Scan(&id, &name, &raw); err != nil {
			return nil, err
		}
		var values map[string]string
		if err := json.Unmarshal([]byte(raw), &values); err != nil {
			return nil, err
		}
		result = append(result, environmentMetadata(id, name, values))
	}
	return result, rows.Err()
}
func (s *Store) snapshot(ctx context.Context, id, owner string) (Snapshot, error) {
	var v Snapshot
	err := s.db.QueryRowContext(ctx, `SELECT id,name,owner,instance_id,volume,image_digest,flatpak,status,created_at FROM snapshots WHERE id=? AND owner=?`, id, owner).Scan(&v.ID, &v.Name, &v.Owner, &v.InstanceID, &v.Volume, &v.ImageDigest, &v.Flatpak, &v.Status, &v.CreatedAt)
	return v, err
}
func (s *Store) Snapshots(ctx context.Context, owner string) ([]Snapshot, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,name,owner,instance_id,volume,image_digest,flatpak,status,created_at FROM snapshots WHERE owner=? ORDER BY created_at`, owner)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []Snapshot{}
	for rows.Next() {
		var v Snapshot
		if err := rows.Scan(&v.ID, &v.Name, &v.Owner, &v.InstanceID, &v.Volume, &v.ImageDigest, &v.Flatpak, &v.Status, &v.CreatedAt); err != nil {
			return nil, err
		}
		result = append(result, v)
	}
	return result, rows.Err()
}
