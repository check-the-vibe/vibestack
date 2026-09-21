# SPEC-004 — Chat agent interface replacing existing UI

- State: draft
- Initiative: [Agent platform](../initiatives/agent-platform.md)
- Owner: project owner for product decisions; Codex for this drafting pass
- Updated: 2026-09-21
- Decision authority: user's request to specify these four features; recommendations below are proposed, not approved implementation choices
- Supersedes: none; refines the [earlier access proposal](../../docs/architecture/agent-access-redesign.md)
- Planning ticket: [VST-004](../tickets/VST-004.md)

This is a target contract, not a claim of shipped behavior. Unresolved decisions
keep the specification in draft; no runtime changes are part of this pass.

## Outcome and user journeys

The VibeStack web experience becomes a conversation with an agent connected to
its services. A user selects a workspace conversationally, asks for work, sees
what the agent is doing, reviews results and can stop or correct it. The existing
Desktop/Terminal/Editor/Apps/Settings navigation is removed from the final product
UI. Source editing remains available through the outer Codespaces editor.

Example: “In this repository, run the tests and explain the failures.” The chat
shows the selected workspace, submits an authorized job, displays progress and
returns evidence-linked results. “Install a browser” uses the same app service
as other clients, showing status and any human-only sign-in handoff. A fluent
answer without execution evidence must not be presented as completed work.

## Current behavior and evidence

`desktop/`, `setup/` and `nginx.conf` implement the current shell, onboarding,
settings, apps, ttyd, noVNC and editor routes. Code-server is a required image
service today; Dockerfile, Supervisor, health checks and browser tests depend on
it. There is no implemented chat backend/provider integration in this scope.
Removing the editor button alone would not remove the service or its costs.

## Scope and exclusions

Replace all existing product UI navigation and control panels with one chat
experience. Provide only the controls needed for a usable conversation: input,
conversation history, target identity, run state, stop, results and contextual
authorization/secure-input handoffs. These are part of chat, not retained legacy
panels. Preserve underlying desktop execution/screenshot/app capabilities where
tools need them; decide removal of unused services separately in migration.
Exclude a new IDE, a public unauthenticated shell, autonomous self-granting agents,
and arbitrary multi-agent delegation from the first release.

## Contract

Recommend a server-side chat orchestrator using the same authorized operation
layer as REST/MCP. Do not make the browser hold model-provider secrets or give the
model direct Docker access. Internal invocation need not round-trip through MCP,
but must use the same target/grant checks and operation semantics. A provider
adapter is proposed; provider/model, key ownership and cost policy remain open.

A conversation is owner-scoped and binds an explicit workspace. Persist message,
run and tool-call IDs, sequence numbers, target, minimal result references and
approval outcomes. Switching targets starts a clearly identified new context;
already-running work retains its original target. Untrusted file/tool text cannot
change the principal, target or allowed tools. Agent instructions and service
authorization are enforced separately.

Proposed lifecycle: queued → running → awaiting_user (when needed) → completed,
failed or cancelled. Each tool call records pending/running/confirmed outcome;
unknown remote outcomes remain unknown while reconciliation runs. Stream events
with stable IDs; reconnect reloads state without resubmitting a job. “Stop” stops
future model/tool dispatch, asks cancellable jobs to stop, and reports any job
still running. Per-run time, output, tool-call and cost budgets are configured
and visible; do not invent a usage price for a provider not selected yet.

Default to existing user intent and configured grants for routine authorized
work. Require explicit human action for irreversible changes, new external
sharing/access and new credentials as appropriate to the operation policy. Bind
an approval to exact operation, arguments, target and expiry; changed input needs
a new approval. Reject a model's forged approval claim. Do not require repetitive
confirmation for every harmless read or already-authorized action.

Secrets are never ordinary chat messages or model tool arguments. Login uses the
identity provider; Linux passwords/provider credentials use a secure human-only
input surface launched from the conversation, submitted directly to the proper
credential handler. Its values bypass model context, history, traces and logs.
If “no UI elements” is interpreted as text-only with no secure handoff, credential
setup must happen externally; it must not fall back to asking for secrets in chat.

Render output as untrusted text/escaped Markdown; artifact downloads and image
previews must be owner-authorized. Show the machine/workspace, action summary,
progress, exit/result status and evidence links in conversation. Distinguish
agent suggestions from executed actions. Provide keyboard navigation, labelled
controls, accessible stream announcements and responsive desktop/tablet layout.
When the model provider is unavailable, show a truthful error and access to
existing conversation/job state; do not restore the legacy UI as a hidden fallback.

