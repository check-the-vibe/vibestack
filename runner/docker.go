package runner

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	neturl "net/url"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	dockertypes "github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/api/types/mount"
	"github.com/docker/docker/api/types/strslice"
	"github.com/docker/docker/api/types/volume"
	"github.com/docker/docker/client"
	"github.com/docker/docker/errdefs"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/docker/go-connections/nat"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

const (
	labelManaged  = "dev.vibestack.runner.managed"
	labelInstance = "dev.vibestack.runner.instance"
	labelVersion  = "dev.vibestack.launch-contract"
	labelRole     = "dev.vibestack.runner.role"
	launchVersion = "1"
)

// Manager owns Docker reconciliation and serialized per-instance mutations.
type Manager struct {
	Config Config
	Store  *Store
	Docker *client.Client
	sem    chan struct{}
	locks  sync.Map
	create sync.Mutex
}

type CreateRequest struct {
	StorageSelection
	Name      string          `json:"name"`
	Template  string          `json:"template"`
	Ports     map[string]int  `json:"ports,omitempty"`
	Resources ResourceRequest `json:"resources,omitempty"`
}

type ResourceRequest struct {
	MemoryBytes int64 `json:"memory_bytes,omitempty"`
	NanoCPUs    int64 `json:"nano_cpus,omitempty"`
	PIDs        int64 `json:"pids,omitempty"`
}

type UpdateRequest struct {
	Template  string          `json:"template"`
	Resources ResourceRequest `json:"resources,omitempty"`
}

func NewManager(config Config, store *Store) (*Manager, error) {
	dockerClient, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, err
	}
	manager := &Manager{Config: config, Store: store, Docker: dockerClient, sem: make(chan struct{}, config.ProvisioningConcurrency)}
	return manager, nil
}

func (m *Manager) Close() error { return m.Docker.Close() }

func (m *Manager) Doctor(ctx context.Context) (map[string]any, error) {
	ping, err := m.Docker.Ping(ctx)
	if err != nil {
		return nil, fmt.Errorf("Docker is unavailable: %w", err)
	}
	version, err := m.Docker.ServerVersion(ctx)
	if err != nil {
		return nil, err
	}
	info, err := m.Docker.Info(ctx)
	if err != nil {
		return nil, err
	}
	var fs syscall.Statfs_t
	if err := syscall.Statfs(m.Config.StateDir, &fs); err != nil {
		return nil, err
	}
	free := int64(fs.Bavail) * int64(fs.Bsize)
	listenAvailable := portAvailableAuthority(m.Config.Listen)
	_, tailscaleErr := os.Stat("/usr/bin/tailscale")
	public, _ := neturl.Parse(m.Config.PublicURL)
	return map[string]any{"ok": free >= m.Config.MinFreeBytes && (!m.Config.ManageTailscaleServe || tailscaleErr == nil), "docker_api_version": ping.APIVersion, "docker_version": version.Version, "architecture": version.Arch, "cpus": info.NCPU, "memory_bytes": info.MemTotal, "state_free_bytes": free, "low_disk": free < m.Config.MinFreeBytes, "runner_listen": m.Config.Listen, "listen_available": listenAvailable, "public_url": m.Config.PublicURL, "public_https": public.Scheme == "https", "tailscale_serve_managed": m.Config.ManageTailscaleServe, "tailscale_cli_available": tailscaleErr == nil}, nil
}

func portAvailableAuthority(authority string) bool {
	listener, err := net.Listen("tcp", authority)
	if err != nil {
		return false
	}
	_ = listener.Close()
	return true
}

func (m *Manager) ResolveImage(ctx context.Context, imageName string) (string, error) {
	inspect, _, err := m.Docker.ImageInspectWithRaw(ctx, imageName)
	if err != nil {
		return "", err
	}
	if strings.HasPrefix(inspect.ID, "sha256:") {
		return inspect.ID, nil
	}
	return "", errors.New("Docker returned no immutable image ID")
}

func (m *Manager) Reconcile(ctx context.Context) error {
	instances, err := m.Store.Instances(ctx, false)
	if err != nil {
		return err
	}
	for _, instance := range instances {
		if instance.DesiredState == "running" {
			selection, err := m.Store.Selection(ctx, instance.ID)
			if err == nil {
				err = m.Store.acquireDrives(ctx, instance.ID, selection)
			}
			if err != nil {
				return errors.New("drive lease reconciliation failed")
			}
		}
		matches, listErr := m.Docker.ContainerList(ctx, container.ListOptions{All: true, Filters: filters.NewArgs(filters.Arg("label", labelManaged+"=true"), filters.Arg("label", labelInstance+"="+instance.ID), filters.Arg("label", labelRole+"=workspace"))})
		if listErr != nil {
			return listErr
		}
		if instance.ContainerID == "" {
			if len(matches) == 1 {
				instance.ContainerID = matches[0].ID
			} else if len(matches) > 1 {
				_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, "", instance.DesiredState, "ownership_error", false, "multiple managed containers claim this instance")
				continue
			} else {
				continue
			}
		}
		if len(matches) > 1 {
			foundCurrent := false
			for _, candidate := range matches {
				if candidate.ID == instance.ContainerID {
					foundCurrent = true
					continue
				}
				// A crash during replacement can leave both generations. Durable
				// state names the committed generation, so discard only the other
				// runner-labeled candidate and preserve the committed container.
				_ = m.Docker.ContainerRemove(ctx, candidate.ID, container.RemoveOptions{Force: true})
			}
			if !foundCurrent {
				_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, instance.DesiredState, "ownership_error", false, "multiple managed containers exist but none matches committed state")
				continue
			}
			if instance.DesiredState == "running" {
				_ = m.Docker.ContainerStart(ctx, instance.ContainerID, container.StartOptions{})
			}
		}
		inspect, err := m.Docker.ContainerInspect(ctx, instance.ContainerID)
		if err != nil {
			_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, instance.DesiredState, "missing", false, "managed container is missing")
			continue
		}
		if inspect.Config == nil || inspect.Config.Labels[labelManaged] != "true" || inspect.Config.Labels[labelInstance] != instance.ID || inspect.Config.Labels[labelVersion] != launchVersion || inspect.Config.Labels[labelRole] != "workspace" {
			_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, instance.DesiredState, "ownership_error", false, "container labels do not match runner state")
			continue
		}
		running := inspect.State != nil && inspect.State.Running
		if instance.DesiredState == "running" && !running {
			if err := m.Docker.ContainerStart(ctx, instance.ContainerID, container.StartOptions{}); err != nil && !errdefs.IsNotModified(err) {
				_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "running", "stopped", false, safeError(err))
				continue
			}
			if err := m.finishProvision(ctx, instance); err != nil {
				_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "running", "failed", false, safeError(err))
			}
			continue
		}
		if instance.DesiredState == "stopped" && running {
			if err := m.Docker.ContainerStop(ctx, instance.ContainerID, container.StopOptions{Timeout: intPtr(30)}); err != nil && !errdefs.IsNotModified(err) {
				_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "stopped", "running", false, safeError(err))
				continue
			}
			_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "stopped", "stopped", false, "")
			continue
		}
		observed := "stopped"
		ready := false
		if inspect.State != nil && inspect.State.Running {
			observed = "running"
			ready = inspect.State.Health != nil && inspect.State.Health.Status == "healthy"
		}
		_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, instance.DesiredState, observed, ready, "")
		if ready && m.Config.ManageTailscaleServe {
			if err := m.ensureServe(ctx, instance); err != nil {
				_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, instance.DesiredState, observed, false, safeError(err))
			}
		}
	}
	_, _ = m.Store.db.ExecContext(ctx, `DELETE FROM drive_leases WHERE instance_id IN (SELECT id FROM instances WHERE observed_state='stopped' OR removed_at IS NOT NULL)`)
	_, _ = m.Store.db.ExecContext(ctx, `UPDATE snapshots SET status='failed' WHERE status='copying'`)
	return m.recoverOperations(ctx)
}

