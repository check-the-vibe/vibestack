# In-container provider runtimes

This is the VST-014 source contract. See [the ticket](../../.context/tickets/VST-014.md)
for exact verification and deployment evidence, and
[SPEC-004](../../.context/specifications/SPEC-004-chat-agent-interface.md) for the
complete overlay outcome. Native startup has been exercised without an account;
signed-in model turns, real approval delivery and the overlay remain unverified.

## Topology and authority

The existing Go workspace service owns the provider manager. REST, generic CLI,
browser requests and permitted MCP tools use its compiled registry, grants,
identity checks, limits and payload-free audit records. No new external listener
or VibeStack model loop is introduced. Native providers run their own agent loops
as `vibe`, with the account's full authority, including persistent application
stores. File API path restrictions do not confine native execution. This remains
a trusted single-user desktop.

Activation selects only a known provider ID. The manager uses the existing
catalog installer, probes the pinned version, launches a fixed executable/argv
and checks its native protocol. Caller-supplied installers, environment maps,
arguments and backend origins are rejected. A minimal child environment excludes
outer Codespace credentials and host accounts. Project choice selects an existing
non-symlink immediate child of `/projects`; it is a working directory, not a
native sandbox guarantee.

| Runtime | Catalog pin | Private connection |
| --- | --- | --- |
| Codex | `@openai/codex` 0.153.4 | `codex app-server --listen stdio://`; JSONL initialize, account/model, thread/turn and approvals |
| OpenCode | `opencode-ai` 1.18.29 | `opencode --pure serve`; ephemeral IPv4 loopback HTTP with Basic authentication and `/global/event` SSE |

Codex threads use `workspace-write`, `on-request` and the human reviewer. Only
one-action command/file decisions are supported; stdin, other environments,
remembered grants and unknown requests fail closed. File approvals need a complete
matching item preview. OpenCode uses `permission: ask` in both server configuration
and every created session. Replies are `once` or `reject`, never persistent grants.
These native policies are not an independent VibeStack isolation boundary.

OpenCode's random per-process API secret is passed only through its documented
child environment; it never appears in status, argv or logs. This is distinct
from the human Linux password. Proxies/redirects are disabled. A port collision
fails the authenticated exact-version health check rather than adopting another
server. Codex uses stdio. Neither transport is forwarded through Codespaces.
Native providers own user sign-in and model credentials; VibeStack does not copy
host auth, add an API-key field or purchase account credits.

Schemas were generated from the exact pinned binaries. OpenCode's `/provider`
catalog measured 5,807,159 bytes, exceeding the 4 MiB adapter bound; the implemented
`/config/providers` returns the configured subset. Only model IDs/names are
projected, never raw configuration or keys. Limits are 50 Codex and 100 OpenCode
models. Configuration does not prove account access, quota or credit. Current
public references may differ from these pins:
[Codex App Server](https://learn.chatgpt.com/docs/app-server),
[OpenCode server](https://dev.opencode.ai/docs/server/),
[OpenCode permissions](https://dev.opencode.ai/docs/permissions/).

## Lifecycle and readiness

One process is managed per provider. Concurrent activate calls share an operation
while it installs/starts/runs. Caller disconnect does not stop activation.
Installation, process, authentication and readiness are separate fields.
`installed: null` means not probed, false means absent, and true means the supported
version was found. A successful handshake means active/running, not verified.
Only a successful native turn in that process sets verified.

Absent login reports `needs_sign_in`. Human owners call `openProviderApp` to open
the fixed native desktop terminal for sign-in/history, then refresh status. No
secret goes through chat. Protocol mismatch, native rejection, connection loss
and storage failure produce bounded errors and explicit next actions. Unsupported
OpenCode interactive questions produce a visible recovery event, never an invented
answer. Raw native diagnostics are suppressed because they may contain private text.

Stop deselects automatic startup, cancels activation supervision, terminates the
managed process group and marks unfinished turns unknown. An already submitted
catalog install may finish after Stop; cancelled activation does not launch it.
Broken metadata storage still permits process termination, while reporting that
selection could not be saved. Stop cannot undo edits or promise to stop unrelated
applications or children that escaped the process group. Crashes never silently
retry prompts; activate is an explicit recovery action.

## Conversations, events and approvals

Conversations bind a public ID to one provider, configured model, project and
private native session. Messages require explicit operation IDs. Metadata and a
SHA-256 prompt digest are saved before dispatch. The same ID/prompt retrieves its
recorded outcome; changed prompts conflict. A lost reply is unknown, not a retry.
Native turn IDs and assistant parent-message IDs prevent late preceding events
from completing a new operation. Resume refuses a still-active native session.

Bounded pages contain text, actions, errors, approvals and completion. All text
is untrusted and must use text-safe rendering. Cursor gaps after eviction/restart
require native history inspection; no transcript is manufactured. Interrupt
addresses the exact native turn and remains stopping until confirmed by events.
It does not mean edits were reverted.

The manager mints approval handles tied to runtime/conversation/operation. Native
duplicates cannot mint another handle after an answer. Answers are consumed once,
even when delivery is uncertain. Human owner approval and sign-in launching are
excluded from MCP. Truncated action details set `can_allow: false`; Allow is
rejected while Decline works. Approval-like model text grants no authority.

## Persistence and bounds

`/data/vibestack/provider-runtime-v1.json` uses the workspace store's atomic `0600`
policy. It holds versioned selection/session/operation metadata and prompt digests,
not prompts, events, secrets or pending decisions. Native auth/history stays in
`/data/codex`, `/data/opencode-config` and `/data/opencode`; user overrides are not
replaced. Restart restores selected runtimes, marks unfinished operations unknown
and never replays prompts/approvals. There is no conversation-delete API in this
first backend pass. Native providers own history retention and account budgets.

Limits: 32 conversations, 32 operations each, 1 MiB metadata, 64 KiB prompts,
256 events/1 MiB transient text per conversation, 32 events/128 KiB text per page,
and 32 pending approvals sharing 256 KiB text. Native frames are limited to 4 MiB,
requests to 128 KiB and Codex pending RPCs to 16. Public operations have 30-second
calls, 128 KiB inputs and 512 KiB outputs; install/start may continue for 30 minutes.
Capacity failures never silently erase history or retry mutations.

## Verification boundary

Unit/fault fixtures cover strict authenticated dispatch, lifecycle races,
uncertain outcomes, event correlation, approval scope and storage failure.
`tests/provider-runtime-check.mjs` is part of disposable acceptance: actual catalog
installs/native runtimes, REST/CLI/MCP activation/status and stop/reactivation.
It signs into no account and sends no model prompt. Separate network-disabled
probes exercise exact native handshakes and OpenCode session permission policy.

Remaining acceptance requires human sign-in, a harmless streamed task per real
provider, approval and interrupt, then restart/upgrade with native state preserved.
VST-015 adds deterministic setup/chat; VST-016 removes the old UI/services.
