package service

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"sort"
	"strconv"
	"strings"

	"github.com/check-the-vibe/vibestack/api"
)

type legacyRoute struct {
	ID, Method, Path, Target string
	Owner                    bool
	BodyLimit                int64
}

func (s *Server) registerLegacy() error {
	var schema struct {
		Paths map[string]map[string]struct {
			ID string `json:"operationId"`
		} `json:"paths"`
	}
	if json.Unmarshal(api.WorkspaceOpenAPI, &schema) != nil {
		return errors.New("invalid workspace route schema")
	}
	for path, methods := range schema.Paths {
		for method, operation := range methods {
			if operation.ID == "discoverWorkspace" {
				continue
			}
			route := legacyRoute{ID: operation.ID, Method: strings.ToUpper(method), Path: path, Target: s.cfg.ControlURL, BodyLimit: 4096}
			if strings.HasPrefix(path, "/api/v1/automation") {
				route.Target = s.cfg.AutomationURL
				route.BodyLimit = (1 << 20) + 4096
			}
			if strings.Contains(path, "/{path}") {
				route.BodyLimit = 16 << 20
			}
			if strings.Contains(path, "/pairing/") {
				route.Owner = true
			}
			s.operations = append(s.operations, route)
		}
	}
	for _, route := range []legacyRoute{
		{ID: "workspaceSetupState", Method: "GET", Path: "/setup/api/state"},
		{ID: "workspaceSetupDiscovery", Method: "GET", Path: "/setup/api/discovery"},
		{ID: "listWorkspaceClients", Method: "GET", Path: "/setup/api/clients", Owner: true},
		{ID: "workspaceInstallOutput", Method: "GET", Path: "/setup/api/log"},
		{ID: "approveWorkspacePairing", Method: "POST", Path: "/setup/api/pairings/{code}/approve", Owner: true},
		{ID: "denyWorkspacePairing", Method: "POST", Path: "/setup/api/pairings/{code}/deny", Owner: true},
		{ID: "revokeWorkspaceClient", Method: "POST", Path: "/setup/api/clients/{id}/revoke", Owner: true},
		{ID: "setLinuxPassword", Method: "POST", Path: "/setup/api/password", Owner: true},
		{ID: "installWorkspaceComponents", Method: "POST", Path: "/setup/api/install"},
		{ID: "skipWorkspaceSetup", Method: "POST", Path: "/setup/api/skip"},
		{ID: "completeWorkspaceSetup", Method: "POST", Path: "/setup/api/complete"},
		{ID: "resetWorkspaceSetup", Method: "POST", Path: "/setup/api/reset"},
	} {
		route.Target = s.cfg.SetupURL
		route.BodyLimit = 64 << 10
		s.operations = append(s.operations, route)
	}
	sort.Slice(s.operations, func(i, j int) bool { return s.operations[i].ID < s.operations[j].ID })
	for _, route := range s.operations {
		pattern := route.Method + " " + strings.ReplaceAll(route.Path, "{path}", "{path...}")
		if route.ID == "workspaceSetupDiscovery" {
			s.mux.HandleFunc(pattern, s.authorized(route.ID, route.Owner, s.discovery))
			continue
		}
		s.mux.HandleFunc(pattern, s.authorized(route.ID, route.Owner, func(w http.ResponseWriter, r *http.Request) { s.forwardLegacy(w, r, route) }))
	}
	return nil
}

func (s *Server) forwardLegacy(w http.ResponseWriter, r *http.Request, route legacyRoute) {
	if r.ContentLength > route.BodyLimit {
		s.failure(w, 413, "limit_exceeded", "The request exceeds this operation's body limit.", false)
		return
	}
	body, err := readBounded(r.Body, route.BodyLimit)
	if err != nil {
		s.failure(w, 413, "limit_exceeded", "The request exceeds this operation's body limit.", false)
		return
	}
	path := r.URL.EscapedPath()
	if route.Target == s.cfg.SetupURL && strings.HasPrefix(route.Path, "/setup/") {
		path = strings.TrimPrefix(path, "/setup")
	}
	target := route.Target + path
	if r.URL.RawQuery != "" {
		target += "?" + r.URL.RawQuery
	}
	upstream, err := http.NewRequestWithContext(r.Context(), r.Method, target, bytes.NewReader(body))
	if err != nil {
		s.failure(w, 400, "invalid_input", "The request path is invalid.", false)
		return
	}
	for _, header := range []string{"Content-Type", "Accept", "If-Match", "If-None-Match", "If-Range", "Range"} {
		for _, value := range r.Header.Values(header) {
			upstream.Header.Add(header, value)
		}
	}
	upstream.Header.Set("X-Request-ID", w.Header().Get("X-Request-ID"))
	if strings.HasPrefix(route.Path, "/api/v1/automation") {
		token, err := s.cfg.Store.InternalToken()
		if err != nil {
			s.failure(w, 503, "unavailable", "The execution service credential is unavailable.", false)
			return
		}
		upstream.Header.Set("Authorization", "Bearer "+token)
	}
	response, err := s.client.Do(upstream)
	if err != nil {
		s.failure(w, 503, "unavailable", "The local operation did not return a confirmed result; inspect state before retrying.", false)
		return
	}
	defer response.Body.Close()
	if response.StatusCode >= 300 && response.StatusCode < 400 && response.StatusCode != 304 {
		s.failure(w, 502, "unavailable", "The local service returned an unexpected redirect.", false)
		return
	}
	result, err := readBounded(response.Body, 24<<20)
	if err != nil {
		s.failure(w, 413, "limit_exceeded", "The result exceeds the operation response limit; inspect state before retrying.", false)
		return
	}
	for _, header := range []string{"Content-Type", "ETag", "Last-Modified", "Accept-Ranges", "Content-Range"} {
		if value := response.Header.Get(header); value != "" {
			w.Header().Set(header, value)
		}
	}
	if r.Method == "HEAD" {
		if size := response.Header.Get("Content-Length"); size != "" {
			w.Header().Set("Content-Length", size)
		}
	} else {
		w.Header().Set("Content-Length", strconv.Itoa(len(result)))
	}
	w.WriteHeader(response.StatusCode)
	w.Write(result)
}
