package providers

import (
	"context"
	"encoding/json"
	"strings"
	"sync"
	"time"
)

type codexRuntime struct {
	rpc     *rpcConn
	process *childProcess
	events  chan nativeEvent
	once    sync.Once
}

func startCodex(ctx context.Context, binary, dir string) (agentRuntime, error) {
	p, in, out, err := startChild(binary, []string{"app-server", "--listen", "stdio://"}, dir, nil, true)
	if err != nil {
		return nil, err
	}
	c := &codexRuntime{rpc: newRPC(in, out), process: p, events: make(chan nativeEvent, 64)}
	_, err = c.rpc.call(ctx, "initialize", map[string]any{"clientInfo": map[string]string{"name": "vibestack", "version": "1"}, "capabilities": map[string]bool{"experimentalApi": false}})
	if err == nil {
		err = c.rpc.notify(ctx, "initialized", map[string]any{})
	}
	if err != nil {
		c.Close()
		return nil, err
	}
	go c.readEvents()
	return c, nil
}

func (c *codexRuntime) Close()                     { c.once.Do(func() { c.rpc.stop(ErrDisconnected); c.process.close() }) }
func (c *codexRuntime) Events() <-chan nativeEvent { return c.events }

func (c *codexRuntime) Status(ctx context.Context) (RuntimeStatus, error) {
	result := RuntimeStatus{Authentication: "needs_sign_in", Models: []Model{}}
	raw, err := c.rpc.call(ctx, "account/read", map[string]bool{"refreshToken": false})
	if err != nil {
		return result, err
	}
	var account struct {
		Requires bool `json:"requiresOpenaiAuth"`
		Account  *struct {
			Type string `json:"type"`
		} `json:"account"`
	}
	if json.Unmarshal(raw, &account) != nil {
		return result, ErrProtocol
	}
	if account.Account != nil {
		result.Authentication = "configured"
	} else if !account.Requires {
		result.Authentication = "not_required"
	}
	if result.Authentication == "needs_sign_in" {
		return result, nil
	}
	raw, err = c.rpc.call(ctx, "model/list", map[string]any{"limit": 50, "includeHidden": false})
	if err != nil {
		return result, err
	}
	var models struct {
		Data []struct {
			Model   string `json:"model"`
			Name    string `json:"displayName"`
			Default bool   `json:"isDefault"`
			Hidden  bool   `json:"hidden"`
		} `json:"data"`
	}
	if json.Unmarshal(raw, &models) != nil || len(models.Data) > 50 {
		return result, ErrProtocol
	}
	for _, m := range models.Data {
		if !m.Hidden && nativeID(m.Model) {
			result.Models = append(result.Models, Model{ID: m.Model, Name: boundedText(m.Name, 160), Default: m.Default})
		}
	}
	return result, nil
}

func codexThreadOptions(project, model string) map[string]any {
	return map[string]any{"cwd": project, "model": model, "approvalPolicy": "on-request", "approvalsReviewer": "user", "sandbox": "workspace-write"}
}
func (c *codexRuntime) Create(ctx context.Context, project, model string) (string, error) {
	raw, err := c.rpc.call(ctx, "thread/start", codexThreadOptions(project, model))
	if err != nil {
		return "", err
	}
	var value struct {
		Thread struct {
			ID string `json:"id"`
		} `json:"thread"`
	}
	if json.Unmarshal(raw, &value) != nil || !nativeID(value.Thread.ID) {
		return "", ErrProtocol
	}
	return value.Thread.ID, nil
}
func (c *codexRuntime) Resume(ctx context.Context, session, project, model string) error {
	params := codexThreadOptions(project, model)
	params["threadId"] = session
	params["excludeTurns"] = true
	raw, err := c.rpc.call(ctx, "thread/resume", params)
	if err != nil {
		return err
	}
	var reply struct {
		Thread struct {
			ID     string `json:"id"`
			Status struct {
				Type string `json:"type"`
			} `json:"status"`
		} `json:"thread"`
	}
	if json.Unmarshal(raw, &reply) != nil || reply.Thread.ID != session {
		return ErrProtocol
	}
	if reply.Thread.Status.Type != "idle" {
		return ErrConflict
	}
	return nil
}
func (c *codexRuntime) Submit(ctx context.Context, session, model, prompt, operation string) (string, error) {
	raw, err := c.rpc.call(ctx, "turn/start", map[string]any{"threadId": session, "input": []any{map[string]any{"type": "text", "text": prompt}}, "clientUserMessageId": operation})
	if err != nil {
		return "", err
	}
	var value struct {
		Turn struct {
			ID string `json:"id"`
		} `json:"turn"`
	}
	if json.Unmarshal(raw, &value) != nil || !nativeID(value.Turn.ID) {
		return "", ErrProtocol
	}
	return value.Turn.ID, nil
}
func (c *codexRuntime) Interrupt(ctx context.Context, session, turn string) error {
	if !nativeID(turn) {
		return ErrConflict
	}
	_, err := c.rpc.call(ctx, "turn/interrupt", map[string]string{"threadId": session, "turnId": turn})
	return err
}
func (c *codexRuntime) Approve(ctx context.Context, id json.RawMessage, allow bool) error {
	decision := "decline"
	if allow {
		decision = "accept"
	}
	return c.rpc.respond(ctx, id, map[string]string{"decision": decision})
}

