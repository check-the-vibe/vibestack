# Automating VibeStack

VibeStack exposes its live XFCE desktop through a privileged REST API. It can
run commands in the graphical session, capture screenshots, start and stop
known applications, list and change the state of windows, transfer arbitrary Desktop files,
and read or replace the X11 clipboard.

The API is designed for a local coding agent on the Docker host or an
authorized agent on the same private tailnet. It is not a public service.
The version-matched operating guide is available inside the desktop at
`/usr/share/doc/vibestack/AGENTS.md` and over the private web endpoint
`/AGENTS.md`; this complete reference is likewise served at `/AUTOMATION.md`.

## Authentication and URLs

Every request below `/api/v1/automation` requires:

```text
Authorization: Bearer <automation-token>
```

The persistent 256-bit token is created at
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
secret for deliberate provisioning, `rotate` atomically replaces and prints a
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

Do not use Tailscale Funnel or bind the container directly to the public
internet. Requests receive `Cache-Control: no-store` and `X-Request-ID`.
Retain that ID when debugging. An `Origin` header is optional for non-browser
clients; if supplied, it must match the request host. Host is restricted to
loopback or a valid multi-label `*.ts.net` MagicDNS name, including on direct
backend-port requests. CORS is not enabled.

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
`cwd` is relative to the Desktop root; `env` can add bounded ordinary
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
