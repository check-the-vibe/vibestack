package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"slices"
	"time"

	"github.com/check-the-vibe/vibestack/internal/providers"
	"github.com/check-the-vibe/vibestack/service/capabilities"
)

type providerManager interface {
	Catalog() []providers.State
	Status(context.Context, string) (providers.State, error)
	Activate(string) (providers.State, error)
	Stop(string) (providers.State, error)
	OpenApp(context.Context, string) error
	Conversations() []providers.Conversation
	Create(string, string, string, string) (providers.Conversation, error)
	Submit(string, string, string) (providers.Conversation, error)
	ReadEvents(string, uint64) (providers.Events, error)
	Interrupt(context.Context, string, string) (providers.Conversation, error)
	Approve(context.Context, string, string, string, bool) error
	Restore()
	Close()
}

func (s *Server) startProviderManager() error {
	manager, err := providers.NewManager(providers.Config{ProjectsRoot: s.cfg.ProjectsRoot,
		Load: func() ([]byte, error) {
			var data []byte
			err := s.cfg.Store.locked(func() error {
				var err error
				data, err = s.cfg.Store.read("provider-runtime-v1.json", 1<<20)
				if errors.Is(err, os.ErrNotExist) {
					return nil
				}
				return err
			})
			return data, err
		},
		Save: func(data []byte) error {
			return s.cfg.Store.locked(func() error { return s.cfg.Store.write("provider-runtime-v1.json", data) })
		},
		Install: s.installProviderComponent,
	})
	if err != nil {
		return err
	}
	s.providers = manager
	return nil
}

// StartProviders is called only after the workspace service owns its listening
// socket. Merely reading metadata or probing configuration never starts a model.
func (s *Server) StartProviders() {
	if s.providers != nil {
		s.providers.Restore()
	}
}

