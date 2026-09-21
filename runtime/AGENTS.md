# Operating VibeStack

Discover registered operations at authenticated `GET /api/v1/capabilities` and
invoke `POST /api/v1/capabilities/{id}/invoke` with the input JSON object. The
`project_summary` example takes `project` and optional `max_entries` and counts
immediate entries only. Read `/EXTENSIONS.md` before adding a compiled module.
Discovery reports current MCP availability explicitly.
The current source CLI supports `vibestack --profile NAME mcp` for a stdio harness.
Read `/MCP.md` for bootstrap and exact input schemas; older released CLIs may
need rebuilding. Registered tools include jobs, conditional file updates and
screenshots. Keep credentials in the protected profile, never harness JSON or
tool arguments. A job timeout or disconnected MCP call does not justify replaying
a mutation. Clipboard, SSH keys and human authentication are not default tools.

You are working with VibeStack: a private, single-user Ubuntu 24.04/XFCE
desktop running inside Docker. This file is the canonical quick-start for both
agents inside the desktop and authorized agents on the Docker host or private
tailnet. It is packaged at `/usr/share/doc/vibestack/AGENTS.md` and served at
`/AGENTS.md`. The client and runner guides are `/CLI.md` and `/RUNNER.md`; the
exact automation schemas, limits, and longer examples are at
`/usr/share/doc/vibestack/AUTOMATION.md` and `/AUTOMATION.md`.

All API/setup operations now pass through the workspace service. Read
`/SERVICE.md` for local credential creation, browser sign-in, expiry/revocation
and CLI migration. Browser users connect at `/connect.html`; agents use protected
credential files or their CLI profile. Never request a credential in chat. The
workspace `/mcp` endpoint exposes enabled registered capabilities. Read `/MCP.md`
for supported bearer clients and the separate private Codespaces gateway. Legacy
REST operations are not automatically tools; check the capability catalog.

## Trust boundary

- Treat the entire web workspace as an administrative, single-user surface.
  Keep Docker bound to host loopback and use private Tailscale Serve for remote
  access, or GitHub Codespaces private port forwarding for a Codespaces desktop.
  Never use Tailscale Funnel, a public forwarded port or a public bind.
  In Codespaces, the source editor is outside this desktop, HTTP is forwarded
  from port 8080, and GitHub authentication protects remote browser access.
  The checkout is shared read/write at `/projects/vibestack` (or the actual
  repository-directory name); other projects remain under `/projects`. Source
  edits affect the outer editor immediately. The launcher-declared source mount
  supports project file and command APIs across a filesystem boundary; ownership,
  no-symlink and deeper mount checks still apply. No outer credentials or Docker
  socket are injected; run authenticated Git operations in the Codespaces editor.
  Outer runtime storage is `/vibestack-runtime/<repository-directory>` in a
  dedicated volume. Missing storage or unsafe ownership requires operator
  investigation; do not reset state or recursively chown it to make startup pass.
- The legacy `/setup/` UI, `/terminal/` and `/vnc/` rely on the private boundary.
  Every API/setup operation also requires a workspace credential or browser
  session; browser mutations need CSRF protection. Existing paired credentials
  and legacy automation tokens retain workspace authority. Keep the port private.
- An authenticated owner can set or replace the `vibe` Linux password without the old value.
  Do this only when the user explicitly asks. Never collect a password in an
  agent prompt, command argument, file, clipboard, screenshot, or log.
- Any automation credential has the full authority of `vibe`, including shell
  execution, application control, screenshots, clipboard text, and Desktop
  files. Handle it like a password and never put it in a URL, repository,
  prompt, screenshot, clipboard value, command argument, or shared log.

## Identify your execution context

| Agent execution context | Correct interface |
|---|---|
| Inside one VibeStack workspace | Local files/commands, or the loopback workspace API. |
| On a customer Linux/macOS machine | A named `vibestack` profile using the advertised authentication mode. |
| On the Docker host as operator | `vibestack-runner` only for local administration; use an explicit client profile for agent work. |

Never infer a target when several profiles or instances exist. Start external
work with `vibestack --profile NAME doctor` and `capabilities`. New work
defaults to `/projects`; use the Desktop root only when requested. Prefer
argv-based `exec`, and do not resubmit an uncertain mutation—inspect its job or
operation ID. Pairing uses a short operator-approved code plus a separate
polling secret; credentials remain in the mode-0600 local profile and must not
be printed. Install the portable skill with `vibestack skill install --claude`
or export it with `vibestack skill export DIRECTORY` without overwriting an
existing skill directory.

## Filesystem and desktop session

