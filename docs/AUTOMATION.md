# Automating VibeStack

When `startup.sh --mount-source` shares the checkout, it declares the immediate
project directory through `VIBESTACK_SOURCE_PROJECT`. Project file and working
directory operations allow that one mount to establish its own device boundary;
all descendants retain ownership, no-symlink and same-device checks. This is
operator configuration, never a request parameter or a recursive ownership change.

Compiled extensions use the same authenticated workspace service; see
[EXTENSIONS.md](EXTENSIONS.md). Existing raw file/job routes below retain their
compatibility semantics. Authenticated `/mcp` exposes enabled compiled capabilities
through that dispatcher; [MCP.md](MCP.md) describes supported clients and limits.
CLI 0.3 provides `capability list/schema/call` and a stdio bridge
(`vibestack --profile NAME mcp`). Both use an explicitly selected workspace
profile and identity; configured gateway credentials remain separate. Built-in
registered inputs also use `POST /api/v1/operations/ID`; existing raw/friendly
REST responses below stay compatible. Registered file transfers use base64 up
to 8 MiB and require create-only or observed-ETag write conditions. Check the
generated capability schema before forming a tool input.
The generic surfaces retain stable `forbidden`, `not_found`, `invalid_input`,
`limit_exceeded` and `precondition_failed` failures. MCP grant/policy denials use
the same errors even when the requested tool is absent from filtered discovery.
Legacy raw routes keep the compatibility error formats described below.
nginx does not replay API or MCP requests to an upstream. A lost reply or cancelled
MCP request leaves a submitted job's outcome uncertain; inspect its durable ID
and use the explicit cancellation operation when needed. Repeating an argv
submission intentionally creates another job. Conditional file retries retain
their original preconditions and can fail after an earlier write succeeded.

VibeStack exposes its live XFCE desktop through a privileged REST API. It can
run commands in the graphical session, capture screenshots, start and stop
known applications, list and change the state of windows, transfer arbitrary
Desktop or project files, manage API-owned SSH public keys, and read or replace
the X11 clipboard.

The API is designed for a local coding agent on the Docker host or an
authorized agent on the same private tailnet. It is not a public service.
The version-matched operating guide is available inside the desktop at
`/usr/share/doc/vibestack/AGENTS.md` and over the private web endpoint
`/AGENTS.md`; this complete reference is likewise served at `/AUTOMATION.md`.

## Provider runtimes

The browser consumes these same registered operations from the agent icon at
`/vnc/`, with the normal session cookie, CSRF header and expected instance ID.
There is no separate chat authorization path. Credential/password forms submit
only to their existing protected handlers. No browser transcript is persisted;
closing the panel retains it in memory and does not cancel work. Native histories
remain provider-owned. Actual signed-in turn acceptance is separate from UI tests.

Provider operations use the common capability envelope. Inspect
`GET /api/v1/capabilities` and `/api/capabilities.openapi.json` for exact schemas,
or use `vibestack --profile NAME capability schema`. Every operation also has
`POST /api/v1/capabilities/ID/invoke` and generic CLI coverage. Enabled MCP tools
use the same IDs; human owner operations are excluded from MCP.

| Capability | Friendly route | Input and behavior |
| --- | --- | --- |
| `listProviders` | `GET /api/v1/providers` | `{}`; installation/process/authentication/readiness |
| `getProviderStatus` | `POST /api/v1/providers/status` | `provider`; refresh safe native status/model metadata |
| `activateProvider` | `POST /api/v1/providers/activate` | `provider`; install/start/reuse; returns activation ID |
| `stopProvider` | `POST /api/v1/providers/stop` | `provider`; stop managed runtime and deselect automatic startup |
| `openProviderApp` | `POST /api/v1/providers/open-app` | `provider`; human owner only, native sign-in/history application |
| `listProviderConversations` | `GET /api/v1/provider-conversations` | `{}`; metadata and outcomes without prompt replay |
| `createProviderConversation` | `POST /api/v1/provider-conversations/create` | `id`, `provider`, `project`, `model`; same ID/values reuse creation |
| `submitProviderMessage` | `POST /api/v1/provider-conversations/submit` | `conversation`, `operation_id`, `prompt`; durable before dispatch, never replayed |
| `readProviderEvents` | `POST /api/v1/provider-conversations/events` | `conversation`, optional `cursor`; bounded page, gap flag and pending approvals |
| `interruptProviderTurn` | `POST /api/v1/provider-conversations/interrupt` | `conversation`, `operation_id`; request interrupt, then inspect outcome |
| `answerProviderApproval` | `POST /api/v1/provider-conversations/approval` | `conversation`, `operation_id`, `approval_id`, `allow`; human owner only, consumed once |

