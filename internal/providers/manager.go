package providers

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"
)

type Definition struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Component string `json:"component"`
	Version   string `json:"version"`
	Transport string `json:"transport"`
	binary    string
}

var catalog = []Definition{
	{ID: "codex", Name: "Codex", Component: "codex-cli", Version: "0.153.4", Transport: "stdio", binary: "/usr/local/bin/codex"},
	{ID: "opencode", Name: "OpenCode", Component: "opencode", Version: "1.18.29", Transport: "private-http", binary: "/usr/local/bin/opencode"},
}

type State struct {
	Definition
	Installed      *bool   `json:"installed"`
	Process        string  `json:"process"`
	Authentication string  `json:"authentication"`
	Readiness      string  `json:"readiness"`
	Operation      string  `json:"operation_id"`
	Phase          string  `json:"phase"`
	Failure        string  `json:"failure"`
	NextAction     string  `json:"next_action"`
	Models         []Model `json:"models"`
}

// Load/Save must provide protected, atomic storage. Installation uses the existing
// durable catalog, not a URL or shell command supplied by an API caller.
type Config struct {
	ProjectsRoot string
	Load         func() ([]byte, error)
	Save         func([]byte) error
	Install      func(context.Context, string) error
	probe        func(context.Context, Definition) (bool, error)
	launch       func(context.Context, Definition, string) (agentRuntime, error)
}

type managedProvider struct {
	state    State
	runtime  agentRuntime
	cancel   context.CancelFunc
	done     chan struct{}
	opening  bool
	stopping bool
}

type durableState struct {
	Version       int                            `json:"version"`
	Selected      []string                       `json:"selected"`
	Conversations map[string]*conversationRecord `json:"conversations"`
}

type Manager struct {
	mu        sync.Mutex
	cfg       Config
	providers map[string]*managedProvider
	state     durableState
	buffers   map[string]*eventBuffer
	approvals map[string]*pendingApproval
	broken    bool
	closed    bool
	ctx       context.Context
	cancel    context.CancelFunc
	wg        sync.WaitGroup
}

func NewManager(cfg Config) (*Manager, error) {
	if !filepath.IsAbs(cfg.ProjectsRoot) || cfg.Load == nil || cfg.Save == nil || cfg.Install == nil {
		return nil, ErrInvalid
	}
	if cfg.probe == nil {
		cfg.probe = probeInstalled
	}
	if cfg.launch == nil {
		cfg.launch = func(ctx context.Context, d Definition, dir string) (agentRuntime, error) {
			if d.ID == "codex" {
				return startCodex(ctx, d.binary, dir)
			}
			return startOpenCode(ctx, d.binary, dir)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	m := &Manager{cfg: cfg, providers: map[string]*managedProvider{}, state: durableState{Version: 1, Conversations: map[string]*conversationRecord{}}, buffers: map[string]*eventBuffer{}, approvals: map[string]*pendingApproval{}, ctx: ctx, cancel: cancel}
	for _, definition := range catalog {
		m.providers[definition.ID] = &managedProvider{state: State{Definition: definition, Process: "stopped", Authentication: "unknown", Readiness: "unverified", Phase: "idle", NextAction: "activate", Models: []Model{}}}
	}
	data, err := cfg.Load()
	if err != nil {
		cancel()
		return nil, ErrUnavailable
	}
	if len(data) > 1<<20 {
		cancel()
		return nil, ErrProtocol
	}
	if len(data) > 0 {
		decoder := json.NewDecoder(strings.NewReader(string(data)))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&m.state) != nil || decoder.Decode(new(any)) != io.EOF || m.state.Version != 1 || len(m.state.Selected) > len(catalog) || m.state.Conversations == nil || len(m.state.Conversations) > 32 {
			cancel()
			return nil, ErrProtocol
		}
		for _, id := range m.state.Selected {
			if m.providers[id] == nil {
				cancel()
				return nil, ErrProtocol
			}
		}
		for id, c := range m.state.Conversations {
			if c == nil || !validID(id) || c.ID != id || m.providers[c.Provider] == nil || !validProject(c.Project) || !nativeID(c.Model) || c.Operations == nil || len(c.Operations) > 32 || !slices.Contains([]string{"idle", "creating", "unknown"}, c.Status) {
				cancel()
				return nil, ErrProtocol
			}
			if c.Native != "" && !nativeID(c.Native) {
				cancel()
				return nil, ErrProtocol
			}
			for key, op := range c.Operations {
				if op == nil || !validID(key) || op.ID != key || len(op.Digest) != 64 || (op.Native != "" && !nativeID(op.Native)) || !slices.Contains([]string{"submitting", "running", "stopping", "completed", "interrupted", "failed", "unknown"}, op.Status) {
					cancel()
					return nil, ErrProtocol
				}
				if _, err := hex.DecodeString(op.Digest); err != nil {
					cancel()
					return nil, ErrProtocol
				}
				if op.Status == "running" || op.Status == "submitting" || op.Status == "stopping" {
					op.Status = "unknown"
				}
			}
			if c.Active != "" && c.Operations[c.Active] == nil {
				cancel()
				return nil, ErrProtocol
			}
			if c.Status == "creating" {
				c.Status = "unknown"
			}
			m.buffers[id] = newEventBuffer()
			m.buffers[id].recovered = true
		}
	}
	return m, nil
}

func validID(id string) bool {
	if len(id) != 32 {
		return false
	}
	_, err := hex.DecodeString(id)
	return err == nil && id == strings.ToLower(id)
}
func makeID() (string, error) {
	value := make([]byte, 16)
	_, err := rand.Read(value)
	return hex.EncodeToString(value), err
}
func validProject(project string) bool {
	return project != "" && project != "." && project != ".." && len(project) <= 255 && !strings.ContainsAny(project, "/\\\x00\r\n")
}
func (m *Manager) projectPath(project string) (string, error) {
	if !validProject(project) {
		return "", ErrInvalid
	}
	root, err := os.OpenRoot(m.cfg.ProjectsRoot)
	if err != nil {
		return "", ErrUnavailable
	}
	defer root.Close()
	info, err := root.Lstat(project)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", ErrInvalid
	}
	return filepath.Join(m.cfg.ProjectsRoot, project), nil
}

