# VibeStack Specification

VibeStack is a Docker image that gives people and AI coding tools a full Linux
desktop through a browser and an authenticated desktop-automation API.

The image ships **slim**. Only the desktop, browser interfaces, automation
primitives, and operational services are built in. On first boot a setup
wizard asks which optional components to install. This keeps the base small,
keeps the choice with the user, and gives us one place to grow onboarding.

After the upstream base's signature-verified package bootstrap installs its CA
trust store, official Ubuntu archive, security, and ARM ports URLs use HTTPS.
Setup and restoration retain TLS certificate and APT signature verification;
repository identities, suites, components, and signing keys are unchanged.

## 1. Goals

1. Give VibeStack full ownership of the visible browser desktop while retaining
   noVNC's maintained RFB engine as an upstream dependency.
2. Expose a browser terminal and first-boot setup wizard beside that desktop.
3. Make the desktop installable and usable as an iPadOS 17+ Home Screen web app
   over a private HTTPS connection.
4. Put connection settings, clipboard/keyboard controls, service health,
   bounded logs and safe service/display operations in the HTML shell.
5. Keep the shell-facing control API small and allowlisted while exposing
   intentional full-user automation through a separate bearer-authenticated
   API with bounded jobs and scoped convenience resources.
6. Keep the base image as small as a usable XFCE desktop allows, with optional
   components selected and installed on first boot.
7. Persist tool state, the root-private Linux password hash, setup choices and
   non-sensitive browser preferences across rebuilds and launches.
8. Persist redacted UI access, service, and automation audit logs in one
   desktop-linked tree so agents can correlate and debug every interaction.
9. Publish one version-matched operating guide inside the image and over the
   private web surface so local and external agents discover the same commands,
   menus, APIs, logs, package workflows, and trust boundaries.
10. Give Linux and macOS agents a compiled, profile-aware client for workspace
    automation and give Linux Docker hosts a separate durable instance runner.
11. Make `/projects` the explicit durable root for new agent work while keeping
    the existing Desktop file contract compatible.

## 2. Non-goals (this iteration)

- Application login or in-container TLS for the browser desktop, setup, and
  terminal. Run behind private Tailscale Serve and terminate HTTPS externally.
- Public-internet exposure or multi-user isolation. The single `vibe` user gets
  ordinary password-authenticated sudo after onboarding; only three bounded
  VibeStack helpers remain passwordless.
- A fork of the noVNC RFB engine or continued dependence on stock `vnc.html`.
- Arbitrary commands, paths, process names, or logs through the narrow control
  API. Those do not become control inputs merely because the separately
  authenticated automation API deliberately supports user-authorized commands.
- noVNC/RFB `SetDesktopSize` resizing. Remote display changes go through the
  bounded VibeStack control API instead of `RFB.resizeSession`.
- Claude Desktop Cowork, which needs KVM and a nested VM.
- OpenAI Computer Use, which is absent from the Linux build. The Codex
  extension is installed anyway so it works when OpenAI enables it.
- Audio, GPU passthrough, Wayland, or an unmeasured TigerVNC migration.
- A runner dashboard, arbitrary remote image builds, agent-supplied host
  mounts, raw Docker API access, or hostile multi-tenant isolation.

## 3. Architecture

### 3.1 Base image

Ubuntu 24.04 LTS with only what the desktop and interfaces need:

- Xvfb, XRandR utilities, x11vnc and websockify.
- noVNC 1.7.0 `core/` and `vendor/` modules from a pinned, integrity-verified
  upstream release. VibeStack does not ship the upstream UI as its interface.
- XFCE named components rather than the `xfce4` metapackage: xfwm4, xfdesktop4,
  xfce4-panel, xfce4-settings, xfce4-terminal, thunar.
- nginx, supervisor, OpenSSH server, python3, tmux, git, nano, vim-tiny, sudo,
  openssl.
- gnome-keyring with libsecret, D-Bus, xdg-utils.
- scrot, xclip, xdotool, wmctrl, xprop, Xauthority, and GTK/X11 utilities so
  agents can see and drive the desktop out of the box.
- ttyd.

Everything else is a catalog component.

### 3.2 Interfaces

| Path | What |
|---|---|
| `/setup/` | Linux password and component onboarding; redirects to `/` once both are complete. |
| `/terminal/` | ttyd attached to tmux session `main`. |
| `/editor/` | Optional same-origin code-server browser editor. |
| `/vnc/` | VibeStack-owned shell with Desktop and embedded Terminal views. |
| `/vnc/websockify` | Same-origin RFB WebSocket endpoint. |
| `/novnc/core/`, `/novnc/vendor/` | Pinned upstream runtime modules, not UI. |
| `/api/v1/` | Same-origin, loopback-backed desktop control API. |
| `/api/v1/automation` | Bearer-authenticated command and desktop/project automation API. |
| `/.well-known/vibestack` | Public kind, stable identity, versions, API roots, docs and pairing discovery; never credentials or inventory. |
| `/AGENTS.md`, `/CLI.md`, `/AUTOMATION.md`, `/RUNNER.md` | Non-cacheable version-matched guides. |
| `/cli.sh`, `/skills/vibestack/SKILL.md` | Secret-free client bootstrap and portable agent skill. |
| `/manifest.webmanifest`, `/service-worker.js`, `/icons/` | PWA resources. |
| `/` | Opens Desktop; supported panel/view query parameters are preserved. Header logos return here. |

Redirects are relative, so the host and port the client used are preserved.
Dynamic interfaces and API responses are never service-worker cached.

### 3.3 Desktop shell

`desktop/` is a dependency-free HTML/CSS/JavaScript application. It imports
`RFB` from `/novnc/core/rfb.js`, derives a same-origin `ws:` or `wss:` URL, and
connects to `/vnc/websockify`. VibeStack never imports upstream UI modules or
uses underscore-prefixed noVNC internals.

On incomplete first-run or legacy state the root launcher first routes the
browser to `/setup/`. Once onboarding is complete, it sends explicit choices to
`/vnc/?view=desktop` or `/vnc/?view=terminal`. The shell exposes those views as accessible top-bar tabs,
updates same-document history, and embeds the existing same-origin `/terminal/`
route without altering ttyd. A terminal-first launch does not create an RFB
connection; switching away from Desktop disconnects it and switching back
starts a fresh bounded connection.

