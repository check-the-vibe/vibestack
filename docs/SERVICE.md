# Workspace service

One supervised Go process, `vibestack-service`, listens on `127.0.0.1:7996`
inside VibeStack. nginx forwards API, browser-session and MCP paths to it.
Existing execution/control/setup services remain on loopback 7997–7999.
The application has workspace authority and no Docker socket. The separate
host runner retains its own deployment, credentials and API.

This foundation supplies authentication, compatibility adapters and static
publication. The direct MCP adapter and user-authored capability registrations
are subsequent tickets; `/mcp` authenticates and then reports unavailable until
that adapter is installed. Do not advertise it as a working remote MCP server yet.

## Credentials and browser access

Existing automation tokens and previously paired workspace credentials remain
usable for workspace operations. New credentials are created by a local operator
and can have an expiry and an operation allowlist. Only explicitly issued owner
credentials can administer pairing/clients or set the Linux password. Arbitrary
workspace commands already convey the authority of `vibe`; an operation allowlist
is not a sandbox for a client granted command execution.

Run this inside VibeStack as `vibe` to create a browser credential:

```sh
vibestack-service credential create --label browser --owner \
  --output /data/vibestack/browser.token
```

From the outer Codespace terminal, prefix that command with
`docker exec -u vibe vibestack-codespaces`. The command writes a new `0600` file
and prints only its path, credential ID and expiry. It preserves an existing file.
The default expiry is 30 days; `--expires-in` accepts a Go duration up to one year.
Keep credentials out of Git, URLs, chat prompts, command arguments and logs.
The local operator can read/copy the file privately into `/connect.html`; the
input clears immediately and the browser retains only an HttpOnly, host-only
SameSite=Strict session cookie. HTTPS sessions are Secure. There is no default
password or anonymous credential issuer.

Browser mutations require a session-bound CSRF header. Sessions last at most
eight hours and end when their credential expires/revokes or the service restarts.
Credential and Linux password state persist through image replacement. Provider
authentication is separate from workspace authentication.

For CLI access, use the updated client built from this source. Release/bootstrap
verification belongs to VST-009. Protected stdin is supported:

```sh
vibestack connect --name workspace --url https://YOUR-SERVICE-ORIGIN \
  --token-stdin < /path/to/your/protected/credential-file
vibestack --profile workspace status
```

Use the actual forwarded service origin, not the Codespace editor URL. Private
Codespaces forwarding still needs its own GitHub authorization or an approved
local tunnel; a workspace credential does not bypass that gateway. The guide and
two-client MCP bootstrap are verified in their dependent tickets.

Local management commands, run as `vibe`:

```sh
vibestack-service credential list
vibestack-service credential revoke --id CREDENTIAL_ID
vibestack-service credential create --label status-client \
  --capabilities workspaceStatus --expires-in 24h \
  --output /data/vibestack/status-client.token
```

New credentials are stored only as hashes in `/data/vibestack/service-credentials.json`.
The shared identity and `client-auth.lock` remain compatible with the existing
Python client store. Directory mode is `0700`; identity/credential files must
be regular, owned by `vibe`, single-link and `0600`. Unsafe/corrupt state fails
closed. Every API/session request rechecks the underlying credential; no stale
in-memory grant survives revocation. Credential administration is local-only
in this foundation. Revoking a browser credential also revokes its sessions.

Discovery retains the historical `authentication_mode: paired` field for the
0.2 client wire contract, while advertising bearer credentials and local issuance
in the detailed authentication metadata. It no longer advertises anonymous
pairing. Existing credentials and `connect --token-stdin` remain supported. The old 0.2
CLI omits authorization on friendly status/display/services/logs commands; those
commands now require a client upgrade or its authenticated `api` command. Old
automation commands already send credentials. Uncredentialed `connect` requires
the new guide's human/local bootstrap. This is an intentional authentication
migration, not a claim that every old friendly command still works.

## Routes and compatibility

| Route | Foundation behavior |
| --- | --- |
| `/.well-known/vibestack` | Sanitized versions, stable identity, origin and auth/document links |
| `/healthz` | Process readiness only; no private inventory |
| `/api/workspace.openapi.json` | Packaged compatibility schema |
| `/api/v1/capabilities` | Authenticated, grant-filtered source operation catalog; MCP availability is explicit |
| `/auth/session` | POST exchanges a bearer credential for a browser session; GET inspects that session; DELETE signs out with CSRF protection |
| `/api/v1/...`, `/setup/api/...` | Existing operation paths through shared authentication, grants and bounded local adapters |
| `/mcp` | Authenticates, then reports unavailable until the MCP adapter lands |
| `/connect.html` | Human browser credential handoff |
| Other published paths | Files from the configured publish directory only |

API aliases no longer rely solely on the private gateway. Unknown API routes
return an error and cannot fall through to the old services or a static index.
The application strips external credentials/cookies/forwarded identity headers
before calling a backend; automation receives its protected internal token.
JSON, raw files, ETags, range reads and existing response bodies retain their
operation semantics. Limits remain 4 KiB control JSON, 64 KiB setup JSON,
1 MiB + 4096 automation JSON, and 16 MiB raw files. New generic JSON capabilities
will use the [shared contract](architecture/capability-contract.md).

The private desktop WebSocket, terminal and editor routes still use the outer
private boundary during migration. Keep Codespaces ports Private and local Docker
loopback-bound. This foundation does not authorize public desktop access.
Legacy UI removal is VST-016; provider/chat deployment is separate work.

## Publishing static files and operating the service

Add publishable files beneath `web/public/`, then rebuild. They are packaged at
`/usr/share/vibestack/public`; adding a file requires no new nginx route.
`/status.txt` is the minimal smoke check. Never set the publish root to the Git
checkout, `/projects`, `/data` or a home directory. Hidden files, credential/key
filenames, directory listings, non-regular files, traversal and symlinks are
rejected. Static content is trusted same-origin application code, not user uploads.

`VIBESTACK_PUBLIC_URL` sets the canonical HTTPS origin; `VIBESTACK_ALLOWED_HOSTS`
adds exact custom hosts. Configure the actual Tailscale/Codespaces hostname.
The listener remains loopback; forged forwarding headers cannot set identity or
origin. Application errors carry an opaque request ID and instance ID, with
bounded messages and no request content. The envelope retains top-level legacy
`code`/`message` aliases (including `unauthorized`) alongside its canonical nested
error. nginx generates and overwrites the correlation ID; the service preserves
that bounded ID only from its loopback proxy. It is never a retry key.
Unknown mutation outcomes are not
automatically retried. Static and authenticated-service readiness are distinct.

Use `bin/vibestack-dev test`, then build/accept an isolated candidate. Disposable
acceptance creates its own temporary owner credential, uses it for onboarding
and browser tests, and removes the entire fixture afterward. Authenticated
Playwright traces are disabled to keep cookies/credentials out of artifacts.
For an explicitly selected running target, set `VIBESTACK_BROWSER_CREDENTIAL_FILE`
to a protected local file before `bin/vibestack-dev browser`; do not put a token
in an environment variable. Live checks use the existing local automation token
without printing it or placing it in process arguments.
