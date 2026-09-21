# SPEC-003 — Authenticated MCP

- State: draft
- Initiative: [Agent platform](../initiatives/agent-platform.md)
- Owner: project owner for product decisions; Codex for this drafting pass
- Updated: 2026-09-21
- Decision authority: user's request to specify these four features; recommendations below are proposed, not approved implementation choices
- Supersedes: the retired combined agent-access proposal; these four feature specifications now define the proposed work
- Planning ticket: [VST-004](../tickets/VST-004.md)

This is a target contract, not a claim of shipped behavior. Unresolved decisions
keep the specification in draft; no runtime changes are part of this pass.

## Outcome and user journeys

A local Codespaces agent discovers workspace tools without a host broker. An
external MCP client connects to the public broker, authenticates as its user,
selects an authorized workspace and calls those same operations. Revocation
removes access. A client cannot gain host authority merely by connecting to MCP.

## Current behavior and evidence

`runner/mcp.go` uses Go MCP SDK v1.7.0 with Streamable HTTP and calls existing
REST dispatch under the resolved principal. Its tools cover host/instance
operations and workspace commands, jobs, output and screenshots. The current
runner supports paired/private and trusted-tailnet modes; this is not the
proposed public OAuth service. A direct workspace MCP adapter is not implemented.

## Scope and exclusions

Deliver a local stdio adapter and authenticated remote HTTP service, shared
operation authorization, a documented tool inventory and real client verification.
Keep passwords, provider keys, raw Docker access, arbitrary upstream URLs and
irreversible volume purge out of model tool arguments/results. Linux passwords
and external account login use human-only secure handoffs. No new MCP-only
execution engine or authorization store.

## Contract

Remote endpoint recommendation: `/mcp` on the public broker origin, behind the
same identity/resource grants as REST. Use Streamable HTTP and publish the
protected resource metadata/challenges needed by supported clients. Use OAuth
for remote user delegation; do not confuse a GitHub/private-port login with
VibeStack authorization. Bind tokens to intended resource/audience, issuer,
expiry and capabilities; reject machine credentials as client access tokens.
Never pass a client's bearer token through to a local desktop. Broker/connector
uses its separate authenticated channel and operation-bound target authorization.

Pin supported MCP protocol versions against actual SDK and client behavior.
Select the authorization-server/client registration approach in the compatibility
matrix, rather than assuming every harness supports the newest published option.
Token issuance/refresh belongs to the chosen identity service. Enforce resource
ownership on every call and recheck revocation for continuing sessions. Bind
session identifiers to principals; session IDs themselves are not credentials.
Validate Origin and exact public host, bound request/result sizes and ensure
nginx does not stall streaming responses through inappropriate buffering.

Local recommendation: a `vibestack mcp` subcommand runs stdio, calls loopback REST
and obtains credentials from an explicitly configured protected local profile or
credential file. The command does not exist yet. No token in repository MCP JSON,
command-line arguments, stdout or prompt context. Stdout contains protocol frames
only; sanitized diagnostics use stderr. The adapter needs workspace credentials,
not the Docker socket. Host trust and tool approval controls remain in effect.

| Tool group | Planned coverage / authority |
| --- | --- |
| Discovery/status | Server identity, selected target, allowed capabilities and readiness |
| Workspace jobs | Explicit argv submission, inspect, bounded output and cancel; broad workspace execution authority |
| Projects | Read/write authorized roots with preconditions and existing traversal protections |
| Desktop operations | Screenshot, supported apps/windows and bounded diagnostics |
| Host lifecycle | Separate grant and explicit instance/machine; never bundled into workspace access |
| Credential-adjacent actions | Explicit coverage decision; no implicit clipboard/SSH-key tools in the default set |

