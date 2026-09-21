# SPEC-001 — Public machine broker

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

A machine owner enrolls a local Docker host or Codespace with a broker. The
machine connects outbound, so clients do not need inbound access to that machine.
An authorized browser, CLI or agent on the internet selects a workspace and
operates it through the broker. Public reachability never means anonymous access.
A disconnected machine is visibly offline; requests cannot drift to another one.

## Current behavior and evidence

`runner/server.go` manages a local Docker host, dispatches the runner REST API,
and mediates workspace operations. `runner/mcp.go` reuses that dispatch.
`nginx.conf` fronts the private desktop, not a public machine-connection service.
The current trusted-tailnet mode grants broad shared access and is unsuitable
as the public authentication mode. Codespaces uses a private forwarded port.
There is no implemented internet machine connector or public identity service.

## Scope and exclusions

Include enrollment, machine identity, outbound sessions, workspace registration,
authorized routing, presence, revocation, operation reconciliation and deployment.
Keep container lifecycle execution on the enrolled host. Exclude arbitrary TCP
forwarding, public raw Docker access, billing, organization administration and
horizontal broker clustering from the initial release. Multi-owner isolation is
required even if the first deployment has only one owner.

## Contract

Proposed topology: `client → HTTPS nginx → Go broker → outbound machine session
→ connector → registered local runner/workspace`. PostgreSQL holds identities,
grants, registrations, operation references and audit metadata. A single broker
process is the initial deployment; a broker restart must not erase durable state.

| Component | Responsibility |
| --- | --- |
| nginx | TLS edge, exact host routing, request limits, WebSocket/stream forwarding; never decide ownership from an untrusted header |
| Go broker | Authenticate, authorize every operation, register machines/workspaces, route typed operations and reconcile outcomes |
| Machine connector | Authenticate its machine, publish approved capabilities, dispatch only allowed operations to configured local targets |
| Identity service | Human/client login and token issuance, shared with REST/MCP; provider selected before implementation |

Identity hierarchy is owner → machine → workspace. IDs are stable and opaque;
connections have independent session generations. Grants identify a principal,
resource and allowed capabilities. Client and machine credentials are distinct.
A machine cannot choose a different owner or self-grant access through its payload.
Command execution grants broad authority inside that workspace; it is not a
read-only role merely because a separate file tool is unavailable.

Enrollment requires an authenticated owner action and a short-lived, one-use
claim, stored hashed at the broker. Recommend a machine-generated private key
and a revocable certificate for recurring mTLS sessions. TLS termination must
verify the certificate and pass identity over a protected internal connection;
strip caller-supplied identity headers. Define issuance, rotation, expiry and
recovery before enabling this path. No enrollment secret in URLs, Git or logs.

Use an outbound WSS session on port 443 with a versioned typed envelope:
request ID, operation name, workspace ID, deadline, payload and result/error.
Do not accept caller-selected backend URLs or raw proxy paths. Publish explicit
frame/body/output/concurrency limits in configuration and discovery before code
ships. Heartbeats determine presence; newer authenticated session generations
fence older connections. Backoff includes jitter and remains bounded.

Persist an operation intent before dispatch. Mutations use an owner/resource/
operation-scoped idempotency key plus request digest; mismatched reuse conflicts.
Deduplicate at the executor too. After lost acknowledgement report unknown or
reconciling, query the executor, and never blindly replay arbitrary commands.
Offline submissions initially fail with a retryable `machine_offline` error;
there is no hidden durable offline command queue.

## Design decisions and alternatives

Recommend Go to reuse the existing client, runner types and MCP SDK. Keep broker
and host runner separate processes; moving the Docker socket to the public edge
would combine unrelated authority. Recommend PostgreSQL over a new file registry
for transactional enrollment/grants/dispatch records and future concurrency.
SQLite is a smaller single-node alternative and must be evaluated against the
actual hosting choice before locking storage. Nginx alone cannot supply this
application state or ownership policy. WSS is the initial transport recommendation;
gRPC is an alternative if the selected edge supports its operational needs better.

## Failure, migration and operations

Fail closed on unknown, expired or revoked identity. Enforce revocation for new
requests and terminate associated sessions within a configured, tested bound;
report separately what happens to already-running jobs. Connector loss must not
be presented as successful cancellation. Authentication failures never fall back
to trusted-tailnet mode. Audit actor, target, operation, request ID and outcome,
without command text, payload bodies or credentials.

Add the public service beside the private runner; require explicit enrollment.
Do not switch existing private desktops or Codespaces ports to public. Broker
credentials stay outside the repository shared at `/projects/vibestack`. Database
migrations and backup/restore checks precede production use. Rollback disables
public routing and retains machine registration/data; it does not wipe desktops.

## Acceptance criteria

- AC-01: An owner enrolls a machine using outbound-only networking; reuse/expiry of its enrollment claim is rejected, and restart preserves identity. Verify with a real isolated connector and registry restart.
- AC-02: Two owners and two machines cannot read or act on each other's resources; forged headers, machine owner claims and arbitrary backend targets fail without side effects. Verify REST and connector adversarial integration cases.
- AC-03: Disconnect/reconnect and concurrent sessions preserve workspace identity, fence stale sessions and expose offline state; offline mutations are explicitly rejected. Verify network interruption and broker restart.
- AC-04: Lost acknowledgements and repeated mutation keys produce at most one accepted execution for the same intent; changed-payload reuse conflicts and unknown outcomes remain honest. Verify fault injection at dispatch/ack boundaries.
- AC-05: Revoking a client or machine denies subsequent requests within the documented bound; logs contain no enrolled/test secrets. Verify active-session revocation and log scans.
- AC-06: A clean deployment and backup/restore exercise work through nginx, while existing private clients and source/data mounts remain usable. Record rollback and end-to-end checks on the exact candidate.

## Open decisions

- D1: Hosting origin, operator and identity provider. Recommend one operator-controlled origin and an established OAuth/OIDC provider; blocks public deployment and credential implementation.
- D2: Confirm nginx + Go, registry database and certificate issuer. Prototype transport/identity compatibility before committing operations dependencies.
- D3: Set measurable quotas, heartbeat/offline thresholds, revocation bound and retention from expected machine/client scale; blocks release acceptance, not contract discovery.

## Project plan

| Ticket | Bounded outcome | Depends on | Criteria covered | Verification |
| --- | --- | --- | --- | --- |
| [VST-005](../tickets/VST-005.md) | Registry, grants and enrollment | VST-008 | AC-01, AC-02, AC-05 | Identity/ownership and revocation cases |
| [VST-006](../tickets/VST-006.md) | Outbound connector and typed routing | VST-005, VST-008 | AC-02, AC-03 | Two-machine and interrupted-session cases |
| [VST-007](../tickets/VST-007.md) | Dispatch recovery and deployment | VST-006, VST-010 | AC-04, AC-05, AC-06 | Fault injection, backup/restore and rollback |

## Decision history and references

- 2026-09-21: Public machine connectivity is user-requested; topology and operational defaults above are recommendations awaiting resolution of D1–D3.
- nginx requires explicit WebSocket proxy handling; validate the chosen edge configuration against [official WebSocket guidance](https://nginx.org/en/docs/http/websocket.html) and [proxy buffering controls](https://nginx.org/en/docs/http/ngx_http_proxy_module.html). These sources inform transport configuration, not the proposed ownership architecture.
