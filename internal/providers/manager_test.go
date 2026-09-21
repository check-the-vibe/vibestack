package providers

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type fakeRuntime struct {
	events      chan nativeEvent
	once        sync.Once
	submits     atomic.Int32
	approvals   atomic.Int32
	beforeReply chan struct{}
	submitted   chan struct{}
}

func (f *fakeRuntime) Status(context.Context) (RuntimeStatus, error) {
	return RuntimeStatus{Authentication: "configured", Models: []Model{{ID: "fixture", Name: "Fixture"}}}, nil
}
func (f *fakeRuntime) Create(context.Context, string, string) (string, error) {
	return "session-fixture", nil
}
func (f *fakeRuntime) Resume(context.Context, string, string, string) error { return nil }
func (f *fakeRuntime) Submit(ctx context.Context, session, model, prompt, operation string) (string, error) {
	f.submits.Add(1)
	if f.submitted != nil {
		close(f.submitted)
	}
	if f.beforeReply != nil {
		select {
		case <-f.beforeReply:
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}
	return "turn-" + operation, nil
}
func (f *fakeRuntime) Interrupt(context.Context, string, string) error { return nil }
func (f *fakeRuntime) Approve(context.Context, json.RawMessage, bool) error {
	f.approvals.Add(1)
	return nil
}
func (f *fakeRuntime) Events() <-chan nativeEvent { return f.events }
func (f *fakeRuntime) Close()                     { f.once.Do(func() { close(f.events) }) }

func eventually(t *testing.T, condition func() bool) {
	t.Helper()
	end := time.Now().Add(3 * time.Second)
	for !condition() {
		if time.Now().After(end) {
			t.Fatal("condition did not become true")
		}
		time.Sleep(time.Millisecond)
	}
}

type fixtureStore struct {
	mu     sync.Mutex
	data   []byte
	failed bool
}

func (s *fixtureStore) load() ([]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]byte(nil), s.data...), nil
}
func (s *fixtureStore) save(data []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.failed {
		return errors.New("private persistence failure")
	}
	s.data = append([]byte(nil), data...)
	return nil
}

