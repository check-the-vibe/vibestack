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

A local or external harness follows the instance's `/AGENTS.md`, connects to its
`/mcp` endpoint, authenticates and calls workspace capabilities. New capabilities
registered in [SPEC-001](SPEC-001-service-host.md) appear through the same adapter.
An optional local stdio bridge supports clients that need it. No machine broker
or enrollment is required, and workspace tools do not grant Docker-host control.

## Current behavior and evidence

`runner/mcp.go` uses Go MCP SDK v1.7.0 with Streamable HTTP and calls existing
REST dispatch under the resolved principal. Its tools cover host/instance
operations and workspace commands, jobs, output and screenshots. The current
runner supports paired/private and trusted-tailnet modes; this is not the
proposed public OAuth service. VST-011 adds the direct workspace adapter; read its ticket for source, image and
hosted validation separately. [The runtime guide](../../docs/MCP.md) defines its
configured-bearer client matrix; it is not an OAuth authorization server.

## Scope and exclusions

Deliver authenticated HTTP MCP in the workspace service and a thin local stdio
bridge for supported clients that need it, with shared
operation authorization, a documented tool inventory and real client verification.
Keep passwords, provider keys, raw Docker access, arbitrary upstream URLs and
irreversible volume purge out of model tool arguments/results. Linux passwords
and external account login use human-only secure handoffs. No new MCP-only
execution engine or authorization store.

## Contract

Expose `/mcp` in the same workspace service process and origin as REST, using
Streamable HTTP and the shared authentication/authorization middleware. Configured
personal bearer credentials are supported only for clients verified to accept
them. Clients needing OAuth discovery/consent use an established authorization
server integration, with protected-resource metadata and challenges validated
against the selected protocol version. A token-only integration must not be
advertised as universal remote-client support.

Validate the selected credential type's instance/resource binding, validity and
permissions; for OAuth validate issuer, audience and expiry. Reuse protected
internal credentials for backend adapters rather than passing external access
tokens to local services. GitHub/private-port login is a separate gateway layer,
not a substitute for this authentication. Do not enable anonymous fallback.

Pin supported MCP protocol versions against actual SDK and client behavior.
Select the authorization-server/client registration approach in the compatibility
matrix, rather than assuming every harness supports the newest published option.
OAuth issuance/refresh belongs to the configured authorization server; personal
credentials use the local protected configuration. Enforce instance permissions
on every call and recheck revocation for continuing connections. Bind
session identifiers to principals; session IDs themselves are not credentials.
Validate Origin and exact public host, bound request/result sizes and ensure
nginx does not stall streaming responses through inappropriate buffering.

Local recommendation: a `vibestack mcp` subcommand bridges stdio to the same
HTTP MCP endpoint (loopback when running inside the workspace)
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
| Host lifecycle | Remains in the optional existing runner; not exposed by the workspace endpoint |
| Credential-adjacent actions | Explicit coverage decision; no implicit clipboard/SSH-key tools in the default set |

HTTP connects to one explicit workspace origin; stdio binds that origin for its
process. Target identity stays stable for the connection. Host management requires
a separate runner connection and is not introduced by this implementation.
Tools retain REST operation IDs/idempotency semantics internally. Return structured
job/operation handles and bounded content, not unbounded terminal transcripts.
Annotate read/write/destructive behavior accurately; annotations do not enforce
access. Cancellation of a protocol request does not automatically mean the
remote job was cancelled: expose its confirmed state and explicit cancel tool.

## Design decisions and alternatives

Use thin adapters over SPEC-001's registered capabilities and SPEC-002's operation
contract. Preserve the separate runner's existing private-client behavior. Choose
authentication support from the tested harness matrix; do not add a fleet registry,
custom OAuth server or independent MCP execution engine.

## Failure, migration and operations