| Location | Meaning |
|---|---|
| `/projects` | Host-mounted durable project workspace. Put lasting work here. |
| `/home/vibe/Desktop` | Desktop file API root. Ordinary files here are container-local. |
| `/data` | Persistent VibeStack state. Use only documented application paths. |
| `/data/logs/vibestack` | Persistent access, service, menu-action, and automation audit logs. |
| `~/.vibestack/automation/jobs` | Private job metadata and bounded stdout/stderr; not part of shared logs. |
| `/run/vibestack/session.env` | Current X11, D-Bus, keyring, and XDG session environment. |

The graphical session is X11 display `:0`. When running a graphical command
directly inside VibeStack, run it as `vibe` and source the session file first:

```bash
source /run/vibestack/session.env
```

Prefer the automation API when an action should be auditable or may also be
driven from outside the container. Do not patch a running container as the
final fix: change the VibeStack source, build a tagged image, run disposable
acceptance, and use the documented rollback-aware launcher.

## Web workspace and menus

Use same-origin paths beneath the selected loopback or private Tailscale base
URL:

| Path | Surface |
|---|---|
| `/` | Launcher for Desktop, Terminal, setup, and this agent guide. |
| `/vnc/?view=desktop` | Custom browser shell showing the XFCE desktop. |
| `/vnc/?view=terminal` | The same shell with the persistent terminal selected. |
| `/terminal/` | Raw ttyd terminal, backed by the same persistent tmux session. |
| `/setup/?force=1` | Linux-password onboarding and durable component catalog. |
| `/editor/` | Optional code-server project editor. |
| `/AGENTS.md` | This canonical operating guide. |
| `/CLI.md`, `/RUNNER.md` | Client and Docker-host runner references. |
| `/AUTOMATION.md` | Complete REST API reference and examples. |

The browser shell's **Desktop** and **Terminal** tabs switch views without
leaving the workspace. **Menu** contains the on-screen keyboard, clipboard,
modifier keys, Ctrl-Alt-Delete, Match screen, **Settings**, and **Tools**.
Settings controls connection, scaling, image quality/compression, view-only,
reconnect, and desktop resolution. Tools shows service health, bounded logs,
and allowlisted restart actions.

The XFCE **VibeStack** menu contains Projects, Desktop, persistent logs, Setup
& Onboarding, the Agent and Automation guides, service status, the Flathub
marketplace, Flatpak management, and screenshots. Other collections organize
coding, creation/review, installed applications, and system settings. Flatpak
desktop entries appear from the persistent per-user installation after the
next menu refresh; if needed, reopen the menu or restart the XFCE panel.

## Automation REST API

The pairing request/poll routes are the only unauthenticated automation
bootstrap. Every other request to the exact API root and its descendants needs:

```text
Authorization: Bearer <automation-token>
```

The legacy token is mode `0600` at `~/.vibestack/automation.token` and persists
under `/data`; individually revocable paired credentials are preferred for the
compiled client. For legacy host automation, load the token without printing it:

```bash
export VIBESTACK_URL=http://127.0.0.1:8080
VIBESTACK_TOKEN="$(docker exec -u vibe vibestack vibestack-api-token show)"
API="${VIBESTACK_URL%/}/api/v1/automation"
vibestack_curl() {
  printf 'header = "Authorization: Bearer %s"\n' "$VIBESTACK_TOKEN" |
    command curl --config - "$@"
}
vibestack_curl -fsS "$API"
```

Inside VibeStack, use `http://127.0.0.1/api/v1/automation`. From another
tailnet device, use the private Tailscale Serve HTTPS base and provision the
token through a separate trusted channel. Discovery returns the live route
catalog, limits, accepted application IDs, application operations, and window
states; inspect it instead of assuming a particular image has an app.

| Operation | Routes and behavior |
|---|---|
| Commands | `POST /commands` with an argv array; preferred because no shell parses it. |
| Shell | `POST /shell` with a command string only when pipes, redirects, expansion, or other shell syntax is intentional. |
| Jobs | `GET /jobs/{id}`, paged byte-preserving `GET /jobs/{id}/output`, and `POST /jobs/{id}/cancel`. |
| Screenshot | `POST /screenshot` with `{}` for raw PNG, or a Desktop-relative `.png` filename to save it atomically. |
| Applications | `GET /applications`; start/stop only returned catalog IDs with `POST /applications/{id}/start` or `/stop`. |
| Windows | `GET /windows`; set a freshly returned ID to `minimized`, `maximized`, or `normal` with `POST /windows/{id}/state`. |
| Files | Raw binary `GET`, `HEAD`, and `PUT` beneath `/files` (Desktop) or `/projects` (durable projects), with ETag/precondition support. |
| SSH keys | List fingerprints and add/remove API-managed public keys; private keys never enter VibeStack. |
| Clipboard | UTF-8 text `GET` and `PUT /clipboard`. Preserve and restore temporary values. |

Commands and shell requests return `202 Accepted` asynchronous jobs. Prefer:

