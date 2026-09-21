package runner

import (
	"bytes"
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	assets "github.com/check-the-vibe/vibestack"
	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

var (
	idPattern   = regexp.MustCompile(`^[0-9a-f]{32}$`)
	codePattern = regexp.MustCompile(`^[A-Z2-9]{4}-[A-Z2-9]{4}$`)
)

type Server struct {
	Config          Config
	Store           *Store
	Manager         *Manager
	HTTP            *http.Server
	MCP             http.Handler
	authError       error
	sharedPrincipal string
}

type principal struct {
	ID          string
	Permissions map[string]bool
}
type principalKey struct{}

type apiError struct {
	Status        int
	Code, Message string
}

func (e *apiError) Error() string { return e.Message }

func NewServer(config Config, store *Store, manager *Manager) *Server {
	server := &Server{Config: config, Store: store, Manager: manager}
	server.sharedPrincipal, server.authError = store.ConfigureAuthentication(context.Background(), config.AuthenticationMode)
	server.MCP = server.mcpHandler()
	mux := http.NewServeMux()
	mux.HandleFunc("/", server.handle)
	server.HTTP = &http.Server{Addr: config.Listen, Handler: mux, ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 65 * time.Second, WriteTimeout: 65 * time.Second, IdleTimeout: 90 * time.Second, MaxHeaderBytes: 32 << 10}
	return server
}

func (s *Server) Serve() error                       { return s.HTTP.ListenAndServe() }
func (s *Server) Shutdown(ctx context.Context) error { return s.HTTP.Shutdown(ctx) }

func (s *Server) handle(w http.ResponseWriter, r *http.Request) {
	requestID := requestID(r)
	w.Header().Set("X-Request-ID", requestID)
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	if err := s.validateSource(r); err != nil {
		s.error(w, requestID, err)
		return
	}
	defer func() {
		if recovered := recover(); recovered != nil {
			s.error(w, requestID, &apiError{500, "internal_error", "The runner request failed."})
		}
	}()
	if s.authError != nil {
		s.error(w, requestID, &apiError{503, "authentication_configuration", "Authentication mode requires an empty registry before switching."})
		return
	}
	if s.Config.AuthenticationMode == AuthTrustedTailnet && strings.HasPrefix(r.URL.Path, APIRoot+"/pairing/") {
		s.error(w, requestID, &apiError{404, "pairing_disabled", "Trusted-tailnet mode does not use pairing."})
		return
	}
	if r.URL.Path == api.DiscoveryPath && r.Method == http.MethodGet {
		s.discovery(w, r, requestID)
		return
	}
	if r.URL.Path == "/cli.sh" && r.Method == http.MethodGet {
		s.asset(w, "cli.sh", "text/x-shellscript; charset=utf-8")
		return
	}
	if r.Method == http.MethodGet && r.URL.Path == "/AGENTS.md" {
		s.agentsGuide(w)
		return
	}
	if r.Method == http.MethodGet && r.URL.Path == "/api/runner.openapi.json" {
		s.asset(w, "api/runner.openapi.json", "application/json")
		return
	}
	if r.Method == http.MethodGet {
		if name, ok := map[string]string{"/CLI.md": "docs/CLI.md", "/AUTOMATION.md": "docs/AUTOMATION.md", "/RUNNER.md": "docs/RUNNER.md", "/skills/vibestack/SKILL.md": "skills/vibestack/SKILL.md"}[r.URL.Path]; ok {
			s.asset(w, name, "text/markdown; charset=utf-8")
			return
		}
	}
	if r.Method == http.MethodPost && r.URL.Path == APIRoot+"/pairing/requests" {
		s.pairingRequest(w, r, requestID)
		return
	}
	if r.Method == http.MethodPost && strings.HasPrefix(r.URL.Path, APIRoot+"/pairing/requests/") && strings.HasSuffix(r.URL.Path, "/poll") {
		s.pairingPoll(w, r, requestID)
		return
	}
	p, err := s.authenticate(r)
	if err != nil {
		s.error(w, requestID, err)
		return
	}
	r = r.WithContext(context.WithValue(r.Context(), principalKey{}, p))
	if r.URL.Path == "/mcp" {
		if r.URL.RawQuery != "" {
			s.error(w, requestID, &apiError{400, "invalid_query", "MCP accepts no query parameters."})
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
		s.MCP.ServeHTTP(w, r)
		return
	}
	if err := s.dispatch(w, r, requestID, p); err != nil {
		s.error(w, requestID, err)
	}
}

func (s *Server) asset(w http.ResponseWriter, name, contentType string) {
	data, err := assets.Files.ReadFile(name)
	if err != nil {
		http.NotFound(w, nil)
		return
	}
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Content-Length", fmt.Sprint(len(data)))
	w.WriteHeader(200)
	_, _ = w.Write(data)
}

func (s *Server) validateSource(r *http.Request) *apiError {
	hosts := r.Header.Values("Host")
	if len(hosts) > 1 {
		return &apiError{400, "invalid_host", "A single Host header is required."}
	}
	host := r.Host
	if host == "" {
		return &apiError{400, "invalid_host", "A Host header is required."}
	}
	hostname, _, err := net.SplitHostPort(host)
	if err != nil {
		hostname = host
	}
	hostname = strings.Trim(hostname, "[]")
	public, _ := url.Parse(s.Config.PublicURL)
	ip := net.ParseIP(hostname)
	localHost := strings.EqualFold(hostname, "localhost") || ip != nil && ip.IsLoopback()
	if !strings.EqualFold(host, s.Config.Listen) && !strings.EqualFold(host, public.Host) {
		return &apiError{421, "host_not_allowed", "The request Host is not allowed."}
	}
	fetchSites := r.Header.Values("Sec-Fetch-Site")
	if len(fetchSites) > 1 {
		return &apiError{400, "invalid_request", "Duplicate fetch metadata is not allowed."}
	}
	if site := strings.ToLower(r.Header.Get("Sec-Fetch-Site")); site == "cross-site" || site == "same-site" {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			return &apiError{403, "cross_origin", "Cross-origin requests are not allowed."}
		}
		modes := r.Header.Values("Sec-Fetch-Mode")
		destinations := r.Header.Values("Sec-Fetch-Dest")
		if len(modes) != 1 || len(destinations) != 1 {
			return &apiError{400, "invalid_request", "Safe navigation fetch metadata is required."}
		}
		destination := strings.ToLower(strings.TrimSpace(destinations[0]))
		if !strings.EqualFold(strings.TrimSpace(modes[0]), "navigate") || (destination != "document" && destination != "empty") {
			return &apiError{403, "cross_origin", "Cross-origin requests are not allowed."}
		}
	} else if site != "" && site != "none" && site != "same-origin" {
		return &apiError{400, "invalid_request", "Fetch metadata is invalid."}
	}
	origins := r.Header.Values("Origin")
	if len(origins) > 1 {
		return &apiError{400, "invalid_request", "Duplicate Origin headers are not allowed."}
	}
	if origin := r.Header.Get("Origin"); origin != "" {
		parsed, err := url.Parse(origin)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.User != nil || parsed.Path != "" || parsed.RawQuery != "" || parsed.Fragment != "" || !(strings.EqualFold(origin, s.Config.PublicURL) || localHost && strings.EqualFold(parsed.Host, r.Host) && parsed.Scheme == "http") {
			return &apiError{403, "cross_origin", "Cross-origin requests are not allowed."}
		}
	}
	return nil
}

func requestID(r *http.Request) string {
	value := r.Header.Get("X-Request-ID")
	if matched, _ := regexp.MatchString(`^[A-Za-z0-9._:-]{1,64}$`, value); matched {
		return value
	}
	bytes := make([]byte, 16)
	_, _ = rand.Read(bytes)
	return hex.EncodeToString(bytes)
}

func (s *Server) authenticate(r *http.Request) (principal, *apiError) {
	if s.Config.AuthenticationMode == AuthTrustedTailnet {
		return principal{ID: s.sharedPrincipal, Permissions: map[string]bool{"instances:read": true, "instances:write": true}}, nil
	}
	values := r.Header.Values("Authorization")
	if len(values) != 1 {
		return principal{}, &apiError{401, "unauthorized", "A valid bearer credential is required."}
	}
	scheme, credential, ok := strings.Cut(values[0], " ")
	if !ok || !strings.EqualFold(scheme, "Bearer") || len(credential) > 512 {
		return principal{}, &apiError{401, "unauthorized", "A valid bearer credential is required."}
	}
	id, permissions, valid := s.Store.Authenticate(r.Context(), strings.TrimSpace(credential))
	if !valid {
		return principal{}, &apiError{401, "unauthorized", "A valid bearer credential is required."}
	}
	p := principal{ID: id, Permissions: map[string]bool{}}
	for _, permission := range permissions {
		p.Permissions[permission] = true
	}
	return p, nil
}

func (s *Server) discovery(w http.ResponseWriter, r *http.Request, requestID string) {
	if r.URL.RawQuery != "" {
		s.error(w, requestID, &apiError{400, "invalid_query", "Discovery accepts no query."})
		return
	}
	identity, err := s.Store.Identity(r.Context())
	if err != nil {
		s.error(w, requestID, &apiError{503, "state_unavailable", "Runner identity is unavailable."})
		return
	}
	payload := map[string]any{"kind": "runner", "identity": identity, "version": api.Version, "api_versions": []string{"1"}, "api_roots": map[string]string{"runner": APIRoot}, "documentation": map[string]string{"agents": "/AGENTS.md", "cli": "/CLI.md", "automation": "/AUTOMATION.md", "runner": "/RUNNER.md", "openapi": "/api/runner.openapi.json"}, "pairing": map[string]any{"request": APIRoot + "/pairing/requests", "approval": "Run vibestack-runner pairings approve CODE on the host.", "permissions": []string{"instances:read", "instances:write"}}, "cli": map[string]string{"installer": "/cli.sh", "compatible": ">=0.2.0 <1.0.0"}}
	payload["authentication_mode"] = s.Config.AuthenticationMode
	payload["mcp_url"] = s.Config.PublicURL + "/mcp"
	if s.Config.AuthenticationMode == AuthTrustedTailnet {
		delete(payload, "pairing")
	}
	writeJSON(w, 200, payload)
}

func (s *Server) pairingRequest(w http.ResponseWriter, r *http.Request, requestID string) {
	var body struct {
		DeviceLabel string   `json:"device_label"`
		Permissions []string `json:"permissions"`
	}
	if err := decodeBody(r, &body); err != nil {
		s.error(w, requestID, err)
		return
	}
	value, err := s.Store.RequestPairing(r.Context(), body.DeviceLabel, body.Permissions)
	if err != nil {
		s.error(w, requestID, &apiError{400, "invalid_pairing_request", safeError(err)})
		return
	}
	writeJSON(w, 201, value)
}

func (s *Server) pairingPoll(w http.ResponseWriter, r *http.Request, requestID string) {
	trimmed := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, APIRoot+"/pairing/requests/"), "/poll")
	if !idPattern.MatchString(trimmed) {
		s.error(w, requestID, &apiError{404, "pairing_not_found", "The pairing request does not exist."})
		return
	}
	var body struct {
		PollingSecret string `json:"polling_secret"`
	}
	if err := decodeBody(r, &body); err != nil {
		s.error(w, requestID, err)
		return
	}
	value, err := s.Store.PollPairing(r.Context(), trimmed, body.PollingSecret)
	if err != nil {
		status := 404
		code := "pairing_not_found"
		if strings.Contains(err.Error(), "expired") {
			status = 410
			code = "pairing_expired"
		}
		s.error(w, requestID, &apiError{status, code, "The pairing request is unavailable."})
		return
	}
	writeJSON(w, 200, value)
}

