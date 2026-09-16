package runner

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

const pairingTTL = 10 * time.Minute

type PairingAdmin struct {
	PairingID        string   `json:"pairing_id"`
	VerificationCode string   `json:"verification_code"`
	DeviceLabel      string   `json:"device_label"`
	Permissions      []string `json:"permissions"`
	Status           string   `json:"status"`
	ExpiresAt        string   `json:"expires_at"`
}

type ClientAdmin struct {
	ClientID    string   `json:"client_id"`
	DeviceLabel string   `json:"device_label"`
	Permissions []string `json:"permissions"`
	CreatedAt   string   `json:"created_at"`
	RevokedAt   string   `json:"revoked_at,omitempty"`
}

func validPermissions(values []string) bool {
	if len(values) != 2 {
		return false
	}
	found := map[string]bool{}
	for _, value := range values {
		if value != "instances:read" && value != "instances:write" {
			return false
		}
		found[value] = true
	}
	return found["instances:read"] && found["instances:write"]
}

func randomToken(bytesCount int) (string, error) {
	value := make([]byte, bytesCount)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return hex.EncodeToString(value), nil
}

func verificationCode() (string, error) {
	alphabet := "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
	value := make([]byte, 8)
	random := make([]byte, 8)
	if _, err := rand.Read(random); err != nil {
		return "", err
	}
	for index := range value {
		value[index] = alphabet[int(random[index])%len(alphabet)]
	}
	return string(value[:4]) + "-" + string(value[4:]), nil
}

func (s *Store) RequestPairing(ctx context.Context, label string, permissions []string) (api.PairingRequest, error) {
	s.pairings.Lock()
	defer s.pairings.Unlock()
	label = strings.TrimSpace(label)
	if len(label) < 1 || len(label) > 80 || strings.IndexFunc(label, func(value rune) bool { return value < 0x20 || value == 0x7f }) >= 0 {
		return api.PairingRequest{}, errors.New("device_label is invalid")
	}
	if !validPermissions(permissions) {
		return api.PairingRequest{}, errors.New("requested permissions are invalid")
	}
	var pending int
	if err := s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM pairings WHERE status='pending' AND expires_at>?`, time.Now().Unix()).Scan(&pending); err != nil {
		return api.PairingRequest{}, err
	}
	if pending >= 8 {
		return api.PairingRequest{}, errors.New("too many pairing requests are pending")
	}
	id, err := randomID()
	if err != nil {
		return api.PairingRequest{}, err
	}
	code, err := verificationCode()
	if err != nil {
		return api.PairingRequest{}, err
	}
	secret, err := randomToken(32)
	if err != nil {
		return api.PairingRequest{}, err
	}
	expires := time.Now().Add(pairingTTL)
	_, err = s.db.ExecContext(ctx, `INSERT INTO pairings(id,code,label,permissions_json,polling_hash,status,expires_at,created_at) VALUES(?,?,?,?,?,'pending',?,?)`, id, code, label, encode(permissions), HashCredential(secret), expires.Unix(), nowISO())
	if err != nil {
		return api.PairingRequest{}, err
	}
	return api.PairingRequest{PairingID: id, VerificationCode: code, PollingSecret: secret, ExpiresAt: expires.UTC().Format(time.RFC3339), IntervalSeconds: 2}, nil
}

func (s *Store) PollPairing(ctx context.Context, id, secret string) (api.PairingResult, error) {
	s.pairings.Lock()
	defer s.pairings.Unlock()
	if len(secret) < 32 || len(secret) > 128 {
		return api.PairingResult{}, sql.ErrNoRows
	}
	var code, label, raw, pollHash, status string
	var expires int64
	err := s.db.QueryRowContext(ctx, `SELECT code,label,permissions_json,COALESCE(polling_hash,''),status,expires_at FROM pairings WHERE id=?`, id).Scan(&code, &label, &raw, &pollHash, &status, &expires)
	if errors.Is(err, sql.ErrNoRows) {
		return api.PairingResult{}, sql.ErrNoRows
	}
	if err != nil {
		return api.PairingResult{}, err
	}
	if !hmac.Equal([]byte(HashCredential(secret)), []byte(pollHash)) {
		return api.PairingResult{}, sql.ErrNoRows
	}
	if time.Now().Unix() >= expires {
		_, _ = s.db.ExecContext(ctx, `UPDATE pairings SET status='expired',polling_hash=NULL WHERE id=?`, id)
		return api.PairingResult{}, errors.New("pairing expired")
	}
	if status == "pending" {
		return api.PairingResult{Status: "pending", ExpiresAt: time.Unix(expires, 0).UTC().Format(time.RFC3339)}, nil
	}
	if status != "approved" {
		return api.PairingResult{}, fmt.Errorf("pairing is %s", status)
	}
	key, err := s.PairingKey(ctx)
	if err != nil {
		return api.PairingResult{}, err
	}
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(id + ":" + secret))
	credential := "vsr_" + hex.EncodeToString(mac.Sum(nil))
	clientID, err := randomID()
	if err != nil {
		return api.PairingResult{}, err
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return api.PairingResult{}, err
	}
	defer tx.Rollback()
	result, err := tx.ExecContext(ctx, `UPDATE pairings SET status='completed',polling_hash=NULL,client_id=? WHERE id=? AND status='approved'`, clientID, id)
	if err != nil {
		return api.PairingResult{}, err
	}
	changed, _ := result.RowsAffected()
	if changed != 1 {
		return api.PairingResult{}, errors.New("credential was already delivered")
	}
	var clientCount int
	if err := tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM clients`).Scan(&clientCount); err != nil {
		return api.PairingResult{}, err
	}
	if clientCount >= 128 {
		return api.PairingResult{}, errors.New("runner client limit reached")
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO clients(id,label,permissions_json,credential_hash,created_at) VALUES(?,?,?,?,?)`, clientID, label, raw, HashCredential(credential), nowISO())
	if err != nil {
		return api.PairingResult{}, err
	}
	if err := tx.Commit(); err != nil {
		return api.PairingResult{}, err
	}
	var permissions []string
	_ = json.Unmarshal([]byte(raw), &permissions)
	return api.PairingResult{Status: "approved", ClientID: clientID, Credential: credential, Permissions: permissions}, nil
}

func (s *Store) Pairings(ctx context.Context) ([]PairingAdmin, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,code,label,permissions_json,status,expires_at FROM pairings WHERE status IN ('pending','approved') AND expires_at>? ORDER BY created_at`, time.Now().Unix())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var values []PairingAdmin
	for rows.Next() {
		var v PairingAdmin
		var raw string
		var expires int64
		if err := rows.Scan(&v.PairingID, &v.VerificationCode, &v.DeviceLabel, &raw, &v.Status, &expires); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(raw), &v.Permissions)
		v.ExpiresAt = time.Unix(expires, 0).UTC().Format(time.RFC3339)
		values = append(values, v)
	}
	return values, rows.Err()
}