The shell has a full-viewport canvas, embedded terminal, status/recovery UI, Settings and Tools
drawers, accessible focus management and touch-sized controls. It explicitly
handles connect, disconnect, security failure, credential requirement,
server-verification, clipboard and desktop-name events. An unexpected network
disconnect uses bounded reconnects; a security failure never loops.

The top bar's collapsed **Menu** disclosure opens a popover containing the
software-keyboard trigger, clipboard, latched Ctrl/Alt/Super keys,
Ctrl-Alt-Delete, a one-shot **Match screen** action, and the **Settings** and
**Tools** drawer launchers. It replaces the persistent bottom control dock and
the separate top-level drawer buttons, so these actions do not permanently
reserve or cover canvas space. Focus and fullscreen remain directly available
in the top bar.

Settings offers balanced (quality 7/compression 2), maximum-clarity (9/2), and
constrained-link (5/6) rendering profiles plus fit/1:1 local scaling, manual
JPEG quality/compression, view-only, automatic reconnect, optional automatic
screen matching and an explicit fixed OS display resolution. Automatic
matching is off by default. It derives the
remote size from the rendered desktop stage in CSS pixels, preserves the stage
orientation, debounces viewport changes and pauses while the page is hidden or
a browser text field/software keyboard owns the viewport. Fit scaling remains
enabled as the local presentation fallback; `RFB.resizeSession` remains false.
Tools exposes core service cards, bounded logs and confirmed restart actions.
The same control contract manages SSH, native VNC, and core editor
services with explicit start/stop/restart operations. Stopping native VNC does
not stop the independent browser desktop path.

Inside XFCE, the stock application tree is replaced by a VibeStack menu with
VibeStack Actions, Coding, Create & Review, Applications, and System collections.
It includes install-aware coding-tool and Flatpak launchers, Terminal, Projects,
File Manager, Settings, Setup, service status, persistent logs, the agent and
automation guides, stable Flathub, Flatpak management, and fixed common actions
such as taking a screenshot. Category discovery lets per-user Flatpak exports
appear without regenerating the menu. The menu never exposes arbitrary shell
text as a desktop action.

Only these preferences are persisted in versioned browser local storage:
scale mode, quality, compression, view-only, reconnect and the automatic-match
toggle. Clipboard text, credentials, logs and API data are never persisted.

The PWA manifest starts at `/`, has root scope and uses standalone display.
The root-scoped service worker caches versioned static shell/runtime assets and
a truthful offline shell. It never caches WebSockets, API calls, setup,
terminal, logs or non-GET requests. An update does not reload an active remote
session without consent.

The shell uses dynamic viewport units, safe-area insets and separate portrait
and landscape arrangements. HTTPS on a private tailnet through Tailscale Serve
is the recommended iPad deployment. The launcher publishes HTTP to
`127.0.0.1` by default and requires an explicit bind option for direct LAN
access; direct HTTP is development-only for PWA purposes. Detailed research and the physical-device gate are in
`docs/research/novnc-shell.md`; the implementation contract and wireframes are
in `docs/architecture/desktop-shell.md`.

### 3.4 Control API