func (s *Server) dispatch(w http.ResponseWriter, r *http.Request, requestID string, p principal) *apiError {
	if strings.HasPrefix(r.URL.Path, APIRoot+"/instances/") {
		return s.instanceRoute(w, r, requestID, p)
	}
	if r.URL.RawQuery != "" {
		return &apiError{400, "invalid_query", "This endpoint accepts no query."}
	}
	switch r.URL.Path {
	case APIRoot + "/host", APIRoot + "/drives", APIRoot + "/environment-sets", APIRoot + "/snapshots":
		return s.storageRoute(w, r, p)
	}
	if r.URL.Path == APIRoot && r.Method == http.MethodGet {
		return s.capabilities(w, r, p)
	}
	if r.URL.Path == APIRoot+"/instances" {
		if r.Method == http.MethodGet {
			return s.listInstances(w, r, p)
		}
		if r.Method == http.MethodPost {
			return s.createInstance(w, r, requestID, p)
		}
	}
	if r.URL.Path == APIRoot+"/operations" && r.Method == http.MethodGet {
		return s.listOperations(w, r, p)
	}
	if strings.HasPrefix(r.URL.Path, APIRoot+"/operations/") && r.Method == http.MethodGet {
		return s.getOperation(w, r, p)
	}
	return &apiError{404, "not_found", "Endpoint not found."}
}