func (m *Manager) SubmitCreate(ctx context.Context, request CreateRequest, owner, key, requestID string) (api.Operation, error) {
	if !validInstanceName(request.Name) {
		return api.Operation{}, errors.New("instance name must use 1-48 lowercase letters, digits, or hyphens")
	}
	if !validIdempotencyKey(key) {
		return api.Operation{}, errors.New("a bounded Idempotency-Key is required")
	}
	opID, err := randomID()
	if err != nil {
		return api.Operation{}, err
	}
	instanceID, err := randomID()
	if err != nil {
		return api.Operation{}, err
	}
	now := nowISO()
	op := api.Operation{ID: opID, InstanceID: instanceID, Kind: "create", Status: "queued", IdempotencyKey: key, RequestID: requestID, CreatedAt: now, UpdatedAt: now}
	stored, duplicate, err := m.Store.CreateOperation(ctx, op, owner, request)
	if err != nil {
		return api.Operation{}, err
	}
	if duplicate {
		return stored, nil
	}
	if err := validateRequestedPorts(request.Ports); err != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "invalid_ports", safeError(err), nil)
		return op, err
	}
	if err := m.validateResources(request.Resources); err != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "invalid_resources", safeError(err), nil)
		return op, err
	}
	if err := m.requireDiskSpace(); err != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "low_disk", safeError(err), nil)
		return op, err
	}
	template, err := m.Store.Template(ctx, request.Template)
	if err != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "template_not_approved", "The requested template is not approved.", nil)
		return op, errors.New("template is not approved")
	}
	m.create.Lock()
	defer m.create.Unlock()
	count, err := m.Store.CountInstances(ctx)
	if err != nil {
		return op, err
	}
	if count >= m.Config.MaxInstances {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "instance_limit", "The runner instance limit was reached.", nil)
		return op, errors.New("instance limit reached")
	}
	ports, err := m.allocatePorts(ctx, instanceID, request.Ports)
	if err != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "port_unavailable", safeError(err), nil)
		return op, err
	}
	publicBase := strings.TrimSuffix(m.Config.PublicURL, "/")
	if !m.Config.ManageTailscaleServe {
		publicBase = "http://127.0.0.1"
	}
	urls := map[string]string{"browser": replaceURLPort(publicBase, ports["http"]), "ssh": fmt.Sprintf("ssh://vibe@127.0.0.1:%d", ports["ssh"]), "vnc": fmt.Sprintf("vnc://127.0.0.1:%d", ports["vnc"])}
	resources := map[string]any{"memory_bytes": choose(request.Resources.MemoryBytes, m.Config.DefaultMemoryBytes), "nano_cpus": choose(request.Resources.NanoCPUs, m.Config.DefaultNanoCPUs), "pids": choose(request.Resources.PIDs, m.Config.DefaultPIDs)}
	instance := api.Instance{ID: instanceID, Name: request.Name, Owner: owner, Template: template.Name, ImageDigest: template.Digest, DesiredState: "running", ObservedState: "provisioning", Ports: ports, URLs: urls, Onboarding: true, CreatedAt: now, UpdatedAt: now}
	dataVolume := "vibestack-" + instanceID + "-data"
	projectsVolume := "vibestack-" + instanceID + "-projects"
	if err := m.Store.CreateInstance(ctx, instance, dataVolume, projectsVolume, resources); err != nil {
		m.releasePorts(ctx, instanceID)
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "instance_conflict", "The instance name is already used.", nil)
		return op, err
	}
	if err := m.prepareStorage(ctx, instance, request.StorageSelection, dataVolume, projectsVolume); err != nil {
		_ = m.Store.MarkRemoved(ctx, instance.ID)
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "storage_rejected", safeError(err), nil)
		return op, err
	}
	go m.runProvision(op, instance, template, dataVolume, projectsVolume, resources)
	return op, nil
}

