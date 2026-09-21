package service

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/check-the-vibe/vibestack/api"
	"github.com/check-the-vibe/vibestack/internal/release"
	"github.com/check-the-vibe/vibestack/service/capabilities"
)

type Config struct {
	Store         *Store
	PublicURL     string
	AllowedHosts  []string
	StaticRoot    string
	AutomationURL string
	ControlURL    string
	SetupURL      string
	ProjectsRoot  string
	Capabilities  []capabilities.Registration
	Audit         func(AuditEvent)
}

type session struct {
	Digest, CSRF string
	Expires      time.Time
}
type contextKey int

const principalKey contextKey = 1

type Server struct {
	cfg        Config
	mux        *http.ServeMux
	static     *os.Root
	client     *http.Client
	slots      chan struct{}
	mu         sync.Mutex
	sessions   map[string]session
	operations []legacyRoute
	projects   *os.Root
	registry   *capabilities.Registry
}

func NewServer(cfg Config) (*Server, error) {
	if cfg.Store == nil {
		return nil, errors.New("credential store is required")
	}
	if cfg.PublicURL != "" {
		u, err := url.Parse(cfg.PublicURL)
		if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" || (u.Scheme != "https" && !(u.Scheme == "http" && loopbackHost(u.Hostname()))) {
			return nil, errors.New("public URL must be an HTTPS origin or local HTTP origin")
		}
	}
	for _, target := range []string{cfg.AutomationURL, cfg.ControlURL, cfg.SetupURL} {
		u, err := url.Parse(target)
		if err != nil || u.Scheme != "http" || !loopbackHost(u.Hostname()) || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" {
			return nil, errors.New("backend must be a fixed loopback HTTP origin")
		}
	}
	staticPath, err := filepath.EvalSymlinks(cfg.StaticRoot)
	if err != nil || !filepath.IsAbs(staticPath) {
		return nil, errors.New("static publish directory unavailable")
	}
	for _, forbidden := range []string{"/", "/data", "/projects", "/home", "/home/vibe", "/root", "/etc"} {
		if staticPath == forbidden {
			return nil, errors.New("sensitive directories cannot be published")
		}
	}
	if _, err := os.Lstat(filepath.Join(staticPath, ".git")); err == nil || !errors.Is(err, os.ErrNotExist) {
		return nil, errors.New("a Git checkout cannot be the publish root")
	}
	root, err := os.OpenRoot(staticPath)
	if err != nil {
		return nil, errors.New("static publish directory unavailable")
	}
	s := &Server{cfg: cfg, mux: http.NewServeMux(), static: root, slots: make(chan struct{}, 32), sessions: make(map[string]session)}
	s.client = &http.Client{Timeout: 60 * time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }, Transport: &http.Transport{Proxy: nil, DisableCompression: true, MaxIdleConns: 16, IdleConnTimeout: 30 * time.Second, ResponseHeaderTimeout: 30 * time.Second}}
	if err := s.registerLegacy(); err != nil {
		root.Close()
		return nil, err
	}
	if err := s.registerCapabilities(); err != nil {
		if s.projects != nil {
			s.projects.Close()
		}
		root.Close()
		return nil, err
	}
	s.mux.HandleFunc("GET /.well-known/vibestack", s.discovery)
	s.mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		s.json(w, 200, map[string]any{"service": "workspace", "ready": true})
	})
	s.mux.HandleFunc("GET /api/workspace.openapi.json", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write(api.WorkspaceOpenAPI)
	})
	s.mux.HandleFunc("/auth/session", s.authSession)
	s.mux.HandleFunc("GET /api/v1/capabilities", s.authorized("", false, s.capabilityCatalog))
	s.mux.HandleFunc("/mcp", s.authorized("", false, s.workspaceMCP()))
	s.mux.HandleFunc("/", s.publishedFile)
	return s, nil
}

func (s *Server) Close() error {
	s.client.CloseIdleConnections()
	if s.projects != nil {
		s.projects.Close()
	}
	return s.static.Close()
}