func requirePermission(p principal, value string) *apiError {
	if !p.Permissions[value] {
		return &apiError{403, "permission_denied", "The client credential lacks the required permission."}
	}
	return nil
}

func (s *Server) capabilities(w http.ResponseWriter, r *http.Request, p principal) *apiError {
	if err := requirePermission(p, "instances:read"); err != nil {
		return err
	}
	templates, err := s.Store.Templates(r.Context())
	if err != nil {
		return &apiError{503, "state_unavailable", "Template state is unavailable."}
	}
	writeJSON(w, 200, map[string]any{"api_version": "1", "base_path": APIRoot, "authentication": s.Config.AuthenticationMode, "mcp_url": s.Config.PublicURL + "/mcp", "launch_contract": launchVersion, "approved_templates": templates, "limits": map[string]any{"instances": s.Config.MaxInstances, "provisioning_concurrency": s.Config.ProvisioningConcurrency, "port_min": s.Config.PortMin, "port_max": s.Config.PortMax, "minimum_free_bytes": s.Config.MinFreeBytes}, "routes": map[string]string{"host": APIRoot + "/host", "drives": APIRoot + "/drives", "environment_sets": APIRoot + "/environment-sets", "snapshots": APIRoot + "/snapshots", "attachments": APIRoot + "/instances/{id}/attachments", "snapshot": APIRoot + "/instances/{id}/snapshot", "instances": APIRoot + "/instances", "instance": APIRoot + "/instances/{id}", "operations": APIRoot + "/operations/{id}", "workspace_proxy": APIRoot + "/instances/{id}/workspace/{supported-path}"}})
	return nil
}