```bash
vibestack_curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"argv":["/usr/bin/printf","ready\\n"],"timeout_seconds":10}' \
  "$API/commands"
```

Use the explicit shell route only when required:

```bash
vibestack_curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"command":"printf %s\\n ready","timeout_seconds":10}' \
  "$API/shell"
```

Poll the returned job ID, then read stdout or stderr pages. Output payloads are
base64 because command output is bytes, not necessarily UTF-8. Jobs allow
1–300 second timeouts, four running workers, 32 queued jobs, and 4 MiB per
output stream. Cancel work that is no longer needed.

Screenshots return exact PNG bytes. Desktop files accept text or arbitrary
binary bodies without base64 and are limited to 16 MiB; GET byte ranges are
limited to 8 MiB. Clipboard text is limited to 1 MiB. Desktop-relative file
paths reject traversal, symlinks, hard links, mount crossings, and special
files. V1 intentionally has no file-delete route.

Application lifecycle uses fixed argv and checked X11 window classes rather
than caller-controlled process matching. Window IDs are ephemeral: list again
immediately before a state change. Start/stop responses describe pending
launches and asynchronous close requests; they do not promise that a GUI has
already appeared or exited.

When finished with an external token:

```bash
unset VIBESTACK_TOKEN API
unset -f vibestack_curl
```

## Logs and diagnosis

The Desktop link **VibeStack Logs** opens `/data/logs/vibestack`. Retain the
`X-Request-ID` response header and correlate it across:

- `nginx/access.jsonl` for every UI and HTTP request (path, never query/body);
- `automation-audit.jsonl` for redacted privileged-operation metadata;
- `services/` for bounded Supervisor service logs;
- `desktop/actions.jsonl` for fixed XFCE menu actions;
- `~/.vibestack/automation/jobs/` for private command metadata and output.

Shared logs deliberately exclude tokens, cookies, command text/argv,
environment values, clipboard and file bodies, screenshots, and stdout/stderr.
They retain safe target identifiers and file paths needed for diagnosis. If an
external action fails, record its HTTP status, JSON error code, and request ID
before retrying.

External desktop-app authentication should open ordinary web URLs in Chrome.
If a sign-in button appears inert, verify all three defaults and the XFCE
helper:

```bash
xdg-settings get default-web-browser
xdg-mime query default x-scheme-handler/https
xdg-mime query default x-scheme-handler/http
grep '^X-XFCE-Commands' /usr/share/xfce4/helpers/google-chrome.desktop
```

The browser and MIME results should be `google-chrome.desktop`, and the helper
must invoke `vibestack-app`. ChatGPT must not claim ordinary HTTP/HTTPS URLs.

## Installing software: catalog, Flatpak, and apt

Use the durable VibeStack catalog first when it contains the required tool:

```bash
vibestack-setup list
vibestack-setup install <component-id>
```

Catalog installs use a fixed passwordless helper and are recorded for
automatic restoration after container replacement. The `vibe` account has no
default password; the user creates one at `/setup/`. All other `sudo` commands
prompt for that password in both terminals. An agent cannot retrieve it and
must leave the prompt visibly waiting for the user rather than asking them to
put the password in a prompt or command.

Flatpak is the preferred route for a desktop application that is not in the
catalog, when VibeStack was started in Flatpak mode. It installs per-user, so
apps, runtimes, remotes, and app data survive image replacement without sudo:

```bash
vibestack-flatpak status
vibestack-flatpak search 'search terms'
vibestack-flatpak info org.example.App
vibestack-flatpak install org.example.App
vibestack-flatpak list
vibestack-flatpak update
```

The current Flathub web page's **Install** action opens a `flatpak+https` link.
XFCE's default VibeStack handler opens a held terminal, accepts only the exact
stable-Flathub appstream URL shape, downloads at most 64 KiB over HTTPS,
validates that the reference matches the linked app, shows the exact app
permissions, and waits for the user to confirm. Downloaded `.flatpakref` files
use the same bounded review path; the equivalent explicit commands are
`vibestack-flatpak install-url 'flatpak+https://dl.flathub.org/repo/appstream/org.example.App.flatpakref'`
and `vibestack-flatpak install-ref /path/to/application.flatpakref`. Do not
bypass the handlers for an unreviewed reference; `.flatpakrepo` files remain
unassociated because they establish a new software trust root.

Search first and identify the exact application ID and remote. Prefer the
stable `flathub` remote configured by VibeStack. Before installing, review the
publisher/verification status on Flathub and inspect requested permissions;
the helper's `info` command does this for the selected ID. Get user approval
before installing third-party code or large runtimes. A verified badge means
the publisher proved control of the app identity; it is not a guarantee that
the app needs no review.