func (c *codexRuntime) readEvents() {
	defer close(c.events)
	// A file approval can be allowed only with the complete, matching item
	// preview. Missing/oversized previews still permit a human decline.
	previews := map[string]string{}
	for wire := range c.rpc.events {
		event, ok := codexEvent(wire)
		if !ok {
			if len(wire.ID) != 0 {
				ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
				c.rpc.rejectUnsupported(ctx, wire.ID)
				cancel()
				var scope struct {
					Thread string `json:"threadId"`
					Turn   string `json:"turnId"`
				}
				if json.Unmarshal(wire.Params, &scope) == nil && nativeID(scope.Thread) && nativeID(scope.Turn) {
					event = nativeEvent{session: scope.Thread, turn: scope.Turn, kind: "error", outcome: "unsupported", text: "The provider requested an unsupported approval or interaction. It was not approved; inspect the native session or stop the turn."}
					ok = true
				}
			}
			if !ok {
				continue
			}
		}
		key := event.session + "\x00" + event.turn + "\x00" + event.item
		if event.filePreview && len(previews) < 32 {
			previews[key] = event.text
		}
		if wire.Method == "item/fileChange/requestApproval" && event.kind == "approval" {
			if preview, exists := previews[key]; exists {
				event.text = preview + "\n" + event.text
				event.denyOnly = false
			}
			delete(previews, key)
		}
		if event.kind == "completed" {
			for key := range previews {
				if strings.HasPrefix(key, event.session+"\x00"+event.turn+"\x00") {
					delete(previews, key)
				}
			}
		}
		select {
		case c.events <- event:
		case <-c.rpc.done:
			return
		default:
			c.rpc.stop(ErrProtocol)
			return
		}
	}
}

func codexEvent(wire wireEvent) (nativeEvent, bool) {
	var p struct {
		Thread      string          `json:"threadId"`
		TurnID      string          `json:"turnId"`
		ItemID      string          `json:"itemId"`
		Delta       string          `json:"delta"`
		Command     string          `json:"command"`
		CWD         string          `json:"cwd"`
		Reason      string          `json:"reason"`
		Kind        string          `json:"kind"`
		Environment *string         `json:"environmentId"`
		Network     json.RawMessage `json:"networkApprovalContext"`
		GrantRoot   *string         `json:"grantRoot"`
		Turn        struct {
			ID     string `json:"id"`
			Status string `json:"status"`
		} `json:"turn"`
		Item struct {
			ID      string `json:"id"`
			Type    string `json:"type"`
			Text    string `json:"text"`
			Command string `json:"command"`
			Changes []struct {
				Path string `json:"path"`
				Diff string `json:"diff"`
			} `json:"changes"`
		} `json:"item"`
	}
	if json.Unmarshal(wire.Params, &p) != nil || !nativeID(p.Thread) {
		return nativeEvent{}, false
	}
	e := nativeEvent{session: p.Thread, turn: p.TurnID, item: p.ItemID}
	if len(wire.ID) > 0 {
		// Only one-action decisions are supported. No remembered grants,
		// permission amendments, or unknown requests are approved implicitly.
		if !nativeID(p.TurnID) {
			return nativeEvent{}, false
		}
		switch wire.Method {
		case "item/commandExecution/requestApproval":
			if p.Command == "" || len(p.Command) > 12<<10 || (p.Kind != "" && p.Kind != "command") || p.Environment != nil {
				return nativeEvent{}, false
			}
			e.text = "Command: " + p.Command + "\nDirectory: " + boundedText(p.CWD, 4096) + "\nReason: " + boundedText(p.Reason, 4096)
			e.denyOnly = p.CWD == "" || len(p.CWD) > 4096 || len(p.Reason) > 4096
			if len(p.Network) > 0 && string(p.Network) != "null" {
				e.text += "\nNetwork request: " + boundedText(string(p.Network), 4096)
				e.denyOnly = e.denyOnly || len(p.Network) > 4096
			}
		case "item/fileChange/requestApproval":
			if p.GrantRoot != nil {
				return nativeEvent{}, false
			}
			e.text = "File change request. " + boundedText(p.Reason, 4096)
			e.denyOnly = true
		default:
			return nativeEvent{}, false
		}
		e.kind = "approval"
		e.approval = append(json.RawMessage(nil), wire.ID...)
		return e, true
	}
	switch wire.Method {
	case "item/agentMessage/delta":
		e.kind = "text_delta"
		e.text = boundedText(p.Delta, 32<<10)
	case "item/started", "item/completed":
		e.kind = "action"
		e.item = p.Item.ID
		switch p.Item.Type {
		case "commandExecution":
			e.text = boundedText(p.Item.Command, 16<<10)
		case "fileChange":
			e.filePreview = len(p.Item.Changes) > 0 && len(p.Item.Changes) <= 8
			for i, change := range p.Item.Changes {
				if i == 8 {
					e.text += "\nAdditional changes omitted; inspect the native session."
					break
				}
				if len(change.Path) > 1024 || len(change.Diff) > 4<<10 {
					e.filePreview = false
				}
				e.text += boundedText(change.Path, 1024) + "\n" + boundedText(change.Diff, 4<<10) + "\n"
			}
		default:
			return nativeEvent{}, false
		}
	case "turn/started":
		e.kind = "running"
		e.turn = p.Turn.ID
	case "turn/completed":
		e.kind = "completed"
		e.turn = p.Turn.ID
		switch p.Turn.Status {
		case "completed":
			e.outcome = "completed"
		case "interrupted":
			e.outcome = "interrupted"
		default:
			e.outcome = "failed"
		}
	default:
		return nativeEvent{}, false
	}
	return e, true
}
