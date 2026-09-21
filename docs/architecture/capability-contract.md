# Workspace capability contract, version 1

This is the implementation contract for VST-005 through VST-016, agreed in
[VST-008](../../.context/tickets/VST-008.md). It does not advertise endpoints as
deployed. The [source inventory](../../contracts/capability-inventory-v1.json)
records the baseline 43 workspace and 21 optional host operations, including
12 setup operations absent from the published OpenAPI, plus service transport
routes added during implementation. Its `current` mappings
describe source support; `target` describes the migration. An HTTP operation in
the web column is not evidence of a dedicated browser control or a live test.

## One registration, one dispatcher

Use one Go application, `cmd/vibestack-service`, with explicit compiled
registrations in `service/capabilities/`. A registration consists of the metadata
in [the definition schema](../../contracts/capability-definition-v1.schema.json)
and one Go handler. The handler receives a cancellation context, an authenticated
workspace principal, validated JSON input and internal service dependencies.
Never take the principal, service credentials or workspace root from input.
This metadata is not a runtime code-loading or package-install format.

The dispatcher resolves authentication on every call, checks instance and
capability grants, validates input, applies limits, invokes the handler once and
validates/bounds its output. REST, MCP and browser HTTP call that dispatcher;
the CLI calls REST. No adapter has an independent permission policy. Native
provider processes still have their own workspace privileges and approval
controls; registering a tool does not sandbox their shell/file access.

An explicit startup registration rejects duplicate IDs, MCP names and REST
method/path pairs, invalid schemas, unavailable handlers and reserved routes.
IDs are case-sensitive, 1–64 ASCII letters/digits/underscores, starting with a
letter. Keep existing OpenAPI operation IDs. New IDs should use `snake_case`.
Schema references must be local and resolved at startup; never fetch remote
schemas while validating a request. Unknown object fields are rejected unless
the capability deliberately declares a map. Bound strings, arrays and nesting.

Reserved prefixes are `/mcp`, `/auth`, `/.well-known`, `/assets`, `/api/v1/capabilities`,
and packaged documentation/schema/download routes. Capabilities use `/api/v1/...`
and cannot replace authentication, discovery or static delivery. Trusted
extensions run as `vibe`; a restart/build explicitly enables them. There is no
Docker socket, machine router, plugin uploader or second agent loop.

## Access paths and availability

| Interface | Convention |
| --- | --- |
| Discovery | Authenticated `GET /api/v1/capabilities` returns visible definitions, limits and readiness |
| Generic REST | `POST /api/v1/capabilities/{id}/invoke` with the input JSON object |
| Friendly REST | A registered method/path, for example `POST /api/v1/project-summary`; same dispatcher |
| CLI | `vibestack capability list` and `vibestack capability call <id> --input <JSON>`; human secrets use stdin/file handoffs, never that JSON flag |
| MCP | The registered ID is the tool name; input/output schemas come from the same definition |
| Web | Same-origin authenticated fetch of the REST route; the future overlay is a client |

The generic route is always POST, including reads. Effect/retry metadata, not the
HTTP verb, determines whether a retry is safe. Existing friendly v1 paths,
status codes, raw file responses and CLI commands remain compatibility adapters.
Do not silently redirect authenticated requests to another origin or translate
workspace grants into optional host-runner grants. The runner's `/mcp` is a
separate server; its four workspace proxy tools are not direct workspace MCP.

Discovery reports each surface as `implemented`, `unavailable` or `human-only`,
with an actionable reason/next step for the latter two. Do not list an absent
adapter as implemented merely because its definition exists. Filter inaccessible
capabilities before returning private metadata. Anonymous discovery exposes only
protocol/version/authentication links; it does not expose projects, jobs, users,
client inventory, provider state or credentials.

Credential issuance, pairing approval and password entry are human/local-owner
flows, not MCP tools accepting secrets. Existing setup completion/skip/reset
flags retire with the old UI; installation selections and credentials persist.
Clipboard and SSH-key tools are disabled by default in MCP and require an
explicit owner opt-in; their authenticated REST/CLI path remains available.
This limits accidental model disclosure, not the authority of a client already
granted arbitrary shell execution. Revocation/client listings may be exposed as
owner operations only; a workspace token must not grant client administration.

## Authentication and identity

Use revocable, random instance-bound credentials stored as hashes under a
restricted persistent service directory. Re-read revocation state per request
and MCP tool call, including an existing connection. Never accept tokens in URLs,
logs, model arguments or forwarded identity headers. The initial grant is
`workspace`; an optional capability allowlist can narrow the exposed operations.
Administrative credential/session creation requires a separate local-owner or
explicit owner grant. No anonymous pairing route can issue a new credential.

Compatibility adapters authenticate first, including legacy `/setup/api/*`,
`/api/v1/status`, diagnostics, control and automation aliases. They use a
protected internal credential when calling the old execution service. A browser
session is same-origin, HttpOnly, host-only and short-lived; mutations require
CSRF protection. The local credential/session bootstrap must be implemented and
tested in VST-005/VST-009 before claiming browser API access. Static documentation
can explain a human handoff without containing a token.

The private Codespaces gateway is an additional boundary. A browser login does
not authorize an external harness. Test a supported gateway connection or local
tunnel separately. Personal bearer credentials do not claim OAuth interoperability;
VST-011/VST-013 determine and test the supported MCP-client matrix.

## Results, errors and versions

The new generic route returns `instance_id`, `capability`, server-generated
`request_id`, and `result`. MCP structured content carries the same envelope;
its text fallback contains the same bounded JSON. Friendly legacy routes retain
their existing bodies and gain request/instance headers where compatible.
Never include a request body, exception text, credentials or raw command in errors.