func (m *Manager) validateResources(value ResourceRequest) error {
	if value.MemoryBytes < 0 || value.NanoCPUs < 0 || value.PIDs < 0 {
		return errors.New("resource values cannot be negative")
	}
	if value.MemoryBytes > m.Config.MaxMemoryBytes || value.NanoCPUs > m.Config.MaxNanoCPUs || value.PIDs > m.Config.MaxPIDs {
		return errors.New("requested resources exceed the operator-configured limits")
	}
	if value.MemoryBytes > 0 && value.MemoryBytes < 512<<20 || value.NanoCPUs > 0 && value.NanoCPUs < 100_000_000 || value.PIDs > 0 && value.PIDs < 128 {
		return errors.New("requested resources are below supported minimums")
	}
	return nil
}

func validateRequestedPorts(values map[string]int) error {
	for name, value := range values {
		if name != "http" && name != "ssh" && name != "vnc" {
			return fmt.Errorf("unknown requested port purpose %q", name)
		}
		if value < 0 || value > 65535 {
			return fmt.Errorf("requested %s port is invalid", name)
		}
	}
	return nil
}

func validIdempotencyKey(value string) bool {
	if len(value) < 1 || len(value) > 128 {
		return false
	}
	for _, character := range value {
		if character < 0x20 || character == 0x7f {
			return false
		}
	}
	return true
}

func (m *Manager) requireDiskSpace() error {
	var fs syscall.Statfs_t
	if err := syscall.Statfs(m.Config.StateDir, &fs); err != nil {
		return err
	}
	free := int64(fs.Bavail) * int64(fs.Bsize)
	if free < m.Config.MinFreeBytes {
		return fmt.Errorf("runner state filesystem is below the configured free-space floor (%d bytes available)", free)
	}
	return nil
}

func choose(value, fallback int64) int64 {
	if value > 0 {
		return value
	}
	return fallback
}

func validInstanceName(value string) bool {
	if len(value) < 1 || len(value) > 48 || value[0] == '-' || value[len(value)-1] == '-' {
		return false
	}
	for _, r := range value {
		if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-') {
			return false
		}
	}
	return true
}

func replaceURLPort(raw string, port int) string {
	parts, err := neturl.Parse(raw)
	if err != nil {
		return raw
	}
	parts.Host = net.JoinHostPort(parts.Hostname(), strconv.Itoa(port))
	return parts.String()
}

func (m *Manager) allocatePorts(ctx context.Context, instanceID string, requested map[string]int) (map[string]int, error) {
	servePorts, serveErr := m.tailscaleServePorts(ctx)
	if serveErr != nil && m.Config.ManageTailscaleServe {
		return nil, fmt.Errorf("inspect Tailscale Serve ports: %w", serveErr)
	}
	tx, err := m.Store.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	ports := map[string]int{}
	for _, purpose := range []string{"http", "ssh", "vnc"} {
		wanted := requested[purpose]
		if wanted != 0 {
			if wanted < 1024 || wanted > 65535 {
				return nil, fmt.Errorf("requested %s port is invalid", purpose)
			}
			if !portAvailable(wanted) {
				return nil, fmt.Errorf("requested %s port %d is occupied", purpose, wanted)
			}
			if _, occupied := servePorts[wanted]; occupied {
				return nil, fmt.Errorf("requested %s port %d is used by Tailscale Serve", purpose, wanted)
			}
			if _, err := tx.ExecContext(ctx, `INSERT INTO port_allocations(port,instance_id,purpose) VALUES(?,?,?)`, wanted, instanceID, purpose); err != nil {
				return nil, fmt.Errorf("requested %s port %d is allocated", purpose, wanted)
			}
			ports[purpose] = wanted
			continue
		}
		allocated := 0
		for candidate := m.Config.PortMin; candidate <= m.Config.PortMax; candidate++ {
			if !portAvailable(candidate) {
				continue
			}
			if _, occupied := servePorts[candidate]; occupied {
				continue
			}
			result, insertErr := tx.ExecContext(ctx, `INSERT OR IGNORE INTO port_allocations(port,instance_id,purpose) VALUES(?,?,?)`, candidate, instanceID, purpose)
			if insertErr != nil {
				return nil, insertErr
			}
			changed, _ := result.RowsAffected()
			if changed == 1 {
				allocated = candidate
				break
			}
		}
		if allocated == 0 {
			return nil, errors.New("no host ports are available")
		}
		ports[purpose] = allocated
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return ports, nil
}

func portAvailable(port int) bool {
	listener, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)))
	if err != nil {
		return false
	}
	_ = listener.Close()
	return true
}
func (m *Manager) releasePorts(ctx context.Context, id string) {
	_, _ = m.Store.db.ExecContext(ctx, `DELETE FROM port_allocations WHERE instance_id=?`, id)
}

func (m *Manager) runProvision(op api.Operation, instance api.Instance, template Template, dataVolume, projectsVolume string, resources map[string]any) {
	m.sem <- struct{}{}
	defer func() { <-m.sem }()
	lock := m.instanceLock(instance.ID)
	lock.Lock()
	defer lock.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	_ = m.Store.UpdateOperation(ctx, op.ID, "running", "", "", nil)
	current, currentErr := m.Store.Instance(ctx, instance.ID)
	containerID := ""
	var err error
	if currentErr == nil && current.ContainerID != "" {
		containerID = current.ContainerID
		err = m.finishProvision(ctx, current)
	} else {
		containerID, err = m.provision(ctx, instance, template, dataVolume, projectsVolume, resources)
	}
	if err != nil {
		safe := safeError(err)
		_ = m.Store.UpdateInstanceObserved(context.Background(), instance.ID, containerID, "running", "failed", false, safe)
		_ = m.Store.UpdateOperation(context.Background(), op.ID, "failed", "provisioning_failed", safe, nil)
		return
	}
	updated, err := m.Store.Instance(ctx, instance.ID)
	if err == nil {
		_ = m.Store.UpdateOperation(context.Background(), op.ID, "succeeded", "", "", map[string]any{"instance": updated})
	} else {
		_ = m.Store.UpdateOperation(context.Background(), op.ID, "succeeded", "", "", map[string]string{"instance_id": instance.ID})
	}
}

