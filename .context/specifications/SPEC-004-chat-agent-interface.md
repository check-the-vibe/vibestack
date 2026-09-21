# SPEC-004 — Agent overlay and in-VibeStack provider runtimes

- State: draft
- Initiative: [Agent platform](../initiatives/agent-platform.md)
- Owner: project owner for product decisions; Codex for this drafting pass
- Updated: 2026-09-21
- Decision authority: user requires complete removal of the existing UI, a clickable agent-icon overlay, supported providers running inside VibeStack, and host-initiated API installation/launch; adapter details below remain proposed
- Supersedes: the earlier full-page chat-shell draft of SPEC-004 and the retired combined agent-access proposal
- Planning ticket: [VST-004](../tickets/VST-004.md)

This is a specification update, not an implemented UI or working provider integration.

## Outcome: three requirements

1. **Replace the current UI with an agent overlay.** Remove the existing
   Desktop/Terminal/Editor/Apps/Settings navigation, menus, panels and setup pages.
   The default collapsed interface is one small agent icon. Clicking it opens a
   chat panel; closing it returns to the icon without stopping ongoing work.
2. **Offer supported agent/LLM providers from inside VibeStack.** Users choose a
   supported provider and are guided through automatic installation, launch and
   any human sign-in. Codex App Server and OpenCode server mode are the initial
   integration targets. VibeStack knows how to connect to each runtime's API.
3. **Control provider setup through the authenticated VibeStack API.** A call
   from the host requests installation or activation. VibeStack executes the
   registered installer, starts the local API or opens the appropriate application
   when needed, verifies readiness and reports a usable result to the host.

Here “host” means the authenticated caller outside the VibeStack runtime, such as
its host web interface, outer Codespaces process or CLI. The installation and
provider process run **inside VibeStack**, not on that caller's machine.

The proposed overlay sits above the desktop canvas, preserving the desktop as
working content while removing the old VibeStack chrome. This is the working
interpretation of “overlay”; it does not introduce a replacement dashboard or
full-page chat shell. The outer Codespaces source editor remains available.

## Current behavior and evidence

`desktop/`, `setup/` and `nginx.conf` provide the current UI and onboarding.
The catalog already has installers/probes for `codex-cli` (0.153.4) and `opencode`
(1.18.29); their configuration directories have existing persistence mappings.
Installation alone does not establish a managed provider API or chat adapter.
Code-server/ttyd and their health/image dependencies still exist. This pass
neither removes those services nor claims the pinned binaries implement every
method described in newer vendor documentation.

## Contract

### 1. Agent icon and chat panel

The icon is visible on first load, including when no provider is installed. It
has an accessible label and a small readiness/activity indicator. The collapsed
overlay does not intercept desktop pointer or keyboard input outside the icon.
Clicking or keyboard activation opens chat; close/Escape restores focus sensibly.
Use a side panel on desktop and an appropriate overlay sheet on small screens.
Opening/closing never creates a duplicate provider process, turn or conversation.

The panel contains conversation, provider selection/status, input, streamed
responses, tool/action results, stop, and contextual setup/approval controls.
Provider setup uses a small deterministic flow inside the panel: select provider,
activate, follow progress, complete sign-in if requested, then chat. It must work
without an LLM already installed or available. Errors offer retry or another
supported provider; they do not reopen the legacy Apps/Settings/setup interface.

Retain the current conversation when the panel closes. Bind each conversation
to its provider, provider-native session and workspace. Switching providers starts
a new conversation by default; do not silently replay prompts or copy history to
a different provider. Render provider output as untrusted text/escaped Markdown.

### 2. Supported provider catalog and adapters

A provider entry defines a stable ID, tested versions/platforms, existing catalog
installer (where possible), probe, fixed launch recipe, API transport, readiness
check, sign-in handoff, persisted paths and adapter capabilities. New providers
are added as reviewed service capabilities under SPEC-001, with adapter tests;
the UI consumes this catalog rather than containing vendor-specific launch logic.

“Inside VibeStack” refers to the agent runtime, adapter and managed process.
It does not imply model weights or inference run locally: a selected runtime may
use the user's authorized remote model service. Report its account/model and any
known usage limits honestly; provider/account billing is not included by installing
its executable. Never invent cost estimates for unavailable usage information.

