# SPEC-002 — REST API, agent guidance and CLI distribution

- State: draft
- Initiative: [Agent platform](../initiatives/agent-platform.md)
- Owner: project owner for product decisions; Codex for this drafting pass
- Updated: 2026-09-21
- Decision authority: user requires one-URL AGENTS.md bootstrap, desktop/CLI connection guidance, authenticated MCP and capability access through CLI, REST, MCP and web services; implementation choices below remain proposed
- Supersedes: the retired combined agent-access proposal; these four feature specifications now define the proposed work
- Planning ticket: [VST-004](../tickets/VST-004.md)

This is a target contract, not a claim of shipped behavior. Unresolved decisions
keep the specification in draft; no runtime changes are part of this pass.

## Outcome and user journeys

A person gives an agent harness only `CODESPACE_URL/AGENTS.md`. From that entry
point, the harness immediately knows what VibeStack can do, how to authenticate,
how to interact with the selected service, and how to guide the user to connect
from a desktop application or CLI. It also discovers how to connect a supported
MCP client over authenticated MCP, without requiring repository knowledge or
additional undocumented setup instructions.

Here `CODESPACE_URL` means the VibeStack service's forwarded HTTPS origin, such as
`https://<codespace-name>-8080.app.github.dev`, rather than the VS Code editor URL.
The guide must work for that instance and must not hard-code one Codespace name.
The same entry-point contract applies to other supported VibeStack service origins.

Capabilities are exposed through CLI, REST API, authenticated MCP and web
services, with a shared meaning and authorization policy. The harness learns
which capabilities are available to it and chooses a supported access method.
Authentication or a required human approval may still need user action; the
single URL provides the instructions and next step, not an authentication bypass.

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
using the service host in [SPEC-001](SPEC-001-service-host.md). Exclude inventing a separate execution engine,
embedding tokens in documentation, or changing authentication independently of
SPEC-001/SPEC-003. Windows distribution is outside the first target matrix.

## Contract

### One-URL agent bootstrap

`/AGENTS.md` is the primary agent-facing entry point, served as readable Markdown
with the deployed service version. It must be sufficient to start using the
service, with links to detailed references when necessary. Do not make the user
supply the repository, a second base URL or a separate instruction prompt.

The guide must provide:

- Service identity, canonical origin, selected/default workspace when authorized,
  version, readiness and a concise capability overview.
- Concrete discovery, authentication and first-operation instructions, including
  an example harmless status/readiness call and its expected response. Examples
  use the service's actual origin and released client syntax.
- Desktop application access: supported applications and platforms, trusted
  download/setup links where applicable, the connection URL/profile fields,
  sign-in steps, workspace selection and a connection check. Distinguish a local
  desktop client from the browser-hosted VibeStack desktop. Do not advertise an
  unimplemented application or an unverified client as supported.
- CLI access: verified installer/download links, platform requirements, install,
  connect/authenticate and status examples, target selection, and where to find
  the full command reference. A user with an existing compatible CLI can connect
  without reinstalling it.
- Provider runtime setup: how an authenticated host/CLI requests a supported
  provider's installation and activation inside VibeStack, observes readiness and
  completes any human sign-in. Link the [provider/overlay contract](SPEC-004-chat-agent-interface.md);
  do not imply that opening an app window proves its API is ready.
- Authenticated MCP access: the advertised endpoint or supported local adapter,
  tested harness configuration examples, supported authentication flow, required
  permissions, credential storage guidance and a harmless tool call that proves
  connection. Link the [MCP contract](SPEC-003-authenticated-mcp.md) for the
  detailed authentication and client-compatibility requirements.
- REST and web service access: API base/schema links, browser entry point,
  capability discovery, operation examples and the applicable authentication
  boundary. Web access can present capabilities through the planned chat agent;
  this does not require keeping the current collection of UI controls.
- How to recover from an offline Codespace, incomplete onboarding, unavailable
  capability, expired authentication or unsupported client, including the exact
  next action and a supported alternative where one exists.