func (m *Manager) provision(ctx context.Context, instance api.Instance, template Template, dataVolume, projectsVolume string, resources map[string]any) (string, error) {
	labels := map[string]string{labelManaged: "true", labelInstance: instance.ID, labelVersion: launchVersion, labelRole: "workspace"}
	for _, name := range []string{dataVolume, projectsVolume} {
		if _, err := m.Docker.VolumeCreate(ctx, volume.CreateOptions{Name: name, Labels: labels}); err != nil {
			return "", err
		}
	}
	if err := m.prepareDriveVolumes(ctx, instance); err != nil {
		return "", err
	}
	if err := m.seedState(ctx, instance, dataVolume); err != nil {
		return "", err
	}
	if err := m.initializeVolumes(ctx, template.Digest, dataVolume, projectsVolume, labels); err != nil {
		return "", err
	}
	created, err := m.createContainer(ctx, instance, template, dataVolume, projectsVolume, resources, "vibestack-"+instance.Name+"-"+instance.ID[:8])
	if err != nil {
		return "", err
	}
	if err := m.Store.UpdateInstanceObserved(ctx, instance.ID, created.ID, "running", "starting", false, ""); err != nil {
		return created.ID, err
	}
	if err := m.Docker.ContainerStart(ctx, created.ID, container.StartOptions{}); err != nil {
		return created.ID, err
	}
	if err := m.finishProvision(ctx, api.Instance{ID: instance.ID, ContainerID: created.ID, DesiredState: "running", Ports: instance.Ports}); err != nil {
		return created.ID, err
	}
	return created.ID, nil
}

func (m *Manager) createContainer(ctx context.Context, instance api.Instance, template Template, dataVolume, projectsVolume string, resources map[string]any, name string) (container.CreateResponse, error) {
	return m.createContainerSelected(ctx, instance, template, dataVolume, projectsVolume, resources, name, nil)
}
func (m *Manager) createContainerSelected(ctx context.Context, instance api.Instance, template Template, dataVolume, projectsVolume string, resources map[string]any, name string, override *StorageSelection) (container.CreateResponse, error) {
	ports := nat.PortMap{}
	for purpose, containerPort := range map[string]string{"http": "80/tcp", "ssh": "22/tcp", "vnc": "5901/tcp"} {
		binding := nat.PortBinding{HostIP: "127.0.0.1", HostPort: strconv.Itoa(instance.Ports[purpose])}
		ports[nat.Port(containerPort)] = []nat.PortBinding{binding}
	}
	selection, err := m.Store.Selection(ctx, instance.ID)
	if err != nil {
		return container.CreateResponse{}, err
	}
	if override != nil {
		selection = *override
	}
	mounts, err := m.Store.selectedMounts(ctx, instance, dataVolume, projectsVolume, selection)
	if err != nil {
		return container.CreateResponse{}, err
	}
	pids := resources["pids"].(int64)
	host := &container.HostConfig{RestartPolicy: container.RestartPolicy{Name: "unless-stopped"}, ShmSize: 1 << 30, Mounts: mounts, PortBindings: ports, Resources: container.Resources{Memory: resources["memory_bytes"].(int64), NanoCPUs: resources["nano_cpus"].(int64), PidsLimit: &pids}}
	env := []string{
		"VIBESTACK_MANAGED=1",
		"VIBESTACK_INSTANCE_NAME=" + instance.Name,
		"VIBESTACK_PUBLIC_PORT=" + strconv.Itoa(instance.Ports["http"]),
		"VIBESTACK_SSH_PORT=" + strconv.Itoa(instance.Ports["ssh"]),
		"VIBESTACK_NATIVE_VNC_PORT=" + strconv.Itoa(instance.Ports["vnc"]),
		"VIBESTACK_PUBLIC_URL=" + replaceURLPort(m.Config.PublicURL, instance.Ports["http"]),
	}
	if selection.EnvironmentSet != "" {
		values, err := m.Store.environmentValues(ctx, selection.EnvironmentSet, instance.Owner)
		if err != nil {
			return container.CreateResponse{}, errors.New("environment set is unavailable")
		}
		if err := validateEnvironment(values); err != nil {
			return container.CreateResponse{}, err
		}
		for key, value := range values {
			env = append(env, key+"="+value)
		}
	}
	if public, err := neturl.Parse(m.Config.PublicURL); err == nil && public.Hostname() != "" {
		env = append(env, "VIBESTACK_ALLOWED_HOSTS="+public.Hostname())
	}
	if template.Flatpak {
		env = append(env, "VIBESTACK_FLATPAK_ENABLED=1")
		host.SecurityOpt = []string{"seccomp=unconfined", "apparmor=unconfined", "systempaths=unconfined"}
	}
	labels := map[string]string{labelManaged: "true", labelInstance: instance.ID, labelVersion: launchVersion, labelRole: "workspace"}
	return m.Docker.ContainerCreate(ctx, &container.Config{Image: template.Digest, Hostname: "vibestack-" + instance.ID[:8], Env: env, Labels: labels, ExposedPorts: nat.PortSet{"80/tcp": struct{}{}, "22/tcp": struct{}{}, "5901/tcp": struct{}{}}}, host, nil, nil, name)
}

func (m *Manager) finishProvision(ctx context.Context, instance api.Instance) error {
	if err := m.waitHealthy(ctx, instance.ContainerID); err != nil {
		return err
	}
	_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "running", "running", true, "")
	credential, err := m.captureWorkspaceCredential(ctx, instance.ContainerID)
	if err != nil {
		return fmt.Errorf("capture workspace credential: %w", err)
	}
	if err := m.Store.SaveWorkspaceCredential(instance.ID, []byte(credential)); err != nil {
		return fmt.Errorf("store workspace credential: %w", err)
	}
	restored, onboarding, password, err := m.waitWorkspaceReadiness(ctx, instance.Ports["http"])
	if err != nil {
		return err
	}
	if m.Config.ManageTailscaleServe {
		if err := m.ensureServe(ctx, instance); err != nil {
			return err
		}
	}
	if _, err := m.Store.db.ExecContext(ctx, `UPDATE instances SET password_status=? WHERE id=?`, password, instance.ID); err != nil {
		return err
	}
	return m.Store.UpdateInstanceReadiness(ctx, instance.ID, restored, onboarding)
}