func (s *Server) listInstances(w http.ResponseWriter, r *http.Request, p principal) *apiError {
	if err := requirePermission(p, "instances:read"); err != nil {
		return err
	}
	values, err := s.Store.Instances(r.Context(), false)
	if err != nil {
		return &apiError{503, "state_unavailable", "Instance state is unavailable."}
	}
	owned := values[:0]
	for _, value := range values {
		if value.Owner == p.ID {
			if s.Manager != nil {
				value = s.Manager.RefreshInstance(r.Context(), value)
			}
			owned = append(owned, value)
		}
	}
	writeJSON(w, 200, map[string]any{"instances": owned})
	return nil
}

func (s *Server) createInstance(w http.ResponseWriter, r *http.Request, requestID string, p principal) *apiError {
	if err := requirePermission(p, "instances:write"); err != nil {
		return err
	}
	keys := r.Header.Values("Idempotency-Key")
	if len(keys) != 1 || len(keys[0]) < 1 || len(keys[0]) > 128 {
		return &apiError{400, "idempotency_key_required", "One bounded Idempotency-Key is required."}
	}
	var request CreateRequest
	if err := decodeBody(r, &request); err != nil {
		return err
	}
	op, err := s.Manager.SubmitCreate(r.Context(), request, p.ID, keys[0], requestID)
	if err != nil {
		return &apiError{409, "create_rejected", safeError(err)}
	}
	writeJSON(w, 202, map[string]any{"operation": op})
	return nil
}