func loopbackHost(host string) bool {
	return host == "localhost" || host == "127.0.0.1" || host == "::1"
}

func (s *Server) validSource(r *http.Request) bool {
	if strings.ContainsAny(r.Host, "/@?#\\, \t\r\n") {
		return false
	}
	u, err := url.Parse("http://" + r.Host)
	if err != nil || u.Hostname() == "" || u.User != nil {
		return false
	}
	host := strings.ToLower(u.Hostname())
	allowed := loopbackHost(host)
	for _, candidate := range s.cfg.AllowedHosts {
		allowed = allowed || strings.EqualFold(host, candidate)
	}
	if s.cfg.PublicURL != "" {
		p, _ := url.Parse(s.cfg.PublicURL)
		allowed = allowed || strings.EqualFold(host, p.Hostname())
	}
	if !allowed {
		return false
	}
	if len(r.Header.Values("Origin")) > 1 {
		return false
	}
	if origin := r.Header.Get("Origin"); origin != "" {
		o, err := url.Parse(origin)
		if err != nil || o.User != nil || o.Path != "" || o.RawQuery != "" || o.Fragment != "" || !strings.EqualFold(o.Host, r.Host) || (o.Scheme != "https" && !(o.Scheme == "http" && loopbackHost(host))) {
			return false
		}
	}
	return true
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	id, err := randomHex(16)
	if err != nil {
		http.Error(w, "service unavailable", 503)
		return
	}
	// nginx overwrites this header with its generated ID. Trust only a loopback
	// peer and the exact bounded format; this value never grants authority or
	// deduplicates an operation.
	peer, _, peerErr := net.SplitHostPort(r.RemoteAddr)
	if peerErr == nil && net.ParseIP(peer) != nil && net.ParseIP(peer).IsLoopback() {
		values := r.Header.Values("X-Request-ID")
		if len(values) == 1 && identifier.MatchString(values[0]) {
			id = values[0]
		}
	}
	w.Header().Set("X-Request-ID", id)
	w.Header().Set("X-VibeStack-Instance-ID", s.cfg.Store.Identity)
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	if !s.validSource(r) {
		s.failure(w, 403, "forbidden", "The request origin is not allowed.", false)
		return
	}
	// Do not let ServeMux turn a malformed API path into an unauthenticated
	// canonicalization redirect before the route's authorization middleware.
	for _, part := range strings.Split(r.URL.Path, "/") {
		if part == "." || part == ".." || strings.ContainsAny(part, "\\\x00") {
			s.failure(w, 400, "invalid_input", "The request path is invalid.", false)
			return
		}
	}
	if strings.Contains(r.URL.Path, "//") {
		s.failure(w, 400, "invalid_input", "The request path is invalid.", false)
		return
	}
	if r.URL.Query().Has("token") || r.URL.Query().Has("access_token") || r.URL.Query().Has("authorization") {
		s.failure(w, 400, "invalid_input", "Credentials are not accepted in URLs.", false)
		return
	}
	defer func() {
		if recover() != nil {
			s.failure(w, 500, "internal_error", "The request could not be completed.", false)
		}
	}()
	s.mux.ServeHTTP(w, r)
}