func (m *Manager) waitHealthy(ctx context.Context, containerID string) error {
	for {
		inspect, err := m.Docker.ContainerInspect(ctx, containerID)
		if err != nil {
			return err
		}
		ready, err := containerHealthReady(inspect.State)
		if err != nil {
			return err
		}
		if ready {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}

func containerHealthReady(state *dockertypes.ContainerState) (bool, error) {
	if state == nil || !state.Running {
		return false, errors.New("container stopped before becoming ready")
	}
	if state.Restarting {
		return false, errors.New("container restarted before becoming ready")
	}
	if state.Health == nil {
		return false, errors.New("container image does not define the required health check")
	}
	switch state.Health.Status {
	case "healthy":
		return true, nil
	case "starting":
		return false, nil
	case "unhealthy":
		return false, errors.New("container health check reported unhealthy")
	default:
		return false, errors.New("container health check reported an invalid status")
	}
}

func (m *Manager) captureWorkspaceCredential(ctx context.Context, containerID string) (string, error) {
	created, err := m.Docker.ContainerExecCreate(ctx, containerID, container.ExecOptions{User: "vibe", AttachStdout: true, AttachStderr: true, Cmd: []string{"/usr/local/bin/vibestack-api-token", "show"}})
	if err != nil {
		return "", err
	}
	attached, err := m.Docker.ContainerExecAttach(ctx, created.ID, container.ExecAttachOptions{})
	if err != nil {
		return "", err
	}
	defer attached.Close()
	var stdout, stderr bytes.Buffer
	if _, err := stdcopy.StdCopy(&stdout, &stderr, io.LimitReader(attached.Reader, 4096)); err != nil {
		return "", err
	}
	inspect, err := m.Docker.ContainerExecInspect(ctx, created.ID)
	if err != nil {
		return "", err
	}
	if inspect.ExitCode != 0 {
		return "", errors.New("workspace credential helper failed")
	}
	credential := strings.TrimSpace(stdout.String())
	if len(credential) < 32 || len(credential) > 512 || strings.ContainsAny(credential, " \t\r\n") {
		return "", errors.New("workspace credential helper returned invalid data")
	}
	return credential, nil
}

func (m *Manager) waitWorkspaceReadiness(ctx context.Context, port int) (bool, bool, string, error) {
	client := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	endpoint := "http://127.0.0.1:" + strconv.Itoa(port) + "/setup/api/state"
	for {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
		if err != nil {
			return false, true, "unknown", err
		}
		resp, err := client.Do(req)
		if err == nil && resp.StatusCode == http.StatusOK {
			var state struct {
				StateValid bool `json:"state_valid"`
				State      *struct {
					Completed bool `json:"completed"`
				} `json:"state"`
				Job struct {
					Running bool   `json:"running"`
					Phase   string `json:"phase"`
					OK      *bool  `json:"ok"`
				} `json:"job"`
				Missing        []string `json:"missing"`
				Unknown        []string `json:"unknown_selected"`
				Unsupported    []string `json:"unsupported_selected"`
				Authentication struct {
					PasswordConfigured bool `json:"password_configured"`
				} `json:"authentication"`
			}
			decodeErr := json.NewDecoder(io.LimitReader(resp.Body, 2<<20)).Decode(&state)
			resp.Body.Close()
			if decodeErr == nil {
				if state.Job.Running && state.Job.Phase == "restore" {
					// Keep waiting for the setup service's persisted application restore.
				} else {
					restored := state.StateValid && len(state.Missing) == 0 && len(state.Unknown) == 0 && len(state.Unsupported) == 0 && (state.Job.OK == nil || *state.Job.OK)
					onboarding := state.State == nil || !state.State.Completed || !state.Authentication.PasswordConfigured
					password := "required"
					if state.Authentication.PasswordConfigured {
						password = "configured"
					}
					return restored, onboarding, password, nil
				}
			}
		} else if resp != nil {
			resp.Body.Close()
		}
		select {
		case <-ctx.Done():
			return false, true, "unknown", ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}

func (m *Manager) initializeVolumes(ctx context.Context, imageDigest, dataVolume, projectsVolume string, labels map[string]string) error {
	initLabels := make(map[string]string, len(labels))
	for key, value := range labels {
		initLabels[key] = value
	}
	initLabels[labelRole] = "volume-init"
	name := "vibestack-init-" + labels[labelInstance][:8]
	if existing, err := m.Docker.ContainerInspect(ctx, name); err == nil {
		if existing.Config == nil || existing.Config.Labels[labelManaged] != "true" || existing.Config.Labels[labelInstance] != labels[labelInstance] || existing.Config.Labels[labelRole] != "volume-init" {
			return errors.New("volume initializer name is occupied by an unmanaged container")
		}
		if err := m.Docker.ContainerRemove(ctx, existing.ID, container.RemoveOptions{Force: true}); err != nil {
			return err
		}
	}
	instance, err := m.Store.Instance(ctx, labels[labelInstance])
	if err != nil {
		return err
	}
	mounts, err := m.Store.instanceMounts(ctx, instance, dataVolume, projectsVolume)
	if err != nil {
		return err
	}
	extra := []string{}
	initMounts := []mount.Mount{}
	for _, v := range mounts {
		if v.Target == "/data" || v.Target == "/projects" {
			initMounts = append(initMounts, v)
		} else if v.Type == mount.TypeVolume && !v.ReadOnly {
			initMounts = append(initMounts, v)
			extra = append(extra, v.Target)
		}
	}
	args := []string{"/usr/bin/python3", "-I", "-c", "import os,pwd,subprocess,sys; subprocess.run(['/usr/local/bin/vibestack-volume-init'],check=True); u=pwd.getpwnam('vibe'); [(os.chown(p,u.pw_uid,u.pw_gid),os.chmod(p,0o755)) for p in sys.argv[1:]]"}
	args = append(args, extra...)
	created, err := m.Docker.ContainerCreate(
		ctx,
		&container.Config{
			Image:      imageDigest,
			Entrypoint: strslice.StrSlice(args),
			Labels:     initLabels,
		},
		&container.HostConfig{Mounts: initMounts},
		nil,
		nil,
		name,
	)
	if err != nil {
		return err
	}
	defer m.Docker.ContainerRemove(context.Background(), created.ID, container.RemoveOptions{Force: true})
	if err := m.Docker.ContainerStart(ctx, created.ID, container.StartOptions{}); err != nil {
		return err
	}
	status, failures := m.Docker.ContainerWait(ctx, created.ID, container.WaitConditionNotRunning)
	select {
	case err := <-failures:
		return err
	case result := <-status:
		if result.StatusCode != 0 {
			return errors.New("managed volume initialization failed")
		}
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (m *Manager) SubmitAction(ctx context.Context, idOrName, action, owner, requestID string) (api.Operation, error) {
	instance, err := m.Store.Instance(ctx, idOrName)
	if err != nil {
		return api.Operation{}, err
	}
	if instance.Owner != owner {
		return api.Operation{}, sql.ErrNoRows
	}
	opID, err := randomID()
	if err != nil {
		return api.Operation{}, err
	}
	now := nowISO()
	op := api.Operation{ID: opID, InstanceID: instance.ID, Kind: action, Status: "queued", RequestID: requestID, CreatedAt: now, UpdatedAt: now}
	op, _, err = m.Store.CreateOperation(ctx, op, owner, map[string]string{"action": action})
	if err != nil {
		return op, err
	}
	go m.runAction(op, instance)
	return op, nil
}

func (m *Manager) instanceLock(id string) *sync.Mutex {
	value, _ := m.locks.LoadOrStore(id, &sync.Mutex{})
	return value.(*sync.Mutex)
}

func (m *Manager) runAction(op api.Operation, instance api.Instance) {
	lock := m.instanceLock(instance.ID)
	lock.Lock()
	defer lock.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	_ = m.Store.UpdateOperation(ctx, op.ID, "running", "", "", nil)
	current, currentErr := m.Store.Instance(ctx, instance.ID)
	if currentErr != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "instance_unavailable", "The instance is no longer available.", nil)
		return
	}
	instance = current
	if op.Kind == "start" || op.Kind == "restart" {
		selection, err := m.Store.Selection(ctx, instance.ID)
		if err == nil {
			err = m.Store.acquireDrives(ctx, instance.ID, selection)
		}
		if err != nil {
			_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "drive_conflict", safeError(err), nil)
			return
		}
	}
	var err error
	desired := instance.DesiredState
	switch op.Kind {
	case "start":
		if instance.ObservedState == "stopped" {
			data, projects, initErr := m.Store.Volumes(ctx, instance.ID)
			if initErr == nil {
				initErr = m.initializeVolumes(ctx, instance.ImageDigest, data, projects, map[string]string{labelManaged: "true", labelInstance: instance.ID, labelVersion: launchVersion, labelRole: "workspace"})
			}
			if initErr != nil {
				_ = m.Store.releaseDrives(ctx, instance.ID)
				_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "drive_initialization_failed", "Drive initialization failed.", nil)
				return
			}
		}
		desired = "running"
		_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "running", "starting", false, "")
		err = m.Docker.ContainerStart(ctx, instance.ContainerID, container.StartOptions{})
		if errdefs.IsNotModified(err) {
			err = nil
		}
		if err == nil {
			err = m.finishProvision(ctx, instance)
		}
	case "stop":
		desired = "stopped"
		_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "stopped", "stopping", false, "")
		err = m.Docker.ContainerStop(ctx, instance.ContainerID, container.StopOptions{Timeout: intPtr(30)})
		if errdefs.IsNotModified(err) {
			err = nil
		}
		if err == nil {
			err = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "stopped", "stopped", false, "")
			if err == nil {
				err = m.Store.releaseDrives(ctx, instance.ID)
			}
		}
	case "restart":
		desired = "running"
		_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "running", "restarting", false, "")
		err = m.Docker.ContainerRestart(ctx, instance.ContainerID, container.StopOptions{Timeout: intPtr(30)})
		if err == nil {
			err = m.finishProvision(ctx, instance)
		}
	case "remove":
		desired = "removed"
		_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, "removed", "removing", false, "")
		if m.Config.ManageTailscaleServe {
			err = m.removeServe(ctx, instance.ID)
		}
		if err == nil && instance.ContainerID != "" {
			err = m.Docker.ContainerRemove(ctx, instance.ContainerID, container.RemoveOptions{Force: true})
			if client.IsErrNotFound(err) {
				err = nil
			}
		}
		if err == nil {
			err = m.Store.MarkRemoved(ctx, instance.ID)
		}
	default:
		err = errors.New("unsupported operation")
	}
	if err != nil {
		if op.Kind == "remove" && m.Config.ManageTailscaleServe {
			_ = m.ensureServe(context.Background(), instance)
		}
		m.recordActionFailure(ctx, instance, desired, safeError(err))
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "operation_failed", safeError(err), nil)
	} else {
		_ = m.Store.UpdateOperation(ctx, op.ID, "succeeded", "", "", map[string]string{"instance_id": instance.ID})
	}
}

