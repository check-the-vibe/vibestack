# VibeStack

A slim Docker image that gives AI coding tools a full Linux desktop, reachable
from any browser:

- **Terminal** at `/terminal/` — a tmux-backed shell (ttyd).
- **Desktop** at `/vnc/` — VibeStack's installable web shell around an XFCE desktop.
- **Setup** at `/setup/` — first-boot Linux password and application wizard.
- **Desktop** at `/` — the default workspace, with Apps and Settings sidebars.
- **Automation** at `/api/v1/automation` — bearer-authenticated desktop, command,
  application, window, project/file, SSH-key, screenshot, and clipboard operations for agents.
- **Browser editor** at `/editor/` — required, preinstalled code-server rooted at `/projects`.
- **Agent CLI** — a compiled Linux/macOS client with named profiles, device
  pairing, byte-safe project workflows, and stable JSON output.
- **Host runner** — a separate Linux service for approved-image, multi-instance
  Docker lifecycle; it has an authenticated API and local admin CLI, not a dashboard.
- **Agent guide** at `/AGENTS.md` — version-matched operating instructions for
  authorized local and tailnet agents; `/AUTOMATION.md` is the full REST reference.
- **Workspace service** — shared API authentication, revocable credentials,
  browser sessions and a static publish directory. Read [the service guide](docs/SERVICE.md).

API calls now require credentials, including status/control and setup aliases.
Browser access uses the human credential handoff at `/connect.html`. Upgrade the
CLI for authenticated friendly control commands; existing automation credentials
remain supported. The direct MCP adapter is not yet enabled in this foundation.

The desktop shell owns the complete browser interface while using noVNC's
maintained RFB engine underneath. Accessible Desktop/Terminal tabs keep the
graphical workspace and an embedded ttyd terminal in one browser view. A compact
**Menu** button in the top bar
opens keyboard, clipboard, modifier, Ctrl-Alt-Delete, screen-matching,
**Settings**, and **Tools** actions, then collapses so they do not continuously
cover the desktop. Settings controls connection and display preferences; Tools
exposes service health, bounded logs and safe restart actions through a small
local API.

The base image includes the desktop, browser interfaces, automation runtime,
and core code editor. Optional coding agents, browsers and other applications
are installed by you from a catalog. The full specification is in
[docs/SPEC.md](docs/SPEC.md). Read the checked-in
[Linux desktop automation research](docs/research/linux-desktop-automation.md)
for the Ubuntu/XFCE choices and execution primitives, and the
[desktop rendering audit](docs/research/performance-audit.md) for measurements
and adopted noVNC improvements.

## Run

Development plans, feature specifications and branch-owned tickets live in
[`.context`](.context/README.md). Read its [operating instructions](.context/workflow.md)
to distinguish checked-in main state from work in flight.
The [capability contract](docs/architecture/capability-contract.md) and
[source inventory](contracts/capability-inventory-v1.json) guide the next API/MCP
implementation. Their target mappings are not claims of deployed endpoints.

### GitHub Codespaces