func (s *Server) json(w http.ResponseWriter, status int, value any) {
	b, err := json.Marshal(value)
	if err != nil {
		http.Error(w, "response unavailable", 500)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	w.Write(append(b, '\n'))
}

func (s *Server) failure(w http.ResponseWriter, status int, code, message string, retry bool) {
	if status == 401 {
		w.Header().Set("WWW-Authenticate", `Bearer realm="vibestack"`)
	}
	legacyCode := code
	if code == "unauthenticated" {
		legacyCode = "unauthorized"
	}
	s.json(w, status, map[string]any{"instance_id": s.cfg.Store.Identity, "request_id": w.Header().Get("X-Request-ID"), "code": legacyCode, "message": message, "error": map[string]any{"code": code, "message": message, "retryable": retry}})
}

func (s *Server) authenticate(r *http.Request) (Principal, error) {
	auth := r.Header.Values("Authorization")
	if len(auth) > 0 {
		if len(auth) != 1 || !strings.HasPrefix(auth[0], "Bearer ") {
			return Principal{}, ErrUnauthenticated
		}
		return s.cfg.Store.Authenticate(strings.TrimPrefix(auth[0], "Bearer "))
	}
	cookies := r.CookiesNamed("vibestack_session")
	if len(cookies) != 1 || len(cookies[0].Value) != 64 {
		return Principal{}, ErrUnauthenticated
	}
	s.mu.Lock()
	value, ok := s.sessions[tokenDigest(cookies[0].Value)]
	s.mu.Unlock()
	if !ok || !value.Expires.After(time.Now()) {
		return Principal{}, ErrUnauthenticated
	}
	if r.Method != "GET" && r.Method != "HEAD" {
		csrf := r.Header.Values("X-VibeStack-CSRF")
		if len(csrf) != 1 || subtle.ConstantTimeCompare([]byte(csrf[0]), []byte(value.CSRF)) != 1 {
			return Principal{}, ErrUnauthenticated
		}
	}
	return s.cfg.Store.authenticateDigest(value.Digest)
}

func (s *Server) authorized(id string, owner bool, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if site := r.Header.Get("Sec-Fetch-Site"); site == "cross-site" || site == "same-site" {
			s.failure(w, 403, "forbidden", "Cross-origin API access is not allowed.", false)
			return
		}
		p, err := s.authenticate(r)
		if err != nil {
			if errors.Is(err, ErrUnsafeState) {
				s.failure(w, 503, "unavailable", "Credential storage is unavailable.", false)
			} else {
				s.failure(w, 401, "unauthenticated", "Authenticate with a workspace credential.", false)
			}
			return
		}
		if (id != "" || owner) && !p.Allows(id, owner) {
			s.failure(w, 403, "forbidden", "This operation requires a different grant.", false)
			return
		}
		expected := r.Header.Values("X-VibeStack-Expected-Instance")
		if len(expected) > 1 || (len(expected) == 1 && expected[0] != p.InstanceID) {
			s.failure(w, 409, "wrong_instance", "The selected instance does not match this service.", false)
			return
		}
		select {
		case s.slots <- struct{}{}:
			defer func() { <-s.slots }()
		default:
			w.Header().Set("Retry-After", "1")
			s.failure(w, 429, "busy", "The service is at capacity.", true)
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), principalKey, p)))
	}
}

