package runner

import (
	"context"
	_ "embed"
	"errors"
	"time"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/mount"
	"github.com/docker/docker/api/types/volume"
	"github.com/docker/docker/client"
)

//go:embed state_copy.py
var stateCopyScript string

func (m *Manager) prepareStorage(ctx context.Context, instance api.Instance, selection StorageSelection, data, projects string) error {
	// Legacy volumes are registered in-place. Contents are never moved.
	for _, d := range []Drive{{ID: instance.ID + "-data", Name: instance.Name + "-state", Owner: instance.Owner, Kind: "volume", Role: "state", Source: data, CreatedAt: instance.CreatedAt}, {ID: instance.ID + "-projects", Name: instance.Name + "-projects", Owner: instance.Owner, Kind: "volume", Role: "files", Source: projects, CreatedAt: instance.CreatedAt}} {
		if _, err := m.Store.db.ExecContext(ctx, `INSERT INTO drives VALUES(?,?,?,?,?,?,?)`, d.ID, d.Name, d.Owner, d.Kind, d.Role, d.Source, d.CreatedAt); err != nil {
			return errors.New("default drive registration failed")
		}
	}
	if selection.ProjectDrive == "" {
		selection.ProjectDrive = instance.ID + "-projects"
	}
	if err := m.Store.validateSelection(ctx, selection, instance.Owner); err != nil {
		return err
	}
	if selection.StateSeed != "" {
		snap, err := m.Store.snapshot(ctx, selection.StateSeed, instance.Owner)
		if err != nil {
			return err
		}
		t, err := m.Store.Template(ctx, instance.Template)
		if err != nil {
			return err
		}
		if snap.Flatpak && !t.Flatpak {
			return errors.New("state seed requires a Flatpak-enabled template")
		}
	}
	if err := m.Store.saveSelection(ctx, instance.ID, selection); err != nil {
		return err
	}
	return m.Store.acquireDrives(ctx, instance.ID, selection)
}
func (m *Manager) prepareDriveVolumes(ctx context.Context, instance api.Instance) error {
	selection, err := m.Store.Selection(ctx, instance.ID)
	if err != nil {
		return err
	}
	all := append([]Attachment{{DriveID: selection.ProjectDrive}}, selection.FileDrives...)
	for _, a := range all {
		if a.DriveID == "" {
			continue
		}
		d, err := m.Store.drive(ctx, a.DriveID, instance.Owner)
		if err != nil {
			return err
		}
		if d.Kind == "volume" {
			if _, err := m.Docker.VolumeCreate(ctx, volume.CreateOptions{Name: d.Source, Labels: map[string]string{labelManaged: "true", "dev.vibestack.runner.drive": d.ID}}); err != nil {
				return errors.New("drive volume creation failed")
			}
		}
	}
	return nil
}
func (m *Manager) copyState(ctx context.Context, image, source, target, id string) error {
	if _, err := m.Docker.VolumeCreate(ctx, volume.CreateOptions{Name: target, Labels: map[string]string{labelManaged: "true", "dev.vibestack.runner.snapshot": id}}); err != nil {
		return errors.New("state target creation failed")
	}
	pids := int64(64)
	created, err := m.Docker.ContainerCreate(ctx, &container.Config{Image: image, Entrypoint: []string{"/usr/bin/python3", "-I", "-c", stateCopyScript}, NetworkDisabled: true, Labels: map[string]string{labelManaged: "true", labelRole: "state-copy", "dev.vibestack.runner.snapshot": id}}, &container.HostConfig{ReadonlyRootfs: true, NetworkMode: "none", Resources: container.Resources{Memory: 256 << 20, PidsLimit: &pids}, Mounts: []mount.Mount{{Type: mount.TypeVolume, Source: source, Target: "/source", ReadOnly: true}, {Type: mount.TypeVolume, Source: target, Target: "/target"}}}, nil, nil, "")
	if err != nil {
		return errors.New("state copy container creation failed")
	}
	defer m.Docker.ContainerRemove(context.Background(), created.ID, container.RemoveOptions{Force: true})
	if err := m.Docker.ContainerStart(ctx, created.ID, container.StartOptions{}); err != nil {
		return errors.New("state copy could not start")
	}
	status, failures := m.Docker.ContainerWait(ctx, created.ID, container.WaitConditionNotRunning)
	select {
	case result := <-status:
		if result.StatusCode != 0 {
			return errors.New("state copy failed; partial target retained for local cleanup")
		}
		return nil
	case <-failures:
		return errors.New("state copy wait failed")
	case <-ctx.Done():
		return ctx.Err()
	}
}
func (m *Manager) seedState(ctx context.Context, instance api.Instance, data string) error {
	v, err := m.Store.Selection(ctx, instance.ID)
	if err != nil || v.StateSeed == "" {
		return err
	}
	// Only copy before first creation. Nonempty partial copies fail closed on recovery.
	snap, err := m.Store.snapshot(ctx, v.StateSeed, instance.Owner)
	if err != nil || snap.Status != "ready" {
		return errors.New("state seed is unavailable")
	}
	return m.copyState(ctx, instance.ImageDigest, snap.Volume, data, instance.ID)
}
func (m *Manager) requireStopped(ctx context.Context, instance api.Instance) error {
	if instance.DesiredState != "stopped" || instance.ObservedState != "stopped" {
		return errors.New("desktop must be stopped")
	}
	inspect, err := m.Docker.ContainerInspect(ctx, instance.ContainerID)
	if err != nil || inspect.State == nil || inspect.State.Running {
		return errors.New("Docker must confirm the desktop is stopped")
	}
	return nil
}
func (m *Manager) SubmitSnapshot(ctx context.Context, instance api.Instance, name, key, requestID string) (api.Operation, error) {
	if !validInstanceName(name) || !validIdempotencyKey(key) {
		return api.Operation{}, errors.New("snapshot name and Idempotency-Key are required")
	}
	id, err := randomID()
	if err != nil {
		return api.Operation{}, err
	}
	now := nowISO()
	op := api.Operation{ID: id, InstanceID: instance.ID, Kind: "snapshot", Status: "queued", IdempotencyKey: key, RequestID: requestID, CreatedAt: now, UpdatedAt: now}
	op, duplicate, err := m.Store.CreateOperation(ctx, op, instance.Owner, map[string]string{"instance_id": instance.ID, "name": name})
	if err != nil || duplicate {
		return op, err
	}
	go func() {
		m.sem <- struct{}{}
		defer func() { <-m.sem }()
		lock := m.instanceLock(instance.ID)
		lock.Lock()
		defer lock.Unlock()
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
		defer cancel()
		_ = m.Store.UpdateOperation(ctx, op.ID, "running", "", "", nil)
		snapshot, err := m.snapshotStopped(ctx, instance.ID, name, op.ID)
		if err != nil {
			_ = m.Store.UpdateOperation(context.Background(), op.ID, "failed", "snapshot_failed", safeError(err), nil)
			return
		}
		_ = m.Store.UpdateOperation(ctx, op.ID, "succeeded", "", "", map[string]any{"snapshot": snapshot})
	}()
	return op, nil
}
func (m *Manager) snapshotStopped(ctx context.Context, id, name, snapshotID string) (Snapshot, error) {
	instance, err := m.Store.Instance(ctx, id)
	if err != nil {
		return Snapshot{}, errors.New("instance is unavailable")
	}
	if err := m.requireStopped(ctx, instance); err != nil {
		return Snapshot{}, err
	}
	if err := m.requireDiskSpace(); err != nil {
		return Snapshot{}, err
	}
	data, _, err := m.Store.Volumes(ctx, id)
	if err != nil {
		return Snapshot{}, err
	}
	t, err := m.Store.Template(ctx, instance.Template)
	if err != nil {
		return Snapshot{}, err
	}
	v := Snapshot{ID: snapshotID, Name: name, Owner: instance.Owner, InstanceID: id, Volume: "vibestack-snapshot-" + snapshotID, ImageDigest: instance.ImageDigest, Flatpak: t.Flatpak, Status: "copying", CreatedAt: nowISO()}
	if _, err := m.Store.db.ExecContext(ctx, `INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)`, v.ID, v.Name, v.Owner, v.InstanceID, v.Volume, v.ImageDigest, v.Flatpak, v.Status, v.CreatedAt); err != nil {
		return Snapshot{}, errors.New("snapshot name is already used")
	}
	err = m.copyState(ctx, instance.ImageDigest, data, v.Volume, v.ID)
	if err != nil {
		_, _ = m.Store.db.ExecContext(context.Background(), `UPDATE snapshots SET status='failed' WHERE id=?`, v.ID)
		return Snapshot{}, err
	}
	v.Status = "ready"
	_, err = m.Store.db.ExecContext(ctx, `UPDATE snapshots SET status='ready' WHERE id=?`, v.ID)
	return v, err
}
func (m *Manager) ChangeAttachments(ctx context.Context, instance api.Instance, project string, files []Attachment) error {
	lock := m.instanceLock(instance.ID)
	lock.Lock()
	defer lock.Unlock()
	current, err := m.Store.Instance(ctx, instance.ID)
	if err != nil {
		return err
	}
	if err := m.requireStopped(ctx, current); err != nil {
		return err
	}
	old, err := m.Store.Selection(ctx, instance.ID)
	if err != nil {
		return err
	}
	v := old
	v.ProjectDrive = project
	v.FileDrives = files
	if err := m.Store.validateSelection(ctx, v, current.Owner); err != nil {
		return err
	}
	data, projects, err := m.Store.Volumes(ctx, current.ID)
	if err != nil {
		return err
	}
	resources, err := m.Store.Resources(ctx, current.ID)
	if err != nil {
		return err
	}
	t, err := m.Store.Template(ctx, current.Template)
	if err != nil {
		return err
	}
	t.Digest = current.ImageDigest
	// Materialize new managed volumes without modifying the selected generation.
	for _, a := range append([]Attachment{{DriveID: v.ProjectDrive}}, v.FileDrives...) {
		d, err := m.Store.drive(ctx, a.DriveID, current.Owner)
		if err != nil {
			return err
		}
		if d.Kind == "volume" {
			if _, err := m.Docker.VolumeCreate(ctx, volume.CreateOptions{Name: d.Source, Labels: map[string]string{labelManaged: "true"}}); err != nil {
				return errors.New("drive creation failed")
			}
		}
	}
	candidate, err := m.createContainerSelected(ctx, current, t, data, projects, resources, "", &v)
	if err != nil {
		return errors.New("attachment replacement failed")
	}
	tx, err := m.Store.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	committed := false
	defer func() {
		if !committed {
			_ = m.Docker.ContainerRemove(context.Background(), candidate.ID, container.RemoveOptions{})
		}
	}()
	if _, err := tx.ExecContext(ctx, `UPDATE instance_storage SET selection_json=? WHERE instance_id=?`, encode(v), current.ID); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx, `UPDATE instances SET container_id=?,updated_at=? WHERE id=?`, candidate.ID, nowISO(), current.ID); err != nil {
		return err
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	committed = true
	if err := m.Docker.ContainerRemove(ctx, current.ContainerID, container.RemoveOptions{}); err != nil {
		return errors.New("attachments saved; previous stopped container cleanup required")
	}
	return m.Store.releaseDrives(ctx, current.ID)
}
func (m *Manager) PurgeDrive(ctx context.Context, id string) error {
	var kind, source, role string
	if err := m.Store.db.QueryRowContext(ctx, `SELECT kind,source,role FROM drives WHERE id=?`, id).Scan(&kind, &source, &role); err != nil {
		return err
	}
	if role == "state" {
		return errors.New("private state is purged through instances purge")
	}
	var count int
	if err := m.Store.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM instance_storage s JOIN instances i ON i.id=s.instance_id WHERE i.removed_at IS NULL AND (json_extract(s.selection_json,'$.project_drive')=? OR EXISTS(SELECT 1 FROM json_each(s.selection_json,'$.file_drives') WHERE json_extract(value,'$.drive_id')=?))`, id, id).Scan(&count); err != nil {
		return err
	}
	if count > 0 {
		return errors.New("drive is still attached")
	}
	if kind == "volume" {
		if err := m.Docker.VolumeRemove(ctx, source, false); err != nil && !client.IsErrNotFound(err) {
			return errors.New("drive volume could not be removed")
		}
	}
	_, err := m.Store.db.ExecContext(ctx, `DELETE FROM drives WHERE id=?`, id)
	return err
}
func (m *Manager) PurgeSnapshot(ctx context.Context, id string) error {
	var source string
	if err := m.Store.db.QueryRowContext(ctx, `SELECT volume FROM snapshots WHERE id=?`, id).Scan(&source); err != nil {
		return err
	}
	var count int
	if err := m.Store.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM operations o JOIN instance_storage s ON o.instance_id=s.instance_id WHERE o.kind='create' AND o.status IN ('queued','running') AND json_extract(s.selection_json,'$.state_seed')=?`, id).Scan(&count); err != nil {
		return err
	}
	if count > 0 {
		return errors.New("snapshot is being copied")
	}
	if err := m.Docker.VolumeRemove(ctx, source, false); err != nil && !client.IsErrNotFound(err) {
		return errors.New("snapshot volume could not be removed")
	}
	_, err := m.Store.db.ExecContext(ctx, `DELETE FROM snapshots WHERE id=?`, id)
	return err
}