func (s *Server) instanceRoute(w http.ResponseWriter, r *http.Request, requestID string, p principal) *apiError {
	suffix := strings.TrimPrefix(r.URL.Path, APIRoot+"/instances/")
	parts := strings.Split(suffix, "/")
	if len(parts) < 1 || parts[0] == "" {
		return &apiError{404, "not_found", "Endpoint not found."}
	}
	instance, err := s.Store.Instance(r.Context(), parts[0])
	if err != nil || instance.Owner != p.ID {
		return &apiError{404, "instance_not_found", "The instance does not exist."}
	}
	if len(parts) == 1 && r.Method == http.MethodGet {
		if r.URL.RawQuery != "" {
			return &apiError{400, "invalid_query", "This endpoint accepts no query."}
		}
		if err := requirePermission(p, "instances:read"); err != nil {
			return err
		}
		if s.Manager != nil {
			instance = s.Manager.RefreshInstance(r.Context(), instance)
		}
		selection, err := s.Store.Selection(r.Context(), instance.ID)
		if err != nil {
			return storageUnavailable()
		}
		writeJSON(w, 200, map[string]any{"instance": instance, "storage": selection})
		return nil
	}
	if len(parts) >= 3 && parts[1] == "workspace" {
		return s.workspaceProxy(w, r, requestID, p, instance, "/"+strings.Join(parts[2:], "/"))
	}
	if len(parts) == 2 && parts[1] == "attachments" && r.Method == http.MethodPut {
		if r.URL.RawQuery != "" {
			return &apiError{400, "invalid_query", "This endpoint accepts no query."}
		}
		if err := requirePermission(p, "instances:write"); err != nil {
			return err
		}
		var body struct {
			ProjectDrive string       `json:"project_drive"`
			FileDrives   []Attachment `json:"file_drives"`
		}
		if err := decodeBody(r, &body); err != nil {
			return err
		}
		if err := s.Manager.ChangeAttachments(r.Context(), instance, body.ProjectDrive, body.FileDrives); err != nil {
			return storageRejected(err)
		}
		writeJSON(w, 200, map[string]any{"updated": true})
		return nil
	}
	if len(parts) == 2 && r.Method == http.MethodPost {
		if r.URL.RawQuery != "" {
			return &apiError{400, "invalid_query", "This endpoint accepts no query."}
		}
		if err := requirePermission(p, "instances:write"); err != nil {
			return err
		}
		action := parts[1]
		if action == "password" {
			return s.setInstancePassword(w, r, instance)
		}
		if action == "snapshot" {
			var body struct {
				Name string `json:"name"`
			}
			if err := decodeBody(r, &body); err != nil {
				return err
			}
			keys := r.Header.Values("Idempotency-Key")
			if len(keys) != 1 {
				return &apiError{400, "idempotency_key_required", "One Idempotency-Key is required."}
			}
			op, err := s.Manager.SubmitSnapshot(r.Context(), instance, body.Name, keys[0], requestID)
			if err != nil {
				return storageRejected(err)
			}
			writeJSON(w, 202, map[string]any{"operation": op})
			return nil
		}
		if action == "update" {
			keys := r.Header.Values("Idempotency-Key")
			if len(keys) != 1 || len(keys[0]) < 1 || len(keys[0]) > 128 {
				return &apiError{400, "idempotency_key_required", "One bounded Idempotency-Key is required."}
			}
			var request UpdateRequest
			if err := decodeBody(r, &request); err != nil {
				return err
			}
			if request.Template == "" {
				return &apiError{400, "invalid_template", "Update requires an approved template."}
			}
			op, err := s.Manager.SubmitUpdate(r.Context(), instance.ID, request, p.ID, keys[0], requestID)
			if err != nil {
				return &apiError{409, "update_rejected", safeError(err)}
			}
			writeJSON(w, 202, map[string]any{"operation": op})
			return nil
		}
		if action != "start" && action != "stop" && action != "restart" && action != "remove" {
			return &apiError{404, "not_found", "Endpoint not found."}
		}
		var empty map[string]any
		if err := decodeBody(r, &empty); err != nil {
			return err
		}
		if len(empty) != 0 {
			return &apiError{400, "unknown_field", "Lifecycle operation accepts no fields."}
		}
		op, err := s.Manager.SubmitAction(r.Context(), instance.ID, action, p.ID, requestID)
		if err != nil {
			return &apiError{409, "operation_rejected", safeError(err)}
		}
		writeJSON(w, 202, map[string]any{"operation": op})
		return nil
	}
	return &apiError{404, "not_found", "Endpoint not found."}
}

func (s *Server) listOperations(w http.ResponseWriter, r *http.Request, p principal) *apiError {
	if err := requirePermission(p, "instances:read"); err != nil {
		return err
	}
	values, err := s.Store.OperationsOwned(r.Context(), p.ID)
	if err != nil {
		return &apiError{503, "state_unavailable", "Operation state is unavailable."}
	}
	writeJSON(w, 200, map[string]any{"operations": values})
	return nil
}

func (s *Server) getOperation(w http.ResponseWriter, r *http.Request, p principal) *apiError {
	if err := requirePermission(p, "instances:read"); err != nil {
		return err
	}
	id := strings.TrimPrefix(r.URL.Path, APIRoot+"/operations/")
	if !idPattern.MatchString(id) {
		return &apiError{404, "operation_not_found", "The operation does not exist."}
	}
	op, err := s.Store.OperationOwned(r.Context(), id, p.ID)
	if err != nil {
		return &apiError{404, "operation_not_found", "The operation does not exist."}
	}
	writeJSON(w, 200, map[string]any{"operation": op})
	return nil
}

