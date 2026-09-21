package runner

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func (s *Server) storageRoute(w http.ResponseWriter, r *http.Request, p principal) *apiError {
	permission := "instances:read"
	if r.Method != "GET" {
		permission = "instances:write"
	}
	if err := requirePermission(p, permission); err != nil {
		return err
	}
	path := strings.TrimPrefix(r.URL.Path, APIRoot)
	switch path {
	case "/host":
		if r.Method != "GET" {
			break
		}
		ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
		defer cancel()
		status := map[string]any{"docker_available": false, "ready": false, "public_url": s.Config.PublicURL}
		version, err := s.Manager.Docker.ServerVersion(ctx)
		if err == nil {
			status["docker_available"] = true
			status["docker_version"] = version.Version
			status["docker_api_version"] = version.APIVersion
			status["ready"] = true
		}
		var fs syscall.Statfs_t
		if syscall.Statfs(s.Config.StateDir, &fs) == nil {
			free := int64(fs.Bavail) * int64(fs.Bsize)
			status["available_disk_bytes"] = free
			if free < s.Config.MinFreeBytes {
				status["ready"] = false
			}
		}
		if mem, err := os.ReadFile("/proc/meminfo"); err == nil {
			for _, line := range strings.Split(string(mem), "\n") {
				fields := strings.Fields(line)
				if len(fields) == 3 && fields[0] == "MemAvailable:" {
					kb, _ := strconv.ParseInt(fields[1], 10, 64)
					status["available_memory_bytes"] = kb * 1024
				}
			}
		}
		templates, err := s.Store.Templates(ctx)
		if err != nil {
			return storageUnavailable()
		}
		status["approved_images"] = templates
		instances, err := s.Store.Instances(ctx, false)
		if err != nil {
			return storageUnavailable()
		}
		managed := []any{}
		for _, i := range instances {
			if i.Owner != p.ID {
				continue
			}
			i = s.Manager.RefreshInstance(ctx, i)
			selection, err := s.Store.Selection(ctx, i.ID)
			if err != nil {
				return storageUnavailable()
			}
			managed = append(managed, map[string]any{"instance": i, "storage": selection})
		}
		status["managed_containers"] = managed
		drives, err := s.Store.Drives(ctx, p.ID)
		if err != nil {
			return storageUnavailable()
		}
		status["drives"] = drives
		writeJSON(w, 200, status)
		return nil
	case "/drives":
		if r.Method == "GET" {
			v, err := s.Store.Drives(r.Context(), p.ID)
			if err != nil {
				return storageUnavailable()
			}
			writeJSON(w, 200, map[string]any{"drives": v})
			return nil
		}
		if r.Method == "POST" {
			var body struct {
				Name string `json:"name"`
			}
			if err := decodeBody(r, &body); err != nil {
				return err
			}
			v, err := s.Store.RegisterDrive(r.Context(), body.Name, p.ID, "volume", "")
			if err != nil {
				return storageRejected(err)
			}
			writeJSON(w, 201, map[string]any{"drive": v})
			return nil
		}
	case "/environment-sets":
		if r.Method == "GET" {
			v, err := s.Store.Environments(r.Context(), p.ID)
			if err != nil {
				return storageUnavailable()
			}
			writeJSON(w, 200, map[string]any{"environment_sets": v})
			return nil
		}
		if r.Method == "POST" {
			var body struct {
				Name   string            `json:"name"`
				Values map[string]string `json:"values"`
			}
			if err := decodeBody(r, &body); err != nil {
				return err
			}
			v, err := s.Store.AddEnvironment(r.Context(), body.Name, p.ID, body.Values)
			if err != nil {
				return storageRejected(err)
			}
			writeJSON(w, 201, map[string]any{"environment_set": v})
			return nil
		}
	case "/snapshots":
		if r.Method == "GET" {
			v, err := s.Store.Snapshots(r.Context(), p.ID)
			if err != nil {
				return storageUnavailable()
			}
			writeJSON(w, 200, map[string]any{"snapshots": v})
			return nil
		}
	}
	return &apiError{404, "not_found", "Endpoint not found."}
}
func storageUnavailable() *apiError {
	return &apiError{503, "storage_unavailable", "Storage metadata is unavailable."}
}
func storageRejected(err error) *apiError { return &apiError{409, "storage_rejected", safeError(err)} }
func (s *Server) agentsGuide(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "text/markdown; charset=utf-8")
	_, _ = fmt.Fprintf(w, "Authentication mode: %s. Remote MCP: %s/mcp (Streamable HTTP). The harness itself needs tailnet connectivity.\n\n", s.Config.AuthenticationMode, s.Config.PublicURL)
	_, _ = fmt.Fprintf(w, `# Vibestack Runner agent entrypoint

This is the API-only host broker at %s. It is a private Tailscale origin.
A remote harness must explicitly fetch this document or reference a local copy;
hosting this file does not automatically load it into any agent harness.

1. Fetch [%s/.well-known/vibestack](%s/.well-known/vibestack) and confirm kind=runner.
2. Connect using vibestack connect --url %s --name runner. In trusted-tailnet
   mode no pairing or bearer is needed: everyone reaching the broker shares full
   access to all managed desktops and storage. In paired mode the operator approves
   the displayed code locally with vibestack-runner pairings approve CODE.
   Protect the polling secret and returned bearer credential. Never put them in
   prompts, URLs, logs, or this guide. Use the client's private profile file.
3. GET /api/v1/runner for capabilities and GET /api/v1/runner/host for Docker,
   available resources, approved images, owned desktops, ports and attachments.
4. GET /api/v1/runner/drives and /environment-sets. POST /drives with {"name":"projects"}
   creates a registered managed volume. Dedicated host folders must be registered
   locally by the operator; agents select IDs and never submit host paths.
   Environment sets accept {"name":"tools","values":{...}} in a private request
   body or file; reporting returns keys only. Runner runtime overrides are rejected.
5. POST /api/v1/runner/instances with an Idempotency-Key and a JSON body:
   {"name":"desk","template":"desktop","project_drive":"DRIVE_ID",
    "file_drives":[{"drive_id":"FILES_ID","name":"files","read_only":false}],
    "environment_set":"ENV_ID","state_seed":"SNAPSHOT_ID"}.
   Omit optional selections for empty state and a fresh projects volume.
6. Poll GET /api/v1/runner/operations/OPERATION_ID until succeeded or failed.
   Inspect GET /api/v1/runner/instances/INSTANCE_ID. Infrastructure readiness,
   application restoration, and onboarding_required are distinct. Open the
   instance's urls.password_setup for the user to set a password, choose
   applications and sign into services. Never intercept or invent a user password.
7. Route authenticated automation through
   /api/v1/runner/instances/INSTANCE_ID/workspace/api/v1/automation/commands
   and its published job/file routes. The broker injects private instance credentials.
   Open desktop and terminal directly at the instance origin (/vnc/?view=desktop
   and /vnc/?view=terminal); the broker does not proxy their WebSockets.
8. POST {} to /instances/INSTANCE_ID/stop, poll the operation, then POST
   {"name":"configured"} with an Idempotency-Key to /instances/INSTANCE_ID/snapshot.
   GET /snapshots lists private seeds. Each new desktop gets an independent /data
   copy with its password hash and application caches/keyrings preserved, but fresh
   automation credentials, pairing identity and SSH host keys. Prior jobs, logs and
   runtime locks are excluded. Service policies may still require signing in again.
9. PUT /instances/INSTANCE_ID/attachments with {"project_drive":"ID","file_drives":[]}
   only while stopped. Writable drives have one active desktop. POST {} to /start,
   /restart or /remove and poll operations. Remove retains drives and snapshots;
   destructive purge is a separate local administration command.

Paths abbreviated above are relative to /api/v1/runner. All non-discovery API
requests in paired mode require Authorization: Bearer and retain owner isolation.
Trusted-tailnet requests use one persistent shared principal; device labels and
identity headers do not create private ownership. Tailnet access also grants browser
access; the Linux password is not a web-login gate. Linux username is vibe. SSH
and native VNC ports are host-local, not remote links. Password changes do not
synchronize application logins or keyring encryption.

Use vibestack --profile runner --instance INSTANCE_ID exec -- /usr/bin/pwd
for mediated workspace commands. The human can use instances password ID with
a private terminal prompt or explicit --password-stdin. MCP never accepts passwords.
MCP instance_create returns an operation ID; use operation_get, then instance_inspect.
Use workspace_command, workspace_job, workspace_output or workspace_screenshot with
an explicit instance_id. Do not automatically retry uncertain password changes.

Read [runner operations](%s/RUNNER.md), [client reference](%s/CLI.md),
[workspace automation](%s/AUTOMATION.md), and [runner OpenAPI](%s/api/runner.openapi.json).
The client supports arbitrary published API routes using api --method METHOD
--data-file private.json --idempotency-key KEY /api/v1/runner/....
`, s.Config.PublicURL, s.Config.PublicURL, s.Config.PublicURL, s.Config.PublicURL, s.Config.PublicURL, s.Config.PublicURL, s.Config.PublicURL, s.Config.PublicURL)
}