func (s *Store) ApprovePairing(ctx context.Context, code string, approve bool) (PairingAdmin, error) {
	s.pairings.Lock()
	defer s.pairings.Unlock()
	status := "approved"
	if !approve {
		status = "denied"
	}
	result, err := s.db.ExecContext(ctx, `UPDATE pairings SET status=?,approved_at=?,polling_hash=CASE WHEN ? THEN polling_hash ELSE NULL END WHERE code=? AND status='pending' AND expires_at>?`, status, nowISO(), approve, code, time.Now().Unix())
	if err != nil {
		return PairingAdmin{}, err
	}
	changed, _ := result.RowsAffected()
	if changed != 1 {
		return PairingAdmin{}, sql.ErrNoRows
	}
	var v PairingAdmin
	var raw string
	var expires int64
	err = s.db.QueryRowContext(ctx, `SELECT id,code,label,permissions_json,status,expires_at FROM pairings WHERE code=?`, code).Scan(&v.PairingID, &v.VerificationCode, &v.DeviceLabel, &raw, &v.Status, &expires)
	_ = json.Unmarshal([]byte(raw), &v.Permissions)
	v.ExpiresAt = time.Unix(expires, 0).UTC().Format(time.RFC3339)
	return v, err
}

func (s *Store) Clients(ctx context.Context) ([]ClientAdmin, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,label,permissions_json,created_at,COALESCE(revoked_at,'') FROM clients ORDER BY created_at`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var values []ClientAdmin
	for rows.Next() {
		var v ClientAdmin
		var raw string
		if err := rows.Scan(&v.ClientID, &v.DeviceLabel, &raw, &v.CreatedAt, &v.RevokedAt); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(raw), &v.Permissions)
		values = append(values, v)
	}
	return values, rows.Err()
}

func (s *Store) RevokeClient(ctx context.Context, id string) error {
	result, err := s.db.ExecContext(ctx, `UPDATE clients SET revoked_at=COALESCE(revoked_at,?) WHERE id=?`, nowISO(), id)
	if err != nil {
		return err
	}
	changed, _ := result.RowsAffected()
	if changed != 1 {
		return sql.ErrNoRows
	}
	return nil
}