A harness must be able to fetch the guide through a supported access path. If a
private Codespaces forwarding gateway blocks the initial request, provide and
verify the supported gateway-authentication/bootstrap path before claiming the
one-URL flow works for that external harness. An HTML login page is not the guide,
and a browser login does not prove the harness has access. Service authentication
and gateway authentication are separate requirements. Do not make the desktop
public to satisfy discovery. A sanitized public guide, if later selected, may
explain bootstrap but must not reveal private instance inventory or credentials.

No tokens, passwords or provider keys appear in guide content, example URLs or
model context. Describe secure user handoffs and credential storage explicitly.
Reading the guide does not authorize installing software or executing actions
beyond the user's request and the harness's own permission controls.

### Discovery and shared capabilities

The primary service kind is workspace: one instance, one service origin and its
capabilities. The existing host runner has separate discovery and authority; it
is optional and not part of workspace bootstrap. Discovery identifies kind,
server version, supported API versions, canonical origin, document/endpoint URLs
and supported authentication modes. Anonymous discovery exposes no private
workspace state or credentials. Authenticated discovery reports available
capabilities, limits and readiness, including onboarding or app restoration.

Preserve supported workspace routes under `/api/v1/automation` through the
service's authenticated compatibility adapters. The separate runner retains its
own `/api/v1/runner` interface; do not forward workspace callers to host authority.
New capabilities register under `/api/v1/...` without a machine registry or routing
tier. A client profile selects an explicit service URL; concurrent profiles cannot
change another caller's destination. Responses identify the connected instance.

| Surface | Target behavior |
| --- | --- |
| `/.well-known/vibestack` | Minimal discovery and compatibility, no secrets/inventory |
| `/AGENTS.md` | Complete one-URL harness bootstrap, capability overview and desktop/CLI/MCP/REST/web connection guidance tied to the deployed version |
| `/CLI.md`, `/AUTOMATION.md`, `/RUNNER.md` | Applicable versioned references; discovery does not advertise irrelevant documents |
| `/api/workspace.openapi.json`, `/api/runner.openapi.json` | Preserve current contracts; advertise the workspace service schema including registered extensions |
| `/cli.sh` | Reviewable installer with explicit version/install directory and release-channel identity |

Use one operation inventory to map each capability to REST operation IDs, CLI
commands, MCP tools, web service access, authority and verification. Exposure
through all four surfaces is the default requirement; do not silently leave a
capability available only through the UI or a private endpoint. Each mapping must
report implemented, unavailable or a justified human-only handoff, with the
reason and supported next action visible in discovery/guidance. Sensitive human
secret entry remains a secure handoff rather than a model tool accepting secrets.
Cross-surface parity means the same targets, permissions, effects, result states
and errors, while allowing transport-appropriate presentation. Preserve argv versus
shell distinction. Workspace jobs and host lifecycle operations have different
IDs, states and cancellation semantics; return bounded cursor-based output.
File writes retain preconditions and no-follow/project-root boundaries. Keep each
operation's declared retry/idempotency behavior; where keys are
supported, conflicting payload reuse fails. Do not add a global dispatch ledger
or blindly retry a command whose result is unknown. Existing APIs get additive
changes; breaking behavior requires a new
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
Print the next connect action without credentials; do not elevate,
edit shell profiles or embed secrets. Document download-and-inspect installation.

## Design decisions and alternatives

Recommend shared operation definitions and thin transport adapters over rewriting
APIs into a single new route tree. Keep optional runner discovery separate from
workspace
instructions so an agent does not accidentally use host authority. Use SPEC-001's
capability registration for new endpoints/tools and a generic CLI invocation path
to avoid needing a client release for every user-authored capability. Human-readable
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