[Open in GitHub Codespaces](https://codespaces.new/check-the-vibe/vibestack)
on a branch containing the Codespaces configuration. The source opens in the
Codespaces editor; VibeStack builds and starts automatically on forwarded port
**8080**. Keep that port **Private** and open it for the desktop web interface.
The same Git checkout is writable at `/projects/vibestack` inside the desktop;
other projects keep their separate persistent storage.
The minimum machine is **4 cores / 16 GB RAM**. First creation needs time to build;
full Python installs before the editor opens, and the desktop build continues
in the background. See
[the Codespaces guide](.context/github-codespaces.md) for persistence, prebuilds,
rebuilding, private credential-directory permissions and troubleshooting.

### Local Docker

```bash
./startup.sh                     # build and run on 127.0.0.1:8080
./startup.sh --port 9090         # different host port
./startup.sh --bind 0.0.0.0      # explicit direct LAN exposure
./startup.sh --data ~/vibestack  # where logins and your setup choice persist
./startup.sh --data ~/vibestack --adopt-data  # one-time use for existing state
./startup.sh --projects ~/code   # mounted at /projects
./startup.sh --mount-source     # additionally share this checkout under /projects/<repo-name>
./startup.sh --ssh-port 2222     # password/key SSH, loopback only (0 disables)
./startup.sh --vnc-port 5900     # full-password native VNC (0 disables)
./startup.sh --allowed-host workspace.example.test  # explicit custom Host allowlist
./startup.sh --flatpak           # opt in to nested Flatpak application sandboxes
./startup.sh --skip-setup        # unattended: skip apps; password setup still remains
./startup.sh check               # run the acceptance checks after start
```

Open `http://localhost:8080/`. A fresh workspace asks for the Linux password
used by `sudo`, then opens Desktop with the Apps sidebar. Browse individual apps
or choose a pack in the full-screen installer. Terminal and Editor fill the
workspace and return to Desktop. The application catalog remains available from
Apps; settings remain available in a sidebar. Catalog installs and restoration
retain certificate-verified HTTPS and APT signature verification. Keep these
single-user interfaces private through loopback or Tailscale Serve.

Nginx accepts only `localhost`, `127.0.0.1`, `[::1]`, valid hostnames below
`*.ts.net`, and exact names explicitly configured with `--allowed-host` or
`VIBESTACK_ALLOWED_HOSTS` (each optionally with a port). Other Host values are rejected before
setup, terminal, desktop, control, or automation routing, which prevents DNS
rebinding from turning a browser's same-origin access into local control. If a
browser sends `Origin`, its HTTP(S) authority must exactly match `Host` (the
scheme may differ across Tailscale TLS termination). A `GET` or `HEAD` carrying
cross-site or same-site fetch metadata is accepted only when it is a safe
top-level request with `mode=navigate` and destination `document` or the
extension-generated `empty`, which lets direct links and browser launchers open
the workspace. Cross-site subresources, WebSockets, mutations, and duplicate
or malformed metadata are rejected on every route. CLI requests may omit these
browser-only headers.
Nginx also overwrites a private proxy-marker header before forwarding the
terminal and RFB WebSockets. ttyd requires that header and checks WebSocket
Origin against the port-preserving Host; websockify requires exactly one
constant-time exact marker match. Direct browser connections from inside the
desktop to the raw loopback ports therefore fail. The fixed marker is defense
in depth, not a user credential; container loopback and private Tailscale Serve
remain the network boundary.

## Connect an agent

Setup and Settings contain a reusable **Connect your agent** walkthrough. Run
the installer on the machine where the agent process actually executes, then
pair a named profile without putting a credential in the command or URL:

```bash
curl -fsSL 'https://workspace.example/cli.sh' | \
  sh -s -- --version 0.2.0 --server 'https://workspace.example'
vibestack connect --name studio --url 'https://workspace.example'
vibestack --profile studio doctor
vibestack --profile studio capabilities
```

Approve the displayed code in workspace Setup/Settings. Each client receives a
separate revocable credential. The legacy automation token remains compatible.
A local Claude Desktop session uses the local CLI; a Claude Code session over
SSH needs the CLI and private-network reachability on that SSH machine. Cloud
web-fetch tools generally cannot reach a private Tailscale URL. See
[the CLI reference](docs/CLI.md), [automation reference](docs/AUTOMATION.md),
and [runner guide](docs/RUNNER.md).

## Managed Docker hosts

`vibestack-runner` runs only on the Docker host and is packaged for Ubuntu
24.04/26.04 systemd. It approves immutable local image digests, allocates
independent `/data` and `/projects` volumes plus loopback ports, applies
operator CPU/memory/PID/count/disk limits, records durable SQLite operations,
and reconciles its labeled containers after restart. Remote clients cannot
submit builds, mounts, capabilities, or Docker flags. Optional runner-owned
Tailscale Serve mappings are explicit and never reset unrelated mappings.
Removing an instance retains both volumes; only the local operator can purge a
removed instance. Installation and trust details are in [docs/RUNNER.md](docs/RUNNER.md).

The launcher marks every newly created state directory with
`.vibestack-state-v1`. If upgrading an existing VibeStack state directory,
inspect the path first and pass `--adopt-data` once. Broad paths such as `/`,
your home directory, the source tree (or anything above or below it), OS-owned
hierarchies, and common credential directories are always rejected because the
container intentionally manages `/data` metadata. Adoption also stops if the
directory contains a top-level name VibeStack does not own, which catches a
mistyped personal directory before its metadata can change.
The projects mount similarly rejects root, OS-owned hierarchy descendants,
your home, credential-directory overlap, Git credential/metadata paths, and
the VibeStack source tree as the projects root. The explicit `--mount-source`
flag separately shares this checkout in a named subfolder and refuses to hide
an existing project. Choose the ordinary project directory you want the
remote development user to edit.

## Linux password and sudo

There is no default password. A new image keeps the `vibe` account locked until
you set a password in the first setup step. The same password works at normal
`sudo` prompts in the graphical XFCE terminal and the browser terminal. Change
it later at `/setup/?force=1`; because setup is a trusted administrator surface,
changing it does not ask for the prior password.

Only a salted SHA-512 crypt hash is saved at
`/data/.vibestack-auth-v1/vibe.shadow` (root-owned mode `0600`). Plaintext is
sent in the same-origin setup request and helper stdin only; it is not placed in
process arguments, responses, shared logs, setup state, or browser storage.
VibeStack treats that durable hash and `vibe`'s live `/etc/shadow` field as one
invariant: configured status is available only when they agree exactly, or when
the durable hash is absent and the live account is locked. A mismatch makes
password status and setup fail closed instead of guessing which copy is valid.
On every container start, entrypoint reconciles the live account from durable
state before unprivileged services run, applying the saved hash or locking the
account when none exists. If an update fails, rollback is attempted; even if
rollback itself cannot restore both copies, the mismatch remains detectable and
the next restart reconciles the live account to the durable record before
services start, or refuses to continue if that postcondition cannot be reached.
The password endpoint has no separate HTTP login in this release, so anyone who
can reach the private desktop can replace it. Keep nginx loopback-only and use
private Tailscale Serve—never Funnel or a public reverse proxy.

After setup, ordinary package management works as expected:

```bash
sudo apt-get update
sudo apt-get install build-essential
```

Those direct changes live only in the current container. For tools that should
return after an image replacement, choose the catalog component instead (for
example `vibestack-setup install build-essential`). Three fixed VibeStack
helpers remain passwordless so onboarding, component installation, and desktop
control can bootstrap safely; all other `sudo` commands require your password.

## SSH, native VNC, and editors

The launcher publishes SSH on `127.0.0.1:2222` and native VNC on
`127.0.0.1:5900` by default; use `0` to disable either host mapping. SSH accepts
the user-created Linux password and public keys. API-managed public keys live
in `~/.ssh/vibestack_authorized_keys`, while an existing user-managed
`authorized_keys` file is preserved; private keys stay on the customer device.
Native VNC is a separate PAM-backed x11vnc listener and therefore requires the
full Linux password. Stopping it does not stop the passwordless browser desktop
transport.

Install the Browser editor catalog component to enable code-server at
`/editor/`. Desktop VS Code is intentionally used through Remote SSH rather
than a second browser editor protocol. Editor configuration and data persist
under `/data`, and projects remain on the independent `/projects` mount.

## Flatpak and Flathub

For desktop applications outside the VibeStack catalog, launch the trusted
private desktop in explicit Flatpak mode and install the optional component:

```bash
./startup.sh --flatpak
vibestack-setup install flatpak
```

The XFCE VibeStack menu then provides **Flathub Marketplace** and **Manage
Flatpak Apps**. VibeStack configures only stable Flathub and installs everything
per-user. Apps and runtimes persist at `/data/flatpak`; app data persists at
`/data/flatpak-apps`; exported launchers join the curated applications menu.
Choosing **Install** on a current Flathub app page opens its `flatpak+https`
application link. XFCE routes that exact stable-Flathub URL to a VibeStack
terminal, which downloads a bounded `.flatpakref`, validates the source,
branch, type, and matching app ID, shows the exact app's permissions, and
leaves the final confirmation to you. Downloaded `.flatpakref` files use the
same review path. Repository `.flatpakrepo` files intentionally have no
automatic handler.

```bash
vibestack-flatpak status
vibestack-flatpak search 'image editor'
vibestack-flatpak info org.gimp.GIMP
vibestack-flatpak install org.gimp.GIMP
vibestack-flatpak install-ref ~/Downloads/org.gimp.GIMP.flatpakref
vibestack-flatpak update
```

Review the exact app ID, publisher verification, requested permissions, and
download before approving an install. Beta, nightly, vendor, and arbitrary
remotes are not added automatically. Use apt or a durable catalog component
for compilers, libraries, drivers, daemons, and other host integration.

Flatpak's nested bubblewrap sandbox needs Docker seccomp, AppArmor, and
protected-system-path policy relaxed for this container. `--flatpak` applies
those three options without `--privileged` or added capabilities, but it still
weakens the outer Docker boundary; the normal launch remains confined. Keep
the flag on future replacements once `flatpak` is saved in setup state. The
evidence and alternatives are in
[docs/research/flatpak-flathub.md](docs/research/flatpak-flathub.md).

## Install on an iPad

An installed web app needs HTTPS when it is opened from another device. Keep
the container HTTP-only and expose it privately with Tailscale Serve:

```bash
tailscale serve --bg --https=9443 http://127.0.0.1:8080
```

Open the resulting `https://<machine>.<tailnet>.ts.net:9443` URL in Safari,
complete setup, then choose **Share → Add to Home Screen**. The manifest launches
Desktop as a standalone app. Direct HTTP remains useful for local development,
but it does not support the service worker on an iPad.

The explicit non-default HTTPS port avoids replacing another Serve mapping on
the host. Check existing mappings first with `tailscale serve status --json`.

The remote desktop itself always needs a live connection. When offline, the
cached shell explains how to reconnect rather than pretending the OS is
available.

## Desktop shell

- **Workspace tabs**: switch between the graphical desktop and the embedded
  persistent terminal. A terminal-first launch defers the RFB connection until
  Desktop is selected; `/terminal/` remains available as a raw ttyd route.
- **Settings**: tuned balanced/clarity/constrained rendering profiles, fit or
  1:1 scaling, manual JPEG quality/compression, view-only mode,
  reconnect preference, fixed display sizes and optional automatic viewport
  matching (off by default).
- **Tools**: desktop/VNC/terminal/setup status, bounded service logs and
  confirmed restarts.
- **Unified menu**: expand **Menu** for keyboard, clipboard, modifier keys,
  Ctrl-Alt-Delete, one-shot **Match screen**, **Settings**, and **Tools**;
  focus and fullscreen remain directly available in the top bar. There is no
  persistent bottom toolbar over the remote desktop.

**Match screen** sizes the Linux desktop from the available canvas in CSS
pixels. The control API creates a bounded XRandR mode (640x480 through
1920x1200, width aligned to 8 pixels and height to 2) and keeps local noVNC
scaling enabled. VibeStack deliberately does not use noVNC `resizeSession`.

The shell-facing control API remains deliberately narrow. The separate
automation API can run commands with the authority of the `vibe` account, but
requires a legacy token or individually paired bearer credential on every request and confines convenience
file operations to the Desktop or durable `/projects` roots. VNC preferences stay in local browser storage;
clipboard contents and credentials are never persisted there.

## Automation and logs

The complete REST contract and copyable inside/outside-container examples are
in [docs/AUTOMATION.md](docs/AUTOMATION.md). The compatible legacy token is generated at
`~/.vibestack/automation.token` with mode `0600` and persists under `/data`.
Pairing creates separate revocable credentials. Treat either as a password: a
holder can execute shell commands as `vibe`.

Every interface request, privileged automation action, and Supervisor service
has bounded persistent logging below `/data/logs/vibestack/`. The desktop links
that directory as **VibeStack Logs**, so a local or remote coding agent can
correlate a response's `X-Request-ID` with access, audit, and service logs.
Tokens, cookies, clipboard/file bodies, screenshots, command text, and command
output are excluded from shared logs.

## What you can install

| Component | Size | Notes |
|-----------|------|-------|
| Node.js 22 LTS | 225 MB | Required by the three CLIs |
| Claude Code | 206 MB | `claude`, drives Chrome with `--chrome` |
| Codex CLI | 320 MB | `codex` |
| OpenCode | 353 MB | `opencode` |
| Google Chrome | 450 MB | Claude and Codex extensions force-installed |
| Claude Desktop | 560 MB | Chat and Claude Code tabs |
| ChatGPT / Codex desktop | 1.3 GB | Large download; installs Chrome for external sign-in |
| Godot Engine 4.7.2 | 200 MB | Pinned standard editor; amd64/arm64, Compatibility renderer |
| Browser editor | 775 MB | Pinned code-server at `/editor/`, rooted at `/projects` |
| Flatpak + stable Flathub | 25 MB plus selected app runtimes | Per-user apps; requires `--flatpak` |
| Native build tools | 200 MB | Distro `build-essential`: GCC, G++, Make, and development headers |
| Editors and diff | 82 MB | Mousepad, Geany, Vim, Meld as `git difftool` |
| Image editing | 210 MB | GIMP, Drawing, Flameshot |

Pick a preset or choose individually. Dependencies are selected for you.
The setup API detects both container architecture and required runtime
capabilities, then visibly disables unavailable choices. Chrome and ChatGPT
desktop are amd64-only; Flatpak supports both architectures but requires
`--flatpak`. Presets omit unavailable entries and show why they were omitted.

Those labels describe catalog behavior inside an image built for that
architecture; they are not a published-image guarantee. The current GHCR
workflow runs on an amd64 GitHub-hosted runner and pushes only that runner-native
image, without an arm64 manifest. Build and test arm64 separately rather than
assuming a published tag is multi-platform.

## Setup from the terminal

```bash
vibestack-setup status                     # what is installed, what is selected
vibestack-setup list                       # catalog ids
vibestack-setup install node claude-code   # install now
vibestack-setup install godot              # install the pinned Godot editor
vibestack-setup install flatpak            # enable stable Flathub in --flatpak mode
vibestack-setup install build-essential    # install GCC, G++, Make, and headers
vibestack-setup skip                       # mark done, install nothing
vibestack-setup reset                      # run the wizard again
```

The setup CLI manages catalog choices, not the Linux password. Set or replace
that password in the web setup screen so it never has to be passed through a
shell command or agent transcript.

Setup state lives canonically at `/data/vibestack/setup.json` and is available
through the persisted `~/.vibestack/setup.json` link. To add components later,
open `/setup/?force=1`. Invalid or future-version state fails closed; reset it
explicitly rather than expecting the service to normalize it. Web and CLI
installs share one process-level lease. If the setup service restarts during a
CLI install, `/api/state` reports the external job and the service defers its
own restore instead of competing with it.

## After installing

1. Open the desktop. Shortcuts appear for whatever you installed.
2. Open Chrome once so the Claude and Codex extensions install themselves.
3. Sign in to each app and CLI. ChatGPT's external sign-in opens in Chrome
   through VibeStack's container-safe XFCE helper; its package is prevented
   from claiming ordinary HTTP/HTTPS links itself.
4. For browser automation, keep Chrome open on the desktop and run
   `claude --chrome`, then `/chrome` inside Claude Code to confirm.

Godot uses its standard GDScript editor build and the OpenGL Compatibility
renderer for this GPU-less container. The much larger .NET build and export
templates are not bundled; install only the templates you need from Godot.
Editor settings and downloaded templates persist under `/data/godot-config`
and `/data/godot-data`. Godot becomes catalog-visible only after its binary,
desktop entry, desktop shortcut, and desktop database update have all succeeded;
the final commit is recorded at
`/usr/local/bin/.vibestack-godot-4.7.2.complete`, so a late failure is repaired
by the next install or auto-restore attempt.

## Rebuilds

Components are installed into the container, so `docker rm` removes them.
Your choice is recorded in the persisted state file, and the setup service
reinstalls anything missing on the next boot, showing progress at `/setup/`.
Set `"auto_restore": false` in the state file to turn that off.
During replacement the launcher retains the stopped rollback container until
this restoration converges, with a configurable one-hour default timeout.
ChatGPT's Linux package stores its desktop profile under `~/.config/Codex`,
which VibeStack persists as `/data/chatgpt`; `~/.codex` remains the separate
Codex CLI profile.
Per-user Flatpak repositories, apps/runtimes, and app data persist separately
at `/data/flatpak` and `/data/flatpak-apps`; the small Ubuntu host integration
package is restored from the catalog on each new image.
The root-private Linux password hash is also stored below `/data`, so the same
password is reapplied before unprivileged services start in a replacement
container. It is independent from the empty-password desktop login keyring used
internally by Chrome and Electron.

## Development

Read [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) before changing a running
deployment. It documents the fast test loop, tagged builds, disposable
container and Playwright acceptance, safe live-state inspection, Tailscale
Serve, logs, and rollout checks. Repository `AGENTS.md` is the source workflow;
the image's version-matched operating guide is packaged at
`/usr/share/doc/vibestack/AGENTS.md` and exposed at `/AGENTS.md`. Codex,
Claude Code, and OpenCode receive links to those packaged defaults without
replacing an existing user file or override.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESOLUTION` | `1920x1200` | Virtual display size |
| `VNC_PORT` | `5900` | Internal x11vnc port |
| `NOVNC_PORT` | `6080` | Internal noVNC/websockify port |
| `TTYD_PORT` | `7681` | Internal ttyd port |
| `SETUP_PORT` | `7999` | Internal setup service port |
| `CONTROL_PORT` | `7998` | Internal desktop control API port |
| `AUTOMATION_PORT` | `7997` | Internal token-authenticated automation API port |
| `VIBESTACK_SSH_PORT` | `2222` | Loopback host SSH port used by `startup.sh`; `0` disables publication |
| `VIBESTACK_NATIVE_VNC_PORT` | `5900` | Loopback host native-VNC port; `0` disables publication |
| `VIBESTACK_ALLOWED_HOSTS` | unset | Comma-separated exact custom DNS/IP Host allowlist (maximum 32) |
| `VIBESTACK_BIND_ADDRESS` | `127.0.0.1` | Host address used by `startup.sh` |
| `VIBESTACK_PORT` | `8080` | Host port used by `startup.sh` |
| `VIBESTACK_SKIP_SETUP` | unset | `1` completes setup at boot with nothing installed |
| `VIBESTACK_RESTORE_TIMEOUT_SECONDS` | `3600` | Maximum live-rollout wait for saved applications |
| `VIBESTACK_PIDS_LIMIT` | `1024` | Bounded container task limit; tune only after measuring the workload |
| `VIBESTACK_FLATPAK` | `0` | `1` enables explicit nested-sandbox Docker mode; equivalent to `--flatpak` |

## Layout

| Path | Role |
|------|------|
| `Dockerfile` | Slim base image |
| `supervisord.conf` | D-Bus, desktop transports, XFCE, APIs, setup, and nginx |
| `nginx.conf` | Routes browser interfaces plus control and automation APIs |
| `setup/catalog.json` | Component catalog: the source of truth |
| `setup/server.py` | Setup service |
| `setup/setuplib.py` | State, catalog and probe helpers |
| `setup/index.html`, `style.css`, `app.js` | Wizard UI |
| `desktop/` | Root launcher, custom noVNC/terminal shell, manifest, service worker and icons |
| `control/` | Local allowlisted status, logs, restart and display API |
| `automation/` | Privileged bearer-authenticated automation API and job runner |
| `cmd/`, `pkg/vibestack/` | Go client/runner entrypoints, shared HTTP client, types, and profiles |
| `runner/`, `packaging/` | Docker host daemon, SQLite state, lifecycle, pairing, and systemd package |
| `api/`, `contracts/` | Machine-readable APIs, CLI coverage, and versioned launch contract |
| `cli.sh`, `skills/vibestack/` | Checksum-verifying client installer and portable agent skill |
| `desktop-config/` | Curated XFCE menu, launchers, and VibeStack actions |
| `runtime/` | Default in-container instructions for coding agents |
| `bin/vibestack-install` | Component installers |
| `bin/vibestack-control` | Fixed-command privileged service helper |
| `bin/vibestack-password` | Root-only password hash persistence and restore helper |
| `bin/vibestack-setup` | Setup CLI |
| `bin/vibestack-check` | Acceptance checks |
| `bin/vibestack-automation-check` | Authenticated end-to-end automation probe |
| `bin/vibestack-api-token` | Ensure, inspect, and rotate the automation credential |
| `bin/vibestack-flatpak` | Stable-Flathub search, review, install, run, update, and history helper |
| `bin/vibestack-app` | Launcher adding container-safe flags to Chromium apps |
| `bin/vibestack-persist` | State relocation into `/data` |
| `bin/vibestack-welcome` | Optional manual welcome banner |
| `chrome/policy.json` | Chrome policy: forced extensions, no nags |

## Adding a component

1. Add an entry to `setup/catalog.json` with a `probe` that detects it.
2. Add a matching branch and installer function in `bin/vibestack-install`.
3. `vibestack-check` fails if the two ever disagree.

## Contributing and security

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) and
the tested workflow in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). The current
iteration is summarized in [CHANGELOG.md](CHANGELOG.md).

VibeStack deliberately exposes powerful private-desktop capabilities. Please
read [SECURITY.md](SECURITY.md) before reporting a vulnerability, changing an
authentication boundary, or making a deployment reachable outside loopback
and a private tailnet.

VibeStack is available under the [MIT License](LICENSE).

## Known limitations

- **Single-user private boundary.** The automation API has bearer
  authentication; the terminal, setup wizard, desktop stream, and narrow
  shell-control API still rely on host loopback plus private Tailscale Serve.
  Setup can replace the Linux password without the old password. Do not expose
  VibeStack to the public internet.
- **Claude Desktop Cowork** needs KVM and cannot run in a container.
- **OpenAI Computer Use** is not in the Linux build.
- No audio, no GPU.
- **Flatpak outer-boundary trade-off.** Flatpak works only with explicit
  `--flatpak`, which relaxes three Docker security layers for the trusted
  private container so bubblewrap can create its inner sandbox.

The optional host runner supports reusable owner-scoped drives, private named
environment sets and stopped-desktop snapshots. Each clone gets independent app
state with fresh machine credentials. Its `/AGENTS.md` is a broker-specific guide
containing the configured private origin; remote harnesses must load it explicitly.
See [runner operations](docs/RUNNER.md) for API, host folder registration,
onboarding, snapshot and retention workflows. Standalone VibeStack remains
independent of the runner service.

For manual onboarding/debugging, the opt-in walkthrough trace and host-only
rapid patch/rollback commands are documented in
[the development guide](docs/DEVELOPMENT.md#manual-walkthrough-and-rapid-source-patches).

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
See [shared access, password, MCP and rollout contract](docs/RUNNER.md#shared-tailnet-broker-and-remote-mcp).

For ongoing development, [reuse the same Codespace across ticket branches](.context/github-codespaces.md#reuse-this-codespace-for-the-next-ticket).
The shared source checkout changes with Git; running image services change only
after a validated rebuild/deployment.
