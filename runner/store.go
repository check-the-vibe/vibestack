package runner

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	_ "modernc.org/sqlite"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

type Store struct {
	db       *sql.DB
	stateDir string
	pairings sync.Mutex
}

type Template struct {
	Name      string `json:"name"`
	Image     string `json:"image"`
	Digest    string `json:"digest"`
	Flatpak   bool   `json:"flatpak"`
	CreatedAt string `json:"created_at"`
}

func OpenStore(stateDir string) (*Store, error) {
	if err := ensurePrivateDirectory(stateDir); err != nil {
		return nil, err
	}
	if err := ensurePrivateDirectory(filepath.Join(stateDir, "credentials")); err != nil {
		return nil, err
	}
	databasePath := filepath.Join(stateDir, "runner.db")
	db, err := sql.Open("sqlite", databasePath)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	store := &Store{db: db, stateDir: stateDir}
	if err := store.migrate(); err != nil {
		db.Close()
		return nil, err
	}
	if err := store.migrateStorage(); err != nil {
		db.Close()
		return nil, err
	}
	if err := os.Chmod(databasePath, 0600); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

func ensurePrivateDirectory(path string) error {
	if err := os.Mkdir(path, 0700); err != nil && !errors.Is(err, os.ErrExist) {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || stat.Uid != uint32(os.Geteuid()) || info.Mode().Perm()&0077 != 0 {
		return errors.New("runner state directory has unsafe ownership, type, or permissions")
	}
	return nil
}

func (s *Store) Close() error { return s.db.Close() }

func (s *Store) migrate() error {
	_, err := s.db.Exec(`
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS templates (
 name TEXT PRIMARY KEY, image TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
 flatpak INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clients (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, permissions_json TEXT NOT NULL,
 credential_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS pairings (
 id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
 permissions_json TEXT NOT NULL, polling_hash TEXT, status TEXT NOT NULL,
 expires_at INTEGER NOT NULL, created_at TEXT NOT NULL, approved_at TEXT,
 client_id TEXT
);
CREATE TABLE IF NOT EXISTS instances (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, owner TEXT NOT NULL,
 template TEXT NOT NULL, image_digest TEXT NOT NULL, container_id TEXT,
 data_volume TEXT NOT NULL, projects_volume TEXT NOT NULL,
 desired_state TEXT NOT NULL, observed_state TEXT NOT NULL,
 ready INTEGER NOT NULL DEFAULT 0, infrastructure_ready INTEGER NOT NULL DEFAULT 0,
 applications_restored INTEGER NOT NULL DEFAULT 0,
 onboarding_required INTEGER NOT NULL DEFAULT 1,
 ports_json TEXT NOT NULL, urls_json TEXT NOT NULL, resource_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_error TEXT NOT NULL DEFAULT '',
 removed_at TEXT
);
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, instance_id TEXT, owner TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
 idempotency_key TEXT, request_id TEXT NOT NULL, request_json TEXT NOT NULL,
 result_json TEXT, error_code TEXT, error_message TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(kind, owner, idempotency_key)
);
CREATE TABLE IF NOT EXISTS port_allocations (
 port INTEGER PRIMARY KEY, instance_id TEXT NOT NULL, purpose TEXT NOT NULL,
 UNIQUE(instance_id,purpose)
);
CREATE TABLE IF NOT EXISTS serve_mappings (
 instance_id TEXT PRIMARY KEY, https_port INTEGER NOT NULL UNIQUE,
 proxy TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_instance ON operations(instance_id, created_at);
`)
	if err != nil {
		return err
	}
	// These additive migrations keep state created by early runner previews usable.
	for _, statement := range []string{
		`ALTER TABLE instances ADD COLUMN password_status TEXT NOT NULL DEFAULT 'unknown'`,
		`ALTER TABLE instances ADD COLUMN infrastructure_ready INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE instances ADD COLUMN applications_restored INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE operations ADD COLUMN owner TEXT NOT NULL DEFAULT ''`,
	} {
		if _, alterErr := s.db.Exec(statement); alterErr != nil && !strings.Contains(strings.ToLower(alterErr.Error()), "duplicate column") {
			return alterErr
		}
	}
	return nil
}

func nowISO() string { return time.Now().UTC().Format(time.RFC3339Nano) }

func randomID() (string, error) {
	value := make([]byte, 16)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return hex.EncodeToString(value), nil
}

func (s *Store) Identity(ctx context.Context) (string, error) {
	var value string
	err := s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='identity'`).Scan(&value)
	if err == nil {
		return value, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return "", err
	}
	value, err = randomID()
	if err != nil {
		return "", err
	}
	_, err = s.db.ExecContext(ctx, `INSERT OR IGNORE INTO metadata(key,value) VALUES('identity',?)`, value)
	if err != nil {
		return "", err
	}
	return s.Identity(ctx)
}

func (s *Store) PairingKey(ctx context.Context) ([]byte, error) {
	var value string
	err := s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='pairing_key'`).Scan(&value)
	if errors.Is(err, sql.ErrNoRows) {
		bytes := make([]byte, 32)
		if _, err := rand.Read(bytes); err != nil {
			return nil, err
		}
		value = hex.EncodeToString(bytes)
		if _, err := s.db.ExecContext(ctx, `INSERT OR IGNORE INTO metadata(key,value) VALUES('pairing_key',?)`, value); err != nil {
			return nil, err
		}
		return s.PairingKey(ctx)
	}
	if err != nil {
		return nil, err
	}
	return hex.DecodeString(value)
}

func HashCredential(value string) string {
	digest := sha256.Sum256([]byte(value))
	return hex.EncodeToString(digest[:])
}

func (s *Store) Authenticate(ctx context.Context, credential string) (string, []string, bool) {
	hash := HashCredential(credential)
	var id, raw string
	err := s.db.QueryRowContext(ctx, `SELECT id, permissions_json FROM clients WHERE credential_hash=? AND revoked_at IS NULL`, hash).Scan(&id, &raw)
	if err != nil {
		return "", nil, false
	}
	var permissions []string
	if json.Unmarshal([]byte(raw), &permissions) != nil {
		return "", nil, false
	}
	return id, permissions, true
}

func (s *Store) AddTemplate(ctx context.Context, template Template) error {
	if template.CreatedAt == "" {
		template.CreatedAt = nowISO()
	}
	_, err := s.db.ExecContext(ctx, `INSERT INTO templates(name,image,digest,flatpak,created_at) VALUES(?,?,?,?,?)
ON CONFLICT(name) DO UPDATE SET image=excluded.image,digest=excluded.digest,flatpak=excluded.flatpak,created_at=excluded.created_at`, template.Name, template.Image, template.Digest, template.Flatpak, template.CreatedAt)
	return err
}

func (s *Store) Templates(ctx context.Context) ([]Template, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT name,image,digest,flatpak,created_at FROM templates ORDER BY name`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var values []Template
	for rows.Next() {
		var v Template
		if err := rows.Scan(&v.Name, &v.Image, &v.Digest, &v.Flatpak, &v.CreatedAt); err != nil {
			return nil, err
		}
		values = append(values, v)
	}
	return values, rows.Err()
}

func (s *Store) Template(ctx context.Context, name string) (Template, error) {
	var value Template
	err := s.db.QueryRowContext(ctx, `SELECT name,image,digest,flatpak,created_at FROM templates WHERE name=?`, name).Scan(&value.Name, &value.Image, &value.Digest, &value.Flatpak, &value.CreatedAt)
	return value, err
}

func encode(value any) string { data, _ := json.Marshal(value); return string(data) }

func (s *Store) Instances(ctx context.Context, includeRemoved bool) ([]api.Instance, error) {
	query := `SELECT id,name,owner,template,image_digest,COALESCE(container_id,''),desired_state,observed_state,ready,infrastructure_ready,applications_restored,onboarding_required,ports_json,urls_json,created_at,updated_at,last_error,password_status FROM instances`
	if !includeRemoved {
		query += ` WHERE removed_at IS NULL`
	}
	query += ` ORDER BY created_at`
	rows, err := s.db.QueryContext(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var values []api.Instance
	for rows.Next() {
		value, err := scanInstance(rows)
		if err != nil {
			return nil, err
		}
		values = append(values, value)
	}
	return values, rows.Err()
}

type scanner interface{ Scan(...any) error }

func scanInstance(row scanner) (api.Instance, error) {
	var value api.Instance
	var ready, infrastructure, restored, onboarding bool
	var ports, urls string
	err := row.Scan(&value.ID, &value.Name, &value.Owner, &value.Template, &value.ImageDigest, &value.ContainerID, &value.DesiredState, &value.ObservedState, &ready, &infrastructure, &restored, &onboarding, &ports, &urls, &value.CreatedAt, &value.UpdatedAt, &value.LastError, &value.PasswordStatus)
	if err != nil {
		return value, err
	}
	value.Ready = ready
	value.InfrastructureReady = infrastructure
	value.ApplicationsRestored = restored
	value.Onboarding = onboarding
	if json.Unmarshal([]byte(ports), &value.Ports) != nil || json.Unmarshal([]byte(urls), &value.URLs) != nil {
		return value, errors.New("stored instance JSON is invalid")
	}
	if value.URLs == nil {
		value.URLs = map[string]string{}
	}
	value.LinuxUsername = "vibe"
	value.Reachability = map[string]string{"browser": "host-local", "ssh": "host-local", "native_vnc": "host-local"}
	if strings.HasPrefix(value.URLs["browser"], "https://") {
		for _, key := range []string{"browser"} {
			value.Reachability[key] = "tailnet"
		}
	}
	base := strings.TrimSuffix(value.URLs["browser"], "/")
	value.URLs["password_setup"] = base + "/vnc/"
	value.URLs["desktop"] = base + "/vnc/"
	delete(value.URLs, "terminal")
	delete(value.URLs, "editor")
	delete(value.URLs, "ssh")
	delete(value.URLs, "vnc")
	value.Connections = map[string]string{"browser": "unavailable", "ssh": "unavailable", "native_vnc": "unavailable"}
	if value.ObservedState == "running" && value.InfrastructureReady {
		value.Connections["browser"] = "available"
		value.Connections["ssh"] = "available"
		value.Connections["native_vnc"] = "password_required"
		if value.PasswordStatus == "configured" {
			value.Connections["native_vnc"] = "available"
		}
	}
	return value, nil
}

func (s *Store) Instance(ctx context.Context, idOrName string) (api.Instance, error) {
	row := s.db.QueryRowContext(ctx, `SELECT id,name,owner,template,image_digest,COALESCE(container_id,''),desired_state,observed_state,ready,infrastructure_ready,applications_restored,onboarding_required,ports_json,urls_json,created_at,updated_at,last_error,password_status FROM instances WHERE (id=? OR name=?) AND removed_at IS NULL`, idOrName, idOrName)
	return scanInstance(row)
}

func (s *Store) InstanceAny(ctx context.Context, idOrName string) (api.Instance, error) {
	row := s.db.QueryRowContext(ctx, `SELECT id,name,owner,template,image_digest,COALESCE(container_id,''),desired_state,observed_state,ready,infrastructure_ready,applications_restored,onboarding_required,ports_json,urls_json,created_at,updated_at,last_error,password_status FROM instances WHERE id=? OR name=?`, idOrName, idOrName)
	return scanInstance(row)
}

func (s *Store) CreateInstance(ctx context.Context, value api.Instance, dataVolume, projectsVolume string, resources map[string]any) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO instances(id,name,owner,template,image_digest,data_volume,projects_volume,desired_state,observed_state,ready,onboarding_required,ports_json,urls_json,resource_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`, value.ID, value.Name, value.Owner, value.Template, value.ImageDigest, dataVolume, projectsVolume, value.DesiredState, value.ObservedState, value.Ready, value.Onboarding, encode(value.Ports), encode(value.URLs), encode(resources), value.CreatedAt, value.UpdatedAt)
	return err
}