func (s *Server) authSession(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" {
		s.failure(w, 400, "invalid_input", "Session routes do not accept query parameters.", false)
		return
	}
	if r.Method == "POST" && len(r.Header.Values("Authorization")) != 1 {
		s.failure(w, 401, "unauthenticated", "Use a human-provided credential to sign in.", false)
		return
	}
	if r.Method != "POST" && r.Method != "GET" && r.Method != "DELETE" {
		s.failure(w, 405, "invalid_input", "Use GET, POST or DELETE for a browser session.", false)
		return
	}
	s.authorized("", false, func(w http.ResponseWriter, r *http.Request) {
		if _, err := readBounded(r.Body, 0); err != nil {
			s.failure(w, 413, "limit_exceeded", "Session requests do not accept a body.", false)
			return
		}
		p := r.Context().Value(principalKey).(Principal)
		s.mu.Lock()
		defer s.mu.Unlock()
		for key, value := range s.sessions {
			if !value.Expires.After(time.Now()) {
				delete(s.sessions, key)
			}
		}
		if r.Method == "DELETE" {
			for _, cookie := range r.CookiesNamed("vibestack_session") {
				delete(s.sessions, tokenDigest(cookie.Value))
			}
			http.SetCookie(w, &http.Cookie{Name: "vibestack_session", Value: "", Path: "/", HttpOnly: true, Secure: true, MaxAge: -1, SameSite: http.SameSiteStrictMode})
			s.json(w, 200, map[string]any{"authenticated": false})
			return
		}
		if r.Method == "POST" {
			if len(s.sessions) >= 128 {
				s.failure(w, 429, "busy", "Too many browser sessions are active.", true)
				return
			}
			secret, err := randomHex(32)
			if err != nil {
				s.failure(w, 503, "unavailable", "Session creation failed.", false)
				return
			}
			csrf, err := randomHex(32)
			if err != nil {
				s.failure(w, 503, "unavailable", "Session creation failed.", false)
				return
			}
			value := session{Digest: p.digest, CSRF: csrf, Expires: time.Now().Add(8 * time.Hour)}
			s.sessions[tokenDigest(secret)] = value
			host, _, err := net.SplitHostPort(r.Host)
			if err != nil {
				host = r.Host
			}
			secure := !loopbackHost(host)
			if strings.HasPrefix(s.cfg.PublicURL, "https://") {
				secure = true
			}
			http.SetCookie(w, &http.Cookie{Name: "vibestack_session", Value: secret, Path: "/", HttpOnly: true, Secure: secure, SameSite: http.SameSiteStrictMode, MaxAge: 8 * 60 * 60})
			s.json(w, 200, map[string]any{"authenticated": true, "csrf": csrf, "instance_id": p.InstanceID, "expires_at": value.Expires.Unix()})
			return
		}
		csrf := ""
		for _, cookie := range r.CookiesNamed("vibestack_session") {
			csrf = s.sessions[tokenDigest(cookie.Value)].CSRF
		}
		s.json(w, 200, map[string]any{"authenticated": true, "csrf": csrf, "instance_id": p.InstanceID, "owner": p.Owner})
	})(w, r)
}

func (s *Server) discovery(w http.ResponseWriter, r *http.Request) {
	origin := s.cfg.PublicURL
	if origin == "" {
		scheme := "https"
		u, _ := url.Parse("http://" + r.Host)
		if loopbackHost(u.Hostname()) {
			scheme = "http"
		}
		origin = scheme + "://" + r.Host
	}
	s.json(w, 200, map[string]any{"kind": "workspace", "version": release.Version, "identity": s.cfg.Store.Identity, "api_versions": []string{"1"}, "api_roots": map[string]string{"automation": "/api/v1/automation", "control": "/api/v1", "setup": "/setup/api"}, "documentation": map[string]string{"agents": "/AGENTS.md", "cli": "/CLI.md", "automation": "/AUTOMATION.md", "mcp": "/MCP.md", "service": "/SERVICE.md", "extensions": "/EXTENSIONS.md"}, "canonical_origin": origin, "mcp_url": origin + "/mcp", "cli": map[string]string{"version": release.Version, "installer": origin + "/cli.sh", "manifest": origin + "/release-manifest.json", "compatible": ">=0.2.0 <1.0.0", "generic_minimum": "0.3.0"}, "authentication_mode": "paired", "authentication": map[string]any{"modes": []string{"bearer", "browser-session"}, "credential_issuance": "local-operator", "session_url": origin + "/auth/session"}, "endpoints": map[string]string{"agents": origin + "/AGENTS.md", "api": origin + "/api/v1", "schema": origin + "/api/workspace.openapi.json", "registered_schema": origin + "/api/capabilities.openapi.json", "capabilities": origin + "/api/v1/capabilities"}, "mcp": map[string]any{"state": "available", "url": origin + "/mcp", "transport": "streamable-http", "stateless": true, "authentication": "configured-bearer", "oauth": "unavailable", "next_action": "Use a verified bearer-capable client; private Codespaces gateway authentication is separate."}})
}

func readBounded(r io.Reader, limit int64) ([]byte, error) {
	data, err := io.ReadAll(io.LimitReader(r, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, errors.New("body exceeds limit")
	}
	return data, nil
}
