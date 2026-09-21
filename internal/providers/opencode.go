package providers

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/url"
	"slices"
	"strings"
	"sync"
	"time"
)

type openCodeTurn struct {
	id       string
	seen     bool
	messages map[string]bool
}
type openCodeRuntime struct {
	process        *childProcess
	client         *http.Client
	origin, secret string
	ctx            context.Context
	cancel         context.CancelFunc
	events         chan nativeEvent
	mu             sync.Mutex
	projects       map[string]string
	turns          map[string]*openCodeTurn
	once           sync.Once
}

func startOpenCode(ctx context.Context, binary, dir string) (agentRuntime, error) {
	// The provider does not accept an inherited socket. Reserve an ephemeral
	// loopback port, close it and detect a conflicting bind by the secret-backed
	// health probe. A conflict fails activation; it never selects another server.
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return nil, ErrUnavailable
	}
	address := listener.Addr().String()
	listener.Close()
	_, port, _ := net.SplitHostPort(address)
	secret := make([]byte, 32)
	if _, err = rand.Read(secret); err != nil {
		return nil, ErrUnavailable
	}
	token := hex.EncodeToString(secret)
	// This random, process-private API secret is distinct from the Linux login
	// password. OpenCode accepts it only through its documented child environment.
	p, _, _, err := startChild(binary, []string{"--pure", "serve", "--hostname", "127.0.0.1", "--port", port}, dir, []string{"OPENCODE_SERVER_USERNAME=vibestack", "OPENCODE_SERVER_PASSWORD=" + token, `OPENCODE_CONFIG_CONTENT={"permission":"ask"}`}, false)
	if err != nil {
		return nil, err
	}
	lifetime, cancel := context.WithCancel(context.Background())
	r := &openCodeRuntime{process: p, origin: "http://" + address, secret: token, ctx: lifetime, cancel: cancel, events: make(chan nativeEvent, 64), projects: map[string]string{}, turns: map[string]*openCodeTurn{}}
	r.client = &http.Client{Transport: &http.Transport{Proxy: nil, DisableCompression: true, MaxIdleConns: 4, ResponseHeaderTimeout: 10 * time.Second}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	ticker := time.NewTicker(150 * time.Millisecond)
	defer ticker.Stop()
	for {
		var health struct {
			Healthy bool   `json:"healthy"`
			Version string `json:"version"`
		}
		if err = r.request(ctx, "GET", "/global/health", "", nil, &health); err == nil {
			if !health.Healthy || health.Version != "1.18.29" {
				r.Close()
				return nil, ErrProtocol
			}
			break
		}
		select {
		case <-ctx.Done():
			r.Close()
			return nil, ctx.Err()
		case <-p.done:
			r.Close()
			return nil, ErrUnavailable
		case <-ticker.C:
		}
	}
	response, err := r.openStream(ctx)
	if err != nil {
		r.Close()
		return nil, err
	}
	go r.readEvents(response)
	return r, nil
}

func (r *openCodeRuntime) Events() <-chan nativeEvent { return r.events }
func (r *openCodeRuntime) Close() {
	r.once.Do(func() { r.cancel(); r.process.close(); r.client.CloseIdleConnections() })
}

func (r *openCodeRuntime) request(ctx context.Context, method, path, project string, body, result any) error {
	var data []byte
	if body != nil {
		var err error
		data, err = json.Marshal(body)
		if err != nil || len(data) > rpcRequestBytes {
			return ErrInvalid
		}
	}
	target := r.origin + path
	if project != "" {
		target += "?" + url.Values{"directory": []string{project}}.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, target, bytes.NewReader(data))
	if err != nil {
		return ErrInvalid
	}
	req.SetBasicAuth("vibestack", r.secret)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	response, err := r.client.Do(req)
	if err != nil {
		return ErrDisconnected
	}
	defer response.Body.Close()
	data, err = io.ReadAll(io.LimitReader(response.Body, rpcFrameBytes+1))
	if err != nil {
		return ErrDisconnected
	}
	if len(data) > rpcFrameBytes {
		return ErrProtocol
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return ErrRejected
	}
	if result != nil && json.Unmarshal(data, result) != nil {
		return ErrProtocol
	}
	return nil
}

