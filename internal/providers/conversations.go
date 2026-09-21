package providers

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"slices"
	"strings"
	"time"
)

type Operation struct {
	ID      string `json:"id"`
	Status  string `json:"status"`
	Created int64  `json:"created_at"`
}
type operationRecord struct {
	Operation
	Digest        string `json:"digest"`
	Native        string `json:"native"`
	pending       []nativeEvent
	pendingBytes  int
	approvalsSeen map[string]bool
}
type Conversation struct {
	ID         string      `json:"id"`
	Provider   string      `json:"provider"`
	Project    string      `json:"project"`
	Model      string      `json:"model"`
	Status     string      `json:"status"`
	Created    int64       `json:"created_at"`
	Operations []Operation `json:"operations"`
}
type conversationRecord struct {
	ID         string                      `json:"id"`
	Provider   string                      `json:"provider"`
	Project    string                      `json:"project"`
	Model      string                      `json:"model"`
	Status     string                      `json:"status"`
	Created    int64                       `json:"created_at"`
	Native     string                      `json:"native"`
	Active     string                      `json:"active"`
	Operations map[string]*operationRecord `json:"operations"`
}
type Event struct {
	Sequence  uint64 `json:"sequence"`
	Kind      string `json:"kind"`
	Operation string `json:"operation_id"`
	Item      string `json:"item_id,omitempty"`
	Text      string `json:"text,omitempty"`
	Approval  string `json:"approval_id,omitempty"`
	CanAllow  bool   `json:"can_allow,omitempty"`
	Outcome   string `json:"outcome,omitempty"`
}
type Events struct {
	Conversation Conversation `json:"conversation"`
	Events       []Event      `json:"events"`
	Cursor       uint64       `json:"cursor"`
	Gap          bool         `json:"gap"`
	Approvals    []Event      `json:"approvals"`
}
type eventBuffer struct {
	events    []Event
	next      uint64
	bytes     int
	recovered bool
}

func newEventBuffer() *eventBuffer { return &eventBuffer{next: 1, events: []Event{}} }

type pendingApproval struct {
	conversation, operation string
	runtime                 agentRuntime
	handle                  json.RawMessage
	answering               bool
	public                  Event
}

func publicConversation(c *conversationRecord) Conversation {
	result := Conversation{ID: c.ID, Provider: c.Provider, Project: c.Project, Model: c.Model, Status: c.Status, Created: c.Created, Operations: []Operation{}}
	for _, op := range c.Operations {
		result.Operations = append(result.Operations, op.Operation)
	}
	slices.SortFunc(result.Operations, func(a, b Operation) int {
		if a.Created < b.Created {
			return -1
		}
		if a.Created > b.Created {
			return 1
		}
		return strings.Compare(a.ID, b.ID)
	})
	return result
}
func (m *Manager) Conversations() []Conversation {
	m.mu.Lock()
	defer m.mu.Unlock()
	result := []Conversation{}
	for _, c := range m.state.Conversations {
		result = append(result, publicConversation(c))
	}
	slices.SortFunc(result, func(a, b Conversation) int {
		if a.Created < b.Created {
			return -1
		}
		if a.Created > b.Created {
			return 1
		}
		return strings.Compare(a.ID, b.ID)
	})
	return result
}

