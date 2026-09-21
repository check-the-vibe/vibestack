# Operating VibeStack

Service and CLI release: **0.3.0**. This guide is the starting point for a
single-user Linux desktop and its authenticated workspace service.

## Start from the URL you were given

Use the scheme and authority of this guide's URL as `SERVICE_ORIGIN`. A Codespace
service origin ends in `-8080.app.github.dev`; the `github.dev` editor URL is a
different application. Resolve every `/path` below against that origin. Do not
ask for a second URL, infer another workspace, or follow a login page as Markdown.

1. Fetch `/.well-known/vibestack`. Expect `kind: "workspace"`, version `0.3.0`, a
   32-character `identity`, `canonical_origin`, authentication metadata and
   document/endpoint URLs. `/healthz` returns HTTP 200 for service readiness;
   this alone does not mean applications or provider APIs are ready.
2. Use the existing compatible CLI or install it below. Let the operator supply
   a workspace credential through a protected file. `connect` records the
   discovered identity; authenticated workspace requests pin that identity.
3. Run `capability list`, then `capability schema`. The catalog reflects the
   credential's grants. Call a listed read operation, such as `workspaceStatus`
   with `{}`. Its JSON envelope identifies the instance, request, capability and
   result. Missing grants require the operator, not a different transport.
4. Choose REST, the CLI, a supported MCP client, or the private browser desktop.
   They address the same workspace. The optional host runner is separate and is
   not required for this journey.

In a private Codespace, GitHub protects the entire forwarded origin, including
this guide. Browser sign-in does not authenticate an external harness. A client
that receives HTML or a redirect must stop and complete gateway setup; it must
not make the port public. From within that Codespace, use loopback
`http://127.0.0.1:8080` to avoid the external gateway while retaining workspace
credential checks. This is the supported alternative for a harness running in
the Codespaces editor. `/CLI.md` and `/MCP.md` explain explicit protected gateway
files for outside clients; no ambient GitHub credential is read automatically.

## Install, authenticate and make the first call

The publisher is `check-the-vibe/vibestack` on GitHub. Installer downloads require
curl 8.4+, a SHA-256 utility, Linux or macOS, and amd64 or arm64. No Docker or Go
installation is needed on the client. Download and inspect the script before
running it; this public release URL does not require workspace credentials:

```sh
curl -q -fLsS --proto '=https' --proto-redir '=https' \
  'https://github.com/check-the-vibe/vibestack/releases/download/v0.3.0/cli.sh' \
  -o /tmp/vibestack-cli.sh
# Inspect /tmp/vibestack-cli.sh, then install the selected version:
sh /tmp/vibestack-cli.sh --version 0.3.0 --server "$SERVICE_ORIGIN"
vibestack version
```

A compatible installed CLI can skip installation. Add `~/.local/bin` to your
shell's PATH yourself if needed. `/cli.sh` on this service is the same versioned
installer; `/release-manifest.json` describes compatibility and publisher trust.
The installer checks HTTPS and SHA-256, stages an atomic replacement and preserves
an old binary on failure. Optional signed build-provenance verification is in
`/CLI.md`; a checksum alone does not authenticate a compromised publisher.

The local operator issues an expiring, capability-scoped credential as `vibe`:

```sh
vibestack-service credential create --label agent-status \
  --capabilities workspaceStatus --expires-in 24h \
  --output /data/vibestack/agent-status.token
```

That command runs **inside VibeStack**, not on the customer laptop. From the outer
Codespace terminal, prefix it with `docker exec -u vibe vibestack-codespaces`.
It prints metadata only, preserves an existing output file, and creates a mode
0600 credential file. The operator privately transfers it to the client's
protected storage; do not print it, paste it into chat, or put it in an argument,
URL, MCP configuration, source file or environment variable. See `/SERVICE.md`
for browser credentials, expiry, revocation and existing paired credentials.

```sh
vibestack connect --name workspace --url "$SERVICE_ORIGIN" \
  --token-stdin < /path/to/protected/workspace.token
vibestack --profile workspace capability list
vibestack --profile workspace capability schema
vibestack --profile workspace capability call workspaceStatus
```

