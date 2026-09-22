# Add a workspace capability

VibeStack enables trusted Go modules at build time. One registration supplies
input/output schemas, permission, limits, effects, retry policy and a handler.
The service derives generic REST, the friendly route, authenticated discovery
and OpenAPI from it. [MCP](MCP.md) exposes the registered ID when its policy is
`enabled`; human-only and owner-opt-in tools are excluded by default.

The working example is [register.go](https://github.com/check-the-vibe/vibestack/blob/main/service/capabilities/register.go) with
[project_summary.json](https://github.com/check-the-vibe/vibestack/blob/main/service/capabilities/project_summary.json). It counts
immediate entries of one named `/projects` child without running shell/git code.
Missing projects return `exists: false`; symlinks and inaccessible paths fail.

1. Add a module in `service/capabilities/` with a definition matching
   [contract version 1](https://github.com/check-the-vibe/vibestack/blob/main/contracts/capability-definition-v1.schema.json).
   Declare unknown-field policy, bounded fields, permission, deadline,
   request/result budgets and honest effect/retry metadata.
2. Implement `Handler(context.Context, Principal, json.RawMessage) (any, error)`.
   Supply fixed roots/backend dependencies through registration, never request
   input. Respect cancellation. Return `capabilities.Fail(code)` for a documented
   failure; other errors/panics become sanitized internal errors. Do not log input
   or output. The module runs as trusted `vibe` code, without a Docker socket.
3. Add one entry to `Builtins` in `register.go`. Use an unused ID and literal
   `/api/v1/...` friendly route. GET/HEAD use declared scalar query properties;
   other methods take the input object as `application/json`. The generic POST
   always takes that input object. Parameter/raw-file aliases need explicit
   compatibility adapters. No nginx, authentication or listener edit is needed.
4. Add focused handler, schema and denial tests, then follow the
   [candidate workflow](https://github.com/check-the-vibe/vibestack/blob/main/docs/DEVELOPMENT.md#candidate-image-and-disposable-acceptance).
   Rebuild and deliberately deploy after acceptance. Editing shared source does
   not alter a packaged running binary. There is no dynamic plugin loader.

Authenticate using [SERVICE.md](SERVICE.md), then inspect
`GET /api/v1/capabilities` and `GET /api/capabilities.openapi.json`. Both filter
by grant. Invoke `POST /api/v1/capabilities/project_summary/invoke` or
`POST /api/v1/project-summary` with `{"project":"vibestack"}`. They return the
same envelope/errors. Browser mutations also need the session CSRF header. The
CLI supports `vibestack capability list`, `vibestack capability schema` and
`vibestack capability call project_summary --input -` (JSON on stdin). A new
registered capability works through these generic commands without a CLI release.

GET/HEAD registrations must declare a read effect and scalar query fields.
Every object schema, including nested output objects, declares its unknown-field
policy. At most 128 registrations and 1 MiB of combined definitions are accepted.

Duplicate/reserved IDs/routes, missing handlers, invalid or remote schemas and
unspecified unknown-field policy reject startup. Removing a registration removes
its route, invocation, discovery and schema on next deployment. Use the launcher's
rollback workflow to retain the previous service if a candidate fails.

Dispatch checks permission/input before execution, starts at most 32 handlers,
invokes each once, and validates/bounds the serialized result and full REST
envelope. MCP also bounds its serialized structured/text result by the declared
response budget. It never truncates JSON or replays mutations. Deadline/disconnect does
not prove a mutation was undone: inspect state before retrying. A timed-out
non-cooperative handler keeps its capacity slot until it exits, bounding
background work. Trusted modules must avoid unbounded allocation and respect
cancellation; this is not a sandbox for third-party code.

Audit records contain request/instance ID, capability, outcome and duration;
never arguments, credentials, file contents or command/provider output. Real
CLI/MCP parity is covered by VST-010/VST-012; final hosted acceptance is VST-007.

The disposable `bin/vibestack-dev accept` workflow includes an executable
authoring demonstration in `tests/extension-authoring-check.py`. It copies only
build inputs, adds one bounded echo definition/handler and registration, compiles
it, and checks duplicate IDs and invalid schemas reject startup. In the named
acceptance container it replaces the workspace binary temporarily, invokes the
new capability through REST, MCP, generic CLI and authenticated Chromium, then
restores the original binary and verifies every discovery/dispatch surface drops
the removed capability. It also checks narrower grants and input errors. This
does not install an extension in a live workspace or introduce runtime loading.
Production extensions still follow the complete image build/accept/deploy path.