func (m *Manager) Create(id, provider, project, model string) (Conversation, error) {
	if !validID(id) || !nativeID(model) {
		return Conversation{}, ErrInvalid
	}
	path, err := m.projectPath(project)
	if err != nil {
		return Conversation{}, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.closed || m.broken {
		return Conversation{}, ErrUnavailable
	}
	if existing := m.state.Conversations[id]; existing != nil {
		if existing.Provider != provider || existing.Project != project || existing.Model != model {
			return Conversation{}, ErrConflict
		}
		return publicConversation(existing), nil
	}
	p := m.providers[provider]
	if p == nil {
		return Conversation{}, ErrInvalid
	}
	if p.runtime == nil || !slices.ContainsFunc(p.state.Models, func(value Model) bool { return value.ID == model }) {
		return Conversation{}, ErrUnavailable
	}
	if len(m.state.Conversations) >= 32 {
		return Conversation{}, ErrBusy
	}
	c := &conversationRecord{ID: id, Provider: provider, Project: project, Model: model, Status: "creating", Created: time.Now().UnixMilli(), Operations: map[string]*operationRecord{}}
	m.state.Conversations[id] = c
	m.buffers[id] = newEventBuffer()
	if err = m.saveLocked(); err != nil {
		return Conversation{}, err
	}
	r := p.runtime
	m.wg.Add(1)
	go func() {
		defer m.wg.Done()
		ctx, cancel := context.WithTimeout(m.ctx, 30*time.Second)
		defer cancel()
		native, err := r.Create(ctx, path, model)
		m.mu.Lock()
		defer m.mu.Unlock()
		if err != nil || m.closed || p.runtime != r {
			c.Status = "unknown"
		} else {
			c.Native = native
			c.Status = "idle"
		}
		m.saveLocked()
	}()
	return publicConversation(c), nil
}

func (m *Manager) Submit(conversation, operation, prompt string) (Conversation, error) {
	if !validID(operation) || len(prompt) == 0 || len(prompt) > 64<<10 || strings.ContainsRune(prompt, 0) {
		return Conversation{}, ErrInvalid
	}
	digest := sha256.Sum256([]byte(prompt))
	fingerprint := hex.EncodeToString(digest[:])
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.closed || m.broken {
		return Conversation{}, ErrUnavailable
	}
	c := m.state.Conversations[conversation]
	if c == nil {
		return Conversation{}, ErrInvalid
	}
	if prior := c.Operations[operation]; prior != nil {
		if prior.Digest != fingerprint {
			return Conversation{}, ErrConflict
		}
		return publicConversation(c), nil // Never replay, including after a crash.
	}
	p := m.providers[c.Provider]
	if p.runtime == nil || c.Native == "" || c.Status != "idle" {
		return Conversation{}, ErrUnavailable
	}
	if c.Active != "" {
		previous := c.Operations[c.Active]
		if previous != nil && (previous.Status == "submitting" || previous.Status == "running" || previous.Status == "stopping") {
			return Conversation{}, ErrBusy
		}
	}
	if len(c.Operations) >= 32 {
		return Conversation{}, ErrBusy
	}
	path, err := m.projectPath(c.Project)
	if err != nil {
		return Conversation{}, err
	}
	op := &operationRecord{Operation: Operation{ID: operation, Status: "submitting", Created: time.Now().UnixMilli()}, Digest: fingerprint}
	c.Operations[operation] = op
	c.Active = operation
	if err = m.saveLocked(); err != nil {
		return Conversation{}, err
	}
	r := p.runtime
	m.wg.Add(1)
	go m.submit(r, c, op, path, prompt)
	return publicConversation(c), nil
}

func (m *Manager) submit(r agentRuntime, c *conversationRecord, op *operationRecord, path, prompt string) {
	defer m.wg.Done()
	ctx, cancel := context.WithTimeout(m.ctx, 30*time.Second)
	defer cancel()
	err := r.Resume(ctx, c.Native, path, c.Model)
	var native string
	if err == nil {
		native, err = r.Submit(ctx, c.Native, c.Model, prompt, op.ID)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if err != nil {
		if op.Status == "submitting" {
			op.Status = "unknown"
			m.appendEventLocked(c.ID, Event{Kind: "error", Operation: op.ID, Text: "Provider submission could not be confirmed. Inspect the native conversation; this prompt was not retried.", Outcome: failureCode(err)})
		}
	} else if op.Status == "submitting" {
		op.Native = native
		op.Status = "running"
		for _, event := range op.pending {
			m.applyEventLocked(m.providers[c.Provider], r, c, op, event)
		}
	}
	op.pending = nil
	op.pendingBytes = 0
	// Completion can arrive before the submit response; never overwrite it.
	m.saveLocked()
}

func (m *Manager) ReadEvents(conversation string, cursor uint64) (Events, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	c := m.state.Conversations[conversation]
	if c == nil {
		return Events{}, ErrInvalid
	}
	buffer := m.buffers[conversation]
	result := Events{Conversation: publicConversation(c), Events: []Event{}, Approvals: []Event{}, Cursor: cursor}
	for _, approval := range m.approvals {
		if approval.conversation == conversation {
			result.Approvals = append(result.Approvals, approval.public)
		}
	}
	if cursor >= buffer.next || buffer.recovered || (len(buffer.events) > 0 && cursor+1 < buffer.events[0].Sequence) {
		result.Gap = true
	}
	// A restart loses only the transient stream, not native history or recorded
	// outcomes. Tell clients to inspect the native app instead of inventing text.
	bytes := 0
	for _, event := range buffer.events {
		if event.Sequence <= cursor && cursor < buffer.next {
			continue
		}
		if len(result.Events) >= 32 || bytes+len(event.Text) > 128<<10 {
			break
		}
		result.Events = append(result.Events, event)
		result.Cursor = event.Sequence
		bytes += len(event.Text)
	}
	if len(result.Events) == 0 && result.Gap {
		result.Cursor = buffer.next - 1
	}
	return result, nil
}

func (m *Manager) appendEventLocked(id string, event Event) {
	b := m.buffers[id]
	if b == nil {
		return
	}
	event.Sequence = b.next
	b.next++
	event.Text = boundedText(event.Text, 48<<10)
	event.Item = boundedText(event.Item, 256)
	b.events = append(b.events, event)
	b.bytes += len(event.Text)
	for len(b.events) > 256 || b.bytes > 1<<20 {
		b.bytes -= len(b.events[0].Text)
		b.events = b.events[1:]
	}
}

func (m *Manager) collect(p *managedProvider, r agentRuntime) {
	defer m.wg.Done()
	for event := range r.Events() {
		m.mu.Lock()
		if p.runtime != r || m.closed {
			m.mu.Unlock()
			continue
		}
		var c *conversationRecord
		for _, candidate := range m.state.Conversations {
			if candidate.Provider == p.state.ID && candidate.Native == event.session {
				c = candidate
				break
			}
		}
		if c == nil || c.Active == "" {
			m.mu.Unlock()
			continue
		}
		op := c.Operations[c.Active]
		if op == nil || (op.Status != "running" && op.Status != "submitting" && op.Status != "stopping") {
			m.mu.Unlock()
			continue
		}
		if op.Native == "" {
			// Never bind a newly submitted operation to a late event from the
			// preceding turn. Wait for this submission's authoritative reply.
			if len(op.pending) >= 64 || op.pendingBytes+len(event.text) > 1<<20 {
				op.Status = "unknown"
				m.appendEventLocked(c.ID, Event{Kind: "error", Operation: op.ID, Text: "Provider events exceeded the pending submission buffer; inspect or stop the native session.", Outcome: "unknown"})
				m.saveLocked()
			} else {
				op.pending = append(op.pending, event)
				op.pendingBytes += len(event.text)
			}
		} else {
			m.applyEventLocked(p, r, c, op, event)
		}
		m.mu.Unlock()
	}
	m.mu.Lock()
	if p.runtime == r {
		p.runtime = nil
		p.state.Process = "stopped"
		p.state.Phase = "failed"
		p.state.Failure = "connection_lost"
		p.state.NextAction = "activate"
		p.state.Readiness = "unverified"
		m.markUnknownLocked(p.state.ID)
	}
	m.mu.Unlock()
	r.Close()
}

func (m *Manager) applyEventLocked(p *managedProvider, r agentRuntime, c *conversationRecord, op *operationRecord, event nativeEvent) {
	if p.runtime != r || (op.Status != "running" && op.Status != "submitting" && op.Status != "stopping") || event.turn == "" || op.Native != event.turn {
		return
	}
	public := Event{Kind: event.kind, Operation: op.ID, Text: event.text, Item: event.item, Outcome: event.outcome}
	switch event.kind {
	case "approval":
		// A repeated native request never creates a second usable approval,
		// including after an uncertain response. The ledger is per live turn.
		var compact bytes.Buffer
		if len(event.approval) == 0 || len(event.approval) > 1024 || json.Compact(&compact, event.approval) != nil {
			return
		}
		key := compact.String()
		if op.approvalsSeen[key] {
			return
		}
		if op.approvalsSeen == nil {
			op.approvalsSeen = map[string]bool{}
		}
		if len(op.approvalsSeen) >= 128 {
			op.Status = "unknown"
			m.appendEventLocked(c.ID, Event{Kind: "error", Operation: op.ID, Outcome: "unknown", Text: "Native approval limit reached. Stop and inspect the provider session."})
			m.saveLocked()
			return
		}
		op.approvalsSeen[key] = true
		approvalBytes := len(public.Text)
		for _, pending := range m.approvals {
			approvalBytes += len(pending.public.Text)
		}
		if len(m.approvals) >= 32 || approvalBytes > 256<<10 {
			op.Status = "unknown"
			public.Kind = "error"
			public.Text = "Approval capacity reached. Stop and inspect the native session."
			m.saveLocked()
			break
		}
		id, err := makeID()
		if err != nil {
			return
		}
		public.Approval = id
		public.CanAllow = !event.denyOnly
		m.approvals[id] = &pendingApproval{conversation: c.ID, operation: op.ID, runtime: r, handle: append(json.RawMessage(nil), event.approval...), public: public}
	case "completed":
		op.Status = event.outcome
		op.approvalsSeen = nil
		if op.Status == "completed" && !m.broken {
			p.state.Readiness = "verified"
		} else if op.Status != "completed" && !m.broken {
			p.state.Readiness = "unverified"
		}
		for id, a := range m.approvals {
			if a.conversation == c.ID && a.operation == op.ID {
				delete(m.approvals, id)
			}
		}
		m.saveLocked()
	case "running":
		if op.Status != "stopping" {
			op.Status = "running"
		}
	}
	if m.broken {
		m.storageFailedLocked()
	}
	m.appendEventLocked(c.ID, public)
}

func (m *Manager) markUnknownLocked(provider string) {
	for _, c := range m.state.Conversations {
		if c.Provider != provider {
			continue
		}
		for _, op := range c.Operations {
			if op.Status == "submitting" || op.Status == "running" || op.Status == "stopping" {
				op.Status = "unknown"
				m.appendEventLocked(c.ID, Event{Kind: "error", Operation: op.ID, Outcome: "unknown", Text: "Provider stopped. Its last turn may have changed files. Inspect native history before starting another turn."})
			}
		}
	}
	for id, a := range m.approvals {
		if c := m.state.Conversations[a.conversation]; c != nil && c.Provider == provider {
			delete(m.approvals, id)
		}
	}
	m.saveLocked()
}

func (m *Manager) Interrupt(ctx context.Context, conversation, operation string) (Conversation, error) {
	m.mu.Lock()
	c := m.state.Conversations[conversation]
	if c == nil || c.Active != operation {
		m.mu.Unlock()
		return Conversation{}, ErrConflict
	}
	op := c.Operations[operation]
	r := m.providers[c.Provider].runtime
	if op == nil || r == nil || op.Native == "" || (op.Status != "running" && op.Status != "stopping") {
		m.mu.Unlock()
		return Conversation{}, ErrConflict
	}
	op.Status = "stopping"
	if err := m.saveLocked(); err != nil {
		m.mu.Unlock()
		return Conversation{}, err
	}
	native := op.Native
	session := c.Native
	m.mu.Unlock()
	err := r.Interrupt(ctx, session, native)
	m.mu.Lock()
	defer m.mu.Unlock()
	if err != nil && op.Status == "stopping" {
		op.Status = "unknown"
		m.saveLocked()
	}
	return publicConversation(c), err
}

// The service exposes this only with owner authority and excludes it from MCP.
// Exact public handles are consumed once, even when delivery is uncertain.
func (m *Manager) Approve(ctx context.Context, conversation, operation, approval string, allow bool) error {
	m.mu.Lock()
	a := m.approvals[approval]
	if a == nil || a.conversation != conversation || a.operation != operation || a.answering {
		m.mu.Unlock()
		return ErrConflict
	}
	c := m.state.Conversations[conversation]
	if c == nil || c.Active != operation || m.providers[c.Provider].runtime != a.runtime || m.broken || m.closed {
		m.mu.Unlock()
		return ErrConflict
	}
	if allow && !a.public.CanAllow {
		m.mu.Unlock()
		return ErrUnsupported
	}
	a.answering = true
	m.mu.Unlock()
	err := a.runtime.Approve(ctx, a.handle, allow)
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.approvals, approval)
	if err != nil {
		m.appendEventLocked(conversation, Event{Kind: "error", Operation: operation, Outcome: "unknown", Text: "Approval delivery was not confirmed. It was not retried; inspect or stop the native turn."})
	} else {
		m.appendEventLocked(conversation, Event{Kind: "approval_answered", Operation: operation, Approval: approval})
	}
	return err
}