A Python standard-library service runs as `vibe` on `127.0.0.1:7998`; nginx
proxies `/api/v1/`. Responses are JSON and `Cache-Control: no-store`.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/status` | API version, uptime, disk, display and logical service states. |
| `GET /api/v1/display` | Current resolution, preset modes and dynamic-resize bounds/alignment. |
| `PUT /api/v1/display` | Set one bounded and aligned resolution. |
| `GET /api/v1/logs/{service}?cursor=&limit=` | Read bounded, sanitized service logs. |
| `POST /api/v1/services/{service}/{operation}` | Start, stop, or restart one allowlisted logical service. |

The core logical IDs are `desktop`, `vnc`, `terminal` and `setup`; optional IDs
are `ssh`, `native-vnc`, and `editor`. Fixed code maps them to supervisor
programs and log paths. A narrow helper performs only those supervisor
operations. XRandR changes run as `vibe`, use a validated connected
output name, and accept dimensions from 640x480 through 1920x1200 with widths
aligned to 8 pixels and heights to 2. Existing presets remain available; other
valid sizes are generated with `cvt`, attached to the parsed output, applied
with argv-only commands and re-queried before success. The boot default is
1920x1200 and x11vnc monitors XRandR changes.

Mutation requests require JSON no larger than 4096 bytes, exact fields, one
valid `Host`, and a matching browser `Origin`; cross-origin requests and CORS
are rejected. Mutations are serialized and concurrent work returns 409. Log
pages are at most 200 lines/64 KiB, use byte-offset cursors, tolerate rotation,
strip ANSI escapes and render as text. No request value becomes a command,
program name or filesystem path. This defense reduces browser risk but does not
replace the private-network authorization boundary.

### 3.5 Automation API

A second Python standard-library service runs as `vibe` on
`127.0.0.1:7997`; nginx proxies `/api/v1/automation`. Pairing request/poll are
the only unauthenticated bootstrap routes. All other routes accept either the
compatible persistent 256-bit token in `~/.vibestack/automation.token` or a
separately revocable paired-client credential, including capability discovery.
Responses are non-cacheable and carry a request ID that correlates nginx access
and redacted automation audit events.

The API exposes asynchronous argv and explicit-shell jobs, persisted bounded
stdout/stderr pages, cancellation, PNG screenshots, a fixed application
catalog, EWMH window list/minimize/maximize/normal operations, UTF-8 X11
clipboard access, raw binary `GET`/`HEAD`/`PUT` files below the Desktop and
`/projects`, and API-owned SSH public-key management. Commands can select
Desktop or project root for a confined working directory.
Commands inherit the live Xauthority/D-Bus/keyring environment and target
display `:0` without caller-supplied session variables.

Jobs have four workers, a 32-item queue, 1–300 second timeouts, process-group
cancellation, and 4 MiB caps per output stream. Clipboard text is capped at
1 MiB. Desktop files are capped at 16 MiB, reject symlinks/hard links/mount
crossings/special files, and use ETags, preconditions, descriptor-relative
opens, atomic create-only commits, and immediate best-effort revalidation
before conditional replacement by uncoordinated local writers. Application
responses distinguish pending launches, cancelled launch groups, and
asynchronous window close requests. Full routes and schemas are in
`docs/architecture/automation-api.md`; examples are in `docs/AUTOMATION.md`.

All raw services bind container loopback. Xvfb disables TCP and requires a
per-boot MIT-MAGIC-COOKIE. Docker uses its default seccomp profile and a process
limit. Nginx overwrites a fixed `X-VibeStack-Proxy` marker on terminal and RFB
WebSocket proxying. ttyd requires the header and matching Origin/Host authority;
websockify rejects missing, wrong, or duplicate markers before connecting to
VNC. The marker prevents direct browser use of the container-loopback ports
but is not a user credential. An automation or workspace-client credential is
full `vibe` authority, not a sandbox; private Tailscale Serve remains a required
outer boundary.

### 3.6 Component catalog

`setup/catalog.json` is the single source of truth for what can be installed.
Each component declares an id, group, name, description, approximate installed
size, supported `architectures`, optional `runtime_requirements`, `requires`, a
`probe` shell command that reports whether it is present, and `next_steps`
shown after installing.

| id | Group | Component | Size |
|----|-------|-----------|------|
| `node` | Coding CLIs | Node.js 22.23.2 LTS + npm 10.9.8 | 225 MB |
| `claude-code` | Coding CLIs | Claude Code 2.1.263 | 206 MB |
| `codex-cli` | Coding CLIs | Codex CLI 0.153.4 | 320 MB |
| `opencode` | Coding CLIs | OpenCode 1.18.29 | 353 MB |
| `chrome` | Desktop apps | Google Chrome, amd64 only, with the Claude and Codex extensions | 450 MB |
| `claude-desktop` | Desktop apps | Claude Desktop, amd64/arm64 | 560 MB |
| `chatgpt` | Desktop apps | ChatGPT / Codex desktop, amd64 only | 1.3 GB |
| `godot` | Desktop apps | Godot Engine 4.7.2 standard editor, amd64/arm64 | 200 MB |
| `flatpak` | Desktop apps | Per-user Flatpak, stable Flathub, and XFCE portal integration; explicit runtime mode | 25 MB |
| `build-essential` | Development tools | Distro native compiler toolchain and headers | 200 MB |
| `editors` | Development tools | Mousepad, Geany, Vim, Meld | 82 MB |
| `images` | Development tools | GIMP, Drawing, Flameshot | 210 MB |

Presets: Recommended, Terminal only, Everything, Nothing for now.

The state API annotates every component with `supported` and a
`support_reason` for the current architecture and verified runtime
capabilities. It filters unavailable entries out of each preset's actionable
`components` and lists them separately as `unsupported_components`, so the UI
can visibly disable them. Chrome and ChatGPT desktop are amd64-only. Flatpak is
amd64/arm64 but requires the root-owned nested-sandbox capability marker. The
remaining entries support both architectures. For compatibility, an explicit
unavailable install request returns `409 unsupported_architecture` before the
privileged installer starts, with a runtime-generic error message.

The three coding CLIs require `node`; the ChatGPT desktop app requires Chrome
for its external OAuth flow. `build-essential` installs the distro's exact
metapackage through apt so GCC, G++, Make, and development headers remain an
optional, auto-restored setup choice. The wizard selects dependencies
automatically and the installer orders them. Installing Chrome writes explicit
XFCE, HTTP, HTTPS, and HTML defaults for `google-chrome.desktop`. Installing
ChatGPT keeps its private `codex:` scheme but removes the vendor package's
generic HTTP and HTTPS claims, preventing external sign-in URLs from looping
back into ChatGPT.

Godot installs the pinned 4.7.2 standard Linux editor on amd64 and arm64. Its
desktop entry uses the OpenGL Compatibility renderer and dummy audio for the
GPU-less, audio-less container. The .NET build and export templates are not
installed by this component. Publication first invalidates convergence, writes
the binary and desktop integration, then atomically creates
`/usr/local/bin/.vibestack-godot-4.7.2.complete` as its final step. The catalog
probe requires that exact marker, so interruption or a late shortcut/database
failure remains eligible for repair on the next install or auto-restore pass.

Flatpak installs Ubuntu's `flatpak`, `xdg-desktop-portal`, and
`xdg-desktop-portal-xapp` packages, configures only the exact stable Flathub
repository for `vibe`, and verifies a real bubblewrap namespace/mount preflight.
Applications, runtimes, remotes, app data, and launcher exports are per-user.
The helper exposes search, exact-ID permission inspection, interactive install,
stable-Flathub reference review/install, run, list, update, uninstall, remotes,
and history. A hidden desktop handler is the default for
`application/vnd.flatpak.ref`; it accepts only a bounded regular application
reference naming the stable branch and exact configured Flathub URL, then
installs its validated ID from the existing remote after interactive review.
There is no automatic `.flatpakrepo` handler. An existing remote named `flathub`
with any other URL is refused rather than silently trusted.

Flatpak's inner sandbox cannot nest beneath the normal Docker seccomp, AppArmor,
and protected-system-path policies on the tested host. The default launch keeps
those policies. Explicit `startup.sh --flatpak` relaxes all three for this one
trusted private container, without `--privileged` or added Linux capabilities,
and passes `VIBESTACK_FLATPAK_ENABLED=1`. Entrypoint turns that host selection
into a fresh root-owned, mode-`0444`
`/run/vibestack/host/flatpak-enabled` marker. The unprivileged catalog and root
installer trust the marker rather than a forgeable process environment. Full
ecosystem and sandbox evidence is in
[`docs/research/flatpak-flathub.md`](research/flatpak-flathub.md).

The Node and Godot archives are pinned by version and per-architecture SHA-256.
Node's member graph and extracted filesystem tree are validated before an
atomic rename into a versioned `/opt/vibestack` tree; one `node-current`
pointer activates stable command-only symlinks without merging Node into shared
`/usr/local` trees. Godot's ZIP must contain exactly its expected regular
64-bit ELF for the selected architecture before publication. The three
top-level npm package versions are pinned and verified after installation.
Chrome and ChatGPT still use vendor-controlled moving package URLs; see
[`docs/research/installer-supply-chain.md`](research/installer-supply-chain.md)
for the exact trust boundary and upgrade procedure.

Chrome installs an enterprise policy that force-installs two extensions:

| Extension | ID |
|-----------|-----|
| Claude in Chrome | `fcoeoabgfenejglbffodgkkbkcdhcgfn` |
| Codex | `hehggadaopoacecdllhhajmbjkdcmajg` |

### 3.7 The setup application

A Python standard-library HTTP server (`setup/server.py`) on `127.0.0.1:7999`,
proxied by nginx at `/setup/`, started by supervisor at boot. It runs as `vibe`
and installs through `sudo vibestack-install`. A separate root-only
`vibestack-password` helper hashes, persists, applies, and restores only the
fixed `vibe` account's password.

The UI is three plain files, kept separate so they can be restyled freely:
`index.html`, `style.css`, `app.js`.

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Wizard, or 302 to `/` when component state and password are complete. `?force=1` always shows the wizard. |
| `GET /api/state` | Catalog, installed/saved state, running job, bounded password status |
| `GET /api/log?offset=N` | Incremental install log |
| `POST /api/password` | Set or replace `vibe`'s Linux password from exact `{password, confirmation}` JSON |
| `POST /api/install` | Start an install for the given component ids |
| `POST /api/skip` | Mark setup complete, install nothing |
| `POST /api/complete` | Mark setup complete with what is already installed |
| `POST /api/reset` | Clear state so the wizard returns |
| `GET /api/clients` | Pending pairings and revocable client metadata; never credentials |
| `POST /api/pairings/{code}/approve|deny` | Resolve one expiring verification code |
| `POST /api/clients/{id}/revoke` | Revoke one paired client credential |

The wizard has no application login and is therefore tailnet-private. Its first
step requires a 12–256 UTF-8-byte Linux password before presenting component
selection; `/setup/?force=1` exposes a later replacement action. Replacement
does not require the old value because possession of this private setup surface
is the administrative trust boundary. The server passes plaintext only in the
request body and fixed helper stdin, never argv, responses, shared logs, setup
state, or browser storage.

Setup can invoke only the fixed `vibestack-install` and `vibestack-password`
helpers through restricted passwordless sudo rules. Normal terminal sudo uses
the user-created password. The arbitrary automation surface is separate and
always requires its bearer token. Setup, control, and automation enforce the
same loopback, multi-label `*.ts.net`, or operator-configured exact Host
allowlist on their direct listeners as nginx does,
so a DNS-rebound browser origin cannot bypass the edge Host boundary.

The image contains no default Linux password and builds `vibe` in a locked
state. Bootstrap creates `/data/.vibestack-auth-v1` as root-owned mode `0700`;
the password helper writes only one salted SHA-512 crypt hash with 656,000
rounds to `vibe.shadow` as root-owned mode `0600`. Before any unprivileged
service starts, entrypoint restores that hash into `/etc/shadow`, or explicitly
locks the account when the hash is absent.

The saved hash and `vibe`'s live `/etc/shadow` field are a single invariant.
Status succeeds only when the fields match exactly, or when no saved hash exists
and the live account is locked. Any mismatch fails closed: the helper emits no
status, setup `GET /api/state` returns a safe 503, and a password update cannot
report success. Updates first verify the old invariant, durably publish the new
hash, apply it live, and verify both copies. A failed update rolls the live copy
back before the durable copy; if that rollback itself cannot restore agreement,
the mismatch remains detectable rather than being reported as configured. The
next entrypoint restart makes durable state authoritative again by applying its
hash, or locking the account if the hash is absent, and fails startup if that
postcondition cannot be established. A successful `GET /api/state` exposes only:

```json
{"authentication":{"password_configured":true,"sudo_password_required":true}}
```

There is no endpoint to read, export, or reset to a known password. The desktop
keyring's empty internal unlock value is separate from this Linux credential.

### 3.8 State and bypass

State is stored canonically at `/data/vibestack/setup.json` and is visible at
`~/.vibestack/setup.json` through the persisted user-state link:

```json
{
  "version": 1,
  "completed": true,
  "completed_at": "2026-09-07T11:19:35Z",
  "selected": ["editors"],
  "skipped": false,
  "auto_restore": true
}
```

Ways to bypass component selection (never password creation):

- `vibestack-setup skip` marks setup complete without installing anything.
- `VIBESTACK_SKIP_SETUP=1` does the same at boot, unattended.
- Any valid version-1 state file with `completed: true` sends `/setup/` on to
  `/` only after a Linux password is configured. Skipping components never
  invents or persists a default password.
- `vibestack-setup reset` clears it and the wizard returns.

`vibestack-setup` also offers `status`, `list`, and `install <id>...`.

State reads and writes use a fixed mode-`0600` cross-process lock plus atomic,
synced replacement. Truncated, unreadable, malformed, or unsupported-version
state fails closed instead of being normalized. If a saved component ID is no
longer present in the image catalog, `/api/state` reports it in both `missing`
and `unknown_selected`; auto-restore never passes that unknown ID to the
installer, and startup remains unresolved until the operator rolls back or
resets the selection. Setup state mutations return `409 job_running` while an
installer job is active. A selected component that exists but is unsupported
on the new machine remains in `missing` and `unsupported_selected`; it is not
passed to auto-restore or erased, allowing startup to retain the rollback
image. Web and CLI installers hold the same cross-process lease through
installer exit and the durable state transaction, so CLI skip/reset cannot
race a web install. `/api/state` derives `job.running` from that shared lease,
not only the setup service's in-memory worker. While a CLI owns it the job is
reported with `external: true`, `phase: "external"`, and an empty target. If
the setup service starts while a CLI owns the lease, that process skips its one
boot-time auto-restore attempt and continues serving status; it does not retry
after the lease is released. A later setup-service or container restart
performs the comparison again. An unsafe lease entry instead sets `state_valid`
and `job.lease_valid` false, preserving fail-closed startup behavior.

### 3.9 Auto-restore

Components are installed into the container filesystem, so `docker rm` destroys
them while the persisted state file survives. At boot the setup service compares
`selected` against the probes and reinstalls whatever is missing, streaming the
work into the same wizard UI under a "restore" phase. This is a one-shot startup
decision, not an in-process retry loop. Set `auto_restore` to false in the state
file to turn this off. The state endpoint explicitly reports validity,
parse/version errors, and selected IDs absent from the current catalog. The host
rollout gate treats any of those unresolved states as a candidate failure and
retains/restores its prior container.

### 3.10 Persistence

`startup.sh` bind-mounts a host directory at `/data`. The entrypoint moves each
state path into `/data` and symlinks it back:

The launcher canonicalizes the host state path before creating it. New state
directories receive a `.vibestack-state-v1` marker; a reviewed directory from
an older VibeStack release is adopted once with `--adopt-data`, provided every
existing top-level entry is a known VibeStack state name. Root, the host home,
the repository or any path above or below it, common credential directories,
OS-owned hierarchies, and a path shared with `/projects` are rejected before
Docker runs. The projects mount likewise rejects root, OS-owned hierarchy
descendants, the host home, credential-directory overlap, Git credential or
metadata paths, and the VibeStack source tree. During a
replacement, the old container is retained until Docker health and the saved
auto-restore component set both converge.

| In the container | In `/data` |
|------------------|-----------|
| `~/.vibestack` | `vibestack/` |
| `~/.claude`, `~/.claude.json` | `claude/`, `claude.json` |
| `~/.codex` | `codex/` |
| `~/.config/opencode`, `~/.local/share/opencode` | `opencode-config/`, `opencode/` |
| `~/.config/google-chrome` | `chrome/` |
| `~/.config/Claude`, `~/.config/Codex` | `claude-desktop/`, `chatgpt/` |
| `~/.local/share/flatpak`, `~/.var/app` | `flatpak/`, `flatpak-apps/` |
| `~/.config/godot`, `~/.local/share/godot` | `godot-config/`, `godot-data/` |
| `~/.local/share/keyrings` | `keyrings/` |
| `~/.gitconfig`, `~/.bash_history` | `gitconfig`, `bash_history` |
| Linux password hash (no home link) | `.vibestack-auth-v1/vibe.shadow` |
| Paired-client hashes and workspace identity | `vibestack/client-auth.json`, `vibestack/workspace-id` |
| API-managed SSH public keys | `ssh/vibestack_authorized_keys` |

Stale Chromium `Singleton*` locks in persisted profiles are cleared at boot, and
the container runs with a fixed hostname, so recreated containers reopen them.
`~/.config/Codex` is the ChatGPT/Codex desktop profile used by the Linux package;
it is distinct from the Codex CLI's `~/.codex`. Persistence migrates a nonempty
real profile into an empty persistent target and fails closed rather than
discarding either side when both contain state.

Persistent logs live below `/data/logs/vibestack` and are linked into the
desktop as `VibeStack Logs`. The immutable image guide is available at
`/usr/share/doc/vibestack/AGENTS.md`, `/AGENTS.md`, and
`/home/vibe/AGENTS.md`. Fresh Codex, Claude Code, and OpenCode profiles receive
links to the packaged guide only when the user has not already created the
corresponding instruction or Codex override file; existing instructions are
never replaced. Nginx serves the same file at `/AGENTS.md`, with `/CLI.md`,
`/AUTOMATION.md`, `/RUNNER.md`, the portable skill, and the client bootstrap
beside it.

### 3.11 Session

gnome-keyring runs with a seeded, empty-password `login` keyring so Electron
apps and Chrome store credentials without ever prompting. A system D-Bus runs
under supervisor. A protected `/run/vibestack` directory owns the Xauthority,
XDG runtime directory, root-owned host capability markers, and mode-0600
session environment used by automation. That session publishes per-user and
system Flatpak export directories in `XDG_DATA_DIRS` for menu discovery.
The empty keyring unlock is not the Linux password used by PAM or sudo.
Startup opens the desktop without an interactive terminal or automatic banner.
Its generated background identifies the workspace and its published ports.

### 3.12 Client, SSH, editor, and native VNC

The compiled Go `vibestack` client runs on Linux and macOS amd64/arm64 without
Docker, Go, Python, Node, sudo, or agent configuration. Named profiles store an
origin, stable server identity, kind, optional custom CA, and credential in a
user-only file. When several profiles match a command, the client requires an
explicit `--profile`; it never guesses an instance. HTTPS certificate
validation is mandatory except for loopback HTTP development, server origins
cannot contain reverse-proxy subpaths, and credentials are never forwarded to
an origin-changing redirect.

`cli.sh` downloads a versioned release binary and its published SHA-256 over
HTTPS, checks the digest, then atomically installs to a user-owned directory
(default `~/.local/bin`). It never edits shell profiles or uses sudo, and a
failed download or verification preserves an existing binary. HTTPS
authenticates delivery; the checksum is an integrity check, not an independent
publisher signature.

OpenSSH listens on container port 22 and supports the user-created full Linux
password plus public keys. The public-key API writes only its separate managed
file; the user's ordinary `authorized_keys` is not replaced and private keys
never enter VibeStack. Native VNC listens separately on container port 5901 and
uses PAM/full Linux-password remote login. Its root process disables MIT-SHM
capture because the X server belongs to `vibe`; password authentication becomes
usable once onboarding unlocks that account. The browser VNC service remains
independent. code-server is included in the base image, starts automatically, and is proxied at `/editor/`;
desktop VS Code is expected to use Remote SSH rather than a second in-container
desktop editor install.

### 3.13 Docker host runner

`vibestack-runner` is a separate Linux Go daemon with an authenticated API and
local administrative CLI; it is not the in-container command-job runner. It
alone accesses the local Docker Unix socket. It stores a stable identity,
approved immutable image IDs, instance ownership/intent, ports/resources,
credential hashes, operations, and Serve mappings in SQLite under
`/var/lib/vibestack-runner`, with private workspace credentials in separate
mode-0600 files. Full design details are in
[`docs/architecture/runner.md`](architecture/runner.md).

Each managed instance gets independent named `/data` and `/projects` volumes,
loopback-only HTTP/SSH/VNC ports, bounded CPU/memory/PIDs, and labels from the
shared versioned launch contract. The runner reconciles known records with
Docker inspection and never adopts unknown containers. Agents select only
operator-approved templates; they cannot submit builds, host mounts, networks,
capabilities, or raw Docker options.

Create/update operations are durable, conflicting operations serialize per
instance, and idempotency keys are scoped to the owning principal. Remove
retains volumes by default; purge is an explicit local-only operation. Update
retains the prior container until candidate health and saved application
restoration succeed, then commits the new generation. Failure restarts the old
generation and preserves data, subject to the documented limitation that
container rollback cannot undo arbitrary data migrations.

When enabled, Tailscale Serve management changes only exact mappings recorded
by the runner and never uses a global reset. Runner mediation resolves a
recorded instance server-side and forwards only supported workspace API paths;
it never accepts an arbitrary proxy destination or releases the workspace
credential.

## 4. Acceptance criteria

`vibestack-check` runs non-destructive container checks. Python unit tests cover
the control boundary, and browser tests cover behavior that a raw curl cannot.
`--install` additionally exercises a real component install. Items explicitly
marked physical are release checks performed on an iPadOS 17+ device.

**Routes and transport**

- AC-1 `/terminal/` serves ttyd and `/terminal/ws` upgrades to a WebSocket.
- AC-2 `/vnc/` serves the VibeStack shell, contains no stock noVNC controls,
  imports the pinned RFB module, and reaches ServerInit through
  `/vnc/websockify`.
- AC-3 `/` opens Desktop, requesting password setup only when needed. Successful
  password setup opens the Apps sidebar. Query `panel=apps` forces that sidebar;
  Apps opens the full-screen searchable catalog with pack selection. Terminal and
  Editor each have a full workspace view and a return path to Desktop.
- AC-4 `/manifest.webmanifest`, `/service-worker.js`, shell assets, icons and
  required `/novnc/` modules return correct content types. Obsolete `/ui/`,
  `/admin/` and `/mcp` paths return 404.
- AC-5 The product never links to upstream `vnc.html`; its diagnostic route is
  removed or blocked before release.

**Desktop shell**

- AC-6 Connection state covers connect, clean disconnect, unexpected
  disconnect, offline pause, bounded reconnect, manual Retry, security failure
  and VNC restart without creating duplicate RFB objects or retry timers.
- AC-6a Desktop/Terminal tabs are keyboard accessible, preserve same-document
  history, lazy-load the same-origin ttyd frame, avoid an RFB connection for a
  terminal-first launch, and reconnect when Desktop is selected again. The
  disposable browser suite loads the real ttyd client, verifies its iframe,
  CSP, resources, WebSocket and focus path, and observes a computed result from
  harmless keyboard input sent to the PTY.
- AC-7 Fit and 1:1 modes, quality 0–9, compression 0–9, view-only, reconnect
  and automatic-match preferences affect their documented behavior and survive
  reload. Invalid stored fields fall back safely; automatic matching defaults
  off and `RFB.resizeSession` remains false.
- AC-8 The top **Menu** disclosure is collapsed by default and provides
  clipboard send/receive, software-keyboard focus, latched modifiers,
  Ctrl-Alt-Delete, one-shot screen matching, Settings, and Tools without a
  bottom desktop overlay or separate top-level Settings/Tools buttons. Clipboard
  and credentials never enter persistent storage, and modifiers are released
  when the panel closes, on disconnect, and on page hide.
- AC-9 The Menu popover and Settings and Tools drawers are keyboard
  accessible, restore focus, close on Escape, use 44px touch targets and
  communicate status without color alone. Logs and remote strings are rendered
  as text.
- AC-10 Service restart requires explicit confirmation, reports the backend
  result, and an expected VNC disconnect flows into normal reconnect recovery.

**Control API and privilege boundary**

- AC-11 The control server runs as `vibe`, binds only `127.0.0.1`, is exposed at
  `/api/v1/`, returns versioned JSON and sends `Cache-Control: no-store`.
- AC-12 Status returns uptime, disk, display and all core plus configured
  optional logical services while
  degrading an individual failed probe to unknown rather than failing the
  complete response.
- AC-13 Only `desktop`, `vnc`, `terminal`, `setup`, `ssh`, `native-vnc`, and
  `editor` are accepted. Status, start/stop/restart and log calls map to fixed
  supervisor programs and paths; unknown IDs run no command.
- AC-14 Mutations require bounded, exact JSON and matching Host/Origin, reject
  cross-origin and CORS requests, serialize concurrent work and return stable
  `{code,message}` errors.
- AC-15 Helper calls use fixed argv arrays, no shell, non-interactive sudo and
  timeouts. Browser input cannot select a command, executable, supervisor
  program, display output or filesystem path.
- AC-16 Log queries enforce non-negative cursors, limits 1–200, 64 KiB pages and
  4096-byte lines; rotation sets `reset`, ANSI is stripped and control bytes are
  escaped.
- AC-17 Fixed presets and viewport-derived dimensions are restricted to
  640x480–1920x1200, width/height alignment of 8/2 pixels, and the XRandR
  framebuffer maximum. Missing valid modes are generated and attached with
  argv-only execution; every change is re-queried before success. Invalid,
  unavailable and unconfirmed modes return truthful distinct errors.

**PWA and physical iPad**

- AC-18 The manifest uses `/` start URL, root scope and standalone display;
  the worker controls root scope, precaches only versioned static dependencies,
  deletes old caches and never caches API, setup, terminal, WebSocket, logs,
  clipboard or mutations.
- AC-19 Offline launch renders a cached shell that says the remote desktop
  needs connectivity. A worker update never reloads a live session without
  user consent.
- AC-20 (physical) A private HTTPS tailnet URL installs from Safari, launches
  without browser chrome, respects safe areas in portrait/landscape and remains
  recoverable across rotation and software-keyboard viewport changes.
- AC-21 (physical) Touch gestures, software and Bluetooth keyboards, clipboard,
  background/resume, network loss/recovery, one-shot screen matching and
  opt-in automatic matching work across supported iPadOS 17+ orientations.

**Slim base and setup**

- AC-22 No catalog component or npm is present in a fresh image; scrot, xclip,
  xdotool, wmctrl, xprop, Xauthority, and XRandR utilities are present.
- AC-23 The setup service runs under supervisor and serves its wizard/assets;
  its state API returns a valid catalog, installed list, state, job, and only
  bounded password configuration booleans.
- AC-24 Every catalog ID has an installer branch, every preset and dependency
  references a real ID, and resolution orders `node` before dependent CLIs.
- AC-25 Setup CLI `status` and `list` work; unknown component IDs are rejected;
  web and CLI install failures do not mark setup complete or discard the
  selected components.
- AC-26 `skip` writes completed component state; a locked account remains in
  password onboarding, configured-and-complete state redirects `/setup/` to
  `/`, `?force=1` still shows settings, and `reset` restores component setup.

**Persistence and session**

- AC-27 With `/data` mounted, every declared state path links into `/data`
  without recursively changing ownership of the mounted project tree.
- AC-28 Setup state, Godot settings/data, per-user Flatpak apps/data, and the
  private password hash survive
  container removal and a fresh run against the same data directory; ad-hoc
  apt packages do not. Disposable acceptance then selects Godot and
  `build-essential` plus Flatpak through the catalog, installs one disposable
  stable-Flathub smoke app, recreates the container again, waits boundedly for
  auto-restore, and verifies all component probes, both Godot sentinels, the
  exact remote, and real Godot/Flatpak XFCE windows.
- AC-29 xfwm4, xfdesktop and the keyring daemon run; the login keyring is
  unlocked; `/run/vibestack/session.env` describes the authorized live X11
  session; the background identifies the workspace and no welcome terminal opens.

**Install, CI and release**

- AC-30 Installing a component succeeds, flips its probe, configures expected
  integration/shortcuts and is reported by the API; full disposable acceptance
  downloads the pinned Godot archive, searches exact stable Flathub, and
  observes real Godot and sandboxed Flatpak XFCE windows. Setup completion
  implies auto-restore has converged.
- AC-31 CI builds the image and calls the same disposable acceptance helper as
  local development, including unit/runtime/browser checks, password-auth sudo,
  container recreation, Godot launch, nested bubblewrap preflight, and a real
  stable-Flathub application launch; publication is blocked on failure.
- AC-32 A clean documented `startup.sh check` rebuild passes from source; no
  behavior needed for acceptance exists only in a manually modified container;
  rollback state is retained until saved application restoration converges.

**Automation, logging, performance and desktop experience**

- AC-33 Except for bounded pairing request/poll, every automation route,
  including capability discovery, rejects a missing, revoked, expired, or
  incorrect bearer token; valid responses are non-cacheable, have a server
  request ID, enforce Host/matching optional Origin, and expose no CORS opt-in.
- AC-34 Argv and explicit-shell submissions create asynchronous jobs with the
  fixed graphical session environment, bounded queue/workers/time/output,
  persisted byte-safe stdout/stderr pages, truthful exit state, and
  process-group cancellation.
- AC-35 Screenshots return valid PNG bytes or atomically save a confined `.png`;
  application start/stop accepts only fixed catalog IDs; window actions accept
  only freshly revalidated XIDs and minimized/maximized/normal state.
- AC-36 Desktop and project file GET/HEAD/PUT preserve arbitrary bytes, enforce
  16 MiB objects and 8 MiB ranges, implement ETags/preconditions and atomic
  writes, and reject traversal, symlinks, hard links, mount crossings and
  special files. Command working directories select the same explicit roots.
  No file delete route exists.
- AC-37 Clipboard GET/PUT round-trips up to 1 MiB of UTF-8 `text/plain` and
  deliberately manages the X11 CLIPBOARD owner process.
- AC-38 `/data/logs/vibestack` persists bounded nginx JSON access, service, and
  automation-audit logs and is linked as `VibeStack Logs`. Accepted command
  and shell jobs add exactly one redacted terminal event correlated to the
  original submission request ID. Request IDs
  correlate events while tokens, cookies, commands, custom environment,
  clipboard/file bodies, screenshots, and stdout/stderr never enter shared
  logs.
- AC-39 Xvfb requires its per-boot cookie and disables TCP; raw X11, VNC,
  websockify, ttyd, setup, control and automation listeners are loopback-only;
  Docker uses default seccomp plus a PID cap. Explicit `--flatpak` alone
  relaxes seccomp, AppArmor, and protected system paths without privileged mode
  or added capabilities, and publishes a fresh root-owned capability marker.
  `vibe` has password-authenticated general sudo and exactly three fixed
  passwordless helpers.
  Nginx rejects Hosts outside loopback, valid multi-label `.ts.net`, or the
  bounded operator-configured exact allowlist, and rejects any supplied Origin
  that is not strictly same-authority before HTTP or WebSocket routing.
  Cross-site/same-site fetch metadata is accepted only for a safe top-level
  `GET`/`HEAD` with mode `navigate` and destination `document` or
  extension-generated `empty`; subresources, mutations, and WebSocket upgrades
  remain rejected.
- AC-40 noVNC rendering profiles apply 7/2, 9/2 and 5/6 quality/compression
  pairs; websockify has an idle heartbeat; compositor/XDamage/24-bit/shm
  choices remain intact; Docker health performs one cheap Supervisor probe;
  launchers retain a bounded 1024-task default for multi-process desktop apps.
- AC-41 XFCE presents curated VibeStack, Coding, Create & Review, Applications,
  and System sections with install-aware catalog/Flatpak launchers, direct
  settings/onboarding/logs/agent-guide/Flathub links, and fixed action scriptlets.
- AC-42 Fresh persisted Codex, Claude Code, and OpenCode profiles receive
  links to version-matched global VibeStack guidance and the complete
  automation guide; an existing instruction or Codex override is never
  overwritten.
- AC-43 The accepted image remains healthy after rollback-safe live rollout on
  the original mounts and passes both loopback and private Tailscale Serve
  checks, including RFB/terminal WebSockets and an authenticated automation
  audit event.
- AC-44 Direct WebSocket handshakes to websockify without the nginx marker, or
  with a wrong marker, receive 403. Direct ttyd handshakes without the marker
  are denied before upgrade (an explicit 403 or libwebsockets' empty transport
  close); the acceptance check distinguishes those exact outcomes from an
  unavailable service. The nginx-proxied RFB and terminal handshakes succeed.
- AC-45 When Chrome is installed, XFCE plus the HTTP, HTTPS, and HTML MIME
  defaults resolve to `google-chrome.desktop`, whose XFCE helper runs the
  container-safe `vibestack-app` wrapper; ChatGPT retains its app-specific
  scheme but is not registered as an HTTP/HTTPS handler. Its actual
  `~/.config/Codex` desktop profile persists independently of `~/.codex`.
- AC-47 A fresh account is locked and reports `password_configured: false`.
  A bounded same-origin password POST never echoes or logs plaintext, rejects
  mismatch/bad policy, and makes both terminals' normal sudo password-authenticated.
  Disposable acceptance rejects a wrong password, uses the right one for a real
  `apt-get install build-essential`, recreates the container from the same image
  and `/data`, then proves the password still works and only the hash persisted.
  Saved and live password fields must agree for status to succeed; a mismatch
  makes setup fail closed, remains detectable after an incomplete rollback, and
  is reconciled from durable state (or to a locked account when absent) before
  unprivileged services start on the next container boot.
- AC-48 `/AGENTS.md`, `/CLI.md`, `/AUTOMATION.md`, `/RUNNER.md`, the skill, and
  `/cli.sh` return the exact packaged files without credentials; Markdown is
  non-cacheable UTF-8 and `/AGENTS.md` plus `/home/vibe/AGENTS.md` inside the
  image point to the same canonical operating guide.
- AC-49 Flatpak is unavailable without the verified per-boot marker. In
  explicit mode, stable Flathub's URL is exact, persistence/export paths and
  the XFCE portal backend exist, bubblewrap succeeds, search returns the known
  smoke ID, both `flatpak+https` and `.flatpakref` resolve to bounded
  stable-Flathub review handlers, and the installed app survives replacement
  and opens a real window.
- AC-50 The client installer handles Linux/macOS amd64/arm64, verifies the
  versioned checksum, installs atomically without sudo/profile edits, gives PATH
  guidance, and preserves an existing binary on download/checksum failure.
- AC-51 Workspace and runner pairing require both an expiring verification code
  approval and a separate polling secret. Credentials are delivered once,
  stored user-only, individually revocable, permission-checked, and absent from
  URLs, command arguments, documentation, onboarding prompts, and shared logs.
- AC-52 Client commands cover every operation in the published API
  specifications, preserve binary bytes, surface request/job/operation IDs and
  remote exit status, reject incompatible versions, and require explicit
  selection when multiple profiles exist.
- AC-53 A managed two-instance journey creates independent data/project
  volumes, credentials, resources, loopback ports, and browser origins; uploads
  project bytes, executes work, retrieves results, stops/removes containers
  while retaining volumes, and permits only a separate local purge.
- AC-54 Runner create/update idempotency survives client disconnect/retry;
  reconciliation handles restart during provisioning, external Docker change,
  occupied ports, and leftover candidates without adopting unknown containers
  or disturbing another owner.
- AC-55 Replacement does not remove the old generation before candidate health
  and application restoration succeed. Failure preserves data and restarts the
  old generation; release notes state that application-data migrations require
  compatible rollback or backup.
- AC-56 SSH accepts the configured Linux password and independent public keys;
  native VNC requires the full Linux password and can stop without interrupting
  browser desktop; editor state survives data reuse and desktop VS Code can use
  Remote SSH. Private SSH keys never enter the workspace.
- AC-57 A real Claude Code session in its documented execution environment can
  install the skill without overwriting existing guidance, pair an explicit
  profile, discover capabilities, complete a `/projects` work cycle, and
  retrieve the result. Physical-device and external-agent checks are explicitly
  recorded when the current test environment cannot perform them.

## Runner reusable-state extension

Runner API 1.1 additively exposes authenticated `/api/v1/runner/host`, `/drives`,
`/environment-sets`, `/snapshots`, `/instances/{id}/attachments` and
`/instances/{id}/snapshot`. The existing launch contract v1 gains optional
registered-ID storage selection and a 1 GiB shared-memory default. Desktop
`/data` is private; project/file drives are separately registered and retained.
Attachments change while stopped and writable drives have one active desktop.
Environment values remain private and cannot override runner runtime settings.
Stopped-state seeds preserve password hashes/application caches/keyrings while
regenerating workspace tokens, pairing identities and SSH host keys; operation
logs and runtime locks are excluded. Snapshot copies are independent and require
compatible application images. Remote ownership checks apply to every resource.

The broker serves configured-origin `/AGENTS.md` and its OpenAPI document;
harnesses must explicitly load the guide. No dashboard, automatic password
interception, live credential synchronization or onboarding redesign is added.
Systemd host installation and real selected-service sign-in reuse remain separate
acceptance gates. See [RUNNER.md](RUNNER.md) and [DEVELOPMENT.md](DEVELOPMENT.md).

### Opt-in manual walkthrough diagnostics

`/vnc/walkthrough.js` is loaded by setup, Home and the desktop shell. The
`walkthrough=1` tab setting enables bounded metadata events posted to
`POST /api/v1/diagnostics/events`; `walkthrough=0` disables it. This narrow control
route uses the existing private-network/same-origin boundary, bounded JSON input,
strict enum/numeric fields and a global 200-events/10-second limit. It accepts no
arbitrary text or content and exposes no log-reading endpoint. Supervisor rotates
its output in `/data/logs/vibestack/services/vibestack-control.log`. The host
walkthrough helper combines sanitized metadata into a private rotating JSONL
trace and supports explicitly targeted ephemeral source patches with backups.

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