func (s *Server) workspaceProxy(w http.ResponseWriter, r *http.Request, requestID string, p principal, instance api.Instance, upstreamPath string) *apiError {
	permission := "instances:read"
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		permission = "instances:write"
	}
	if err := requirePermission(p, permission); err != nil {
		return err
	}
	if !allowedWorkspaceRoute(r.Method, upstreamPath) {
		return &apiError{404, "workspace_route_not_supported", "The workspace route is not available through the runner."}
	}
	if !instance.InfrastructureReady || instance.ObservedState != "running" {
		return &apiError{409, "workspace_unavailable", "The workspace is not running and infrastructure-ready."}
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead && r.ContentLength < 0 {
		return &apiError{411, "length_required", "A Content-Length header is required."}
	}
	if r.ContentLength > 16<<20 {
		return &apiError{413, "body_too_large", "The workspace request body is too large."}
	}
	var body []byte
	if r.Body != nil {
		var err error
		body, err = io.ReadAll(io.LimitReader(r.Body, (16<<20)+1))
		if err != nil {
			return &apiError{400, "invalid_body", "The workspace request body could not be read."}
		}
		if len(body) > 16<<20 {
			return &apiError{413, "body_too_large", "The workspace request body is too large."}
		}
	}
	credential, err := s.Store.WorkspaceCredential(instance.ID)
	if err != nil {
		return &apiError{503, "workspace_credential_unavailable", "The workspace credential is unavailable."}
	}
	target := fmt.Sprintf("http://127.0.0.1:%d%s", instance.Ports["http"], upstreamPath)
	if r.URL.RawQuery != "" {
		target += "?" + r.URL.RawQuery
	}
	upstream, err := http.NewRequestWithContext(r.Context(), r.Method, target, bytes.NewReader(body))
	if err != nil {
		return &apiError{500, "proxy_failed", "The workspace request could not be prepared."}
	}
	upstream.Header.Set("Authorization", "Bearer "+credential)
	for _, name := range []string{"Content-Type", "Accept", "Range", "If-Range", "If-Match", "If-None-Match"} {
		if values := r.Header.Values(name); len(values) == 1 {
			upstream.Header.Set(name, values[0])
		} else if len(values) > 1 {
			return &apiError{400, "duplicate_header", "Duplicate workspace request headers are not allowed."}
		}
	}
	client := &http.Client{Timeout: 65 * time.Second, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	response, err := client.Do(upstream)
	if err != nil {
		return &apiError{502, "workspace_unavailable", "The workspace did not answer the mediated request."}
	}
	defer response.Body.Close()
	var responseBody []byte
	if r.Method != http.MethodHead {
		responseBody, err = io.ReadAll(io.LimitReader(response.Body, (16<<20)+1))
		if err != nil {
			return &apiError{502, "workspace_response_invalid", "The workspace response could not be read."}
		}
		if len(responseBody) > 16<<20 {
			return &apiError{502, "workspace_response_too_large", "The workspace response exceeded the runner mediation limit."}
		}
	}
	for _, name := range []string{"Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Content-Disposition"} {
		if value := response.Header.Get(name); value != "" {
			w.Header().Set(name, value)
		}
	}
	if workspaceRequestID := response.Header.Get("X-Request-ID"); workspaceRequestID != "" {
		w.Header().Set("X-VibeStack-Workspace-Request-ID", workspaceRequestID)
	}
	w.Header().Set("X-Request-ID", requestID)
	w.WriteHeader(response.StatusCode)
	if r.Method != http.MethodHead {
		_, _ = w.Write(responseBody)
	}
	return nil
}

func allowedWorkspaceRoute(method, path string) bool {
	prefix := api.WorkspaceAPI
	if path == prefix {
		return method == http.MethodGet
	}
	if path == prefix+"/commands" || path == prefix+"/shell" || path == prefix+"/screenshot" {
		return method == http.MethodPost
	}
	if path == prefix+"/applications" || path == prefix+"/windows" || path == prefix+"/ssh-keys" {
		return method == http.MethodGet || path == prefix+"/ssh-keys" && method == http.MethodPost
	}
	if path == prefix+"/clipboard" {
		return method == http.MethodGet || method == http.MethodPut
	}
	if strings.HasPrefix(path, prefix+"/files/") || strings.HasPrefix(path, prefix+"/projects/") {
		return method == http.MethodGet || method == http.MethodHead || method == http.MethodPut
	}
	if matched, _ := regexp.MatchString(`^`+regexp.QuoteMeta(prefix)+`/jobs/[0-9a-f]{32}(/output|/cancel)?$`, path); matched {
		return method == http.MethodGet && !strings.HasSuffix(path, "/cancel") || method == http.MethodPost && strings.HasSuffix(path, "/cancel")
	}
	if matched, _ := regexp.MatchString(`^`+regexp.QuoteMeta(prefix)+`/applications/[a-z][a-z0-9-]{0,63}/(start|stop)$`, path); matched {
		return method == http.MethodPost
	}
	if matched, _ := regexp.MatchString(`^`+regexp.QuoteMeta(prefix)+`/windows/0x[0-9A-Fa-f]{1,16}/state$`, path); matched {
		return method == http.MethodPost
	}
	if matched, _ := regexp.MatchString(`^`+regexp.QuoteMeta(prefix)+`/ssh-keys/[0-9a-f]{32}/remove$`, path); matched {
		return method == http.MethodPost
	}
	if path == "/setup/api/state" {
		return method == http.MethodGet
	}
	if path == "/api/v1/status" || path == "/api/v1/display" {
		return method == http.MethodGet || path == "/api/v1/display" && method == http.MethodPut
	}
	if matched, _ := regexp.MatchString(`^/api/v1/logs/[a-z][a-z0-9-]{0,63}$`, path); matched {
		return method == http.MethodGet
	}
	if matched, _ := regexp.MatchString(`^/api/v1/services/[a-z][a-z0-9-]{0,63}/(start|stop|restart)$`, path); matched {
		return method == http.MethodPost
	}
	return false
}

func decodeBody(r *http.Request, target any) *apiError {
	contentTypes := r.Header.Values("Content-Type")
	if len(contentTypes) != 1 || contentTypes[0] != "application/json" {
		return &apiError{415, "unsupported_media_type", "Content-Type must be application/json."}
	}
	if r.ContentLength < 0 {
		return &apiError{411, "length_required", "A Content-Length header is required."}
	}
	if r.ContentLength > 1<<20 {
		return &apiError{413, "body_too_large", "The request body is too large."}
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, (1<<20)+1))
	if err != nil || int64(len(raw)) != r.ContentLength {
		return &apiError{400, "invalid_json", "The request body was incomplete or invalid."}
	}
	if duplicateFreeJSON(raw) != nil {
		return &apiError{400, "invalid_json", "The request body must not contain duplicate keys."}
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return &apiError{400, "invalid_json", "The request body must be one valid JSON object."}
	}
	var extra any
	if !errors.Is(decoder.Decode(&extra), io.EOF) {
		return &apiError{400, "invalid_json", "The request body must contain only one JSON value."}
	}
	return nil
}