func (r *openCodeRuntime) Status(ctx context.Context) (RuntimeStatus, error) {
	state := RuntimeStatus{Authentication: "needs_sign_in", Models: []Model{}}
	var catalog struct {
		Default map[string]string `json:"default"`
		All     []struct {
			ID     string `json:"id"`
			Models map[string]struct {
				Name string `json:"name"`
			} `json:"models"`
		} `json:"providers"`
	}
	if err := r.request(ctx, "GET", "/config/providers", "", nil, &catalog); err != nil {
		return state, err
	}
	// The built-in provider can be connected without user authentication.
	// "configured" describes native configuration, not successful model access.
	for _, provider := range catalog.All {
		for id, model := range provider.Models {
			key := provider.ID + "/" + id
			if nativeID(key) {
				state.Models = append(state.Models, Model{ID: key, Name: boundedText(model.Name, 160), Default: catalog.Default[provider.ID] == id})
			}
		}
	}
	slices.SortFunc(state.Models, func(a, b Model) int { return strings.Compare(a.ID, b.ID) })
	if len(state.Models) > 100 {
		state.Models = state.Models[:100]
	}
	if len(state.Models) > 0 {
		state.Authentication = "configured"
	}
	return state, nil
}

func openCodeModel(model string) (map[string]string, error) {
	provider, id, ok := strings.Cut(model, "/")
	if !ok || !nativeID(provider) || !nativeID(id) {
		return nil, ErrInvalid
	}
	return map[string]string{"providerID": provider, "modelID": id}, nil
}
func (r *openCodeRuntime) Create(ctx context.Context, project, model string) (string, error) {
	if _, err := openCodeModel(model); err != nil {
		return "", err
	}
	var result struct {
		ID string `json:"id"`
	}
	// Each session repeats the permission default so native session settings do
	// not silently bypass the visible approval flow.
	params := map[string]any{"title": "VibeStack conversation", "permission": []any{map[string]string{"permission": "*", "pattern": "*", "action": "ask"}}}
	if err := r.request(ctx, "POST", "/session", project, params, &result); err != nil {
		return "", err
	}
	if !nativeID(result.ID) {
		return "", ErrProtocol
	}
	r.mu.Lock()
	r.projects[result.ID] = project
	r.mu.Unlock()
	return result.ID, nil
}
func (r *openCodeRuntime) Resume(ctx context.Context, session, project, model string) error {
	var result struct {
		ID string `json:"id"`
	}
	if err := r.request(ctx, "GET", "/session/"+url.PathEscape(session), project, nil, &result); err != nil {
		return err
	}
	if result.ID != session {
		return ErrProtocol
	}
	var states map[string]struct {
		Type string `json:"type"`
	}
	if err := r.request(ctx, "GET", "/session/status", project, nil, &states); err != nil {
		return err
	}
	if state, ok := states[session]; ok && state.Type != "idle" {
		return ErrConflict
	}
	r.mu.Lock()
	r.projects[session] = project
	r.mu.Unlock()
	return nil
}
func (r *openCodeRuntime) Submit(ctx context.Context, session, model, prompt, operation string) (string, error) {
	selection, err := openCodeModel(model)
	if err != nil {
		return "", err
	}
	message := "msg" + operation
	r.mu.Lock()
	project, known := r.projects[session]
	if !known || r.turns[session] != nil {
		r.mu.Unlock()
		return "", ErrConflict
	}
	r.turns[session] = &openCodeTurn{id: message, messages: map[string]bool{}}
	r.mu.Unlock()
	err = r.request(ctx, "POST", "/session/"+url.PathEscape(session)+"/prompt_async", project, map[string]any{"messageID": message, "model": selection, "parts": []any{map[string]string{"type": "text", "text": prompt}}}, nil)
	// Any failed reply remains uncertain. Do not clear the marker and resubmit.
	if err != nil {
		return "", err
	}
	return message, nil
}
func (r *openCodeRuntime) Interrupt(ctx context.Context, session, turn string) error {
	r.mu.Lock()
	project, known := r.projects[session]
	active := r.turns[session]
	r.mu.Unlock()
	if !known || active == nil || active.id != turn {
		return ErrConflict
	}
	return r.request(ctx, "POST", "/session/"+url.PathEscape(session)+"/abort", project, map[string]any{}, nil)
}
func (r *openCodeRuntime) Approve(ctx context.Context, handle json.RawMessage, allow bool) error {
	var approval struct {
		ID      string `json:"id"`
		Session string `json:"session"`
	}
	if json.Unmarshal(handle, &approval) != nil || !nativeID(approval.ID) {
		return ErrInvalid
	}
	r.mu.Lock()
	project, known := r.projects[approval.Session]
	r.mu.Unlock()
	if !known {
		return ErrConflict
	}
	reply := "reject"
	if allow {
		reply = "once"
	}
	return r.request(ctx, "POST", "/permission/"+url.PathEscape(approval.ID)+"/reply", project, map[string]string{"reply": reply}, nil)
}