func (s *Store) Volumes(ctx context.Context, id string) (string, string, error) {
	var data, projects string
	err := s.db.QueryRowContext(ctx, `SELECT data_volume,projects_volume FROM instances WHERE id=?`, id).Scan(&data, &projects)
	return data, projects, err
}

func (s *Store) Resources(ctx context.Context, id string) (map[string]any, error) {
	var raw string
	if err := s.db.QueryRowContext(ctx, `SELECT resource_json FROM instances WHERE id=?`, id).Scan(&raw); err != nil {
		return nil, err
	}
	var stored map[string]json.Number
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&stored); err != nil {
		return nil, errors.New("stored resource JSON is invalid")
	}
	values := map[string]any{}
	for _, key := range []string{"memory_bytes", "nano_cpus", "pids"} {
		number, ok := stored[key]
		if !ok {
			return nil, errors.New("stored resource JSON is incomplete")
		}
		value, err := number.Int64()
		if err != nil {
			return nil, errors.New("stored resource JSON is invalid")
		}
		values[key] = value
	}
	return values, nil
}

func (s *Store) UpdateInstanceObserved(ctx context.Context, id, containerID, desired, observed string, ready bool, safeError string) error {
	_, err := s.db.ExecContext(ctx, `UPDATE instances SET container_id=?,desired_state=?,observed_state=?,ready=(? AND applications_restored),infrastructure_ready=?,applications_restored=CASE WHEN ? THEN applications_restored ELSE 0 END,last_error=?,updated_at=? WHERE id=?`, containerID, desired, observed, ready, ready, ready, safeError, nowISO(), id)
	return err
}