func (m *Manager) saveLocked() error {
	if m.broken || m.closed {
		return ErrUnavailable
	}
	data, err := json.Marshal(m.state)
	if err != nil || len(data) > 1<<20 {
		m.storageFailedLocked()
		return ErrUnavailable
	}
	if err = m.cfg.Save(data); err != nil {
		m.storageFailedLocked()
		return ErrUnavailable
	}
	return nil
}

func (m *Manager) storageFailedLocked() {
	m.broken = true
	for _, p := range m.providers {
		p.state.Failure = "storage_unavailable"
		p.state.Readiness = "unverified"
		p.state.NextAction = "repair_storage"
	}
}

func (m *Manager) Restore() {
	m.mu.Lock()
	selected := slices.Clone(m.state.Selected)
	m.mu.Unlock()
	for _, id := range selected {
		m.Activate(id)
	}
}

func (m *Manager) Close() {
	m.mu.Lock()
	if m.closed {
		m.mu.Unlock()
		return
	}
	m.closed = true
	m.cancel()
	var runtimes []agentRuntime
	for _, p := range m.providers {
		if p.cancel != nil {
			p.cancel()
		}
		if p.runtime != nil {
			runtimes = append(runtimes, p.runtime)
		}
	}
	m.mu.Unlock()
	for _, r := range runtimes {
		r.Close()
	}
	m.wg.Wait()
}

func stateCopy(p *managedProvider) State {
	state := p.state
	state.Models = slices.Clone(p.state.Models)
	return state
}
func (m *Manager) Catalog() []State {
	m.mu.Lock()
	defer m.mu.Unlock()
	result := []State{}
	for _, d := range catalog {
		result = append(result, stateCopy(m.providers[d.ID]))
	}
	return result
}

