# Workspace MCP

The workspace service exposes authenticated Streamable HTTP at `/mcp`, on the
same origin and in the same process as REST. It uses the shared credential store,
capability registry and dispatcher. It has no Docker socket or host lifecycle
authority. The optional host runner has a different endpoint and credentials.

`project_summary` is the first registered workspace tool. It accepts `project`
and optional `max_entries`, reads bounded directory metadata under `/projects`,
and executes no repository code. Other legacy workspace routes remain REST-only
until their capability adapters land. The authenticated `/api/v1/capabilities`
catalog reports availability per operation; never infer tools from planned specs.

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
| Local stdio harness | Subsequent VST-012 adapter | Protected local profile/file | Not supplied by this transport increment |

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
not weaken the authority of any command capability that may be granted later.

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

Run `npm ci` then `bin/vibestack-dev test` for both SDK source integrations. A
standalone Go test run without npm dependencies reports the TypeScript probe as
skipped; that is not the full acceptance gate. `bin/vibestack-dev accept IMAGE`
requires both probes and exercises them through the candidate's actual nginx.

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
