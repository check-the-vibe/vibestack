# Automation API architecture

## Boundary and service topology

The automation service is a Python standard-library process running as the
single interactive `vibe` user. It binds only to `127.0.0.1:7997`; nginx is the
sole browser/container entrypoint and proxies `/api/v1/automation`. The
existing control service remains a separate, narrow API on 7998 for the
VibeStack shell's status, display, log, and allowlisted restart operations.

The split is intentional. A control request cannot express an arbitrary
command, file, application, process, or window. A paired client credential or
compatible legacy automation token, by contrast, is an explicit
remote-code-execution credential with the same authority as a local `vibe`
shell.

The runtime trust boundary is:

```text
tailnet client ── HTTPS/Tailscale Serve ── host 127.0.0.1:8080
                                             │
                                             ▼
                                           nginx
                                             │
                     /api/v1/automation ─────┴── 127.0.0.1:7997
                                                        │
                         fixed session env ── X11 :0 / XFCE / Desktop
```

Raw X11, VNC, websockify, setup, control, and automation listeners are
container-loopback-only. Xvfb uses MIT-MAGIC-COOKIE authorization and
`-nolisten tcp`; all graphical subprocesses receive the protected
`XAUTHORITY`. Docker uses its default seccomp profile and a process limit.
The browser-stream backends additionally reject direct WebSockets: nginx
overwrites `X-VibeStack-Proxy` with a fixed marker. A root-owned websockify
plugin requires exactly one constant-time exact match. The fixed marker is a
browser-direct-access guard, not a user credential.

## Request authorization

At first boot the service generates 32 random bytes and stores their encoded
form in `~/.vibestack/automation.token` with mode `0600`. The `.vibestack`
directory is persistent under `/data`. That legacy credential remains valid
for compatibility. New clients pair through an expiring device flow and
receive a separate revocable credential whose hash, device label, permissions,
and timestamps are stored below the same private persistent state. Bearer
comparisons are constant-time.

The pairing request and polling routes are the only unauthenticated automation
routes. Every other route, including capability discovery, requires exactly one
`Authorization: Bearer` value. A pending request lasts ten minutes, the number
of pending records is bounded, and its short operator verification code cannot
retrieve a credential: polling additionally requires the distinct high-entropy
secret returned only to the requesting client. The credential is returned
once after approval. Approval, denial, listing, and revocation are same-origin
Setup operations; they never expose credential material.

Requests also require one Host from the concrete loopback, valid multi-label
`*.ts.net`, or operator-configured exact hostname/IP allowlist, with an optional
valid port. `VIBESTACK_ALLOWED_HOSTS` is validated and rendered into a bounded
literal nginx map before services start. The same check runs on the direct
automation, setup, and control listeners, not only at nginx. If Origin is
supplied its authority must match Host. Cross-site and same-site fetch metadata
is accepted only for an exact safe top-level `GET`/`HEAD`
navigation: mode `navigate` and destination `document` or the
extension-generated `empty`; cross-site subresources and mutations are rejected.
The scheme may differ across Tailscale TLS termination. The servers
do not emit CORS opt-in headers. These browser checks reduce credential misuse
but do not weaken or replace bearer authentication.

Before routing any surface, nginx accepts only loopback Host values, valid
multi-label Tailscale MagicDNS names ending in `.ts.net`, or exact validated
operator-configured hosts, with an optional port. Unknown hosts—including
underscores, userinfo, slashes, malformed DNS labels, and lookalike suffixes—
receive 421. This edge check closes DNS-rebinding access to the unauthenticated
setup, terminal, desktop, and control surfaces;
backend Host/Origin comparison remains defense in depth for mutations. The
edge also permits an absent Origin for CLI clients, but otherwise requires one
HTTP(S) Origin whose authority exactly matches the request Host
case-insensitively. The scheme may differ across Tailscale TLS termination.
Malformed, null, multiple, or credential/path-bearing values fail before
static, API or noVNC/WebSocket routing. Safe top-level `GET`/`HEAD`
navigations may carry `cross-site` or `same-site` with destination `document`
or extension-generated `empty`; all other such fetch metadata fails at the
edge.