func (m *Manager) recordActionFailure(ctx context.Context, instance api.Instance, desired, message string) {
	inspect, err := m.Docker.ContainerInspect(ctx, instance.ContainerID)
	if err != nil {
		_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, desired, "missing", false, message)
		return
	}
	observed := "stopped"
	ready := false
	if inspect.State != nil && inspect.State.Running {
		observed = "running"
		ready = inspect.State.Health != nil && inspect.State.Health.Status == "healthy"
	}
	_ = m.Store.UpdateInstanceObserved(ctx, instance.ID, instance.ContainerID, desired, observed, ready, message)
}

func (m *Manager) SubmitUpdate(ctx context.Context, idOrName string, request UpdateRequest, owner, key, requestID string) (api.Operation, error) {
	instance, err := m.Store.Instance(ctx, idOrName)
	if err != nil || instance.Owner != owner {
		return api.Operation{}, sql.ErrNoRows
	}
	if instance.ObservedState != "running" || !instance.InfrastructureReady {
		return api.Operation{}, errors.New("instance must be running and infrastructure-ready before update")
	}
	if !validIdempotencyKey(key) {
		return api.Operation{}, errors.New("a bounded Idempotency-Key is required")
	}
	if err := m.validateResources(request.Resources); err != nil {
		return api.Operation{}, err
	}
	if err := m.requireDiskSpace(); err != nil {
		return api.Operation{}, err
	}
	template, err := m.Store.Template(ctx, request.Template)
	if err != nil {
		return api.Operation{}, errors.New("template is not approved")
	}
	opID, err := randomID()
	if err != nil {
		return api.Operation{}, err
	}
	now := nowISO()
	op := api.Operation{ID: opID, InstanceID: instance.ID, Kind: "update", Status: "queued", IdempotencyKey: key, RequestID: requestID, CreatedAt: now, UpdatedAt: now}
	stored, duplicate, err := m.Store.CreateOperation(ctx, op, owner, request)
	if err != nil || duplicate {
		return stored, err
	}
	go m.runUpdate(op, instance, template, request.Resources)
	return op, nil
}