- AC-01: A contract inventory maps every capability to CLI, REST, MCP and web service access, authority and verification. All four are the default; any unavailable surface or human-only handoff has an explicit reason and next action. Schema/coverage checks catch undocumented omissions and drift.
- AC-02: Give a supported agent harness only `CODESPACE_URL/AGENTS.md`, with no repository context or extra setup prompt. Verify it retrieves Markdown through the supported gateway access path, identifies the service and available capabilities, gives working desktop-app and CLI connection guidance, and discovers authenticated MCP, REST and web access. Follow the guide to a harmless authenticated REST/CLI operation and MCP tool call using supported clients; verify the desktop connection instructions. Record any human authentication steps and client versions. Anonymous discovery leaks no private inventory or secrets; authenticated discovery reflects the caller's grants. Include a fresh Codespace and a locally hosted instance; optional host-runner access remains explicitly separate.
- AC-03: Fresh install and upgrade succeed for each supported OS/architecture; invalid checksum, redirect, missing version or interruption preserves the prior CLI. Verify disposable native/release environments, not just shell syntax.
- AC-04: Calls through CLI, REST, MCP and web services apply the same target authority, operation semantics, file preconditions and job/output limits for built-in and user-authored capabilities. Denied-permission, wrong-instance, oversized and malformed requests have consistent bounded failures. Verify a shared operation matrix across all four surfaces, including declared unavailable capabilities and human handoffs; no transport bypasses authentication.
- AC-05: Lost responses and duplicate submissions obey the documented idempotency contract; concurrent target selection cannot send one client's job to another workspace. Verify concurrency and retry cases.
- AC-06: A supported old client still operates after rollout; public docs, OpenAPI and actual installer artifacts match the release. Verify a pinned old/new compatibility matrix and rollback.

## Open decisions

- D1: Final capability definition, route/CLI invocation conventions, error schema and operation limits; resolve in VST-008 against the small extension example in SPEC-001.
- D2: Public origin, release owner, provenance verification and supported compatibility window; blocks installer release, not the inventory pass.
- D3: Which legacy routes need a deprecation window versus permanent aliases? Resolve before changing any existing route.
- D4: Which desktop applications and agent harnesses are supported initially, and how can each fetch the guide and authenticate through a private Codespaces gateway? Resolve the client/bootstrap matrix in VST-009 with SPEC-003 before claiming end-to-end one-URL access. The one-URL entry point and four-surface capability requirement are user decisions, not open alternatives.

## Project plan

| Ticket | Bounded outcome | Depends on | Criteria covered | Verification |
| --- | --- | --- | --- | --- |
| [VST-008](../tickets/VST-008.md) | Operation inventory and API contract | None | AC-01 | Source/contract mapping and schema validation |
| [VST-009](../tickets/VST-009.md) | One-URL guide, desktop/CLI bootstrap and transport discovery | VST-008, VST-005 | AC-02, AC-03, AC-06 | Guide-only harness/client journey, gateway access and release install/failure matrix |
| [VST-010](../tickets/VST-010.md) | Capability parity and compatibility | VST-006, VST-012 | AC-04, AC-05, AC-06 | Built-in/extension behavior through CLI, REST, MCP and browser HTTP |

VST-008 is the first actionable contract task. Guidance/release work follows the
shared contract and running service. Full AC-02/AC-04 validation needs the real MCP
adapter from SPEC-003. An authenticated browser HTTP client can verify web access
before SPEC-004's chat UI exists. VST-009/VST-010 record their portion; linked
instructions or mocked transports alone do not complete those criteria.

## Decision history

- 2026-09-21: Stable REST, guidance and installer URLs are user-requested. Preserve implemented v1 paths while specifying a separate public broker contract.

- 2026-09-21: User requested removal of the combined agent-access proposal. Review this feature in its own specification; no proposed architecture is approved by that removal.

- 2026-09-21: User requires supplying only `CODESPACE_URL/AGENTS.md` to bootstrap an agent harness, including desktop-app/CLI guidance, authenticated MCP and capabilities exposed through CLI, REST, MCP and web services. Added the guide contract and end-to-end criteria; client selection and private-gateway bootstrap remain implementation decisions.

- 2026-09-21: Aligned with the user-requested SPEC-001 rewrite: one extensible workspace service, no required machine broker, shared authenticated REST/MCP capabilities. Other feature-specific decisions remain draft.