func (r *openCodeRuntime) openStream(startup context.Context) (*http.Response, error) {
	req, _ := http.NewRequestWithContext(r.ctx, "GET", r.origin+"/global/event", nil)
	req.SetBasicAuth("vibestack", r.secret)
	req.Header.Set("Accept", "text/event-stream")
	// Startup cancellation must not cancel the lifetime event stream after the
	// activation returns, but must still bound opening its response headers.
	stop := context.AfterFunc(startup, r.cancel)
	response, err := r.client.Do(req)
	stop()
	if err != nil {
		return nil, ErrDisconnected
	}
	if response.StatusCode != 200 || !strings.HasPrefix(response.Header.Get("Content-Type"), "text/event-stream") {
		response.Body.Close()
		return nil, ErrProtocol
	}
	return response, nil
}
func (r *openCodeRuntime) readEvents(response *http.Response) {
	defer close(r.events)
	defer response.Body.Close()
	reader := bufio.NewScanner(response.Body)
	reader.Buffer(make([]byte, 4096), rpcFrameBytes)
	var data []byte
	for reader.Scan() {
		line := reader.Bytes()
		if len(line) > 0 {
			if bytes.HasPrefix(line, []byte("data:")) {
				data = append(data, bytes.TrimPrefix(line, []byte("data:"))...)
				data = append(data, '\n')
				if len(data) > rpcFrameBytes {
					r.cancel()
					return
				}
			}
			continue
		}
		if len(data) == 0 {
			continue
		}
		event, ok := r.decodeEvent(data)
		data = nil
		if !ok {
			continue
		}
		select {
		case r.events <- event:
		case <-r.ctx.Done():
			return
		default:
			r.cancel()
			return
		}
	}
	// No transparent reconnection: missing approvals or completion are an
	// uncertain turn, surfaced by the manager without replaying a prompt.
	r.cancel()
}