func (m *Manager) runUpdate(op api.Operation, instance api.Instance, template Template, requested ResourceRequest) {
	m.sem <- struct{}{}
	defer func() { <-m.sem }()
	lock := m.instanceLock(instance.ID)
	lock.Lock()
	defer lock.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	_ = m.Store.UpdateOperation(ctx, op.ID, "running", "", "", nil)
	current, err := m.Store.Instance(ctx, instance.ID)
	if err != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "instance_unavailable", "The instance is no longer available.", nil)
		return
	}
	resources, err := m.Store.Resources(ctx, instance.ID)
	if err != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "state_unavailable", safeError(err), nil)
		return
	}
	originalResources := map[string]any{
		"memory_bytes": resources["memory_bytes"],
		"nano_cpus":    resources["nano_cpus"],
		"pids":         resources["pids"],
	}
	if requested.MemoryBytes > 0 {
		resources["memory_bytes"] = requested.MemoryBytes
	}
	if requested.NanoCPUs > 0 {
		resources["nano_cpus"] = requested.NanoCPUs
	}
	if requested.PIDs > 0 {
		resources["pids"] = requested.PIDs
	}
	dataVolume, projectsVolume, err := m.Store.Volumes(ctx, current.ID)
	if err != nil {
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "state_unavailable", safeError(err), nil)
		return
	}
	name := "vibestack-" + current.Name + "-candidate-" + op.ID[:8]
	candidate, err := m.createContainer(ctx, current, template, dataVolume, projectsVolume, resources, name)
	if err == nil {
		err = m.Docker.ContainerStop(ctx, current.ContainerID, container.StopOptions{Timeout: intPtr(30)})
	}
	if err == nil {
		err = m.Docker.ContainerStart(ctx, candidate.ID, container.StartOptions{})
	}
	if err == nil {
		candidateInstance := current
		candidateInstance.ContainerID = candidate.ID
		err = m.finishCandidate(ctx, candidateInstance)
	}
	if err == nil {
		err = m.Store.ReplaceInstanceContainer(ctx, current.ID, template.Name, template.Digest, candidate.ID, resources)
	}
	if err == nil {
		err = m.Docker.ContainerRemove(ctx, current.ContainerID, container.RemoveOptions{Force: true})
	}
	if err != nil {
		if candidate.ID != "" {
			_ = m.Docker.ContainerRemove(context.Background(), candidate.ID, container.RemoveOptions{Force: true})
		}
		_ = m.Docker.ContainerStart(context.Background(), current.ContainerID, container.StartOptions{})
		_ = m.Store.ReplaceInstanceContainer(context.Background(), current.ID, current.Template, current.ImageDigest, current.ContainerID, originalResources)
		rollback, rollbackCancel := context.WithTimeout(context.Background(), 5*time.Minute)
		rollbackErr := m.finishProvision(rollback, current)
		rollbackCancel()
		message := safeError(err)
		if rollbackErr != nil {
			message += "; previous container restoration failed: " + safeError(rollbackErr)
		}
		_ = m.Store.UpdateOperation(context.Background(), op.ID, "failed", "update_failed", message, nil)
		return
	}
	updated, _ := m.Store.Instance(ctx, current.ID)
	_ = m.Store.UpdateOperation(ctx, op.ID, "succeeded", "", "", map[string]any{"instance": updated})
}

func (m *Manager) finishCandidate(ctx context.Context, instance api.Instance) error {
	if err := m.waitHealthy(ctx, instance.ContainerID); err != nil {
		return err
	}
	credential, err := m.captureWorkspaceCredential(ctx, instance.ContainerID)
	if err != nil {
		return err
	}
	if err := m.Store.SaveWorkspaceCredential(instance.ID, []byte(credential)); err != nil {
		return err
	}
	restored, _, _, err := m.waitWorkspaceReadiness(ctx, instance.Ports["http"])
	if err != nil {
		return err
	}
	if !restored {
		return errors.New("saved application restoration did not converge")
	}
	return nil
}