| Initial target | Integration to validate | Readiness evidence |
| --- | --- | --- |
| Codex | Use `codex app-server` behind an in-container adapter; prefer its local stdio protocol initially. This is a programmatic agent interface, distinct from launching the Codex desktop GUI. | Supported protocol handshake, authentication state and a confirmed test turn with streamed output; pin the CLI/protocol version |
| OpenCode | Start `opencode serve` bound to loopback, using authentication supported by the tested release. Consume its HTTP API and events through an adapter. | Version/health check, configured model/provider authentication and a confirmed test session/response |

The Codex interface has its own RPC protocol; it is not assumed to be REST or
VibeStack's MCP endpoint. OpenCode v1/v2 server behavior differs, so record the
chosen release and API contract rather than mixing their examples. Opening a
GUI, seeing a PID or obtaining a healthy HTTP socket alone is not “ready to chat.”
An app-only integration is supported only when a tested API/bridge is available.

The adapter maps a small common interface: inspect/install/activate, sign-in
handoff, create/resume conversation, submit message, stream events, respond to
approvals and interrupt. Report unsupported actions explicitly. The provider owns
its agent loop and native execution; VibeStack owns lifecycle, routing and UI.
Do not build a second competing model/tool loop around Codex or OpenCode.

Provider-native shell/file tools execute with the workspace account's authority
and configured provider approvals; they are not automatically mediated by the
VibeStack REST/MCP dispatcher. Preserve and expose that distinction. Registered
VibeStack capabilities can be supplied through authenticated MCP when the provider
supports it. Neither path receives a Docker socket or host provisioning authority.

### 3. Host-to-VibeStack activation API

Provider lifecycle actions use SPEC-001's authenticated operation layer and are
included in SPEC-002 discovery, CLI and MCP coverage. Human secret entry remains
a secure handoff. Proposed API names below are to be finalized in VST-008; they
are not claims of existing endpoints.

| API | Contract |
| --- | --- |
| `GET /api/v1/providers` | Supported providers, installed/tested versions, installation/process/auth/readiness status and non-secret next actions |
| `POST /api/v1/providers/{id}/activate` | Ensure the selected supported provider is installed, start/reuse its managed runtime and verify its API; return an operation handle immediately |
| `GET /api/v1/providers/{id}` | Current state, activation progress/reference and any required human action |
| `POST /api/v1/providers/{id}/stop` | Stop the managed provider deliberately, with explicit handling of active conversations |
| `POST /api/v1/providers/{id}/open-app` | When supported, launch the registered application in VibeStack's desktop session for setup/use; do not equate window launch with API readiness |

The normal sequence is:

```text
Host requests activate(provider ID)
  → VibeStack probes the supported installation
  → installs through its registered installer if needed
  → starts or reuses the provider inside VibeStack
  → performs protocol, credential and model-readiness checks
  → reports ready, needs user action, or a specific failure
  → host chat connects through VibeStack's provider adapter
```

Callers select a known provider ID and supported options, never arbitrary shell
scripts, installer URLs, binaries or backend addresses. Reuse the pinned catalog
installers and their durable selection/restore mechanisms. A GUI launch uses the
existing `vibe` desktop session environment; a headless runtime also runs as
`vibe`. Only the established installer helper receives its existing elevated
installation authority. Do not introduce a blanket privileged command endpoint.

Activation is idempotent: concurrent/retried requests for the same provider reuse
one operation and managed process. Installed, running, authenticated and ready are
separate status fields. A missing login reports `needs_user_action`; the panel
opens a supported browser/device/application sign-in handoff and rechecks status.
Credentials go directly to the appropriate protected handler/store, never into
chat, prompts, URLs, ordinary API logs or model tool arguments.

The service owns provider process supervision/recovery and private endpoints.
Use stdio or authenticated loopback HTTP as appropriate; do not publish each
provider port through Codespaces. Browsers and external clients use VibeStack's
existing authenticated origin, not provider-private tokens or sockets. Persist
configured providers and supported session/auth data under the established
`/data` mappings. A runtime restart must not resubmit the last chat message.

## Conversations, errors and migration

Map VibeStack conversation/run IDs to provider session/turn IDs and observed
outcomes. Stream bounded events for text, actions, approvals, errors and completion.
On reconnect, inspect/resume the existing session where supported; otherwise say
that recovery is unavailable and offer a new turn. Do not infer success from text
or repeat a mutation whose outcome is unknown. Closing chat keeps work running;
Stop sends the adapter's supported interrupt and reports remaining work honestly.