Do not add beta, nightly, vendor, or arbitrary `.flatpakrepo` remotes without
explicit user approval. Remotes are independent software trust roots and can
contain duplicate app IDs. Flathub Beta and GNOME Nightly are intentionally
unstable. Direct `flatpak --user ...` remains available for an explicitly
approved non-default remote.

Nested Flatpak sandboxes require VibeStack's explicit host launch mode:

```bash
./startup.sh --flatpak
```

Without that mode, setup visibly marks the Flatpak component unavailable.
`--flatpak` relaxes Docker seccomp, AppArmor, and protected-system-path policy
for this one container so bubblewrap can create its inner namespaces and
mounts. It does not add Linux capabilities or use `--privileged`, but it is a
meaningful reduction in the outer Docker boundary; use it only for this
trusted, loopback/tailnet-only desktop.

From the external automation API, use exact argv jobs for
`vibestack-flatpak status`, `search`, and `info`. The helper's install is
interactive; after the user approves one exact stable-Flathub ID, either leave
the web terminal at its confirmation prompt or submit `flatpak --user install
--noninteractive flathub <app-id>` as an argv job. Large runtimes may exceed
the API's 300-second limit and belong in the terminal. Never treat possession
of the automation token as approval to install software or add a remote.

For Ubuntu packages or system libraries, search before installing:

```bash
apt-cache search '<terms>'
apt-cache show <package>
sudo apt-get update
sudo apt-get install <package>
```

Arbitrary apt installs modify only the current container and disappear on
replacement. Prefer or add a reviewed catalog component for anything that
must auto-restore. Flatpak is for desktop applications; use apt/catalog for
drivers, development headers, daemons, system integration, and command-line
tools that need unsandboxed host access.

Fresh Codex, Claude Code, and OpenCode profiles link their default global
instructions to this packaged file. Existing instruction files and Codex
overrides are preserved; create the tool's documented override if the user
wants additional local policy rather than editing the immutable package copy.

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

Desktop is the default landing page (`/` opens `/vnc/`). Navigation retains
Desktop, Terminal, Editor, and Settings. Apps and Settings are contextual
sidebars; `/?panel=apps` and `/?panel=settings` force them open, including when
onboarding was completed earlier. The same parameters work on `/vnc/`.
After a successful password submission, Setup opens `/vnc/?panel=apps`.

Apps opens the full-screen searchable catalog at `/setup/?force=1&screen=apps`.
Packs reuse the existing catalog presets; choosing a pack selects its supported
components, and Install submits the existing durable install operation. Search
never clears the selection. An optional `pack=<catalog-preset-id>` selects a pack
without installing it. Password changes remain available from Settings at
`/setup/?force=1&screen=password`.

Terminal (`/vnc/?view=terminal`) and Editor (`/vnc/?view=editor`) each fill the
workspace beneath its navigation. Their Back control and browser Back return to
Desktop, including on direct entry. The underlying `/terminal/` and `/editor/`
services remain separate same-origin frames. If Editor is unavailable, its view
offers service recovery instead of loading a broken frame. No new API authority or
storage migration is introduced. Patches and later image updates must preserve
existing `/data`, `/projects`, attached drives, passwords and saved selections.

The browser Editor is a required, preinstalled code-server 4.136.2 service. Its
amd64/arm64 package checksums and identities are verified during image build;
Supervisor starts it automatically, and container health includes it. Apps and
packs exclude the former `browser-editor` component. Legacy saved selections
ignore that retired ID without resetting other selections; editor configuration
and extensions retain their existing persistent mounts.

Desktop startup generates `/run/vibestack/runtime/wallpaper.png` with Python
Pillow and the packaged DejaVu fonts, then applies it through XFCE. It shows only
`VIBESTACK_INSTANCE_NAME`, sanitized `VIBESTACK_PUBLIC_URL`, published web/SSH/VNC
ports, and `/projects`. The runner supplies these reserved values; standalone
startup derives them from its name and port flags. Set `VIBESTACK_PUBLIC_URL`
locally when standalone uses a different private HTTPS origin. URL credentials,
paths, queries, fragments and arbitrary environment variables are never drawn.
No startup terminal or automatic shell banner is opened. `vibestack-welcome`
remains available as an explicit compatibility command.

## Shared broker clients

A host runner may advertise `trusted-tailnet` mode: all reachable callers share
control of its desktops and storage. The harness itself must reach the tailnet.
Use the broker's `/mcp` Streamable HTTP endpoint or `vibestack --profile NAME
--instance ID exec -- ...` for mediated automation; tokens stay in the broker.
MCP provisioning returns operation IDs to poll. Never submit Linux passwords
through MCP; hand off `urls.password_setup` or the CLI's private password prompt.
Linux username is vibe. Per-desktop passwords do not gate browser access or
synchronize application logins/keyrings. SSH/native VNC are host-local.
