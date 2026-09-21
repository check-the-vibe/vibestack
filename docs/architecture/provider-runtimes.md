# Provider runtime implementation decisions

VST-014 working design, 21 September 2026. This document does not claim that
provider activation, chat or login is implemented. Product requirements and
acceptance remain in [SPEC-004](../../.context/specifications/SPEC-004-chat-agent-interface.md).

## Integration boundary

Use the existing Go workspace service and capability registry. Add reviewed
provider operations there, so REST, generic CLI, browser requests and allowed
MCP tools share grants, schemas, limits and audit metadata. Do not introduce
another externally accessible service or an independent model loop.

The provider manager runs as `vibe`. It launches fixed, installed executables
inside VibeStack and retains one managed process per selected provider. Install
through the existing setup catalog API, which already records selections and
restores packages. Caller-supplied executable paths, installer URLs, arguments,
environment maps and backend origins are not accepted.

Track installation, activation, process, authentication and successful-turn
readiness independently. An activation operation survives client disconnects;
concurrent activation reuses it. A process or health endpoint alone must never
be labelled ready to chat. Stop is explicit and reports active turn outcomes.

## Version and transport checks

| Runtime | Existing catalog pin | Required probe before support is claimed |
| --- | --- | --- |
| Codex | `@openai/codex` 0.153.4 | Generate this executable's schema, complete stdio initialization, inspect authentication, then exercise a streamed turn, approval and interrupt |
| OpenCode | `opencode-ai` 1.18.29 | Inspect its actual OpenAPI and event schemas; verify authenticated loopback health, model configuration, a streamed session, approval and abort |

Codex documents JSONL over stdio, an initialization exchange, version-specific
schema generation, account methods, thread/turn methods and server-originated
approval requests. Prefer this private transport; verify every field against the
pinned binary rather than relying on the current documentation alone.
[Official Codex App Server reference](https://learn.chatgpt.com/docs/app-server).

OpenCode's v1 server documents loopback HTTP, Basic authentication, health,
session/message operations and an event stream. Keep its private authentication
within the manager and child runtime; only VibeStack's authenticated origin is
forwarded. Do not combine v2 endpoints or permission fields with this v1 pin.
[Official OpenCode server reference](https://dev.opencode.ai/docs/server/),
[v1 permission reference](https://dev.opencode.ai/docs/permissions/).

These are implementation choices inferred from the interfaces, not a claim of
tested compatibility. The existing installers remain pinned until actual binary
evidence justifies a deliberate upgrade.

## Conversation and approval ownership

Bind each VibeStack conversation to one provider, native session and project.
Use an explicit operation identifier for message submission; a retry retrieves
its recorded outcome rather than submitting the prompt again. Losing a reply
means an uncertain result until the native provider reports what happened.
Restarting a process never repeats the last turn.

Keep bounded event buffers for progressive text, actions, errors and completion.
Expose them through the same registered operation layer with a cursor, so the
UI does not gain a second authentication path. When a cursor is no longer
available, report that gap and use native session history where supported.
Never manufacture missed events or claim that cancellation rolled back edits.

An approval is a pending native request associated with its exact conversation,
turn and action. Only the human approval operation can answer it. Exclude this
operation and provider secret-entry operations from MCP. Ignore approval-like
text in model output, and reject stale, duplicated or cross-conversation answers.
Unknown native approval kinds remain blocked rather than being auto-approved.

## Defaults for the first development pass

- Use the provider's own supported human sign-in. Do not copy local-host accounts,
  credentials or environment into the container. Show account/model readiness
  without returning tokens or raw provider configuration.
- Select models from the configured runtime. Preserve provider/account usage
  limits and report missing quota or model access; activation buys no credits
  and creates no account. A real verification turn requires the user's sign-in.
- Persist only necessary conversation identifiers and operation outcomes in
  protected workspace state; native runtimes own their histories and auth stores.
  Do not duplicate prompts or events into shared service logs. Closing the panel
  retains its conversation; changing providers creates a new conversation.
- For VST-015, start with a bottom-right icon, a right-side desktop panel and a
  small-screen sheet. Keep the desktop canvas interactive outside the panel.
  These reversible layout defaults need browser and accessibility verification.

## Verification order

1. Exact-version schema/handshake and absent-login probes, with no model call.
2. Unit tests for lifecycle races, bounded transport, state persistence, scoped
   approvals, crash recovery, unknown outcomes and strict input denial.
3. Registered-operation tests through real REST, CLI, MCP and browser auth.
4. Clean disposable image installs and actual native runtimes. Fakes are useful
   for failure injection but do not satisfy real-provider acceptance.
5. Human login, one harmless streamed task per provider, approval and stop;
   then restart/upgrade checks with saved provider selections and state.
