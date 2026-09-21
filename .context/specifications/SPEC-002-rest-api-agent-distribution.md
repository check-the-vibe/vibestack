# SPEC-002 — REST API, agent guidance and CLI distribution

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

A person gives an agent one service origin. The agent discovers supported APIs,
reads version-matched operating guidance, installs a compatible CLI, authenticates
and selects an explicit workspace. REST, CLI, MCP and chat then mean the same
thing when they submit a command, inspect output or change a file.

## Current behavior and evidence

`api/workspace.openapi.json`, `api/runner.openapi.json` and
`api/command-coverage.json` describe current routes/CLI coverage. Workspace
operations live in `automation/`; `pkg/vibestack` is the Go client.
`runner/server.go` serves discovery, documentation, `/cli.sh` and mediated
workspace operations. `nginx.conf` serves the desktop guidance and installer.
`cli.sh` downloads versioned Linux/macOS amd64/arm64 binaries over HTTPS, checks
a SHA-256 file and stages replacement without sudo. These files do not establish
that every advertised release artifact is currently published or functional.

## Scope and exclusions

Specify the canonical operation inventory, resource/version/error contract,
discovery, guidance and tested installer URLs. Preserve local workspace access
without requiring a public broker. Exclude inventing a separate execution engine,
embedding tokens in documentation, or changing authentication independently of
SPEC-001/SPEC-003. Windows distribution is outside the first target matrix.

## Contract

Separate service kinds: workspace (desktop work), runner (one Docker host), broker
(machine routing). Discovery must identify kind, server version, supported API
versions, canonical origin, relative route/document URLs and supported auth modes.
Anonymous discovery exposes no machine inventory, user identity or credentials.
Authenticated capabilities report the caller's effective access, target IDs,
limits and readiness; readiness separates healthy services, machine online,
app restoration and human onboarding.

Retain working `/api/v1/automation` and `/api/v1/runner` clients. Proposed public
broker routes use `/api/v1/broker/machines` and
`/api/v1/broker/workspaces/{workspace_id}`; route names are a draft to finalize in
VST-008. Derive owner and authorized machine from the registry, not caller claims.
Every multi-workspace action uses an explicit target. Local adapters may bind one
workspace at connection time and must identify it in results.

| Surface | Target behavior |
| --- | --- |
| `/.well-known/vibestack` | Minimal discovery and compatibility, no secrets/inventory |
| `/AGENTS.md` | Service-kind-specific operating instructions with version and discovery links |
| `/CLI.md`, `/AUTOMATION.md`, `/RUNNER.md` | Applicable versioned references; discovery does not advertise irrelevant documents |
| `/api/workspace.openapi.json`, `/api/runner.openapi.json` | Preserve current contracts; publish a separate broker OpenAPI document |
| `/cli.sh` | Reviewable installer with explicit version/install directory and release-channel identity |

Use one operation inventory to map REST operation IDs, CLI commands, MCP tools,
authority and verification. Mark intentional omissions, including human secret
entry, instead of implying every API must be a model tool. Preserve argv versus
shell distinction. Workspace jobs and host lifecycle operations have different
IDs, states and cancellation semantics; return bounded cursor-based output.
File writes retain preconditions and no-follow/project-root boundaries. Apply
idempotency to broker mutation submission and return a conflict for key/payload
mismatch. Existing APIs get additive changes; breaking behavior requires a new
version and a documented migration window.

Errors use a documented envelope containing stable code, safe message, request
ID and retryability, with a human-action URL only when appropriate. Define
validation, unauthenticated, forbidden, unknown target, precondition conflict,
rate-limit, offline and upstream-timeout cases. Decide non-disclosure behavior
for inaccessible IDs consistently across transports. Unknown command outcome
is not a retryable success. Publish body/output/time limits and pagination rules.

Installer requirements: HTTPS-only redirects, explicit platform/version checks,
bounded downloads, checksum verification and atomic replacement. A bad artifact
or unsupported platform leaves the existing CLI intact. Publish immutable
versioned assets and a tested compatibility matrix. A checksum from the same
channel detects mismatches; it does not independently authenticate a compromised
publisher. Decide signed release provenance/trust roots before public release.
Print the next connect action without credentials; do not auto-enroll, elevate,
edit shell profiles or embed secrets. Document download-and-inspect installation.

## Design decisions and alternatives

Recommend shared operation definitions and thin transport adapters over rewriting
APIs into a single new route tree. Keep broker discovery separate from workspace
instructions so an agent does not accidentally use host authority. Human-readable
guidance plus OpenAPI supports both agent context and deterministic clients;
neither is a substitute for runtime authorization.

## Failure, migration and operations

Test fresh install, upgrade, interruption, missing releases, checksum failure
and old-client/server combinations. Guidance must distinguish current commands
from proposed ones and use the selected service's origin. Do not redirect an
old authenticated API request to a new origin while forwarding credentials.
Keep documentation release metadata synchronized with the shipped image/client.
Retain existing paths through a declared compatibility period and publish any
deprecation before removal. API contract tests and coverage checks run in CI.

## Acceptance criteria

- AC-01: A contract inventory maps every supported operation to its authority, routes, CLI and intentional MCP/chat coverage; schema/coverage checks catch drift.
- AC-02: Starting from only an origin, an unauthenticated client discovers the correct guide and installer without learning inventory or secrets; an authenticated client sees only its capabilities. Verify all service kinds.
- AC-03: Fresh install and upgrade succeed for each supported OS/architecture; invalid checksum, redirect, missing version or interruption preserves the prior CLI. Verify disposable native/release environments, not just shell syntax.
- AC-04: Direct and broker-mediated calls enforce the same file preconditions, job/output limits and target authority; cross-owner, oversized and malformed requests have consistent bounded errors. Verify parity integration cases.
- AC-05: Lost responses and duplicate submissions obey the documented idempotency contract; concurrent target selection cannot send one client's job to another workspace. Verify concurrency and retry cases.
- AC-06: A supported old client still operates after rollout; public docs, OpenAPI and actual installer artifacts match the release. Verify a pinned old/new compatibility matrix and rollback.

## Open decisions

- D1: Final broker resource/error schema and operation limits; resolve in VST-008 alongside the identity contract before dependent code.
- D2: Public origin, release owner, provenance verification and supported compatibility window; blocks installer release, not the inventory pass.
- D3: Which legacy routes need a deprecation window versus permanent aliases? Resolve before changing any existing route.

## Project plan

| Ticket | Bounded outcome | Depends on | Criteria covered | Verification |
| --- | --- | --- | --- | --- |
| [VST-008](../tickets/VST-008.md) | Operation inventory and API contract | None | AC-01 | Source/contract mapping and schema validation |
| [VST-009](../tickets/VST-009.md) | Discovery, guidance and installer distribution | VST-008 | AC-02, AC-03, AC-06 | Release install/failure and discovery matrix |
| [VST-010](../tickets/VST-010.md) | Authorized routing parity and compatibility | VST-008, VST-005, VST-006 | AC-04, AC-05, AC-06 | REST/client parity, replay and upgrade tests |

VST-008 is the first actionable contract task. Guidance/release work can proceed
independently of connector implementation after that shared contract is settled.

## Decision history

- 2026-09-21: Stable REST, guidance and installer URLs are user-requested. Preserve implemented v1 paths while specifying a separate public broker contract.

- 2026-09-21: User requested removal of the combined agent-access proposal. Review this feature in its own specification; no proposed architecture is approved by that removal.