Unauthenticated requests return a protocol-compatible authentication challenge,
not an HTML login page. Wrong audience, expired/revoked tokens and changed grants
fail without execution. Partial stream loss can resume only according to the
negotiated protocol; mutations must not silently replay. Return bounded safe tool
errors with request IDs. Tool output and retrieved documents are untrusted data,
not permission to execute follow-on instructions. Preserve existing private MCP
clients while staging the new workspace endpoint; rollback revokes new grants and
routes without deleting workspace data.

## Acceptance criteria

- AC-01: Two independent supported remote clients complete discovery/login, list allowed tools and execute a harmless targeted operation. Record actual client/SDK/protocol versions and authenticated endpoint results.
- AC-02: Missing/expired/wrong-resource/revoked credentials, wrong Origin and wrong-instance or denied-capability requests fail with no side effects, including connection/session reuse after revocation. Verify through both REST and MCP.
- AC-03: A real Codespaces-local client uses stdio for status, argv job, file update and screenshot; source changes appear in the shared repo and secrets stay out of config/protocol logs.
- AC-04: Coverage checks map all exposed tools to shared operation policy; unsupported tools are explicit and host grants cannot be obtained from workspace grants. Verify parity and denial cases.
- AC-05: Stream loss, retries, output limits and cancellation preserve job identity and honest state without duplicate mutations. Verify fault injection through nginx.
- AC-06: Existing private runner clients continue to work through migration and rollback; public clients never fall back to anonymous trusted-tailnet behavior.

## Open decisions

- D1: Initial supported harnesses, token configuration support and any required OAuth provider/registration flow. Verify private Codespaces gateway access too. Shares SPEC-001 D1 and gates claiming those clients work.
- D2: Initial operation/tool coverage, especially clipboard and SSH-key actions; resolve against the shared inventory before exposing tools; user-authored tools inherit the same checks.
- D3: Confirm local credential bootstrap/storage and the desired revocation bound. Do not check a working token into Codespaces settings.

## Project plan

| Ticket | Bounded outcome | Depends on | Criteria covered | Verification |
| --- | --- | --- | --- | --- |
| [VST-011](../tickets/VST-011.md) | Remote discovery and authorization | VST-005, VST-008 | AC-01, AC-02 | Two-client auth and session isolation |
| [VST-012](../tickets/VST-012.md) | Registered workspace tools and optional stdio bridge | VST-011, VST-006 | AC-03, AC-04 | Codespaces and operation parity |
| [VST-013](../tickets/VST-013.md) | Transport faults and compatibility | VST-012, VST-010 | AC-05, AC-06 | nginx interruption and old/new client tests |

The shared authentication and capability contract must settle first; local adapter internals can be
prototyped independently, but release acceptance covers both local and remote use.

## Decision history and references

- 2026-09-21: Authentication is user-required; the OAuth/stdio split is a design recommendation, with no provider or harness silently selected.
- [MCP authorization specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/index.mdx) describes HTTP authorization and discovery. The local stdio transport has a different credential boundary. Check the pinned implementation against the selected version before claiming compliance.
- [Go SDK protocol guidance](https://github.com/modelcontextprotocol/go-sdk/blob/main/docs/protocol.md) informs middleware and protocol integration; its current documentation is not proof that installed v1.7.0 implements every newer capability.

- 2026-09-21: User requested removal of the combined agent-access proposal. Review this feature in its own specification; no proposed architecture is approved by that removal.

- 2026-09-21: Aligned with the user-requested SPEC-001 rewrite: one extensible workspace service, no required machine broker, shared authenticated REST/MCP capabilities. Other feature-specific decisions remain draft.

- 2026-09-21: For the authorized implementation pass, initial remote support is
  the pinned Go 1.7.0 and TypeScript 1.30.0 bearer-configured SDK clients. Private
  Codespaces gateway authentication is verified separately. OAuth-only harnesses
  remain unsupported until a standard provider is selected and integrated; do not
  claim universal client compatibility. Stateless calls recheck local revocation
  before each dispatch; already executing operations are not undone.
