// Package service implements the single-workspace application boundary.
package service

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
	"syscall"
	"time"
	"unicode"

	"golang.org/x/sys/unix"
)

var (
	ErrUnauthenticated = errors.New("authentication required")
	ErrUnsafeState     = errors.New("credential state failed a safety check")
	identifier         = regexp.MustCompile(`^[a-f0-9]{32}$`)
	capabilityID       = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]{0,63}$`)
)

const credentialLimit = 128

type Principal struct {
	ID           string   `json:"id"`
	InstanceID   string   `json:"instance_id"`
	Owner        bool     `json:"owner"`
	Capabilities []string `json:"capabilities"`
	digest       string
}

func (p Principal) Allows(id string, owner bool) bool {
	if owner && !p.Owner {
		return false
	}
	if len(p.Capabilities) == 0 {
		return true
	}
	for _, allowed := range p.Capabilities {
		if allowed == id {
			return true
		}
	}
	return false
}

type Credential struct {
	ID           string   `json:"id"`
	Label        string   `json:"label"`
	Owner        bool     `json:"owner"`
	Capabilities []string `json:"capabilities"`
	Hash         string   `json:"credential_hash,omitempty"`
	CreatedAt    int64    `json:"created_at"`
	ExpiresAt    int64    `json:"expires_at"`
	RevokedAt    int64    `json:"revoked_at"`
}

type credentialState struct {
	Version     int          `json:"version"`
	Credentials []Credential `json:"credentials"`
}

// Store shares the existing protected directory, identity and lock with the
// Python pairing store. Its own new credential file contains hashes only.
type Store struct {
	root     *os.Root
	Identity string
	now      func() time.Time
}

func NewStore(path string) (*Store, error) {
	if err := os.MkdirAll(path, 0700); err != nil {
		return nil, ErrUnsafeState
	}
	root, err := os.OpenRoot(path)
	if err != nil {
		return nil, ErrUnsafeState
	}
	s := &Store{root: root, now: time.Now}
	f, err := root.Open(".")
	if err != nil {
		root.Close()
		return nil, ErrUnsafeState
	}
	info, err := f.Stat()
	f.Close()
	if err != nil || !privateInfo(info, true) {
		root.Close()
		return nil, ErrUnsafeState
	}
	err = s.locked(func() error {
		data, err := s.read("identity", 65)
		if errors.Is(err, os.ErrNotExist) {
			id, err := randomHex(16)
			if err != nil {
				return err
			}
			data = []byte(id + "\n")
			if err := s.write("identity", data); err != nil {
				return err
			}
		} else if err != nil {
			return err
		}
		s.Identity = strings.TrimSpace(string(data))
		if !identifier.MatchString(s.Identity) {
			return ErrUnsafeState
		}
		return nil
	})
	if err != nil {
		root.Close()
		return nil, err
	}
	return s, nil
}

func (s *Store) Close() error { return s.root.Close() }

func privateInfo(info os.FileInfo, directory bool) bool {
	if info == nil || info.IsDir() != directory {
		return false
	}
	if !directory && !info.Mode().IsRegular() {
		return false
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return false
	}
	if directory {
		return info.Mode().Perm() == 0700
	}
	return info.Mode().Perm() == 0600 && stat.Nlink == 1
}

func randomHex(bytes int) (string, error) {
	value := make([]byte, bytes)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return hex.EncodeToString(value), nil
}

func tokenDigest(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

func (s *Store) locked(fn func() error) error {
	f, err := s.root.OpenFile("client-auth.lock", os.O_RDWR|os.O_CREATE|unix.O_NOFOLLOW|unix.O_NONBLOCK, 0600)
	if err != nil {
		return ErrUnsafeState
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !privateInfo(info, false) {
		return ErrUnsafeState
	}
	deadline := time.Now().Add(2 * time.Second)
	for {
		err := unix.Flock(int(f.Fd()), unix.LOCK_EX|unix.LOCK_NB)
		if err == nil {
			break
		}
		if !errors.Is(err, unix.EWOULDBLOCK) || time.Now().After(deadline) {
			return ErrUnsafeState
		}
		time.Sleep(5 * time.Millisecond)
	}
	defer unix.Flock(int(f.Fd()), unix.LOCK_UN)
	return fn()
}

func (s *Store) read(name string, limit int64) ([]byte, error) {
	f, err := s.root.OpenFile(name, os.O_RDONLY|unix.O_NOFOLLOW|unix.O_NONBLOCK, 0)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, os.ErrNotExist
		}
		return nil, ErrUnsafeState
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !privateInfo(info, false) || info.Size() > limit {
		return nil, ErrUnsafeState
	}
	data, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, ErrUnsafeState
	}
	return data, nil
}

func (s *Store) write(name string, data []byte) error {
	id, err := randomHex(16)
	if err != nil {
		return err
	}
	temporary := ".service-" + id
	f, err := s.root.OpenFile(temporary, os.O_WRONLY|os.O_CREATE|os.O_EXCL|unix.O_NOFOLLOW, 0600)
	if err != nil {
		return ErrUnsafeState
	}
	defer s.root.Remove(temporary)
	if _, err = f.Write(data); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil || closeErr != nil {
		return ErrUnsafeState
	}
	if err := s.root.Rename(temporary, name); err != nil {
		return ErrUnsafeState
	}
	dir, err := s.root.Open(".")
	if err != nil {
		return ErrUnsafeState
	}
	defer dir.Close()
	return dir.Sync()
}

func (s *Store) load() (credentialState, error) {
	data, err := s.read("service-credentials.json", 1<<20)
	if errors.Is(err, os.ErrNotExist) {
		return credentialState{Version: 1}, nil
	}
	if err != nil {
		return credentialState{}, err
	}
	var state credentialState
	if json.Unmarshal(data, &state) != nil || state.Version != 1 || len(state.Credentials) > credentialLimit {
		return state, ErrUnsafeState
	}
	for _, c := range state.Credentials {
		if !identifier.MatchString(c.ID) || len(c.Hash) != 64 {
			return state, ErrUnsafeState
		}
	}
	return state, nil
}

func (s *Store) save(state credentialState) error {
	data, err := json.Marshal(state)
	if err != nil {
		return err
	}
	return s.write("service-credentials.json", append(data, '\n'))
}

// Issue is local-operator authority. HTTP adapters must never call it for an
// anonymous principal. The returned token is delivered once and not persisted.
func (s *Store) Issue(label string, owner bool, capabilities []string, lifetime time.Duration) (Credential, string, error) {
	var c Credential
	if len(label) < 1 || len(label) > 80 || strings.IndexFunc(label, unicode.IsControl) >= 0 || lifetime < time.Minute || lifetime > 365*24*time.Hour {
		return c, "", errors.New("invalid credential options")
	}
	if len(capabilities) > 256 {
		return c, "", errors.New("too many capability grants")
	}
	for _, id := range capabilities {
		if !capabilityID.MatchString(id) {
			return c, "", errors.New("invalid capability grant")
		}
	}
	secret := make([]byte, 32)
	if _, err := rand.Read(secret); err != nil {
		return c, "", err
	}
	token := "vss_" + base64.RawURLEncoding.EncodeToString(secret)
	id, err := randomHex(16)
	if err != nil {
		return c, "", err
	}
	c = Credential{ID: id, Label: label, Owner: owner, Capabilities: capabilities, Hash: tokenDigest(token), CreatedAt: s.now().Unix(), ExpiresAt: s.now().Add(lifetime).Unix()}
	err = s.locked(func() error {
		state, err := s.load()
		if err != nil {
			return err
		}
		if len(state.Credentials) >= credentialLimit {
			return errors.New("credential limit reached; inspect local credential state")
		}
		state.Credentials = append(state.Credentials, c)
		return s.save(state)
	})
	if err != nil {
		return Credential{}, "", err
	}
	c.Hash = ""
	return c, token, nil
}

func (s *Store) List() ([]Credential, error) {
	var result []Credential
	err := s.locked(func() error {
		state, err := s.load()
		if err != nil {
			return err
		}
		for _, c := range state.Credentials {
			c.Hash = ""
			result = append(result, c)
		}
		return nil
	})
	return result, err
}

func (s *Store) Revoke(id string) error {
	if !identifier.MatchString(id) {
		return errors.New("invalid credential ID")
	}
	return s.locked(func() error {
		state, err := s.load()
		if err != nil {
			return err
		}
		for i := range state.Credentials {
			if state.Credentials[i].ID == id {
				if state.Credentials[i].RevokedAt == 0 {
					state.Credentials[i].RevokedAt = s.now().Unix()
				}
				return s.save(state)
			}
		}
		return errors.New("credential not found")
	})
}

func (s *Store) Authenticate(token string) (Principal, error) {
	if len(token) < 32 || len(token) > 512 || strings.IndexFunc(token, unicode.IsSpace) >= 0 {
		return Principal{}, ErrUnauthenticated
	}
	return s.authenticateDigest(tokenDigest(token))
}

// Session validation goes through the same fresh credential lookup as bearer
// requests; possession of a session cookie cannot outlive credential revocation.
func (s *Store) authenticateDigest(digest string) (Principal, error) {
	principal := Principal{InstanceID: s.Identity, digest: digest}
	err := s.locked(func() error {
		state, err := s.load()
		if err != nil {
			return err
		}
		for _, c := range state.Credentials {
			if subtle.ConstantTimeCompare([]byte(c.Hash), []byte(digest)) == 1 && c.RevokedAt == 0 && c.ExpiresAt > s.now().Unix() {
				principal.ID, principal.Owner, principal.Capabilities = c.ID, c.Owner, c.Capabilities
				return nil
			}
		}
		// Compatibility credentials retain workspace authority, never owner scope.
		data, err := s.read("client-credentials.json", 1<<20)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		if err == nil {
			var legacy struct {
				Clients []struct {
					ID          string   `json:"id"`
					Hash        string   `json:"credential_hash"`
					RevokedAt   *int64   `json:"revoked_at"`
					Permissions []string `json:"permissions"`
				} `json:"clients"`
			}
			if json.Unmarshal(data, &legacy) != nil || len(legacy.Clients) > credentialLimit {
				return ErrUnsafeState
			}
			for _, c := range legacy.Clients {
				if c.RevokedAt == nil && identifier.MatchString(c.ID) && len(c.Permissions) == 1 && c.Permissions[0] == "workspace" && subtle.ConstantTimeCompare([]byte(c.Hash), []byte(digest)) == 1 {
					principal.ID = c.ID
					return nil
				}
			}
		}
		data, err = s.read("automation.token", 513)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		if err == nil {
			token := strings.TrimSpace(string(data))
			if len(token) < 32 || len(token) > 512 || strings.IndexFunc(token, unicode.IsSpace) >= 0 {
				return ErrUnsafeState
			}
			if subtle.ConstantTimeCompare([]byte(tokenDigest(token)), []byte(digest)) == 1 {
				principal.ID = "legacy-automation"
				return nil
			}
		}
		return ErrUnauthenticated
	})
	if err != nil {
		return Principal{}, err
	}
	return principal, nil
}

func (s *Store) InternalToken() (string, error) {
	data, err := s.read("automation.token", 513)
	if err != nil {
		return "", fmt.Errorf("internal credential unavailable")
	}
	token := strings.TrimSpace(string(data))
	if len(token) < 32 || len(token) > 512 || strings.IndexFunc(token, unicode.IsSpace) >= 0 {
		return "", ErrUnsafeState
	}
	return token, nil
}
