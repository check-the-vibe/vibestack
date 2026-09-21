# Workspace MCP

The workspace service exposes authenticated Streamable HTTP at `/mcp`, on the
same origin and in the same process as REST. It uses the shared credential store,
capability registry and dispatcher. It has no Docker socket or host lifecycle
authority. The optional host runner has a different endpoint and credentials.

The registered workspace tools cover status, argv/shell jobs and their output or
cancellation, project/Desktop files, screenshots, applications/windows, display,
service diagnostics and allowlisted component installation. `project_summary`
reads bounded immediate project metadata without executing repository code.
The authenticated `/api/v1/capabilities` catalog is the grant-filtered inventory.
Clipboard, SSH keys and client administration are excluded from MCP, including
for owner credentials. Passwords, credential issuance and pairing remain human
or local-operator flows. Host operations stay in the separate runner.

Built-ins retain their existing operation IDs. Their registered REST form is
`POST /api/v1/operations/ID`, or the generic capability invocation route, with
the same JSON input as MCP. Existing friendly/raw REST routes preserve their
legacy response shape and limits. Full compatibility-route parity is VST-010;
the registered route and MCP already share validation and dispatch.

## Authentication and client support

Use a personal workspace bearer credential issued by the local operator as
described in [SERVICE.md](SERVICE.md). A restricted probe credential can grant
only `project_summary`. Keep plaintext in a protected file or client secret store,
never in repository MCP JSON, URLs, argv, chat, screenshots or logs.

| Client | Protocol | Authentication | Verification boundary |
| --- | --- | --- | --- |
| Official Go SDK 1.7.0 | 2026-07-28 | Configured bearer header | Source integration and the mandatory image client probe |
| Official TypeScript SDK 1.30.0 | 2025-11-25 | `requestInit.headers` bearer | Independent source integration and the mandatory image client probe |
| OAuth-only remote harness | Not supported in this configuration | Requires an established authorization server integration | No provider is configured; no discovery/consent support claimed |
| CLI stdio bridge | Go SDK 1.7.0 remotely; negotiated locally | Protected workspace profile | Source fixtures and the mandatory TypeScript SDK subprocess probe |

These are tested SDK clients, not claims that every desktop harness can configure
the same headers. A later provider/harness integration must be verified separately.
The server SDK can negotiate older versions; only versions exercised by these
clients are in this support matrix. See the ticket evidence for actual image and
hosted results, which are separate from source tests.

Every HTTP request authenticates before protocol parsing. Each tool dispatch
rechecks expiry, revocation, instance binding and current grants. A revoked token
cannot keep using an existing client connection. Revocation applies before the
next dispatch; it does not undo an already executing operation. Opaque personal
credentials belong to one instance's store; they are not OAuth/JWT access tokens
with issuer/audience claims. A credential from another instance is rejected.

`X-VibeStack-Expected-Instance` binds requests to an expected discovered identity.
Exact Host and Origin checks also apply to MCP. Forged proxy identity headers do
not grant access. Browser sessions require their CSRF header for MCP POST just as
for REST mutations. The verified SDK clients use bearer authentication.

Missing/invalid credentials receive HTTP 401 and a Bearer challenge, never an
HTML sign-in page. The service does not advertise OAuth protected-resource
metadata or silently fall back to anonymous/trusted-tailnet access.

## Private Codespaces gateway

Project file and command tools support the source mount declared by the launcher,
including when `/projects/vibestack` uses a different filesystem from `/projects`.
The opened source directory establishes that subtree's device boundary. Ownership,
no-symlink and deeper mount checks still apply; requests cannot configure mounts.

Use the forwarded **service** origin ending in `-8080.app.github.dev`, not the
editor URL. Keep port 8080 Private. Two independent layers must authenticate:

1. GitHub's private port gateway uses its own GitHub credential.
2. VibeStack uses `Authorization: Bearer` with the workspace credential.

GitHub documents `X-GitHub-Token` for non-browser access to private forwarded
ports. The Codespace's built-in token rotates after restart. Store it separately
and send it only to the exact Codespace origin; never pass it to tool arguments or
local backend services. No GitHub credential is needed for an approved loopback
connection from the outer Codespace terminal to `http://127.0.0.1:8080`.

The checked-in client probes read paths from `VIBESTACK_MCP_CREDENTIAL_FILE` and
optional `VIBESTACK_MCP_GATEWAY_FILE`; both files must be single-link regular files,
owned by the current user with no group/other permissions. They reject redirects
and print only fixed test outcomes and negotiated versions. Use a temporary
short-lived probe credential; revoke it after verification. Do not paste either
file into a prompt. Browser cookie sign-in is not evidence that these clients work.

## Transport, results and limits

This endpoint is stateless. It does not issue session IDs, retain authenticated
sessions, offer SSE resumption, or accept `Mcp-Session-Id`/`Last-Event-ID`. GET and
DELETE return 405 after authentication. JSON POST responses avoid open streams;
nginx buffering/cache are disabled. New-protocol `server/discover` and the older
initialize handshake are handled by the pinned SDK. Tools are rebuilt from current
grants on each request; refresh `tools/list` after a grant change.