```json
{"instance_id":"example-instance","capability":"project_summary","request_id":"example-request","result":{"project":"demo","exists":true,"entry_count":3,"truncated":false}}
```

Errors have `error: {code, message, retryable}`, `instance_id` and `request_id`;
a fixed same-origin `human_action` path is optional. REST statuses below and MCP
tool errors represent the same failure. Protocol parse errors remain MCP protocol
errors. Failure never becomes a fabricated successful tool result.

| Code | REST | Meaning / retry |
| --- | --- | --- |
| `invalid_input` | 400 | Invalid JSON/schema or unknown fields; fix input |
| `unauthenticated` | 401 | Missing, invalid, expired or revoked credential; authenticate |
| `forbidden` | 403 | Operation grant denied; request owner access |
| `not_found` | 404 | Unknown or inaccessible resource; do not disclose which |
| `wrong_instance` | 409 | Explicit expected-instance header disagrees; fix profile |
| `precondition_failed` | 412 | ETag/create-only condition failed; reread before editing |
| `limit_exceeded` | 413 | Body/result exceeds the declared limit; use paging/ranges |
| `busy` | 429 | Capacity exhausted before dispatch; bounded Retry-After |
| `unavailable` | 503 | Dependency/provider not ready; inspect readiness |
| `deadline_exceeded` | 504 | Outcome may be unknown after dispatch; inspect, do not replay |
| `internal_error` | 500 | Bounded opaque failure; request ID supports diagnosis |

`retryable` means the same request is safe to retry, not merely that a failure
is transient. Unknown mutation outcomes always return false. No caller-provided
request ID is a deduplication key. A client can send an explicit expected instance
ID; the application compares it to its persisted identity before dispatch.
An unknown resource and a resource outside the caller's grant both return 404.

The contract version is independent of the build version. Additive capabilities
and optional response fields remain v1. Do not tighten an existing valid input,
change effects or remove routes without a new version/migration notice. Current
v1 compatibility aliases are retained through this implementation series;
VST-016 explicitly removes only the specified legacy UI routes/flags. Credentials
and Linux password state are never reset as a migration shortcut.

## Limits, jobs and retry

Metadata includes a timeout, input/output byte budgets, effect and retry rule.
Default JSON input is 1 MiB, default serialized result 2 MiB, deadline 30 seconds;
maximum synchronous deadline is 300 seconds. Start with 32 in-flight dispatcher
calls and fail excess work before execution. File capabilities may explicitly
raise JSON limits to 24 MiB to carry at most 16 MiB raw bytes in base64, including
envelope overhead. Legacy raw/range endpoints retain their existing 16/8 MiB
limits and avoid base64. Response limits apply after serialization; do not
truncate JSON or silently report a partial success.

Existing execution semantics remain authoritative:

- Argv: 256 entries, 64 KiB total; shell source: 256 KiB. Argv and shell remain
  distinct operations. Environment: 64 entries and 64 KiB total.
- Jobs: 4 workers, queue 32; default timeout 30 seconds, maximum 300. Each output
  stream stores at most 4 MiB, with pages at most 256 KiB. Preserve cursor bounds.
- Job submission returns a durable job ID. Terminal states are `succeeded`,
  `failed`, `timed_out`, `cancelled`, `interrupted`. On restart, queued/running
  jobs become interrupted and are never re-executed automatically.
- A request/stream disconnect cancels synchronous work where possible, not an
  already accepted durable job. Explicit job cancellation and inspection determine
  its terminal state. Losing the submission response does not authorize replay.
- File writes keep ETag/create-only preconditions and no-follow scoped-root
  checks. Two writes against the same ETag cannot both succeed.
- The optional runner's create operation has its own required idempotency key;
  do not copy its ledger into the workspace dispatcher. Pairing poll delivery is
  one-time. Screenshot-to-file is a mutation, even though capture alone reads.

The inventory's limit profiles record existing constants separately from the
new defaults. Compatibility adapters preserve more restrictive endpoint limits
(for example setup 64 KiB and control 4 KiB). Per-operation retries are
`safe-read`, `inspect-before-retry`, `etag-precondition`,
`required-idempotency-key`, or `one-time-delivery`. No generic automatic mutation
retry or shared job/lifecycle ID space is introduced.

## Harmless extension example and acceptance

[project_summary.json](examples/project_summary.json) is the definition used by
the compiled VST-006 module. Its handler inspects only the immediate entries of a
named `/projects` child, rejecting traversal, absolute paths and symlinks; it
does not run git, repository hooks or shell commands. Return a bounded count and
whether it was truncated. An absent project returns `exists: false`; an
inaccessible/out-of-bound path returns the documented error.

`go test ./contracts` validates the registration and input/output examples with
the pinned JSON Schema engine. `tests/test_capability_inventory.py` verifies
published operation/CLI inventory coverage, setup-only routes and surface exceptions.
VST-006 implements the handler and verifies duplicate/invalid registrations
fail before startup. Deployment is recorded separately in its ticket.
VST-010/VST-013 must invoke it through real REST, CLI, MCP
and browser HTTP, including denial, revocation, malformed input and failure.
Passing a definition test alone is not runtime or four-surface acceptance.

References: [Go MCP SDK v1.7.0](https://github.com/modelcontextprotocol/go-sdk/tree/v1.7.0),
[MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools),
[JSON Schema validation](https://json-schema.org/draft/2020-12/json-schema-validation).