func managerFixture(t *testing.T, f *fakeRuntime, store *fixtureStore) (*Manager, *atomic.Int32, *atomic.Int32) {
	t.Helper()
	projects := t.TempDir()
	if err := os.Mkdir(filepath.Join(projects, "source"), 0700); err != nil {
		t.Fatal(err)
	}
	var installed atomic.Bool
	var installs, launches atomic.Int32
	m, err := NewManager(Config{ProjectsRoot: projects, Load: store.load, Save: store.save,
		Install: func(context.Context, string) error { installs.Add(1); installed.Store(true); return nil },
		probe:   func(context.Context, Definition) (bool, error) { return installed.Load(), nil },
		launch:  func(context.Context, Definition, string) (agentRuntime, error) { launches.Add(1); return f, nil },
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Close)
	return m, &installs, &launches
}
func readyConversation(t *testing.T, m *Manager) string {
	t.Helper()
	if _, err := m.Activate("codex"); err != nil {
		t.Fatal(err)
	}
	eventually(t, func() bool { return m.Catalog()[0].Phase == "active" })
	id := strings.Repeat("a", 32)
	if _, err := m.Create(id, "codex", "source", "fixture"); err != nil {
		t.Fatal(err)
	}
	eventually(t, func() bool { return m.Conversations()[0].Status == "idle" })
	return id
}

func TestConcurrentActivationUsesOneInstallAndProcess(t *testing.T) {
	f := &fakeRuntime{events: make(chan nativeEvent, 64)}
	m, installs, launches := managerFixture(t, f, &fixtureStore{})
	var group sync.WaitGroup
	ids := make(chan string, 20)
	for range 20 {
		group.Add(1)
		go func() {
			defer group.Done()
			state, err := m.Activate("codex")
			if err != nil {
				ids <- "error"
			} else {
				ids <- state.Operation
			}
		}()
	}
	group.Wait()
	close(ids)
	var id string
	for value := range ids {
		if !validID(value) || (id != "" && id != value) {
			t.Fatal("activation was duplicated")
		}
		id = value
	}
	eventually(t, func() bool { return m.Catalog()[0].Phase == "active" })
	if installs.Load() != 1 || launches.Load() != 1 {
		t.Fatal("duplicate install/process")
	}
	if m.Catalog()[0].Readiness == "verified" {
		t.Fatal("handshake falsely claimed a successful turn")
	}
}

func TestTurnEventsWaitForExactSubmitReplyAndNeverReplay(t *testing.T) {
	f := &fakeRuntime{events: make(chan nativeEvent, 64), beforeReply: make(chan struct{}), submitted: make(chan struct{})}
	store := &fixtureStore{}
	m, _, _ := managerFixture(t, f, store)
	conversation := readyConversation(t, m)
	operation := strings.Repeat("b", 32)
	if _, err := m.Submit(conversation, operation, "private fixture prompt"); err != nil {
		t.Fatal(err)
	}
	select {
	case <-f.submitted:
	case <-deadline(t).Done():
		t.Fatal("submission not started")
	}
	f.events <- nativeEvent{session: "session-fixture", turn: "old-turn", kind: "completed", outcome: "completed"}
	f.events <- nativeEvent{session: "session-fixture", turn: "turn-" + operation, kind: "text_delta", text: "fixture reply"}
	f.events <- nativeEvent{session: "session-fixture", turn: "turn-" + operation, kind: "completed", outcome: "completed"}
	if _, err := m.Submit(conversation, operation, "private fixture prompt"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.Submit(conversation, operation, "changed prompt"); !errors.Is(err, ErrConflict) {
		t.Fatal("idempotency collision accepted")
	}
	close(f.beforeReply)
	eventually(t, func() bool { return m.Conversations()[0].Operations[0].Status == "completed" })
	page, err := m.ReadEvents(conversation, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Events) != 2 || page.Events[0].Text != "fixture reply" || f.submits.Load() != 1 {
		t.Fatal("stale turn crossed into this operation or submission repeated")
	}
	data, _ := store.load()
	if strings.Contains(string(data), "private fixture prompt") || strings.Contains(string(data), "fixture reply") {
		t.Fatal("conversation content duplicated into metadata")
	}
}

func TestApprovalsAreBoundToExactConversationOperationAndConsumedOnce(t *testing.T) {
	f := &fakeRuntime{events: make(chan nativeEvent, 64)}
	m, _, _ := managerFixture(t, f, &fixtureStore{})
	conversation := readyConversation(t, m)
	operation := strings.Repeat("b", 32)
	m.Submit(conversation, operation, "fixture")
	eventually(t, func() bool { return m.Conversations()[0].Operations[0].Status == "running" })
	f.events <- nativeEvent{session: "session-fixture", turn: "turn-" + operation, kind: "approval", text: "fixture action", approval: json.RawMessage(`42`)}
	var page Events
	eventually(t, func() bool { page, _ = m.ReadEvents(conversation, 0); return len(page.Approvals) == 1 })
	id := page.Approvals[0].Approval
	if f.approvals.Load() != 0 {
		t.Fatal("provider request approved without a human response")
	}
	if err := m.Approve(deadline(t), strings.Repeat("c", 32), operation, id, true); !errors.Is(err, ErrConflict) {
		t.Fatal("cross-conversation approval accepted")
	}
	if err := m.Approve(deadline(t), conversation, strings.Repeat("c", 32), id, true); !errors.Is(err, ErrConflict) {
		t.Fatal("cross-turn approval accepted")
	}
	if err := m.Approve(deadline(t), conversation, operation, id, false); err != nil {
		t.Fatal(err)
	}
	if err := m.Approve(deadline(t), conversation, operation, id, true); !errors.Is(err, ErrConflict) {
		t.Fatal("approval replay accepted")
	}
	if f.approvals.Load() != 1 {
		t.Fatal("approval count mismatch")
	}
	// A repeated native request after consumption must not mint a new handle.
	f.events <- nativeEvent{session: "session-fixture", turn: "turn-" + operation, kind: "approval", text: "fixture action", approval: json.RawMessage(`42`)}
	f.events <- nativeEvent{session: "session-fixture", turn: "turn-" + operation, kind: "text_delta", text: "barrier"}
	eventually(t, func() bool {
		page, _ = m.ReadEvents(conversation, 0)
		return page.Events[len(page.Events)-1].Text == "barrier"
	})
	if len(page.Approvals) != 0 {
		t.Fatal("duplicate native approval minted another public handle")
	}
	f.events <- nativeEvent{session: "session-fixture", turn: "turn-" + operation, kind: "approval", text: "truncated action", approval: json.RawMessage(`43`), denyOnly: true}
	eventually(t, func() bool { page, _ = m.ReadEvents(conversation, 0); return len(page.Approvals) == 1 })
	id = page.Approvals[0].Approval
	if err := m.Approve(deadline(t), conversation, operation, id, true); !errors.Is(err, ErrUnsupported) {
		t.Fatal("truncated approval could be allowed")
	}
	if err := m.Approve(deadline(t), conversation, operation, id, false); err != nil {
		t.Fatal("human could not decline truncated action")
	}
}

func TestPersistenceFailureRemainsVisibleAndCannotPreventStop(t *testing.T) {
	store := &fixtureStore{}
	f := &fakeRuntime{events: make(chan nativeEvent, 64)}
	m, _, _ := managerFixture(t, f, store)
	conversation := readyConversation(t, m)
	store.mu.Lock()
	store.failed = true
	store.mu.Unlock()
	if _, err := m.Submit(conversation, strings.Repeat("b", 32), "fixture"); !errors.Is(err, ErrUnavailable) {
		t.Fatal("submission did not fail closed")
	}
	state, err := m.Status(deadline(t), "codex")
	if err != nil || state.Failure != "storage_unavailable" || state.Readiness == "verified" || f.submits.Load() != 0 {
		t.Fatal("storage failure was hidden or dispatched work")
	}
	if _, err = m.Stop("codex"); !errors.Is(err, ErrUnavailable) {
		t.Fatal("stop did not report that selection could not be saved")
	}
	if m.Catalog()[0].Process != "stopped" {
		t.Fatal("broken storage prevented process stop")
	}
}

func TestRestartReportsUnknownAndDoesNotReplayPersistedPrompt(t *testing.T) {
	store := &fixtureStore{}
	f := &fakeRuntime{events: make(chan nativeEvent, 64)}
	m, _, _ := managerFixture(t, f, store)
	conversation := readyConversation(t, m)
	operation := strings.Repeat("b", 32)
	m.Submit(conversation, operation, "fixture")
	eventually(t, func() bool { return m.Conversations()[0].Operations[0].Status == "running" })
	m.Close()
	second := &fakeRuntime{events: make(chan nativeEvent, 64)}
	reopened, _, launches := managerFixture(t, second, store)
	page, err := reopened.ReadEvents(conversation, 0)
	if err != nil || !page.Gap || page.Conversation.Operations[0].Status != "unknown" {
		t.Fatal("restart invented continuous history or completion")
	}
	if _, err := reopened.Submit(conversation, operation, "fixture"); err != nil {
		t.Fatal(err)
	}
	if second.submits.Load() != 0 || launches.Load() != 0 {
		t.Fatal("opening metadata or retrying an operation started native work")
	}
}

func TestPersistenceFailurePreventsProviderActivation(t *testing.T) {
	store := &fixtureStore{failed: true}
	m, installs, launches := managerFixture(t, &fakeRuntime{events: make(chan nativeEvent, 64)}, store)
	if _, err := m.Activate("codex"); !errors.Is(err, ErrUnavailable) {
		t.Fatal("unsafe activation accepted")
	}
	if installs.Load() != 0 || launches.Load() != 0 {
		t.Fatal("side effect ran before durable state")
	}
}

func TestProjectSelectionRejectsTraversalAndSymlinks(t *testing.T) {
	m, _, _ := managerFixture(t, &fakeRuntime{events: make(chan nativeEvent, 64)}, &fixtureStore{})
	if err := os.Symlink(t.TempDir(), filepath.Join(m.cfg.ProjectsRoot, "outside")); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"../outside", "/tmp", ".", "outside", "source/subfolder", "source\x00"} {
		if _, err := m.projectPath(name); err == nil {
			t.Fatalf("unsafe project %q accepted", name)
		}
	}
}