Only definitions with `mcp_policy: enabled` are exposed. Human-only and
owner-opt-in capabilities stay excluded even for an owner credential. This does
not confine the broad `vibe` execution authority of argv or shell capabilities.

Tools return the REST envelope as structured content and JSON text: `instance_id`,
`request_id`, `capability`, `result`. Safe failures set `isError` and carry the
canonical `error` object. The advertised output schema permits success and error
envelopes because the TypeScript client validates structured error results too.
Protocol errors remain protocol errors. Returned text is untrusted data.

Requests have a 24 MiB outer ceiling plus the capability's usually smaller input
budget. The common dispatcher enforces input/output schemas, permission, 32-call
capacity and the declared deadline. The serialized MCP result, including its
legacy text copy, must fit the capability's response budget; use bounded pages for
large data. Framing adds only protocol metadata and the request identifier. No
partial JSON or truncated success is returned. Audit logs contain request/instance
ID, capability, outcome and duration only. SDK payload diagnostics are disabled.

Neither this adapter nor the acceptance clients automatically replay a mutation.
An interrupted request or timeout does not prove remote work was cancelled; inspect
its state before retrying. Durable jobs and explicit cancel operations are supplied
by their workspace capability adapters. Fault injection is tracked in VST-013.

## Verification

### Local stdio connection

Use CLI 0.3.0 from the versioned release installer in [CLI.md](CLI.md), or build
this checkout for development. The earlier 0.2 source lacks the bridge.

```sh
go build -o /tmp/vibestack ./cmd/vibestack
/tmp/vibestack connect --name codespace --url http://127.0.0.1:8080 \
  --token-stdin < /path/to/protected/workspace.token
/tmp/vibestack --profile codespace mcp
```

The final command is launched by a stdio-capable harness. It reads the selected
protected profile, pins its workspace identity and forwards tool lists/calls to
that workspace's `/mcp`. Configure only the executable, profile name and command:

```json
{"command":"/absolute/path/to/vibestack","args":["--profile","codespace","mcp"]}
```

No credential belongs in that harness JSON. Stdout contains protocol frames only;
sanitized errors use stderr. Lists refresh remote grants; no local tool registry,
host mediation or anonymous fallback is introduced. For an explicitly configured
remote private Codespaces origin, `mcp --gateway-token-file /private/path` reads
the separate gateway file on each request and rejects redirects. It does not
read ambient GitHub tokens. `connect --gateway-token-file FILE` supports explicit
private gateway bootstrap and saves only its absolute path; later REST, document
and MCP requests use that file. The command override is optional. Use loopback
from the Codespace terminal when outside-gateway access is unavailable.

File inputs name a relative `path`. Registered reads return `data_base64`, `bytes`,
`content_type` and an ETag; optional `range`, `if_range` and `if_none_match` retain
bounded conditional reads. `headProjectFile`/`headDesktopFile` return metadata.
Writes accept `data_base64` and exactly one condition: `if_match` containing the
observed strong SHA-256 ETag, or `if_none_match: "*"` for create-only. No wildcard
overwrite is accepted. Registered binary transfers are limited to 8 MiB before
base64; legacy raw file routes retain 16 MiB. Screenshots return PNG in the same
base64 shape, or accept a Desktop-relative `.png` filename to return saved-file
metadata. Large or invalid results fail explicitly, without truncated success.

Job submission returns the existing durable `job.id`; polling and output do not
resubmit it. Output is a bounded base64 page with cursor/eof fields. Explicit
`submitShellCommand` differs from argv submission; both run with the broad authority
of `vibe`. Installation accepts supported catalog IDs, never an installer URL.

### Acceptance clients

Run `npm ci` then `bin/vibestack-dev test` for both SDK source integrations. A
standalone Go test run without npm dependencies reports the TypeScript probe as
skipped; that is not the full acceptance gate. `bin/vibestack-dev accept IMAGE`
requires both HTTP probes plus `tests/mcp-stdio-check.mjs`, which launches the
newly built CLI with the independent TypeScript SDK. It checks tool coverage,
status, an argv job/output, conditional project update, stale-write denial and
a PNG screenshot through actual nginx. This mutating probe runs only against the
disposable loopback fixture and prints fixed metadata, never tool payloads.

For a prepared authenticated origin, the probes are:

```sh
VIBESTACK_MCP_BASE_URL=https://YOUR-SERVICE-ORIGIN \
VIBESTACK_MCP_CREDENTIAL_FILE=/path/to/protected/probe.token \
node tests/mcp-client-check.mjs

VIBESTACK_MCP_BASE_URL=https://YOUR-SERVICE-ORIGIN \
VIBESTACK_MCP_CREDENTIAL_FILE=/path/to/protected/probe.token \
go run ./tests/mcp-client
```

Provide the separate protected gateway file for private remote Codespaces access.
No tool is configured to read a secret automatically from the Git repository.

Sources: [pinned Go SDK protocol behavior](https://github.com/modelcontextprotocol/go-sdk/blob/v1.7.0/docs/protocol.md),
[official TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk),
[GitHub private forwarding authentication](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace).