## Design decisions and alternatives

Recommend chat as the only product shell, with contextual result/approval cards
and secure handoffs. This fulfills the interface replacement while retaining
observability and human control. A plain text-only stream would make safe secret
entry and structured action review difficult. Prefer backend tool dispatch for
consistent policy and resumable runs; browser-direct provider calls would expose
credentials and fragment authorization. Framework choice follows a small UI
prototype and accessibility evaluation rather than introducing a library now.

## Failure, migration and operations

Inventory every current user action: onboarding, app selection/install, target
selection, agent connection/revocation, logs, restart, password changes and work
inspection. Map each to chat, a secure handoff or an explicitly retired behavior
before removing routes. Preserve `/data`, `/projects`, existing files, saved
applications and credential state across upgrades and rollback.

Stage the replacement behind a development rollout switch while verifying it.
The final default has no legacy navigation, panels, or embedded editor/terminal
frames. Retired browser pages should return a documented authenticated migration
response (or safe redirect to chat); do not redirect API clients or accept legacy
mutations anonymously. Remove code-server/ttyd assets, health dependencies and
catalog/docs references only after the capability/retention decision; keep the
outer Codespaces editor. Retain only desktop services needed by automation.
A rollback image must reopen the same persistent data without destructive schema
changes. Do not claim route removal while leaving old unauthenticated controls
reachable. Keep canonical REST/docs/installer endpoints supported.

Conversation retention, deletion, model-provider data handling and log redaction
need explicit policy before real content is sent. Persisted history must be
owner-isolated. Do not automatically forward all repository files to a provider;
only selected tool results needed for the authorized task enter model context.

## Acceptance criteria

- AC-01: A first-time and returning user can select a workspace, run a command, inspect results and install a supported app entirely through chat/human handoffs. Verify browser-to-service-to-result journeys.
- AC-02: The final default has no old navigation/panels/embedded editor or terminal; every prior required journey has a tested replacement or declared retirement. Verify legacy route inventory and desktop/tablet browsers.
- AC-03: Refresh, network loss and double submission resume the same run without duplicate effects; stop accurately reports jobs it could and could not cancel. Verify reconnect and fault scenarios.
- AC-04: Cross-owner access, forged approvals, prompt injection in tool output and credential capture attempts cannot enlarge authority or leak secrets. Verify service and browser adversarial tests, including history/log scans.
- AC-05: Keyboard/screen-reader flows and responsive result/approval rendering work; provider failure, budget exhaustion and offline machines have recoverable honest states. Record real accessibility/browser checks and provider failure simulation.
- AC-06: Upgrade/removal and rollback preserve repo mounts, files, app state and credentials; image services/health/docs match the new UI while Codespaces source editing works. Verify disposable migration and real Codespaces behavior.

## Open decisions

- D1: Model/provider, where orchestration runs, whose key/account is used, and spending limits. Blocks live provider integration; a fake provider supports early contract/UI tests.
- D2: Confirm contextual cards and human-only secure handoffs as part of the chat-only experience. Otherwise onboarding must use an external secure flow.
- D3: Conversation retention/deletion policy and provider data handling. Blocks real-user persistence and transmission defaults.
- D4: Remove embedded editor/ttyd services in the first migration or after chat parity? Recommended: remove only once replacement acceptance passes; retain graphical services needed for tools.

## Project plan

| Ticket | Bounded outcome | Depends on | Criteria covered | Verification |
| --- | --- | --- | --- | --- |
| [VST-014](../tickets/VST-014.md) | Conversation/run engine and authorized tools | VST-010, VST-005 | AC-03, AC-04 | State/replay, approval and provider-failure tests |
| [VST-015](../tickets/VST-015.md) | Chat shell, results and secure handoffs | VST-014, VST-009 | AC-01, AC-04, AC-05 | Browser-to-service, accessibility and secret isolation |
| [VST-016](../tickets/VST-016.md) | Legacy UI removal and migration | VST-015, VST-013 | AC-02, AC-06 | Route/service inventory and upgrade/rollback |

Chat designs and fake-provider prototypes can be evaluated while service work
continues. Do not remove the current interface until replacement acceptance
covers onboarding, agent connectivity and recovery.

## Decision history

- 2026-09-21: Replacing the current UI with a service-connected chat agent is user-requested. Secure handoffs, provider choice and service retirement sequencing above remain proposed decisions.