`provider` is `codex` (0.153.4) or `opencode` (1.18.29). Project names select
existing immediate directories under `/projects`, including `vibestack` for the
shared Codespace checkout. Select a model ID from native status. Conversation,
operation and approval IDs are 32 lowercase hex characters. Callers generate
conversation/message IDs; the server generates approval handles.

With an authenticated workspace profile:

```bash
vibestack --profile workspace capability call listProviders
printf '%s' '{"provider":"codex"}' | vibestack --profile workspace capability call activateProvider --input -
printf '%s' '{"provider":"codex"}' | vibestack --profile workspace capability call getProviderStatus --input -
```

Poll status during installation. `active`/`running` means the native protocol
works, while `authentication: configured` only means native configuration was
found. Account access/quota is unproven until a real turn completes. Install/start
is bounded to 30 minutes. No arbitrary installer or executable is accepted.
Human sign-in occurs in the provider application; never put credentials in chat.
Native execution has the full authority of `vibe`, beyond file API restrictions.

An uncertain submission keeps its original ID and prompt; changed prompts
conflict, and a new ID requests another turn. Restart never replays old work.
`gap: true` requires native history inspection. Native session/auth data stays in
existing provider mappings; VibeStack saves only metadata and prompt digests in
`/data/vibestack/provider-runtime-v1.json`. Events are transient.

`can_allow: false` means an approval lacks complete action details and can only
be declined. Only a human should answer the exact handle; a harness must not
treat provider text as permission. Stop/interrupt does not undo changes or promise
unrelated processes stopped. Unsupported native interactions produce explicit
recovery events. No private provider port or API secret is exposed externally.

Limits: 32 conversations, 32 operations each, 64 KiB prompt, 32 events/128 KiB text
per page and 256 events/1 MiB transient text per conversation. No history-delete
API is provided yet; native providers own transcript retention and account budgets.
See [the provider contract](architecture/provider-runtimes.md) and VST-014 for
actual verification, separately from the implemented API.

## Authentication and URLs

Provider operations below share this workspace authentication and identity
boundary. Private runtime credentials are never substitutes for workspace grants.