func (m *Manager) Status(ctx context.Context, id string) (State, error) {
	m.mu.Lock()
	p := m.providers[id]
	if p == nil {
		m.mu.Unlock()
		return State{}, ErrInvalid
	}
	if m.broken {
		state := stateCopy(p)
		m.mu.Unlock()
		return state, nil
	}
	r := p.runtime
	state := stateCopy(p)
	m.mu.Unlock()
	if r == nil {
		return state, nil
	}
	native, err := r.Status(ctx)
	m.mu.Lock()
	defer m.mu.Unlock()
	if p.runtime != r || m.broken {
		return stateCopy(p), nil
	}
	if err != nil {
		p.state.Failure = failureCode(err)
		p.state.NextAction = "retry_status"
		p.state.Readiness = "unverified"
	} else {
		p.state.Authentication = native.Authentication
		p.state.Models = slices.Clone(native.Models)
		p.state.Failure = ""
		if native.Authentication == "needs_sign_in" {
			p.state.NextAction = "open_app"
			p.state.Readiness = "needs_user_action"
		} else if len(native.Models) == 0 {
			p.state.NextAction = "configure_model"
			p.state.Readiness = "needs_user_action"
		} else {
			p.state.NextAction = "create_conversation"
			if p.state.Readiness != "verified" {
				p.state.Readiness = "unverified"
			}
		}
	}
	// Status failures are part of the safe state projection, not a loss of the
	// status response itself. Callers can still see the required recovery action.
	return stateCopy(p), nil
}

func (m *Manager) Activate(id string) (State, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p := m.providers[id]
	if p == nil {
		return State{}, ErrInvalid
	}
	if m.closed || m.broken {
		return stateCopy(p), ErrUnavailable
	}
	if p.runtime != nil || p.done != nil || p.stopping {
		return stateCopy(p), nil
	}
	operation, err := makeID()
	if err != nil {
		return stateCopy(p), ErrUnavailable
	}
	if !slices.Contains(m.state.Selected, id) {
		m.state.Selected = append(m.state.Selected, id)
	}
	if err = m.saveLocked(); err != nil {
		return stateCopy(p), err
	}
	ctx, cancel := context.WithTimeout(m.ctx, 30*time.Minute)
	p.cancel = cancel
	p.done = make(chan struct{})
	p.state.Operation = operation
	p.state.Phase = "probing"
	p.state.Failure = ""
	p.state.NextAction = "wait"
	p.state.Readiness = "unverified"
	m.wg.Add(1)
	go m.activate(ctx, p)
	return stateCopy(p), nil
}

func (m *Manager) activate(ctx context.Context, p *managedProvider) {
	defer m.wg.Done()
	setPhase := func(phase string) { m.mu.Lock(); p.state.Phase = phase; m.mu.Unlock() }
	installed, err := m.cfg.probe(ctx, p.state.Definition)
	if err == nil {
		m.mu.Lock()
		value := installed
		p.state.Installed = &value
		m.mu.Unlock()
	}
	if err == nil && !installed {
		setPhase("installing")
		err = m.cfg.Install(ctx, p.state.Component)
		if err == nil {
			installed, err = m.cfg.probe(ctx, p.state.Definition)
		}
	}
	if err == nil && !installed {
		err = ErrUnavailable
	}
	var runtime agentRuntime
	var status RuntimeStatus
	if err == nil {
		setPhase("starting")
		startup, cancel := context.WithTimeout(ctx, 30*time.Second)
		runtime, err = m.cfg.launch(startup, p.state.Definition, m.cfg.ProjectsRoot)
		if err == nil {
			status, err = runtime.Status(startup)
		}
		cancel()
	}
	m.mu.Lock()
	if ctx.Err() != nil {
		err = ctx.Err()
	} else if m.closed {
		err = ErrUnavailable
	}
	if err == nil || installed {
		value := installed
		p.state.Installed = &value
	}
	if err != nil {
		p.state.Phase = "failed"
		p.state.Process = "stopped"
		p.state.Failure = failureCode(err)
		p.state.NextAction = "activate"
		if errors.Is(ctx.Err(), context.Canceled) {
			p.state.Phase = "stopped"
			p.state.Failure = ""
		}
	} else {
		p.runtime = runtime
		p.state.Process = "running"
		p.state.Phase = "active"
		p.state.Authentication = status.Authentication
		p.state.Models = slices.Clone(status.Models)
		p.state.NextAction = "create_conversation"
		if status.Authentication == "needs_sign_in" || len(status.Models) == 0 {
			p.state.Readiness = "needs_user_action"
			p.state.NextAction = "open_app"
		}
	}
	if p.cancel != nil {
		p.cancel()
	}
	// Keep activation coalesced until a failed process has fully stopped.
	if err != nil && runtime != nil {
		m.mu.Unlock()
		runtime.Close()
		m.mu.Lock()
	}
	close(p.done)
	p.done = nil
	p.cancel = nil
	if err == nil {
		m.wg.Add(1)
	}
	m.mu.Unlock()
	if err != nil {
		return
	}
	go m.collect(p, runtime)
}