Forward genuine provider approval requests to the user, tied to the exact run and
action. Tool output cannot approve itself. Provider-login and permission requests
remain human handoffs where required; automatic installation is not automatic
account creation, subscription purchase or credential consent.

Remove the old UI routes/assets and unused embedded editor/terminal services in
the final migration, together with their health checks and documentation. Preserve
desktop rendering and execution services needed by the canvas or agents, and the
outer Codespaces editor. Retire old pages with a documented safe transition to the
overlay; do not leave old unauthenticated setup/control mutations reachable.
API/docs/installer routes remain supported. Preserve repositories, app selection,
provider credentials and data through upgrade and rollback.

## Acceptance criteria

- AC-01: With no provider installed, the page shows the agent icon and no legacy navigation. Clicking it opens a working deterministic setup/chat panel; closing/reopening preserves the conversation and desktop input. Verify desktop, keyboard/screen-reader and small-screen behavior.
- AC-02: An authenticated caller outside VibeStack activates each initial supported provider from a clean instance. Installation/launch occur inside VibeStack; progress and human sign-in are visible; readiness requires a working provider protocol/account and a real streamed response. Retry/concurrent activation creates no duplicate process or install. Test Codex and OpenCode at recorded versions.
- AC-03: Send a task from the overlay through each real provider, show streamed text/actions and an approval when required, then stop/reconnect. IDs/results remain tied to the correct provider/workspace; no duplicate turn is sent. Show honest unsupported/recovery states.
- AC-04: Missing/invalid service credentials, arbitrary installer/launch inputs, forged approvals and untrusted provider output cannot bypass service policy. Private provider sockets/credentials are not exposed. Native provider execution authority is documented and tested; secrets stay outside chat/history/logs.
- AC-05: Missing package, failed install, incompatible API, absent/expired login, port conflict, runtime crash and model/quota failure produce distinct next actions. Setup/recovery works without an LLM and does not restore old panels. Adding one test provider uses the catalog/adapter contract without vendor logic in the UI.
- AC-06: Final image/routes have no legacy UI or unused embedded editor/terminal services. Fresh start, upgrade, stop/resume and rollback preserve repository mounts, provider selections/auth/session data and required desktop services; source editing remains available in Codespaces. Verify exact candidate images and hosted behavior.

## Open decisions

- D1: Exact supported Codex/OpenCode versions, available protocol methods and sign-in modes. Validate against the pinned catalog versions; upgrade deliberately if needed. Blocks declaring an adapter supported.
- D2: Icon placement, panel size/mobile behavior and whether the preserved desktop canvas is the desired background. The icon-to-chat interaction and removal of old chrome are user requirements.
- D3: Conversation retention/deletion and account usage/budget defaults. Runtime execution inside VibeStack is settled; inference location depends on the selected provider. Resolve before storing/sending real user content.

## Project plan

| Ticket | Bounded outcome | Depends on | Criteria covered | Verification |
| --- | --- | --- | --- | --- |
| [VST-014](../tickets/VST-014.md) | Provider catalog, activation API and runtime adapters | VST-010, VST-005 | AC-02, AC-03, AC-04, AC-05 | Host-to-container install/start, real Codex/OpenCode turns and failure/retry cases |
| [VST-015](../tickets/VST-015.md) | Agent icon, chat overlay and deterministic provider setup | VST-014, VST-009 | AC-01, AC-03, AC-04, AC-05 | First-run setup, real streaming/approvals, accessibility and recovery |
| [VST-016](../tickets/VST-016.md) | Complete old-UI removal and migration | VST-015, VST-013 | AC-06 | Route/service inventory, source/provider persistence and rollback |

Provider fakes support early UI/contract work; they do not satisfy real-provider
acceptance. These tickets remain planned. No provider is installed or started by
this specification-writing pass.

## Decision history and references

- 2026-09-21: User clarified the three-part outcome: remove the old UI; expose chat through an agent-icon overlay; guide installation/launch of providers running inside VibeStack via host API calls. Replaced the prior generic chat-orchestrator design accordingly.
- [Codex App Server](https://learn.chatgpt.com/docs/app-server): official integration interface and local transport documentation. Validate the installed version's schema and authentication flow before implementation; do not infer desktop-GUI API support.
- [OpenCode server documentation](https://dev.opencode.ai/docs/server/) and [v2 server lifecycle](https://opencode.ai/v2/docs/cli/web): official server-mode references. Select the matching version contract and keep the managed listener private.