For an external private Codespaces origin, add
`--gateway-token-file /path/to/protected/github-gateway.token` to `connect`.
The user supplies that distinct GitHub gateway credential privately. It must be
a single-link regular file owned by the current user, with no group/other access.
The profile stores its absolute path; the CLI reads it afresh for each request and
sends it only to the explicitly selected HTTPS `*.app.github.dev` origin.
Redirects are rejected. A gateway token is never a workspace grant.

## MCP, REST and browser access

A stdio-capable harness launches this command after the profile is connected:

```text
command: /absolute/path/to/vibestack
args: ["--profile", "workspace", "mcp"]
```

Only MCP frames use stdout. List tools and call the allowed `workspaceStatus`
tool with `{}` to confirm the connection. The bridge passes calls to this
workspace's authenticated `/mcp`; it is not a second execution engine. Official
Go SDK 1.7.0 and TypeScript SDK 1.30.0 clients are exercised independently, including
an actual CLI stdio subprocess. See `/MCP.md` for protocol versions and client
verification limits. OAuth-only clients are unsupported in this configuration;
use the stdio adapter or a tested bearer-capable client instead. Never infer
support for a desktop harness from an SDK test alone.

For REST, send the credential as `Authorization: Bearer …` from protected client
storage, with `X-VibeStack-Expected-Instance` set to the discovery identity. Use
`GET /api/v1/capabilities`, the authenticated
`/api/capabilities.openapi.json`, and
`POST /api/v1/capabilities/{id}/invoke` with the declared input object. The generic
CLI `capability call ID --input FILE` uses that same dispatcher; new compiled
capabilities need no bespoke CLI update. `/AUTOMATION.md` documents compatible
legacy/raw routes; `/EXTENSIONS.md` explains trusted server modules and static files.

The browser desktop is `/vnc/?view=desktop`; `/connect.html` is the private human
workspace-credential handoff. API browser mutations also need the session's CSRF
header. Keep the Codespaces port **Private**. Browser access is not Linux password
or provider sign-in, and a screenshot tool's success does not prove a browser
user completed that handoff.

For a local desktop editor, use Microsoft's VS Code with its GitHub Codespaces
extension, sign into the same GitHub account, then open **Remote Explorer → GitHub Codespaces** and click the connection icon
for this Codespace. The editor opens `/workspaces/vibestack`,
the same source mounted at `/projects/vibestack` inside VibeStack. Follow
[the official VS Code connection steps](https://docs.github.com/en/codespaces/developing-in-a-codespace/using-github-codespaces-in-visual-studio-code).
The VibeStack desktop itself remains the browser URL above; no separate native
VibeStack desktop application is shipped. A generic desktop agent may use the
stdio configuration only if its harness supports it; `/MCP.md` states what has
actually been tested. Opening the browser alone does not configure that harness.

Provider installation/activation APIs and the chat overlay are separate planned
work. Do not invent a provider activation endpoint or treat an application window
as a ready API. Existing applications can be installed via the authenticated
catalog, but this release does not yet claim managed Codex/OpenCode chat sessions.

## Recover without changing targets or replaying work

| Observed result | Next action |
| --- | --- |
| Codespace stopped/offline | Open the existing Codespace in GitHub and wait for startup; reuse the saved profile and verify identity. |
| HTML login page or redirect | Complete GitHub gateway access separately, or run the CLI inside the Codespace on loopback; do not send the workspace token to the login page. |
| 401 from VibeStack | Ask the operator to renew/revoke/reissue the scoped workspace credential privately. |
| 403 or tool absent | Check grants and the catalog's `next_action`; do not bypass the restriction through another transport. |
| `wrong_instance` | Stop; inspect the selected URL and profile before explicitly reconnecting. |
| Desktop/app still restoring | Check the authenticated state/status operations; process health is not app readiness. |
| File precondition conflict | Read the new ETag and reconcile changes before submitting a new conditional write. |
| Timeout, lost reply or disconnected mutation | Inspect the returned job/operation ID and remote state; do not blindly submit it again. |
| Installer 404/version unavailable | Preserve the installed binary and report the missing release; do not select an untrusted download. |

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
- Legacy workspace-wide credentials, or a grant for arbitrary commands, convey
  the full authority of `vibe`. Narrow new credentials retain their declared
  grants; command grants are not a sandbox. Handle every credential like a
  password and never put it in a URL, repository,
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