func duplicateFreeJSON(raw []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	var visit func() error
	visit = func() error {
		token, err := decoder.Token()
		if err != nil {
			return err
		}
		delimiter, ok := token.(json.Delim)
		if !ok {
			return nil
		}
		switch delimiter {
		case '{':
			seen := map[string]bool{}
			for decoder.More() {
				keyToken, err := decoder.Token()
				if err != nil {
					return err
				}
				key, ok := keyToken.(string)
				if !ok || seen[key] {
					return errors.New("duplicate JSON key")
				}
				seen[key] = true
				if err := visit(); err != nil {
					return err
				}
			}
			_, err = decoder.Token()
			return err
		case '[':
			for decoder.More() {
				if err := visit(); err != nil {
					return err
				}
			}
			_, err = decoder.Token()
			return err
		default:
			return errors.New("invalid JSON delimiter")
		}
	}
	if err := visit(); err != nil {
		return err
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		return errors.New("trailing JSON value")
	}
	return nil
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	data, err := json.Marshal(value)
	if err != nil {
		status = 500
		data = []byte(`{"code":"internal_error","message":"The response could not be encoded."}`)
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Content-Length", fmt.Sprint(len(data)))
	w.WriteHeader(status)
	_, _ = w.Write(data)
}
func (s *Server) error(w http.ResponseWriter, requestID string, err *apiError) {
	if err.Status == 401 {
		w.Header().Set("WWW-Authenticate", `Bearer realm="VibeStack runner"`)
	}
	writeJSON(w, err.Status, map[string]any{"code": err.Code, "message": err.Message, "request_id": requestID})
}

var _ = sql.ErrNoRows