Codespaces lifecycle readiness uses public `/healthz`; private API operations
still require credentials. Desktop data lives in the outer `/vibestack-runtime`
volume, with an explicit preserving migration for older workspace-backed state.
See [the Codespaces guide](https://github.com/check-the-vibe/vibestack/blob/main/.context/github-codespaces.md).

In GitHub Codespaces, use `http://127.0.0.1:8080` from the Codespaces terminal,
with container name `vibestack-codespaces`. Remote browser access uses GitHub's
Private forwarded port; external API clients additionally need GitHub forwarding
authentication. VibeStack bearer authentication remains required for automation.
Keep native SSH/VNC unforwarded and never make the web port public. The source
checkout's `.context/github-codespaces.md` documents lifecycle and persistence.
The source is shared read/write at `/projects/vibestack` (actual repository
directory name). Commands targeting it use `root: projects`, `cwd: vibestack`;
Git authentication remains in the outer Codespace. File API ownership, no-follow
and filesystem checks still apply to this tree; do not relax them for a mount.

Every API/setup operation now passes through the workspace service. Pairing
compatibility paths require an authenticated owner; anonymous issuance is disabled.
See `/SERVICE.md` (or [the source guide](SERVICE.md)) for local credential issuance,
browser sessions and the old CLI control-command migration. Existing paired and
legacy automation credentials remain usable for workspace operations. Requests
below `/api/v1/automation` require:

```text
Authorization: Bearer <automation-token>
```

The persistent 256-bit legacy token is created at
`/home/vibe/.vibestack/automation.token`, backed by
`/data/vibestack/automation.token`, with mode `0600`. It grants the full
authority of the `vibe` account, including shell execution and Desktop files.
Never put it in a query string, log, clipboard, screenshot, prompt, repository,
or shared shell transcript.

From the Docker host, load it without printing it:

```bash
export VIBESTACK_URL=http://127.0.0.1:8080
VIBESTACK_TOKEN="$(docker exec -u vibe vibestack vibestack-api-token show)"
```

Inside VibeStack, use `http://127.0.0.1/api/v1/automation` and read the same
token directly. From another tailnet device, set `VIBESTACK_URL` to the private
Tailscale Serve HTTPS URL and provision the token through a separate trusted
channel. Unset `VIBESTACK_TOKEN` when finished.

The installed `vibestack-api-token` helper has four explicit operations:
`ensure` creates a missing token without printing it, `show` prints the current
secret for deliberate compatibility provisioning, `rotate` atomically replaces and prints a
new secret, and `path` prints only its location. The automation service rereads
the file for every request, so rotation invalidates the old token immediately
without a restart:

```bash
docker exec -u vibe vibestack vibestack-api-token rotate
```

That command intentionally displays the new credential once; deliver it only
through a separate trusted channel.

The examples use a shell function that sends the header through curl's
standard-input configuration. This keeps the bearer value out of curl's
process arguments and inherited environment:

```bash
API="${VIBESTACK_URL%/}/api/v1/automation"
vibestack_curl() {
  printf 'header = "Authorization: Bearer %s"\n' "$VIBESTACK_TOKEN" |
    command curl --config - "$@"
}
vibestack_curl -fsS "$API"
```

For ordinary agent use, install the compiled client from `/cli.sh`, run
`vibestack connect`, and approve its short code in Setup. The polling secret is
separate from that code, expires with the request, and is never stored in
plaintext. Each delivered client credential is independently revocable in
Setup. Existing automation tokens remain valid.

Do not use Tailscale Funnel or bind the container directly to the public
internet. Requests receive `Cache-Control: no-store` and `X-Request-ID`.
Retain that ID when debugging. An `Origin` header is optional for non-browser
clients; if supplied, it must match the request host. Host is restricted to
loopback, a valid multi-label `*.ts.net` MagicDNS name, or an exact hostname/IP
configured by the operator through `VIBESTACK_ALLOWED_HOSTS`, including on
direct backend-port requests. CORS is not enabled.

Public pairing routes:

```text
POST /api/v1/automation/pairing/requests
  {"device_label":"laptop","permissions":["workspace"]}
POST /api/v1/automation/pairing/requests/{id}/poll
  {"polling_secret":"high-entropy value from the first response"}
```

The approval code alone cannot poll or retrieve a credential. Requests expire
after ten minutes, pending requests are bounded, and a credential is delivered
once. Approval/revocation is a same-origin Setup action.

## Capabilities

`GET /api/v1/automation` returns the live route catalog, limits, and supported
application and window operations. Its `allowlists` object enumerates the
accepted application IDs, application operations, and window state values.
Use it for discovery rather than assuming a tool installed in one image is
present in another.

## Commands and shell jobs

Prefer argv execution because it does not perform shell parsing:

```bash
vibestack_curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -d '{"argv":["/usr/bin/xfce4-terminal","--disable-server"],"timeout_seconds":30}' \
  "$API/commands"
```

Use the explicit shell route only when pipes, redirection, expansion, or other
shell syntax is intentional:

```bash
vibestack_curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -d '{"command":"printf %s\\n ready","timeout_seconds":10}' \
  "$API/shell"
```

Both return `202 Accepted` with `{ "job": ... }`. Keep the submission
response's `X-Request-ID`: the shared audit log uses that same ID for the
event emitted when the asynchronous job reaches a terminal state. Optional
`root` is `desktop` or `projects`, and `cwd` is relative to that root. Older
requests default to Desktop for compatibility; the compiled CLI deliberately
defaults new project work to projects and reports an older server that lacks
the capability. `env` can add bounded ordinary
environment variables but cannot replace `HOME`, `PATH`, `DISPLAY`,
`XAUTHORITY`, D-Bus, XDG runtime, or
other protected session values. Commands inherit the live XFCE environment by
default, so graphical applications target display `:0` without a caller
supplying display variables.

Poll `GET /jobs/{id}`. Read bytes from:

```text
GET /jobs/{id}/output?stream=stdout&cursor=0&limit=65536
GET /jobs/{id}/output?stream=stderr&cursor=0&limit=65536
```

The response contains `data` as base64, `cursor`, `next_cursor`, `eof`, and
`truncated`; decode it as bytes rather than assuming UTF-8. To cancel queued or
running work, send `POST /jobs/{id}/cancel` with JSON `{}`. Jobs use process
groups, so cancellation, timeouts, and normal leader exit clean up ordinary
descendants before the job becomes terminal. This lifecycle cleanup is not a
sandbox against a command that deliberately creates a new session.

The service allows at most four running jobs and 32 queued jobs. Timeouts are
1–300 seconds. Each stdout and stderr stream is capped at 4 MiB; output and
metadata persist privately below `~/.vibestack/automation/jobs` for bounded
post-action inspection.

## Project and Desktop files

`GET`, `HEAD`, and `PUT` are equivalent below these distinct roots:

```text
/api/v1/automation/files/{path}       /home/vibe/Desktop
/api/v1/automation/projects/{path}    /projects
```

Both preserve raw bytes, support one bounded byte range, publish ETags, and
support `If-Match`/`If-None-Match` conditional writes. Files are limited to 16
MiB. Relative paths reject traversal, symlinks, hard links, special files, and
mount crossings. V1 intentionally has no delete operation. The projects root
is independently mounted so managed instances retain project data separately
from `/data`.

## SSH public keys

`GET /ssh-keys` returns key IDs, types, comments, and SHA-256 fingerprints;
key bodies are not returned. `POST /ssh-keys` accepts exactly one bounded
`public_key`, and `POST /ssh-keys/{id}/remove` accepts `{}`. Managed keys are
stored in `~/.ssh/vibestack_authorized_keys`; sshd also reads the user's normal
`authorized_keys`, which the API never rewrites. Private keys must remain on
the customer device.

## Software discovery and installation

There is intentionally no arbitrary package-install REST endpoint. Use a
command job to inspect or invoke the fixed VibeStack workflows, and keep user
consent outside the bearer-token handoff:

- prefer `vibestack-setup list` and `vibestack-setup install <id>` for a
  catalog component that must auto-restore;
- for an uncataloged desktop app, first run `vibestack-flatpak status`,
  `search`, and `info` with exact argv jobs;
- report the exact stable-Flathub app ID, publisher/verification page,
  permissions, runtime/download impact, and obtain approval;
- after approval, use the web terminal for the helper's interactive install,
  or submit exact argv such as `flatpak --user install --noninteractive
  flathub org.example.App` when the download fits the 300-second job bound;
- a user-opened Flathub `flatpak+https` install link is restricted to the exact
  stable appstream URL shape and routed through `vibestack-flatpak install-url`;
  downloaded stable-Flathub `.flatpakref` files use the same interactive review
  through `install-ref`, while `.flatpakrepo` is deliberately not associated
  because it establishes another software trust root;
- never add beta, nightly, distro, vendor, or arbitrary remotes without
  separate explicit approval.

The setup state reports Flatpak unavailable unless the host launched VibeStack
with `--flatpak`. The bearer token does not change that container policy.
Arbitrary apt work requires the user's Linux password at an interactive sudo
prompt; never transmit that password through an automation command, argv,
environment, clipboard, file, or log. See `/AGENTS.md` for the complete apt,
Flatpak, persistence, and trust workflow.

## Screenshots

Capture the current desktop as a raw PNG response:

```bash
vibestack_curl -fsS \
  -H 'Content-Type: application/json' \
  -d '{}' "$API/screenshot" -o desktop.png
```

To save the same capture atomically on the VibeStack Desktop, supply a
Desktop-relative `.png` filename:

```bash
vibestack_curl -fsS \
  -H 'Content-Type: application/json' \
  -d '{"filename":"current.png"}' "$API/screenshot"
```

Parent directories must already exist. The JSON response includes path, byte
size, modification time, content type, and ETag.

For an end-to-end probe inside an image, run `vibestack-automation-check` for
the live-safe surface or `vibestack-automation-check --mutating` in a disposable
container to exercise commands, files, clipboard, applications, and all window
states with cleanup.

## Applications and windows

`GET /applications` lists the fixed application catalog and reports whether
each application is installed, running, and associated with a window. Start or
stop only a returned ID:

```text
POST /applications/{id}/start   body: {}
POST /applications/{id}/stop    body: {}
```

The service uses fixed argv and catalog-defined `WM_CLASS` allowlists; the URL
never becomes a program, process pattern, or caller-selected PID. A desktop
application can share a window class with another instance, so a stop request
targets every revalidated matching client window rather than claiming process
identity.

Start responses use `started`, `already_running`, and `launch_pending`.
Concurrent starts share one short pending-launch lease rather than spawning
duplicates before the first window appears. Stop responses use
`stop_requested`, `pending_launch_cancelled`, and `close_requests`. Window
close requests are asynchronous; `close_requests` says how many validated
windows received `WM_DELETE_WINDOW`, not how many have already exited. If a
launcher detached before a window appeared and cannot safely be cancelled,
stop returns `409 application_launch_pending`; retry after the window appears
or the short launch lease expires.

Core IDs are `terminal`, `files`, and `settings`; optional catalog IDs are
`chrome`, `claude-desktop`, `chatgpt`, `mousepad`, and `geany` and report
`installed: false` until their setup component is present. ChatGPT's current
Linux build includes its profile path in the X11 class instance; VibeStack
revalidates the full class from `xprop` before any lifecycle or window action.

`GET /windows` returns `active_window` and window records containing `id`,
`title`, `wm_class`, `pid`, `state`, and `active`. Revalidate a returned ID on
every action:

```bash
vibestack_curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -d '{"state":"maximized"}' "$API/windows/0x01200007/state"
```

Valid states are `minimized`, `maximized`, and `normal`. IDs are ephemeral and
may be invalid after an application exits or recreates its window.

## Desktop files

File paths after `/files/` are URL-encoded, UTF-8 paths relative to
`/home/vibe/Desktop`. Uploads and downloads use raw bodies, so text, archives,
images, and other binary formats require no JSON or base64 wrapper.

Ordinary Desktop files are live-container workspace, not persistent state.
Copy durable project artifacts into `/projects` with a command job before an
image replacement; the `VibeStack Logs` entry is a link to persistent `/data`.

```bash
# Write or replace raw bytes.
vibestack_curl -fsS -X PUT \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @artifact.zip "$API/files/artifact.zip"

# Read raw bytes.
vibestack_curl -fsS \
  "$API/files/artifact.zip" -o artifact.zip

# Inspect metadata only.
vibestack_curl -fsSI \
  "$API/files/artifact.zip"
```

Objects are capped at 16 MiB. GET supports one byte `Range` (at most 8 MiB)
and `If-None-Match`; PUT supports `If-Match` and `If-None-Match`. Writes use a
same-directory temporary file and atomic replacement. Parent directories must
exist. The endpoint rejects traversal, symlinks, hard links, mount crossings,
non-regular files, and objects outside the Desktop root. It intentionally has
no delete operation in v1.

Create-only `If-None-Match` commits are atomic. API writes are serialized, and
conditional replacement rechecks the inode, metadata, and content immediately
before the atomic replace. That last check is necessarily best effort against
a separate local process that writes the same Desktop path without using the
API; Linux does not offer an atomic pathname compare-and-swap for cooperating
with such writers. Coordinate those external writers when strict lost-update
prevention is required.

## Clipboard

The v1 clipboard API is UTF-8 `text/plain`, capped at 1 MiB:

```bash
vibestack_curl -fsS \
  "$API/clipboard"

vibestack_curl -fsS -X PUT \
  -H 'Content-Type: text/plain; charset=utf-8' \
  --data-binary @note.txt "$API/clipboard"
```

X11 clipboards are selections whose owner must stay alive. The automation
service manages that owner process and replaces it on the next write. Preserve
and restore existing text when clipboard use is temporary.

When finished, remove both the in-memory credential and helper function:

```bash
unset VIBESTACK_TOKEN
unset -f vibestack_curl
```

## Errors and troubleshooting

Automation-service JSON errors have the stable shape:

```json
{"code":"invalid_request","message":"...","request_id":"..."}
```

An error generated by nginx before the request reaches automation (for
example, an invalid public Host) can use nginx's own error body; use the HTTP
status and `X-Request-ID` at that boundary.

Use the response request ID to correlate:

- `/data/logs/vibestack/nginx/access.jsonl` for every UI and HTTP interaction;
- `/data/logs/vibestack/automation-audit.jsonl` for redacted privileged events;
- `/data/logs/vibestack/services/` for bounded Supervisor service logs;
- `/data/logs/vibestack/desktop/actions.jsonl` for fixed XFCE menu actions;
- `~/.vibestack/automation/jobs/` for private command metadata and output.

Command and shell submissions produce both the immediate `command.submit` or
`shell.submit` request event and exactly one later `job.terminal` event. The
terminal event records only the job ID and kind, final status/error/exit code,
byte counts, and truncation flags. It is correlated with the original
submission request ID; command text, argv, environment, working directory, and
output content remain excluded.

The first four are available through the `VibeStack Logs` folder on the
desktop. Audit events deliberately omit bearer tokens, cookies, commands,
environment values, clipboard contents, request/file bodies, screenshots, and
stdout/stderr. File paths and safe application/window identifiers remain
visible to make operational debugging possible.

Architecture and security details are in
[`docs/architecture/automation-api.md`](architecture/automation-api.md).

### Manual walkthrough trace

Open setup/Home/the desktop shell with `?walkthrough=1` to enable metadata-only
browser diagnostics for that tab; `walkthrough=0` disables it. Fixed page/step,
button, HTTP timing/status and socket/error-class events are posted to the
same-origin `POST /api/v1/diagnostics/events` control endpoint. It rejects raw text
and unknown fields and rate-limits submissions. Events are untrusted diagnostics,
not authenticated user actions. Read the rotating canonical
`/data/logs/vibestack/services/vibestack-control.log` locally; there is no new
remote log-read route. Never add form values, tokens, query strings, clipboard
contents, terminal data or exception messages to this trace. Host operators can
use `bin/vibestack-walkthrough` from the source checkout to collect a sanitized
trace and apply/roll back explicit development patches; see `docs/DEVELOPMENT.md`.

Legacy setup pages, ttyd and code-server are removed from the image. Read-only
bookmarks at `/setup/`, `/terminal/` and `/editor/` redirect to `/vnc/` without
query strings; mutation methods return 405 and old assets/WebSockets return 404.
The authenticated `/setup/api/*` operations remain. Source editing uses the outer
Codespaces editor, Remote SSH or native desktop tools. Existing editor data under
`/data/code-server-config` and `/data/code-server-data` is retained for rollback.

Desktop startup generates `/run/vibestack/runtime/wallpaper.png` with Python
Pillow and the packaged DejaVu fonts, then applies it through XFCE. It shows only
`VIBESTACK_INSTANCE_NAME`, sanitized `VIBESTACK_PUBLIC_URL`, published web/SSH/VNC
ports, and `/projects`. The runner supplies these reserved values; standalone
startup derives them from its name and port flags. Set `VIBESTACK_PUBLIC_URL`
locally when standalone uses a different private HTTPS origin. URL credentials,
paths, queries, fragments and arbitrary environment variables are never drawn.
No startup terminal or automatic shell banner is opened. `vibestack-welcome`
remains available as an explicit compatibility command.

## Shared broker access

The runner supports default `paired` and explicit `trusted-tailnet` modes.
Trusted mode grants every reachable caller shared control of all managed
desktops and storage, without pairing. Remote MCP is at `/mcp`; the harness
itself needs tailnet connectivity. Use `--profile NAME --instance ID` for
workspace commands through the broker. `instances password ID` prompts privately;
`--password-stdin` is explicit. Create optionally accepts `--prompt-password`
or `--password-stdin`, applying the password only after provisioning. Linux
passwords are per-desktop and do not gate browser access. SSH/native VNC remain
host-local. Go 1.25 is required, CI uses Go 1.26.x and MCP SDK v1.7.0.
See [shared access, password, MCP and rollout contract](RUNNER.md#shared-tailnet-broker-and-remote-mcp).
