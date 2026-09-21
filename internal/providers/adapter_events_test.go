package providers

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
)

func codexWire(method string, request bool, params map[string]any) wireEvent {
	raw, _ := json.Marshal(params)
	wire := wireEvent{Method: method, Params: raw}
	if request {
		wire.ID = json.RawMessage(`"fixture-approval"`)
	}
	return wire
}

func TestCodexApprovalKeepsExactScopeAndRejectsPersistentOrUnreviewableGrants(t *testing.T) {
	base := map[string]any{"threadId": "session-a", "turnId": "turn-a", "itemId": "item-a", "command": "printf fixture", "cwd": "/projects/source"}
	event, ok := codexEvent(codexWire("item/commandExecution/requestApproval", true, base))
	if !ok || event.kind != "approval" || event.turn != "turn-a" || event.denyOnly || !strings.Contains(event.text, "printf fixture") {
		t.Fatal("lost reviewed command or turn")
	}
	base["cwd"] = strings.Repeat("x", 4097)
	event, ok = codexEvent(codexWire("item/commandExecution/requestApproval", true, base))
	if !ok || !event.denyOnly {
		t.Fatal("incomplete command scope could be allowed")
	}
	base["kind"] = "stdin"
	if _, ok = codexEvent(codexWire("item/commandExecution/requestApproval", true, base)); ok {
		t.Fatal("unsupported stdin action accepted as a command")
	}
	base["grantRoot"] = "/projects"
	if _, ok = codexEvent(codexWire("item/fileChange/requestApproval", true, base)); ok {
		t.Fatal("persistent file grant was accepted")
	}
	delete(base, "grantRoot")
	event, ok = codexEvent(codexWire("item/fileChange/requestApproval", true, base))
	if !ok || !event.denyOnly {
		t.Fatal("file approval without its preview could be allowed")
	}
}

func TestCodexResumeRefusesAnotherActiveTurn(t *testing.T) {
	for _, status := range []string{"idle", "active", "systemError", "notLoaded", "unknown"} {
		t.Run(status, func(t *testing.T) {
			conn, in, out := rpcFixture(t)
			go func() {
				line, _ := bufio.NewReader(in).ReadBytes('\n')
				var request struct{ ID uint64 }
				json.Unmarshal(line, &request)
				fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"thread\":{\"id\":\"session-a\",\"status\":{\"type\":%q}}}}\n", request.ID, status)
			}()
			err := (&codexRuntime{rpc: conn}).Resume(deadline(t), "session-a", "/projects/source", "fixture")
			if (status == "idle" && err != nil) || (status != "idle" && !errors.Is(err, ErrConflict)) {
				t.Fatal("thread status was not respected")
			}
		})
	}
}

func TestOpenCodeEventsRequireThisTurnsAssistantAndSurfaceUnsupportedQuestions(t *testing.T) {
	r := &openCodeRuntime{turns: map[string]*openCodeTurn{"session-a": {id: "msg-current", messages: map[string]bool{}}}}
	decode := func(kind string, properties map[string]any) (nativeEvent, bool) {
		properties["sessionID"] = "session-a"
		raw, _ := json.Marshal(map[string]any{"payload": map[string]any{"type": kind, "properties": properties}})
		return r.decodeEvent(raw)
	}
	if _, ok := decode("session.idle", map[string]any{}); ok {
		t.Fatal("initial idle fabricated a completion")
	}
	decode("message.updated", map[string]any{"info": map[string]string{"id": "old-reply", "role": "assistant", "parentID": "msg-old"}})
	if _, ok := decode("message.part.delta", map[string]any{"messageID": "old-reply", "field": "text", "delta": "old text"}); ok {
		t.Fatal("old message crossed into this turn")
	}
	decode("message.updated", map[string]any{"info": map[string]string{"id": "current-reply", "role": "assistant", "parentID": "msg-current"}})
	event, ok := decode("message.part.delta", map[string]any{"messageID": "current-reply", "field": "text", "delta": "reply"})
	if !ok || event.text != "reply" || event.turn != "msg-current" {
		t.Fatal("current assistant delta missing")
	}
	event, ok = decode("permission.asked", map[string]any{"id": "per-fixture", "permission": "bash", "patterns": []string{"echo fixture"}, "metadata": map[string]string{"command": "echo fixture"}, "tool": map[string]string{"messageID": "current-reply"}})
	if !ok || event.denyOnly || !strings.Contains(event.text, "echo fixture") || event.kind != "approval" {
		t.Fatal("full native action not reviewable")
	}
	event, ok = decode("permission.asked", map[string]any{"id": "per-large", "permission": "bash", "patterns": []string{strings.Repeat("x", 2048)}, "tool": map[string]string{"messageID": "current-reply"}})
	if !ok || !event.denyOnly {
		t.Fatal("truncated action scope could be approved")
	}
	event, ok = decode("question.asked", map[string]any{"id": "que-fixture"})
	if !ok || event.outcome != "unsupported" {
		t.Fatal("native interactive question disappeared")
	}
	event, ok = decode("session.error", map[string]any{"error": map[string]string{"name": "MessageAbortedError"}})
	if !ok || event.outcome != "interrupted" || r.turns["session-a"] != nil {
		t.Fatal("abort fabricated successful completion")
	}
}