func (s *Store) UpdateInstanceReadiness(ctx context.Context, id string, restored, onboarding bool) error {
	_, err := s.db.ExecContext(ctx, `UPDATE instances SET applications_restored=?,onboarding_required=?,ready=(infrastructure_ready AND ?),updated_at=? WHERE id=?`, restored, onboarding, restored, nowISO(), id)
	return err
}

func (s *Store) ReplaceInstanceContainer(ctx context.Context, id, template, digest, containerID string, resources map[string]any) error {
	_, err := s.db.ExecContext(ctx, `UPDATE instances SET template=?,image_digest=?,container_id=?,resource_json=?,desired_state='running',observed_state='running',ready=1,infrastructure_ready=1,applications_restored=1,last_error='',updated_at=? WHERE id=?`, template, digest, containerID, encode(resources), nowISO(), id)
	return err
}

func (s *Store) MarkRemoved(ctx context.Context, id string) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, `UPDATE instances SET desired_state='removed',observed_state='removed',ready=0,removed_at=?,updated_at=? WHERE id=?`, nowISO(), nowISO(), id); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM drive_leases WHERE instance_id=?`, id); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM port_allocations WHERE instance_id=?`, id); err != nil {
		return err
	}
	return tx.Commit()
}

func (s *Store) CountInstances(ctx context.Context) (int, error) {
	var count int
	err := s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM instances WHERE removed_at IS NULL`).Scan(&count)
	return count, err
}

func (s *Store) CreateOperation(ctx context.Context, op api.Operation, owner string, request any) (api.Operation, bool, error) {
	_, err := s.db.ExecContext(ctx, `INSERT INTO operations(id,instance_id,owner,kind,status,idempotency_key,request_id,request_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)`, op.ID, nullable(op.InstanceID), owner, op.Kind, op.Status, nullable(op.IdempotencyKey), op.RequestID, encode(request), op.CreatedAt, op.UpdatedAt)
	if err != nil && op.IdempotencyKey != "" && strings.Contains(err.Error(), "UNIQUE") {
		var existing api.Operation
		var result, existingRequest string
		err = s.db.QueryRowContext(ctx, `SELECT id,COALESCE(instance_id,''),kind,status,COALESCE(idempotency_key,''),request_id,request_json,COALESCE(result_json,''),COALESCE(error_code,''),COALESCE(error_message,''),created_at,updated_at FROM operations WHERE kind=? AND owner=? AND idempotency_key=?`, op.Kind, owner, op.IdempotencyKey).Scan(&existing.ID, &existing.InstanceID, &existing.Kind, &existing.Status, &existing.IdempotencyKey, &existing.RequestID, &existingRequest, &result, &existing.ErrorCode, &existing.ErrorMessage, &existing.CreatedAt, &existing.UpdatedAt)
		if err == nil && existingRequest != encode(request) {
			return api.Operation{}, false, errors.New("idempotency key was already used for a different request")
		}
		existing.Result = json.RawMessage(result)
		return existing, true, err
	}
	return op, false, err
}

func (s *Store) OperationOwned(ctx context.Context, id, owner string) (api.Operation, error) {
	var op api.Operation
	var result string
	err := s.db.QueryRowContext(ctx, `SELECT id,COALESCE(instance_id,''),kind,status,COALESCE(idempotency_key,''),request_id,COALESCE(result_json,''),COALESCE(error_code,''),COALESCE(error_message,''),created_at,updated_at FROM operations WHERE id=? AND owner=?`, id, owner).Scan(&op.ID, &op.InstanceID, &op.Kind, &op.Status, &op.IdempotencyKey, &op.RequestID, &result, &op.ErrorCode, &op.ErrorMessage, &op.CreatedAt, &op.UpdatedAt)
	op.Result = json.RawMessage(result)
	return op, err
}

func nullable(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func (s *Store) UpdateOperation(ctx context.Context, id, status, errorCode, errorMessage string, result any) error {
	var resultJSON any
	if result != nil {
		resultJSON = encode(result)
	}
	_, err := s.db.ExecContext(ctx, `UPDATE operations SET status=?,error_code=?,error_message=?,result_json=?,updated_at=? WHERE id=?`, status, nullable(errorCode), nullable(errorMessage), resultJSON, nowISO(), id)
	return err
}

func (s *Store) Operation(ctx context.Context, id string) (api.Operation, error) {
	var op api.Operation
	var result string
	err := s.db.QueryRowContext(ctx, `SELECT id,COALESCE(instance_id,''),kind,status,COALESCE(idempotency_key,''),request_id,COALESCE(result_json,''),COALESCE(error_code,''),COALESCE(error_message,''),created_at,updated_at FROM operations WHERE id=?`, id).Scan(&op.ID, &op.InstanceID, &op.Kind, &op.Status, &op.IdempotencyKey, &op.RequestID, &result, &op.ErrorCode, &op.ErrorMessage, &op.CreatedAt, &op.UpdatedAt)
	op.Result = json.RawMessage(result)
	return op, err
}

func (s *Store) Operations(ctx context.Context) ([]api.Operation, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(instance_id,''),kind,status,COALESCE(idempotency_key,''),request_id,COALESCE(result_json,''),COALESCE(error_code,''),COALESCE(error_message,''),created_at,updated_at FROM operations ORDER BY created_at DESC LIMIT 200`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var values []api.Operation
	for rows.Next() {
		var value api.Operation
		var result string
		if err := rows.Scan(&value.ID, &value.InstanceID, &value.Kind, &value.Status, &value.IdempotencyKey, &value.RequestID, &result, &value.ErrorCode, &value.ErrorMessage, &value.CreatedAt, &value.UpdatedAt); err != nil {
			return nil, err
		}
		value.Result = json.RawMessage(result)
		values = append(values, value)
	}
	return values, rows.Err()
}