func (r *openCodeRuntime) decodeEvent(raw []byte) (nativeEvent, bool) {
	var wrapped struct {
		Payload json.RawMessage `json:"payload"`
	}
	if json.Unmarshal(raw, &wrapped) != nil {
		return nativeEvent{}, false
	}
	if len(wrapped.Payload) > 0 {
		raw = wrapped.Payload
	}
	var wire struct {
		Type       string `json:"type"`
		Properties struct {
			ID         string          `json:"id"`
			Session    string          `json:"sessionID"`
			Message    string          `json:"messageID"`
			Part       string          `json:"partID"`
			Delta      string          `json:"delta"`
			Field      string          `json:"field"`
			Permission string          `json:"permission"`
			Patterns   []string        `json:"patterns"`
			Metadata   json.RawMessage `json:"metadata"`
			Error      struct {
				Name string `json:"name"`
			} `json:"error"`
			PartData struct {
				ID      string `json:"id"`
				Session string `json:"sessionID"`
				Message string `json:"messageID"`
				Type    string `json:"type"`
				Tool    string `json:"tool"`
				State   struct {
					Status string `json:"status"`
					Title  string `json:"title"`
				} `json:"state"`
			} `json:"part"`
			Info struct {
				ID      string `json:"id"`
				Session string `json:"sessionID"`
				Parent  string `json:"parentID"`
				Role    string `json:"role"`
			} `json:"info"`
			Tool struct {
				Message string `json:"messageID"`
			} `json:"tool"`
			Status struct {
				Type string `json:"type"`
			} `json:"status"`
		} `json:"properties"`
	}
	if json.Unmarshal(raw, &wire) != nil {
		return nativeEvent{}, false
	}
	p := wire.Properties
	if p.Session == "" {
		p.Session = p.Info.Session
	}
	if p.Session == "" {
		p.Session = p.PartData.Session
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	turn := r.turns[p.Session]
	if turn == nil {
		return nativeEvent{}, false
	}
	e := nativeEvent{session: p.Session, turn: turn.id, item: p.Part}
	switch wire.Type {
	case "message.updated":
		if p.Info.Role == "assistant" && p.Info.Parent == turn.id {
			turn.seen = true
			turn.messages[p.Info.ID] = true
		}
		return nativeEvent{}, false
	case "message.part.delta":
		if !turn.messages[p.Message] || p.Field != "text" {
			return nativeEvent{}, false
		}
		e.kind = "text_delta"
		e.text = boundedText(p.Delta, 32<<10)
	case "message.part.updated":
		if !turn.messages[p.PartData.Message] || p.PartData.Type != "tool" {
			return nativeEvent{}, false
		}
		e.kind = "action"
		e.item = p.PartData.ID
		e.text = boundedText(p.PartData.Tool, 256) + ": " + boundedText(p.PartData.State.Status, 64) + "\n" + boundedText(p.PartData.State.Title, 4096)
	case "permission.asked":
		if !turn.messages[p.Tool.Message] || !nativeID(p.ID) {
			e.kind, e.outcome, e.text = "error", "unsupported", "An uncorrelated provider permission request is waiting. It was not approved. Stop and inspect the native session."
			return e, true
		}
		e.kind = "approval"
		e.text = boundedText(p.Permission, 256)
		e.denyOnly = len(p.Permission) > 256 || len(p.Patterns) > 16 || len(p.Metadata) > 16<<10
		for i, pattern := range p.Patterns {
			if i == 16 {
				e.text += "\nAdditional targets omitted; decline and inspect the native session."
				break
			}
			if len(pattern) > 1024 {
				e.denyOnly = true
			}
			e.text += "\n" + boundedText(pattern, 1024)
		}
		e.text += "\nAction details: " + boundedText(string(p.Metadata), 16<<10)
		e.approval, _ = json.Marshal(map[string]string{"id": p.ID, "session": p.Session})
	case "question.asked":
		e.kind, e.outcome, e.text = "error", "unsupported", "The provider is waiting for an interactive question that this adapter cannot answer. Stop the turn and supply the missing guidance in a new message, or use the native application."
	case "session.error":
		e.kind = "completed"
		e.outcome = "failed"
		if p.Error.Name == "MessageAbortedError" {
			e.outcome = "interrupted"
		}
		delete(r.turns, p.Session)
	case "session.idle", "session.status":
		if !turn.seen || (wire.Type == "session.status" && p.Status.Type != "idle") {
			return nativeEvent{}, false
		}
		e.kind = "completed"
		e.outcome = "completed"
		delete(r.turns, p.Session)
	default:
		return nativeEvent{}, false
	}
	return e, true
}