Single-workspace stdio binds its target for that process. Public multi-workspace
tools require explicit workspace IDs; host actions also select the machine.
Tools retain REST operation IDs/idempotency semantics internally. Return structured
job/operation handles and bounded content, not unbounded terminal transcripts.
Annotate read/write/destructive behavior accurately; annotations do not enforce
access. Cancellation of a protocol request does not automatically mean the
remote job was cancelled: expose its confirmed state and explicit cancel tool.

## Design decisions and alternatives

Recommend thin adapters over the common operation contract from SPEC-002. Preserve
current runner tool compatibility for supported private clients. Static personal
tokens can remain an explicit private integration option, but are not the sole
public-client design. Do not require every Codespace to enroll with the public
broker merely to run local tools.

## Failure, migration and operations

Unauthenticated requests return a protocol-compatible authentication challenge,
not an HTML login page. Wrong audience, expired/revoked tokens and changed grants
fail without execution. Partial stream loss can resume only according to the
negotiated protocol; mutations must not silently replay. Return bounded safe tool
errors with request IDs. Tool output and retrieved documents are untrusted data,
not permission to execute follow-on instructions. Preserve existing private MCP
clients while staging the new public endpoint; rollback revokes new grants and
routes without deleting workspace data.

## Acceptance criteria

- AC-01: Two independent supported remote clients complete discovery/login, list allowed tools and execute a harmless targeted operation. Record actual client/SDK/protocol versions and authenticated endpoint results.
- AC-02: Missing/expired/wrong-audience/revoked credentials, wrong Origin and cross-owner targets fail with no side effects, including session reuse after revocation. Verify through both REST and MCP.
- AC-03: A real Codespaces-local client uses stdio for status, argv job, file update and screenshot; source changes appear in the shared repo and secrets stay out of config/protocol logs.
- AC-04: Coverage checks map all exposed tools to shared operation policy; unsupported tools are explicit and host grants cannot be obtained from workspace grants. Verify parity and denial cases.
- AC-05: Stream loss, retries, output limits and cancellation preserve job identity and honest state without duplicate mutations. Verify fault injection through nginx.
- AC-06: Existing private runner clients continue to work through migration and rollback; public clients never fall back to anonymous trusted-tailnet behavior.

## Open decisions

- D1: Identity provider and supported remote client matrix, including their registration/discovery support. Blocks the remote implementation contract; shares SPEC-001 D1.
- D2: Initial operation/tool coverage, especially clipboard and SSH-key actions; resolve against the shared inventory before exposing tools.
- D3: Confirm local credential bootstrap/storage and the desired revocation bound. Do not check a working token into Codespaces settings.

## Project plan

| Ticket | Bounded outcome | Depends on | Criteria covered | Verification |
| --- | --- | --- | --- | --- |
| [VST-011](../tickets/VST-011.md) | Remote discovery and authorization | VST-005, VST-008 | AC-01, AC-02 | Two-client auth and session isolation |
| [VST-012](../tickets/VST-012.md) | Shared tools and local stdio adapter | VST-011, VST-010 | AC-03, AC-04 | Codespaces and operation parity |
| [VST-013](../tickets/VST-013.md) | Transport faults and compatibility | VST-012, VST-007 | AC-05, AC-06 | nginx interruption and old/new client tests |

The shared grant contract must settle first; local adapter internals can be
prototyped independently, but release acceptance covers both local and remote use.

## Decision history and references

- 2026-09-21: Authentication is user-required; the OAuth/stdio split is a design recommendation, with no provider or harness silently selected.
- [MCP authorization specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/index.mdx) describes HTTP authorization and discovery. The local stdio transport has a different credential boundary. Check the pinned implementation against the selected version before claiming compliance.
- [Go SDK protocol guidance](https://github.com/modelcontextprotocol/go-sdk/blob/main/docs/protocol.md) informs middleware and protocol integration; its current documentation is not proof that installed v1.7.0 implements every newer capability.

- 2026-09-21: User requested removal of the combined agent-access proposal. Review this feature in its own specification; no proposed architecture is approved by that removal.
