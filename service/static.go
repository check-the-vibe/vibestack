package service

import (
	"net/http"
	"os"
	"path"
	"strings"
	"syscall"
)

func (s *Server) publishedFile(w http.ResponseWriter, r *http.Request) {
	for _, reserved := range []string{"/api", "/auth", "/mcp", "/.well-known", "/setup/api"} {
		if r.URL.Path == reserved || strings.HasPrefix(r.URL.Path, reserved+"/") {
			s.authorized("", false, func(w http.ResponseWriter, r *http.Request) {
				s.failure(w, 404, "not_found", "The route is not available.", false)
			})(w, r)
			return
		}
	}
	if r.Method != "GET" && r.Method != "HEAD" {
		s.failure(w, 405, "invalid_input", "Published files support GET and HEAD only.", false)
		return
	}
	requested := r.URL.Path
	if requested == "/" {
		requested = "/index.html"
	}
	if !strings.HasPrefix(requested, "/") || path.Clean(requested) != requested || strings.ContainsAny(requested, "\\\x00%") {
		s.failure(w, 404, "not_found", "Published file not found.", false)
		return
	}
	name := strings.TrimPrefix(requested, "/")
	parts := strings.Split(name, "/")
	for i, part := range parts {
		lower := strings.ToLower(part)
		if part == "" || strings.HasPrefix(part, ".") || lower == "credentials.json" || lower == "secrets.json" || strings.HasSuffix(lower, ".pem") || strings.HasSuffix(lower, ".key") || strings.HasSuffix(lower, ".token") {
			s.failure(w, 404, "not_found", "Published file not found.", false)
			return
		}
		info, err := s.static.Lstat(strings.Join(parts[:i+1], "/"))
		if err != nil || info.Mode()&os.ModeSymlink != 0 {
			s.failure(w, 404, "not_found", "Published file not found.", false)
			return
		}
	}
	f, err := s.static.Open(name)
	if err != nil {
		s.failure(w, 404, "not_found", "Published file not found.", false)
		return
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > 16<<20 {
		s.failure(w, 404, "not_found", "Published file not found.", false)
		return
	}
	if stat, ok := info.Sys().(*syscall.Stat_t); !ok || stat.Nlink != 1 {
		s.failure(w, 404, "not_found", "Published file not found.", false)
		return
	}
	if strings.HasSuffix(strings.ToLower(info.Name()), ".md") {
		w.Header().Set("Content-Type", "text/markdown; charset=utf-8")
	}
	w.Header().Set("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
	http.ServeContent(w, r, info.Name(), info.ModTime(), f)
}