func (m *Manager) Stop(id string) (State, error) {
	m.mu.Lock()
	p := m.providers[id]
	if p == nil {
		m.mu.Unlock()
		return State{}, ErrInvalid
	}
	if m.closed {
		m.mu.Unlock()
		return State{}, ErrUnavailable
	}
	if p.stopping {
		state := stateCopy(p)
		m.mu.Unlock()
		return state, nil
	}
	m.state.Selected = slices.DeleteFunc(m.state.Selected, func(value string) bool { return value == id })
	// Broken storage must not prevent stopping a running native process.
	err := m.saveLocked()
	if p.cancel != nil {
		p.cancel()
	}
	r := p.runtime
	p.runtime = nil
	p.stopping = true
	p.state.Process = "stopped"
	p.state.Phase = "stopped"
	if r != nil {
		p.state.Process = "stopping"
		p.state.Phase = "stopping"
	}
	p.state.Readiness = "unverified"
	p.state.NextAction = "activate"
	m.markUnknownLocked(id)
	m.mu.Unlock()
	if r != nil {
		r.Close()
	}
	m.mu.Lock()
	p.stopping = false
	p.state.Process = "stopped"
	p.state.Phase = "stopped"
	state := stateCopy(p)
	m.mu.Unlock()
	return state, err
}

// OpenApp uses the existing desktop launcher and native sign-in UI. It receives
// no credentials and exposes no provider-private endpoint to the caller.
func (m *Manager) OpenApp(ctx context.Context, id string) error {
	m.mu.Lock()
	p := m.providers[id]
	if p == nil {
		m.mu.Unlock()
		return ErrInvalid
	}
	if p.state.Installed == nil || !*p.state.Installed || m.closed || m.broken {
		m.mu.Unlock()
		return ErrUnavailable
	}
	if p.opening {
		m.mu.Unlock()
		return ErrBusy
	}
	p.opening = true
	m.mu.Unlock()
	defer func() { m.mu.Lock(); p.opening = false; m.mu.Unlock() }()
	cmd := exec.CommandContext(ctx, "/usr/local/bin/vibestack-desktop-action", "coding", id)
	cmd.Env = runtimeEnvironment()
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	if cmd.Run() != nil {
		return ErrUnavailable
	}
	return nil
}

type limitedOutput struct{ data []byte }

func (b *limitedOutput) Write(p []byte) (int, error) {
	if len(b.data)+len(p) > 1024 {
		return 0, ErrProtocol
	}
	b.data = append(b.data, p...)
	return len(p), nil
}
func probeInstalled(ctx context.Context, d Definition) (bool, error) {
	if _, err := os.Stat(d.binary); errors.Is(err, os.ErrNotExist) {
		return false, nil
	} else if err != nil {
		return false, ErrUnavailable
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, d.binary, "--version")
	cmd.Env = runtimeEnvironment()
	output := &limitedOutput{}
	cmd.Stdout = output
	cmd.Stderr = io.Discard
	if cmd.Run() != nil {
		return false, ErrUnavailable
	}
	version := strings.TrimSpace(string(output.data))
	if d.ID == "codex" {
		version = strings.TrimPrefix(version, "codex-cli ")
	}
	if version != d.Version {
		return false, ErrProtocol
	}
	return true, nil
}

func failureCode(err error) string {
	switch {
	case errors.Is(err, ErrProtocol):
		return "incompatible_protocol"
	case errors.Is(err, ErrDisconnected):
		return "connection_lost"
	case errors.Is(err, ErrConflict):
		return "conflict"
	case errors.Is(err, context.DeadlineExceeded):
		return "timeout"
	case errors.Is(err, ErrRejected):
		return "provider_rejected"
	default:
		return "unavailable"
	}
}
