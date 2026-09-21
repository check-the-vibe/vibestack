package runner

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"path/filepath"
)

// ConfigureAuthentication never adopts another ownership namespace. Preview
// registries without a mode marker are paired registries.
func (s *Store) ConfigureAuthentication(ctx context.Context, mode string) (string, error) {
	if mode != AuthPaired && mode != AuthTrustedTailnet {
		return "", errors.New("invalid authentication mode")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return "", err
	}
	defer tx.Rollback()
	previous := AuthPaired
	var stored string
	err = tx.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='authentication_mode'`).Scan(&stored)
	if err == nil {
		previous = stored
	} else if !errors.Is(err, sql.ErrNoRows) {
		return "", err
	}
	if previous != mode {
		entries, err := os.ReadDir(filepath.Join(s.stateDir, "credentials"))
		if err != nil {
			return "", err
		}
		if len(entries) != 0 {
			return "", errors.New("switching authentication modes requires an empty credential registry")
		}
		for _, table := range []string{"templates", "clients", "pairings", "instances", "operations", "drives", "environment_sets", "snapshots", "instance_storage", "drive_leases", "port_allocations", "serve_mappings"} {
			var count int
			if err := tx.QueryRowContext(ctx, "SELECT count(*) FROM "+table).Scan(&count); err != nil {
				return "", err
			}
			if count != 0 {
				return "", errors.New("switching authentication modes requires an empty registry; use clean broker-managed state")
			}
		}
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('authentication_mode',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, mode); err != nil {
		return "", err
	}
	var id string
	err = tx.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='shared_principal'`).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		id, err = randomID()
		if err != nil {
			return "", err
		}
		_, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('shared_principal',?)`, id)
	}
	if err != nil {
		return "", err
	}
	return id, tx.Commit()
}