Responses use `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and
an `X-Request-ID`. At the public nginx boundary, nginx always overwrites any
caller-supplied value with its own `$request_id`; the loopback service reuses
that validated value so the response, access record, structured error, and
audit event correlate. A direct loopback caller can supply a syntactically
valid ID, but the service is not exposed outside the container.

## Desktop session environment

`xfce-startup` establishes one protected runtime directory and writes a
mode-0600 session environment file after D-Bus/keyring startup. Automation
children receive a fixed base including:

- `HOME=/home/vibe`, `USER=vibe`, `LOGNAME=vibe`, and a fixed system `PATH`;
- `DISPLAY=:0` and `/run/vibestack/Xauthority`;
- `/run/vibestack/runtime` as `XDG_RUNTIME_DIR`;
- the live session D-Bus and keyring variables.

The API accepts only bounded ordinary environment keys and prevents callers
from replacing security/session fields. This makes a normal command graphical
by default while avoiding the fragile practice of setting only `DISPLAY`.

## Command jobs

The command route requires an argv array and the shell route deliberately
invokes `/bin/bash -lc`. Both produce asynchronous jobs. There are four worker
slots, a 32-item queue, and a 1–300 second timeout. Each job runs in a new
process group. Timeout and cancellation first terminate and then kill the
complete ordinary descendant group; the same cleanup occurs when a leader
exits normally, before a terminal job state is published.

Metadata and two byte streams are stored below a mode-0700 job directory.
Each stdout/stderr stream is capped at 4 MiB and page reads return base64 with
explicit byte cursors. This preserves binary output, bounds memory and disk,
and keeps command output out of HTTP/service audit logs. Jobs use explicit
states and timestamps so a caller can distinguish queueing, active execution,
normal exit, nonzero exit, timeout, and cancellation.

The submission request ID follows the in-memory job lifecycle. Once a job
becomes terminal, the runner consumes that correlation value and emits exactly
one best-effort `job.terminal` audit event. Its reviewed metadata is limited to
job ID/kind, terminal state, exit/error code, stream byte counts, and
truncation flags. A repeated cancellation or poll cannot emit it again, and an
audit-write failure cannot change the completed job's result.

## Fixed applications and ephemeral windows

Application lifecycle is driven by a checked-in catalog. Each record owns its
probe, exact launch argv, and catalog-defined `WM_CLASS` allowlist. Browser
input selects only a catalog ID. A stop operation never turns the URL into a
regular expression, command, executable, or arbitrary PID selection. Because
multiple application instances can share a class, window matching is an
allowlisted lifecycle convenience rather than proof of process identity.

Starts are serialized and retain a short per-application launch lease until a
window can appear. Responses distinguish `started`, `already_running`, and
`launch_pending`, so concurrent callers do not create duplicate launches.
Stops use one bounded deadline. They either cancel a still-tracked launcher
process group, return a conflict while a detached launch is unresolved, or
send asynchronous `WM_DELETE_WINDOW` requests to revalidated windows. The
response therefore reports `pending_launch_cancelled` and `close_requests`,
not an unverified count of windows already closed.

XFCE's window manager implements the Extended Window Manager Hints contract.
The backend combines `wmctrl`, `xdotool`, and `xprop`: enumerate EWMH client
windows, capture their current identity/state, and revalidate the XID before a
minimize, maximize, or normal request. XIDs are ephemeral capabilities, not
persistent application identifiers.

## Project and Desktop file confinement

The two file roots are exactly `/home/vibe/Desktop` and `/projects`. Paths are
decoded once and validated as relative UTF-8 components with a 4096-byte total
limit. Each parent is walked descriptor-relative with `O_NOFOLLOW`; device,
owner, directory/type, and link-count checks reject symlinks, mount crossings,
hard links, and special files. The final regular file is opened relative to the
verified parent. The same root selector is additive on command and shell jobs:
old requests still default to Desktop, while new project-aware clients select
`projects` explicitly and do not substitute Desktop on an older server.

The HTTP handler accepts one bounded raw body (at most 16 MiB), and the file
store writes it to a random same-directory temporary file, hashes and syncs
it, then atomically commits it. `If-None-Match` creation is
an atomic create-if-absent operation. API writes are serialized, and an
`If-Match` replacement revalidates the exact inode, metadata, and content
immediately before atomic replacement. Linux does not provide an atomic
pathname compare-and-swap against unrelated writers, so the final revalidation
is best effort when a local process modifies the same Desktop leaf without
using this API. Downloads provide metadata, one bounded range, and no
MIME-dependent transformation. The convenience boundary prevents accidental
path confusion; it is not a sandbox against a caller who also holds
command-execution authority.

## Screenshots and clipboard

Screenshot capture invokes a fixed `scrot` argv in the established display
environment and reads PNG data directly from its documented standard-output
mode, avoiding a shared temporary pathname. The service validates the complete
PNG before returning or atomically saving it. User input can select only a
confined `.png` destination.

The v1 clipboard is the UTF-8 X11 `CLIPBOARD` selection, not PRIMARY. Because
the selection is owned rather than stored by the X server, the service keeps a
managed `xclip` owner alive and replaces it on writes. Reads and writes are
bounded to 1 MiB. Rich MIME targets are deliberately deferred.

## Logging and retention

All operational logs persist below `/data/logs/vibestack` and are linked into
the Desktop as `VibeStack Logs`:

- nginx writes JSON access events using `$uri`, never query strings,
  Authorization, cookies, or request bodies;
- automation writes one redacted JSON audit event per privileged request plus
  one terminal-lifecycle event for each accepted command or shell job;
- Supervisor writes one redirected, rotating stream per service under
  `services/`;
- nginx errors have their own bounded file.

Nginx access fields include time, request ID, source metadata, route, duration,
status, and byte counts. The correlated automation audit adds the privileged
operation and safe target identity. They exclude tokens, command argv/text,
custom environment values, clipboard contents, file/request bodies,
screenshots, and stdout/stderr. File paths are retained because they are
essential to diagnose file operations; job output remains in the private job
store. Terminal job events expose byte counts and truncation flags, never
stream content, and retain the submission request ID so asynchronous outcomes
can be correlated without logging command text.

Fixed XFCE menu actions append metadata-only events to
`desktop/actions.jsonl` in the same tree.

### Filesystem ownership boundary

The root bootstrap first validates the no-follow, non-group/world-writable
`.vibestack-state-v1` directory marker, then walks every persistent log
component descriptor-relative and fails closed on symlinks, hard links,
special files, mount crossings, and path replacement. `/data` is `root:vibe`
mode `1770`:
UID 1000 can create and retain its own state, while the sticky bit prevents it
from replacing the root-owned `/data/logs` entry. `/data/logs`, `services`, and
`nginx` are root-controlled; their Supervisor/nginx log leaves are created and
validated before either service starts. The group-writable sticky VibeStack
log root permits only the `vibe`-owned audit leaf and desktop audit directory
to rotate their own data.

These logs are operational diagnostics, not a tamper-resistant security
ledger: the automation token deliberately grants arbitrary execution as the
same `vibe` account that owns its audit and desktop-action records.

User persistence and instruction seeding run only after the entrypoint drops
to `vibe`, including creation of the Desktop log symlink; startup never
recursively changes `/data` or `/projects` ownership.
On every container start, the root bootstrap removes the exact
`/run/vibestack` tree without following entries and recreates it. The parent is
`root:vibe` mode `1770`, `runtime` is `vibe` mode `0700`, the Xauthority is
`root:vibe` mode `0640`, and XFCE publishes `session.env` as `vibe` mode
`0600`.

## Route contract and limits

| Route | Contract |
|---|---|
| `GET /api/v1/automation` | Capability and limit discovery. |
| `POST /commands` | `{argv,cwd?,env?,timeout_seconds?}`; returns job, 202. |
| `POST /shell` | `{command,cwd?,env?,timeout_seconds?}`; returns job, 202. |
| `GET /jobs/{id}` | Job metadata. |
| `GET /jobs/{id}/output` | One bounded base64 stdout/stderr page. |
| `POST /jobs/{id}/cancel` | Exact `{}` body; returns job. |
| `POST /screenshot` | Raw PNG for `{}` or saved file metadata for `{filename}`. |
| `GET /applications` | Fixed catalog with installed/running/window state. |
| `POST /applications/{id}/start|stop` | Exact `{}`; catalog ID only; reports pending launch or asynchronous close-request state. |
| `GET /windows` | Active XID and revalidated client-window records. |
| `POST /windows/{xid}/state` | `{state}` from minimized/maximized/normal. |
| `GET|PUT /clipboard` | Raw UTF-8 text/plain, at most 1 MiB. |
| `GET|HEAD|PUT /files/{path}` | Raw Desktop bytes, at most 16 MiB. |
| `GET|HEAD|PUT /projects/{path}` | Raw `/projects` bytes with the same bounds and preconditions. |
| `GET|POST /ssh-keys` | List fingerprints or add one bounded public key. Private keys are never accepted. |
| `POST /ssh-keys/{id}/remove` | Remove one API-managed public key by stable ID. |
| `POST /pairing/requests` | Request an expiring device pairing; unauthenticated and rate/bound limited. |
| `POST /pairing/requests/{id}/poll` | Poll using the separate secret; deliver an approved credential once. |

Unknown routes are 404, unsupported methods are 405, and exact-schema errors
are 400. Authentication failure is 401. Preconditions, ranges, queue pressure,
conflicts, and unavailable session/application state use their corresponding
HTTP status rather than falsely reporting success. Errors produced by the
automation service use `{code,message,request_id}`. Nginx can reject a request
before proxying it (for example, an invalid Host), in which case its edge error
body is not part of this JSON contract.

The operator-facing examples are in [`docs/AUTOMATION.md`](../AUTOMATION.md).