func (s *Store) OperationsOwned(ctx context.Context, owner string) ([]api.Operation, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(instance_id,''),kind,status,COALESCE(idempotency_key,''),request_id,COALESCE(result_json,''),COALESCE(error_code,''),COALESCE(error_message,''),created_at,updated_at FROM operations WHERE owner=? ORDER BY created_at DESC LIMIT 200`, owner)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var values []api.Operation
	for rows.Next() {
		var value api.Operation
		var result string
		if err := rows.Scan(&value.ID, &value.InstanceID, &value.Kind, &value.Status, &value.IdempotencyKey, &value.RequestID, &result, &value.ErrorCode, &value.ErrorMessage, &value.CreatedAt, &value.UpdatedAt); err != nil {
			return nil, err
		}
		value.Result = json.RawMessage(result)
		values = append(values, value)
	}
	return values, rows.Err()
}

type RecoverableOperation struct {
	Operation api.Operation
	Request   json.RawMessage
}

func (s *Store) RecoverableOperations(ctx context.Context) ([]RecoverableOperation, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(instance_id,''),kind,status,COALESCE(idempotency_key,''),request_id,request_json,COALESCE(result_json,''),COALESCE(error_code,''),COALESCE(error_message,''),created_at,updated_at FROM operations WHERE status IN ('queued','running') ORDER BY created_at`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var values []RecoverableOperation
	for rows.Next() {
		var value RecoverableOperation
		var request, result string
		op := &value.Operation
		if err := rows.Scan(&op.ID, &op.InstanceID, &op.Kind, &op.Status, &op.IdempotencyKey, &op.RequestID, &request, &result, &op.ErrorCode, &op.ErrorMessage, &op.CreatedAt, &op.UpdatedAt); err != nil {
			return nil, err
		}
		value.Request = json.RawMessage(request)
		op.Result = json.RawMessage(result)
		values = append(values, value)
	}
	return values, rows.Err()
}