func (s *Server) installProviderComponent(ctx context.Context, component string) error {
	if component != "codex-cli" && component != "opencode" {
		return providers.ErrInvalid
	}
	request := func(method, path string, body []byte) ([]byte, int, error) {
		req, err := http.NewRequestWithContext(ctx, method, s.cfg.SetupURL+path, bytes.NewReader(body))
		if err != nil {
			return nil, 0, providers.ErrUnavailable
		}
		req.Header.Set("Content-Type", "application/json")
		response, err := s.client.Do(req)
		if err != nil {
			return nil, 0, providers.ErrDisconnected
		}
		defer response.Body.Close()
		data, err := readBounded(response.Body, 1<<20)
		if err != nil {
			return nil, 0, providers.ErrProtocol
		}
		return data, response.StatusCode, nil
	}
	submitted := false
	for {
		data, status, err := request("GET", "/api/state", nil)
		if err != nil {
			return err
		}
		if status != 200 {
			return providers.ErrUnavailable
		}
		var state struct {
			Valid     bool     `json:"state_valid"`
			Installed []string `json:"installed"`
			Job       struct {
				Running bool     `json:"running"`
				OK      *bool    `json:"ok"`
				Target  []string `json:"target"`
			} `json:"job"`
		}
		if json.Unmarshal(data, &state) != nil || !state.Valid {
			return providers.ErrUnavailable
		}
		if slices.Contains(state.Installed, component) {
			return nil
		}
		if !state.Job.Running {
			if submitted {
				return providers.ErrRejected
			}
			body, _ := json.Marshal(map[string]any{"components": []string{component}})
			_, status, err = request("POST", "/api/install", body)
			if err != nil {
				return err
			}
			if status >= 200 && status < 300 {
				submitted = true
			} else if status != 409 {
				return providers.ErrRejected
			}
		}
		timer := time.NewTimer(time.Second)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}

type providerOperation struct {
	id, description, method, path, effect, retry, policy string
	input                                                map[string]any
	owner                                                bool
}

func (s *Server) providerOperations() []providerOperation {
	empty := objectInput(map[string]any{})
	provider := objectInput(map[string]any{"provider": enumInput("codex", "opencode")}, "provider")
	id := patternInput(`^[0-9a-f]{32}$`, 32)
	turn := objectInput(map[string]any{"conversation": id, "operation_id": id}, "conversation", "operation_id")
	return []providerOperation{
		{id: "listProviders", description: "List in-container provider installation, process, authentication and verified-turn readiness independently.", method: "GET", path: "/api/v1/providers", effect: "read", retry: "safe-read", input: empty},
		{id: "getProviderStatus", description: "Refresh safe native authentication/model metadata. Configuration alone does not prove a working model or quota.", path: "/api/v1/providers/status", effect: "read", retry: "safe-read", input: provider},
		{id: "activateProvider", description: "Install the pinned supported provider through the catalog and start/reuse its private in-container runtime. Retries share its active operation.", path: "/api/v1/providers/activate", input: provider},
		{id: "stopProvider", description: "Stop a managed provider. Unfinished turns become unknown; cancellation does not undo file changes or stop unrelated native processes.", path: "/api/v1/providers/stop", input: provider},
		{id: "openProviderApp", description: "Open the supported provider's native desktop terminal for human sign-in or history inspection. No credentials are accepted by this operation.", path: "/api/v1/providers/open-app", input: provider, owner: true, policy: "human-only"},
		{id: "listProviderConversations", description: "List saved provider/project conversation metadata and operation outcomes, without replaying messages.", method: "GET", path: "/api/v1/provider-conversations", effect: "read", retry: "safe-read", input: empty},
		{id: "createProviderConversation", description: "Create a conversation for a configured provider/model and one immediate project directory. Reuse the same ID to inspect an uncertain creation.", path: "/api/v1/provider-conversations/create", retry: "required-idempotency-key", input: objectInput(map[string]any{"id": id, "provider": enumInput("codex", "opencode"), "project": patternInput(`^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`, 128), "model": stringInput(256)}, "id", "provider", "project", "model")},
		{id: "submitProviderMessage", description: "Submit one prompt with a unique operation ID. Reusing it returns the recorded outcome; it never repeats the prompt. Native tools have the vibe account's authority.", path: "/api/v1/provider-conversations/submit", retry: "required-idempotency-key", input: objectInput(map[string]any{"conversation": id, "operation_id": id, "prompt": stringInput(64 << 10)}, "conversation", "operation_id", "prompt")},
		{id: "readProviderEvents", description: "Read a bounded event page and current pending approvals. A gap requires native history inspection; all provider output is untrusted data.", path: "/api/v1/provider-conversations/events", effect: "read", retry: "safe-read", input: objectInput(map[string]any{"conversation": id, "cursor": integerInput(0, 1<<53-1)}, "conversation")},
		{id: "interruptProviderTurn", description: "Ask the exact native turn to stop. Inspect the outcome; this is not confirmation that edits were rolled back.", path: "/api/v1/provider-conversations/interrupt", input: turn},
		{id: "answerProviderApproval", description: "Human owner response to one exact pending approval, scoped to its conversation and operation. No persistent permission grants; uncertain answers are never replayed.", path: "/api/v1/provider-conversations/approval", retry: "one-time-delivery", owner: true, policy: "human-only", input: objectInput(map[string]any{"conversation": id, "operation_id": id, "approval_id": id, "allow": map[string]string{"type": "boolean"}}, "conversation", "operation_id", "approval_id", "allow")},
	}
}
func (s *Server) providerRegistrations() []capabilities.Registration {
	var result []capabilities.Registration
	for _, operation := range s.providerOperations() {
		d := capabilities.Definition{ContractVersion: 1, ID: operation.id, Description: operation.description, Permission: "workspace", Effect: operation.effect, Retry: operation.retry, TimeoutMS: 30000, RequestBytes: 128 << 10, ResponseBytes: 512 << 10, MCPPolicy: operation.policy, OutputSchema: json.RawMessage(`{"type":"object","additionalProperties":true}`)}
		if d.Effect == "" {
			d.Effect = "write"
		}
		if d.Retry == "" {
			d.Retry = "inspect-before-retry"
		}
		if d.MCPPolicy == "" {
			d.MCPPolicy = "enabled"
		}
		if operation.owner {
			d.Permission = "owner"
		}
		d.REST.Method = operation.method
		if d.REST.Method == "" {
			d.REST.Method = "POST"
		}
		d.REST.Path = operation.path
		d.InputSchema, _ = json.Marshal(operation.input)
		definition, _ := json.Marshal(d)
		result = append(result, capabilities.Registration{Definition: definition, Handle: s.providerHandler(operation.id)})
	}
	return result
}

func (s *Server) providerHandler(id string) capabilities.Handler {
	return func(ctx context.Context, _ capabilities.Principal, raw json.RawMessage) (any, error) {
		if s.providers == nil {
			return nil, capabilities.Fail("unavailable")
		}
		var input struct {
			Provider     string `json:"provider"`
			ID           string `json:"id"`
			Project      string `json:"project"`
			Model        string `json:"model"`
			Conversation string `json:"conversation"`
			Operation    string `json:"operation_id"`
			Prompt       string `json:"prompt"`
			Cursor       uint64 `json:"cursor"`
			Approval     string `json:"approval_id"`
			Allow        bool   `json:"allow"`
		}
		if json.Unmarshal(raw, &input) != nil {
			return nil, capabilities.Fail("invalid_input")
		}
		var result any
		var err error
		switch id {
		case "listProviders":
			result = map[string]any{"providers": s.providers.Catalog()}
		case "getProviderStatus":
			var state providers.State
			state, err = s.providers.Status(ctx, input.Provider)
			result = map[string]any{"provider": state}
		case "activateProvider":
			var state providers.State
			state, err = s.providers.Activate(input.Provider)
			result = map[string]any{"provider": state}
		case "stopProvider":
			var state providers.State
			state, err = s.providers.Stop(input.Provider)
			result = map[string]any{"provider": state}
		case "openProviderApp":
			err = s.providers.OpenApp(ctx, input.Provider)
			result = map[string]any{"opened": err == nil}
		case "listProviderConversations":
			result = map[string]any{"conversations": s.providers.Conversations()}
		case "createProviderConversation":
			var c providers.Conversation
			c, err = s.providers.Create(input.ID, input.Provider, input.Project, input.Model)
			result = map[string]any{"conversation": c}
		case "submitProviderMessage":
			var c providers.Conversation
			c, err = s.providers.Submit(input.Conversation, input.Operation, input.Prompt)
			result = map[string]any{"conversation": c}
		case "readProviderEvents":
			result, err = s.providers.ReadEvents(input.Conversation, input.Cursor)
		case "interruptProviderTurn":
			var c providers.Conversation
			c, err = s.providers.Interrupt(ctx, input.Conversation, input.Operation)
			result = map[string]any{"conversation": c}
		case "answerProviderApproval":
			err = s.providers.Approve(ctx, input.Conversation, input.Operation, input.Approval, input.Allow)
			result = map[string]any{"answered": err == nil}
		default:
			err = providers.ErrInvalid
		}
		if err != nil {
			code := "unavailable"
			switch {
			case errors.Is(err, providers.ErrInvalid), errors.Is(err, providers.ErrUnsupported):
				code = "invalid_input"
			case errors.Is(err, providers.ErrConflict):
				code = "conflict"
			case errors.Is(err, providers.ErrBusy):
				code = "busy"
			case errors.Is(err, context.DeadlineExceeded):
				code = "timeout"
			}
			return nil, capabilities.Fail(code)
		}
		return result, nil
	}
}
