package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/pkg/stdcopy"
)

func validPassword(password string) bool {
	if !utf8.ValidString(password) || len(password) < 12 || len(password) > 256 || strings.TrimSpace(password) == "" {
		return false
	}
	for _, r := range password {
		if r < 32 || r == 127 {
			return false
		}
	}
	return true
}

func (s *Server) setInstancePassword(w http.ResponseWriter, r *http.Request, instance api.Instance) *apiError {
	if r.ContentLength > 2048 {
		return &apiError{413, "body_too_large", "Password request exceeds 2048 bytes."}
	}
	var body struct {
		Password string `json:"password"`
	}
	if err := decodeBody(r, &body); err != nil {
		return err
	}
	if !validPassword(body.Password) {
		return &apiError{400, "password_policy", "Use 12–256 UTF-8 bytes, without control characters or only whitespace."}
	}
	if s.Manager == nil {
		return &apiError{503, "manager_unavailable", "The desktop manager is unavailable."}
	}
	if err := s.Manager.SetPassword(r.Context(), instance, body.Password); err != nil {
		return err
	}
	instance = s.Manager.RefreshInstance(r.Context(), instance)
	writeJSON(w, 200, map[string]any{"instance": instance, "password_status": "configured"})
	return nil
}

// SetPassword never creates a durable operation. Once exec starts, finish under
// a bounded independent context so disconnects cannot release the lifecycle lock
// while a credential update is still running. The caller never retries it.
func (m *Manager) SetPassword(requestCtx context.Context, instance api.Instance, password string) *apiError {
	lock := m.instanceLock(instance.ID)
	if !lock.TryLock() {
		return &apiError{409, "instance_busy", "A desktop operation is running; wait for it to finish."}
	}
	defer lock.Unlock()
	current, err := m.Store.Instance(requestCtx, instance.ID)
	if err != nil || current.Owner != instance.Owner {
		return &apiError{404, "instance_not_found", "The instance does not exist."}
	}
	var pending int
	if err = m.Store.db.QueryRowContext(requestCtx, `SELECT count(*) FROM operations WHERE instance_id=? AND status IN ('queued','running')`, instance.ID).Scan(&pending); err != nil {
		return storageUnavailable()
	}
	if pending > 0 {
		return &apiError{409, "instance_busy", "A desktop operation is pending; poll it before changing credentials."}
	}
	inspect, err := m.Docker.ContainerInspect(requestCtx, current.ContainerID)
	if err != nil || inspect.Config == nil || inspect.Config.Labels[labelManaged] != "true" || inspect.Config.Labels[labelInstance] != instance.ID || inspect.State == nil || !inspect.State.Running || inspect.State.Health == nil || inspect.State.Health.Status != "healthy" {
		return &apiError{409, "desktop_not_ready", "Start the desktop and wait for healthy infrastructure before setting its password."}
	}
	if requestCtx.Err() != nil {
		return &apiError{408, "request_interrupted", "Password request was interrupted before execution."}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 55*time.Second)
	defer cancel()
	created, err := m.Docker.ContainerExecCreate(ctx, current.ContainerID, container.ExecOptions{User: "root", AttachStdin: true, AttachStdout: true, AttachStderr: true, Cmd: []string{"/usr/bin/timeout", "--kill-after=2s", "45s", "/usr/local/bin/vibestack-password", "set"}})
	if err != nil {
		return &apiError{502, "password_helper_failed", "The password helper could not be prepared."}
	}
	uncertain := &apiError{502, "password_completion_uncertain", "Password completion is uncertain. Check the desktop before explicitly trying again; this request was not retried."}
	// Even an attach/write/read failure can occur after Docker starts the helper.
	// Keep the lifecycle lock until exec is observed complete or its fixed timeout
	// has elapsed. Never surface Docker response bodies to credential callers.
	execDeadline := time.Now().Add(48 * time.Second)
	defer func() {
		for time.Now().Before(execDeadline) {
			probe, stop := context.WithTimeout(context.Background(), time.Second)
			state, err := m.Docker.ContainerExecInspect(probe, created.ID)
			stop()
			if err == nil && !state.Running {
				return
			}
			time.Sleep(100 * time.Millisecond)
		}
	}()
	attached, err := m.Docker.ContainerExecAttach(ctx, created.ID, container.ExecAttachOptions{})
	if err != nil {
		return uncertain
	}
	defer attached.Close()
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			attached.Close()
		case <-done:
		}
	}()
	// Disable HTML escaping to stay inside the helper's 1024-byte UTF-8 bound.
	var input bytes.Buffer
	enc := json.NewEncoder(&input)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(map[string]string{"password": password})
	raw := input.Bytes()
	defer clear(raw)
	if _, err = attached.Conn.Write(raw); err != nil {
		return uncertain
	}
	if err = attached.CloseWrite(); err != nil {
		return uncertain
	}
	if _, err = stdcopy.StdCopy(io.Discard, io.Discard, io.LimitReader(attached.Reader, 4096)); err != nil {
		return uncertain
	}
	for {
		result, err := m.Docker.ContainerExecInspect(ctx, created.ID)
		if err != nil {
			return uncertain
		}
		if !result.Running {
			if requestCtx.Err() != nil {
				return uncertain
			}
			if result.ExitCode != 0 {
				return &apiError{502, "password_helper_failed", "The password helper failed. Verify password status before explicitly trying again."}
			}
			_, err = m.Store.db.ExecContext(ctx, `UPDATE instances SET password_status='configured' WHERE id=?`, instance.ID)
			if err != nil {
				return uncertain
			}
			return nil
		}
		select {
		case <-ctx.Done():
			return uncertain
		case <-time.After(50 * time.Millisecond):
		}
	}
}