func (s *Store) PurgeInstance(ctx context.Context, id string) error {
	credential := s.CredentialPath(id)
	if err := os.Remove(credential); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	_, err := s.db.ExecContext(ctx, `DELETE FROM instances WHERE id=? AND removed_at IS NOT NULL`, id)
	return err
}

func (s *Store) ServeMapping(ctx context.Context, instanceID string) (int, string, error) {
	var port int
	var proxy string
	err := s.db.QueryRowContext(ctx, `SELECT https_port,proxy FROM serve_mappings WHERE instance_id=?`, instanceID).Scan(&port, &proxy)
	return port, proxy, err
}

func (s *Store) SaveServeMapping(ctx context.Context, instanceID string, port int, proxy string) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO serve_mappings(instance_id,https_port,proxy,created_at) VALUES(?,?,?,?) ON CONFLICT(instance_id) DO UPDATE SET https_port=excluded.https_port,proxy=excluded.proxy`, instanceID, port, proxy, nowISO())
	return err
}

func (s *Store) DeleteServeMapping(ctx context.Context, instanceID string) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM serve_mappings WHERE instance_id=?`, instanceID)
	return err
}

func (s *Store) CredentialPath(instanceID string) string {
	return filepath.Join(s.stateDir, "credentials", instanceID+".token")
}

func (s *Store) SaveWorkspaceCredential(instanceID string, value []byte) error {
	if len(value) < 32 || len(value) > 512 {
		return errors.New("workspace credential is invalid")
	}
	path := s.CredentialPath(instanceID)
	tmp, err := os.CreateTemp(filepath.Dir(path), ".credential-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	if err := tmp.Chmod(0600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(value); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(name, path); err != nil {
		return err
	}
	directory, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

func (s *Store) WorkspaceCredential(instanceID string) (string, error) {
	path := s.CredentialPath(instanceID)
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return "", err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 512 {
		return "", errors.New("stored workspace credential has unsafe metadata")
	}
	data, err := io.ReadAll(io.LimitReader(file, 513))
	if err != nil || len(data) > 512 {
		return "", errors.New("stored workspace credential is invalid")
	}
	value := strings.TrimSpace(string(data))
	if len(value) < 32 {
		return "", errors.New("stored workspace credential is invalid")
	}
	return value, nil
}

func safeError(err error) string {
	value := strings.Join(strings.Fields(err.Error()), " ")
	if len(value) > 300 {
		value = value[:300]
	}
	return value
}

var _ = fmt.Sprintf