func (m *Manager) recoverOperations(ctx context.Context) error {
	values, err := m.Store.RecoverableOperations(ctx)
	if err != nil {
		return err
	}
	for _, value := range values {
		op := value.Operation
		if op.Kind == "create" {
			instance, instanceErr := m.Store.Instance(ctx, op.InstanceID)
			if instanceErr != nil {
				_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "interrupted", "Create was interrupted before instance state was committed.", nil)
				continue
			}
			if instance.Ready {
				_ = m.Store.UpdateOperation(ctx, op.ID, "succeeded", "", "", map[string]any{"instance": instance})
				continue
			}
			template, templateErr := m.Store.Template(ctx, instance.Template)
			dataVolume, projectsVolume, volumeErr := m.Store.Volumes(ctx, instance.ID)
			resources, resourceErr := m.Store.Resources(ctx, instance.ID)
			if templateErr != nil || volumeErr != nil || resourceErr != nil {
				_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "interrupted", "Create could not be resumed from durable state.", nil)
				continue
			}
			go m.runProvision(op, instance, template, dataVolume, projectsVolume, resources)
			continue
		}
		// Non-create operations are not blindly replayed: a restart or update may
		// already have crossed an externally visible boundary before the crash.
		_ = m.Store.UpdateOperation(ctx, op.ID, "failed", "interrupted", "The runner restarted while this operation was in progress; inspect the reconciled instance before retrying with a new key.", nil)
	}
	return nil
}

func (m *Manager) PurgeRemoved(ctx context.Context, idOrName string) error {
	instance, err := m.Store.InstanceAny(ctx, idOrName)
	if err != nil {
		return err
	}
	if instance.ObservedState != "removed" {
		return errors.New("instance must be removed before its data can be purged")
	}
	dataVolume, projectsVolume, err := m.Store.Volumes(ctx, instance.ID)
	if err != nil {
		return err
	}
	_ = projectsVolume
	if err := m.Docker.VolumeRemove(ctx, dataVolume, false); err != nil && !client.IsErrNotFound(err) {
		return err
	}
	if _, err := m.Store.db.ExecContext(ctx, `DELETE FROM drives WHERE id=? AND role='state'`, instance.ID+"-data"); err != nil {
		return err
	}
	if _, err := m.Store.db.ExecContext(ctx, `DELETE FROM instance_storage WHERE instance_id=?`, instance.ID); err != nil {
		return err
	}

	return m.Store.PurgeInstance(ctx, instance.ID)
}

func intPtr(value int) *int { return &value }

type cappedBuffer struct {
	bytes.Buffer
	maximum int
}

func (b *cappedBuffer) Write(value []byte) (int, error) {
	original := len(value)
	remaining := b.maximum - b.Len()
	if remaining > 0 {
		if len(value) > remaining {
			value = value[:remaining]
		}
		_, _ = b.Buffer.Write(value)
	}
	return original, nil
}

func (m *Manager) tailscaleServePorts(ctx context.Context) (map[int]string, error) {
	result := map[int]string{}
	if _, err := os.Stat("/usr/bin/tailscale"); errors.Is(err, os.ErrNotExist) {
		return result, nil
	} else if err != nil {
		return nil, err
	}
	commandCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	output := &cappedBuffer{maximum: 1 << 20}
	command := exec.CommandContext(commandCtx, "/usr/bin/tailscale", "serve", "status", "--json")
	command.Stdout = output
	command.Stderr = io.Discard
	if err := command.Run(); err != nil {
		return nil, err
	}
	var status struct {
		Web map[string]struct {
			Handlers map[string]struct {
				Proxy string `json:"Proxy"`
			} `json:"Handlers"`
		} `json:"Web"`
	}
	if err := json.Unmarshal(output.Bytes(), &status); err != nil {
		return nil, err
	}
	for authority, site := range status.Web {
		_, rawPort, err := net.SplitHostPort(authority)
		if err != nil {
			continue
		}
		port, err := strconv.Atoi(rawPort)
		if err != nil {
			continue
		}
		if handler, ok := site.Handlers["/"]; ok {
			result[port] = handler.Proxy
		}
	}
	return result, nil
}

func (m *Manager) ensureServe(ctx context.Context, instance api.Instance) error {
	port := instance.Ports["http"]
	proxy := fmt.Sprintf("http://127.0.0.1:%d", port)
	ports, err := m.tailscaleServePorts(ctx)
	if err != nil {
		return fmt.Errorf("read Tailscale Serve status: %w", err)
	}
	recordedPort, recordedProxy, recordErr := m.Store.ServeMapping(ctx, instance.ID)
	recorded := recordErr == nil
	if recordErr != nil && !errors.Is(recordErr, sql.ErrNoRows) {
		return recordErr
	}
	if existing, occupied := ports[port]; occupied {
		if !recorded || recordedPort != port || recordedProxy != proxy || existing != proxy {
			return fmt.Errorf("Tailscale Serve HTTPS port %d belongs to another mapping", port)
		}
	}
	if ports[port] != proxy {
		commandCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
		defer cancel()
		command := exec.CommandContext(commandCtx, "/usr/bin/tailscale", "serve", "--bg", "--yes", "--https="+strconv.Itoa(port), proxy)
		command.Stdout = io.Discard
		command.Stderr = io.Discard
		if err := command.Run(); err != nil {
			return fmt.Errorf("configure Tailscale Serve HTTPS port %d: %w", port, err)
		}
	}
	return m.Store.SaveServeMapping(ctx, instance.ID, port, proxy)
}

func (m *Manager) removeServe(ctx context.Context, instanceID string) error {
	port, expected, err := m.Store.ServeMapping(ctx, instanceID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	ports, err := m.tailscaleServePorts(ctx)
	if err != nil {
		return err
	}
	if current, ok := ports[port]; ok {
		if current != expected {
			return errors.New("recorded Tailscale Serve mapping was changed externally and was preserved")
		}
		commandCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
		defer cancel()
		command := exec.CommandContext(commandCtx, "/usr/bin/tailscale", "serve", "--yes", "--https="+strconv.Itoa(port), "off")
		command.Stdout = io.Discard
		command.Stderr = io.Discard
		if err := command.Run(); err != nil {
			return err
		}
	}
	return m.Store.DeleteServeMapping(ctx, instanceID)
}

func (m *Manager) ManagedContainers(ctx context.Context) (int, error) {
	values, err := m.Docker.ContainerList(ctx, container.ListOptions{All: true, Filters: filters.NewArgs(filters.Arg("label", labelManaged+"=true"))})
	return len(values), err
}