// RefreshInstance observes only the recorded container and never competes with
// a lifecycle operation. This lets completed onboarding become visible without
// restarting the desktop or trusting stale readiness in the registry.
func (m *Manager) RefreshInstance(ctx context.Context, instance api.Instance) api.Instance {
	lock := m.instanceLock(instance.ID)
	if !lock.TryLock() {
		return instance
	}
	defer lock.Unlock()
	current, err := m.Store.Instance(ctx, instance.ID)
	if err != nil {
		return instance
	}
	instance = current
	if instance.ContainerID == "" {
		return instance
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	observed := instance.ObservedState
	ready := false
	inspect, err := m.Docker.ContainerInspect(ctx, instance.ContainerID)
	if err != nil {
		return instance
	}
	if inspect.Config == nil || inspect.Config.Labels[labelManaged] != "true" || inspect.Config.Labels[labelInstance] != instance.ID {
		return instance
	}
	observed = "stopped"
	if inspect.State != nil && inspect.State.Running {
		observed = "running"
		ready = inspect.State.Health != nil && inspect.State.Health.Status == "healthy"
	}
	_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, instance.DesiredState, observed, ready, instance.LastError)
	if ready {
		restored, onboarding, err := m.waitWorkspaceReadiness(ctx, instance.Ports["http"])
		if err == nil {
			_ = m.Store.UpdateInstanceReadiness(ctx, instance.ID, restored, onboarding)
		}
	}
	if value, err := m.Store.Instance(ctx, instance.ID); err == nil {
		return value
	}
	return instance
}
