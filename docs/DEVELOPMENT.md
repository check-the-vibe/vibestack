# Developing VibeStack

This is the canonical local workflow for building, testing, running, and
debugging VibeStack. The goal is to validate a candidate image independently,
then deliberately move the live private Tailscale-served desktop to it without
losing state or masking regressions.

For the OS choices, host/kernel distinction and existing execution primitives,
see [Linux desktop automation research](research/linux-desktop-automation.md).
The [desktop rendering audit](research/performance-audit.md) records the measured
stack and adopted noVNC improvements. Historical measurements do not replace
image acceptance or authorize a live migration.

Ticket branches can reuse an existing Codespace. Source files are shared with
the desktop immediately, while image services need deliberate tested deployment.
See [branch switching in Codespaces](../.context/github-codespaces.md#reuse-this-codespace-for-the-next-ticket).

For API/MCP changes, read [the shared capability contract](architecture/capability-contract.md)
and keep [the operation inventory](../contracts/capability-inventory-v1.json)
aligned with actual handlers. `go test ./contracts` validates the example
registration and schemas; Python source checks catch published API/CLI mapping
and setup-route omissions. These checks are part of `bin/vibestack-dev test`.
They do not replace live authentication or transport-parity acceptance.

The 0.3 CLI provides `capability list`, `capability schema`, and generic
`capability call ID --input FILE`; new registered endpoints do not require a
bespoke command release. The release workflow executes native installation on
Linux/macOS amd64/arm64 before publishing tagged binaries and build attestations.
Run `python3 tests/cli_release_check.py /absolute/path/to/native/vibestack` to
exercise fresh install, upgrade and failure preservation over disposable HTTPS.
Installer downloads require curl 8.4+ for streaming size limits. Read
[CLI.md](CLI.md) for release trust and explicit private gateway profiles.

## Prerequisites

The [workspace service guide](SERVICE.md) covers loopback 7996, protected
credential state, local issuance/revocation, browser sessions, static publication
and the 0.2 CLI control-command migration. API aliases now authenticate through
that service before reaching loopback 7997–7999. Update both the public schema
and source inventory when adding or changing routes. Private desktop transport
does not become public merely because the API has application authentication.

- Docker Engine with permission to build, run, inspect, and exec containers.
- Python 3 for unit and source-contract tests.
- Node.js 22 and npm for the Playwright browser suite.
- Go 1.25 or newer for the client and host runner.
- Tailscale on the host, logged into the intended tailnet, for private HTTPS.
- `curl` and OpenSSL; `jq` is useful but not required by the development helper.

Install test dependencies once:

```bash
npm ci
npx playwright install chromium
```

`npx playwright install --with-deps chromium` is appropriate on a disposable
CI host. It changes host packages, so local machines should install system
dependencies through their normal package-management workflow.

The checked-in Dev Container supplies full Python 3, Node 22, Go 1.26.4 and an isolated
Docker-in-Docker daemon. In GitHub Codespaces it requests at least 4 cores and
16 GB RAM, prepares the browser suite and desktop image, then automatically
starts `vibestack-codespaces` on loopback port 8080. The source editor can attach
while preparation runs. The checkout is shared read/write at
`/projects/<repository-directory>` inside the desktop through `--mount-source`;
other projects retain their separate persistent directory. The launcher declares
that one immediate child with `VIBESTACK_SOURCE_PROJECT`; file APIs pin the opened
directory's device, retaining ownership, no-symlink and deeper mount checks.
Desktop data and
projects use the outer named volume at `/vibestack-runtime/<repository-directory>`;
a workspace witness detects missing or replaced storage. Existing Codespaces
require the documented explicit migration after an outer rebuild. GitHub's private forwarding supplies remote HTTPS;
no Tailscale is needed there. Local Dev Containers skip desktop autostart.
Read [the Codespaces context](../.context/github-codespaces.md) before changing
this workflow, especially its persistent paths and real-Codespaces test gates.
Entrypoint normalizes its umask to `0022`; unprivileged persistence makes the
automation-token and SSH directories `0700`, including on resumed state.

## Fast edit loop

Provider adapters live in `internal/providers/`, with registry bindings in
`service/providers.go`. Read [their contract](architecture/provider-runtimes.md)
before changing native protocols, approvals or persistence. `go test -race
./internal/providers ./service` covers concurrent activation, uncertain outcomes,
approval scope and authenticated dispatch. The disposable `accept` gate runs
`tests/provider-runtime-check.mjs`: real catalog installs, native private
transports, REST/CLI/MCP activation, status, stop and reactivation. It makes no
model call and uses no human account; it cannot establish signed-in chat support.
Use the exact catalog binaries for native protocol checks. Never copy a host's
provider credentials into a fixture. Live sign-in and real turns are a separate
human handoff, recorded in VST-014/VST-015.

Provider metadata is `/data/vibestack/provider-runtime-v1.json`, owned by `vibe`
with the workspace store's `0600` atomic-write policy. Native auth/history stays
in the existing `/data/codex`, `/data/opencode-config` and `/data/opencode`
mappings. Stop the managed runtime before investigating its database with another
writer. Restart restores selected processes, never prior prompts or approvals.

Capabilities follow [EXTENSIONS.md](EXTENSIONS.md): one compiled registration and
handler, generated `/api/capabilities.openapi.json`, generic
`POST /api/v1/capabilities/{id}/invoke`, shared authorization and validation.
Dispatch has 32 slots and declared time/body/result limits. The operator supplies
`/projects`; requests cannot select another root. The same compiled definitions
feed `/mcp`; read [MCP.md](MCP.md) before changing transport/authentication.
The pinned TypeScript SDK 1.30.0 is a development-only independent client; Go SDK
1.7.0 is the runtime transport. Full acceptance runs both through actual nginx,
with private credential-file paths and payload-free diagnostics.
Acceptance also builds the actual CLI and launches it over stdio from the
independent TypeScript client. The probe runs jobs, performs conditional file
updates and captures a screenshot against the disposable loopback workspace.
Built-in adapters live in `service/workspace_capabilities.go`: fixed local
backends, existing operation IDs and preserved legacy routes. Registered JSON
operations use `/api/v1/operations/ID` or the generic invocation route; raw files
retain their legacy route. See MCP.md for the 8 MiB registered binary limit.

The disposable gate also runs `tests/capability-parity-check.mjs` through nginx:
real REST, TypeScript MCP, native CLI and Chromium session calls share extension
results, grant/identity denials, invalid and excessive inputs, conditional files
and jobs with bounded output. Credentials are issued only in the disposable
container and kept in protected fixture files; browser traces are disabled.
For historical compatibility, set `VIBESTACK_LEGACY_CLI` to an absolute path to
the 0.2 executable built from `a3fa6ac5242d9f3a6123a305c27a3af084974251` before
running `accept`. This adds real old/new argv/job/raw-API checks and the documented
old unauthenticated-status migration. It is source-version evidence, not proof
of a published 0.2 artifact. Without the variable, that extra matrix is not run.

`tests/mcp-recovery-check.mjs` places a disposable loopback fault proxy in front
of the real nginx listener. It checks dropped accepted-command replies through
HTTP MCP, CLI stdio and generic CLI; truncated replies; cancellation after job
acceptance; explicit duplicate commands; conditional-write retries; and bounded
job output. A cancelled protocol request is not confirmation that its durable
job was cancelled. No fault proxy is used for the live workspace.
With the historical CLI path set, acceptance also exercises the old/current
CLI against a private runner fixture in paired and explicit trusted-tailnet
modes, including store reopen and a real SDK client. It has no Docker manager.

For image rollback acceptance, set `VIBESTACK_ROLLBACK_IMAGE` to a locally
available previously accepted image when running `accept`. After normal checks,
the helper moves only its disposable mounts from the candidate to that image
and back. It waits for catalog/password restoration and checks identity, existing
credential access, file bytes/ETag, completed job metadata and live readiness.
The live container and mounts are never used. Without this variable, rollback
is not exercised and must not be claimed from an ordinary replacement check.

Before a development pass, read [the context index](../.context/README.md) and
[ticket workflow](../.context/workflow.md). Associate the branch with at least
one ticket, use the specification and plan as its scope, and update acceptance
evidence with the change. Main is the checked-in ledger; branch records describe
work in flight. Validated branch work is delivered only when its record and
implementation reach main. For planning/tracking documentation alone, check
relative links, metadata, branch ownership and `git diff --check`; no image
rebuild is needed. Runtime and source changes retain the full workflow below.

Run the source tests before editing so pre-existing failures are visible, and
again before building:

```bash
bin/vibestack-dev test
```

The command runs Python and Go unit/contract tests, browser diagnostics privacy tests, JavaScript syntax checks,
shell syntax checks, machine-readable API/launch-contract parsing, and
`git diff --check`. Useful focused forms:

```bash
python3 -m unittest tests.test_control_api -v
python3 -m unittest tests.test_desktop_contract -v
go test ./...
VIBESTACK_BASE_URL=http://127.0.0.1:8080 npm run test:browser -- --project=desktop-chromium
```

Most runtime source is copied into the image, so changes to `desktop/`,
`control/`, `setup/`, `bin/`, nginx, Supervisor, entrypoint, or XFCE startup
require a rebuild. Playwright tests can target an already-running container;
Python source tests run directly from the checkout.

The desktop entry point (`/` → `/vnc/`) shows a full canvas and one agent icon.
The icon opens a nonmodal panel for workspace connection, first Linux password,
provider activation/sign-in, conversations, approvals and recovery. Closing it
keeps provider work running and restores focus to the icon. Old `view`/`panel`
query parameters do not reopen retired navigation. No chat text, provider output
or credentials are stored in browser local/session storage. API authorization,
browser CSRF, persistent mounts and provider execution authority remain unchanged.
Standalone `/setup/`, `/terminal/` and `/editor/` services remain during VST-015;
VST-016 owns their complete removal after replacement acceptance. Source editing
remains available in the outer Codespaces editor.

The same image's canonical operating instructions are available internally at
`/usr/share/doc/vibestack/AGENTS.md` and externally at `/AGENTS.md`; the full
automation reference is similarly served at `/AUTOMATION.md`. Update and test
both paths as one versioned contract. `/CLI.md`, `/RUNNER.md`, `/cli.sh`,
`/.well-known/vibestack`, and `/skills/vibestack/SKILL.md` are part of the same
versioned surface. Route changes must update both OpenAPI files and
`api/command-coverage.json`.

The product evidence and acceptance expectations for Home, Applications,
Settings, onboarding, agent connection, failure recovery, and the reproduced
browser-only 403 regression are recorded in
[`research/guided-workspaces-audit.md`](research/guided-workspaces-audit.md).
Do not mark that browser gate validated from source inspection alone.

The Go code has two deliverables: `cmd/vibestack` is the cross-platform client;
`cmd/vibestack-runner` is Linux-only and uses Docker's official SDK with API
negotiation. Verify all release targets before tagging:

```bash
go test ./...
GOOS=darwin GOARCH=arm64 CGO_ENABLED=0 go build -o /dev/null ./cmd/vibestack
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o /dev/null ./cmd/vibestack-runner
```

Do not use `go mod tidy` as an incidental formatting step: Docker's
`+incompatible` module test graph is broader than the packages VibeStack
builds. Change dependency pins deliberately and run all cross-builds.

Install the optional native compiler toolchain with
`vibestack-setup install build-essential`. Using the setup CLI records the
selection for automatic restoration. Once onboarding has set the Linux
password, `vibe` also has ordinary password-authenticated sudo, so interactive
`sudo apt-get install build-essential` works in either terminal. That direct
install is deliberately ephemeral; it disappears at container replacement.
The catalog route is the durable choice.

Install the pinned standard Godot editor with `vibestack-setup install godot`.
Its catalog probe and saved selection restore the same version after a
container replacement; editor settings and explicit in-editor export-template
downloads persist as `/data/godot-config` and `/data/godot-data`. The probe
requires `/usr/local/bin/.vibestack-godot-4.7.2.complete`, which is published
atomically only after the binary, desktop entry, database refresh, and desktop
shortcut succeed. A late failure leaves the marker absent so retry/auto-restore
repairs the partial publication.

Flatpak is deliberately a host-policy opt-in. The normal container keeps
Docker's default seccomp, AppArmor, and protected-system-path policy. For a
trusted loopback/tailnet-only development instance that needs nested Flatpak
application sandboxes, use:

```bash
./startup.sh --flatpak
vibestack-setup install flatpak
vibestack-flatpak search 'search terms'
```

The image supplies `vibestack-flatpak-url.desktop` as the system default for
Flathub's `x-scheme-handler/flatpak+https` install links, and
`vibestack-flatpakref.desktop` for downloaded `application/vnd.flatpak.ref`
files. The URL handler accepts only the exact stable-Flathub appstream URL
shape, performs a bounded HTTPS download, then validates the regular reference
file, stable-Flathub URL, stable branch, application ID match, and non-runtime
type. Both paths use the already-verified `flathub` remote for the ordinary
interactive permission/install flow. VibeStack deliberately does not register
a handler for `.flatpakrepo` files. Diagnose both associations inside a running
desktop with:

```bash
xdg-mime query default application/vnd.flatpak.ref
xdg-mime query default x-scheme-handler/flatpak+https
```

The expected results are `vibestack-flatpakref.desktop` and
`vibestack-flatpak-url.desktop` once the component is installed.

`--flatpak` adds `seccomp=unconfined`, `apparmor=unconfined`, and
`systempaths=unconfined` only to that container. It does not use
`--privileged` or add capabilities, but it is still a meaningful reduction in
the outer Docker boundary. Entrypoint converts the launch selection into the
fresh root-owned `/run/vibestack/host/flatpak-enabled` marker; catalog and
installer code must not trust a user-set environment variable instead.

Stable Flathub is the only default remote. Per-user repositories/apps/runtimes
and app data persist at `/data/flatpak` and `/data/flatpak-apps`. Do not add a
beta, nightly, distro, vendor, or arbitrary remote during development without
explicitly recording the trust decision. See
[research/flatpak-flathub.md](research/flatpak-flathub.md) for experiments,
source links, UI alternatives, and the agent workflow.

## Candidate image and disposable acceptance

The upstream Ubuntu base has no CA trust store. Its existing signature-verified
base-package bootstrap installs `ca-certificates`; immediately afterward the
Dockerfile switches only the official Ubuntu archive, security, and ARM ports
URLs to HTTPS. Runtime setup and restoration therefore use certificate-verified
HTTPS without changing repositories, suites, components, or signing keys.
Never work around download failures by disabling TLS or APT signature checks.

Use an informative immutable tag rather than overwriting the live tag:

```bash
bin/vibestack-dev build vibestack:automation-YYYYMMDD
bin/vibestack-dev accept vibestack:automation-YYYYMMDD
```

`accept` starts an isolated, disposable container on loopback port 18080 with
temporary `/data` and `/projects` directories. It waits for Docker health and
runs `vibestack-check --display --restart --automation`. It then creates a
random stdin-only onboarding password, calls the real setup API, rejects a bad
sudo password, uses the good password for a real `apt-get update` and
`build-essential` install, and checks that shared logs contain no plaintext.
It recreates the container from the clean image against the same `/data`, proves
that the password restores while the ad-hoc apt install does not, then installs
Godot, `build-essential`, and Flatpak through the durable catalog route, with
code-server already available as a core service. The
acceptance container alone receives all three explicit Flatpak security
options. It verifies the nested bubblewrap preflight and exact stable Flathub
remote, installs `org.gnome.Calculator` only in disposable state, and observes
its real sandboxed XFCE window alongside Godot's editor and verifies the
code-server process plus `/editor/` route before and after replacement. It also sends the
actual Flathub `flatpak+https` link for VLC through the bounded handler, proves
that remote permissions are displayed with the image's Flatpak version, answers
`n`, and verifies that review remains a consent boundary rather than installing
the app. It recreates the container a second time, waits boundedly for catalog
restoration, and repeats the package, persistent-state, search, and GUI checks
before both Playwright projects. Cleanup removes only the exact temporary
containers, state directory, and password directory.
Override the port with `VIBESTACK_ACCEPTANCE_PORT` if 18080 is occupied.
The catalog-restore wait defaults to 3600 seconds and accepts a measured
60–7200-second override through `VIBESTACK_ACCEPTANCE_RESTORE_TIMEOUT_SECONDS`.
Both disposable and live GUI containers use a bounded 1024-task default because
Chromium/Electron processes and their threads exceeded 80% of the former 512
limit in a representative full desktop. Override it with
`VIBESTACK_PIDS_LIMIT` only after measuring the intended application set; the
launcher accepts 128 through 4096.

`.github/workflows/publish-docker.yml` calls this same helper against its built
candidate, so local and release acceptance cannot silently diverge. CI retries
one failed disposable run from completely fresh state to tolerate a transient
hosted-runner or package-network failure; a release still requires one full
end-to-end pass. A failed attempt prints bounded container, Supervisor, and
service-log diagnostics before cleanup, including the last 80 lines (at most
64 KiB per service) from code-server, SSH, and native VNC.
The disposable project directory explicitly uses mode `0755` so the required
core editor can start in `/projects` as `vibe` even when the CI host UID differs.
Its host ownership is preserved, and the sentinel ownership is rechecked from
container root after bootstrap secures the bind root. The onboarding password
directory remains private (`0700`).

Disposable image acceptance covers one workspace. Runner lifecycle acceptance
uses a separate private state directory and the accepted candidate digest;
never point a development runner at `/var/lib/vibestack-runner` or adopt the
live `vibestack` container. Exercise two managed instances, independent volume
sentinels/credentials/ports, idempotent create, restart reconciliation,
occupied-port rejection, failed update rollback, retained-volume removal, and
operator purge. Keep `manage_tailscale_serve` off unless the test owns exact
isolated mappings; never use `tailscale serve reset` because that would delete
unrelated operator mappings.

Release CI is pinned to GitHub's Ubuntu 24.04 runner. Noble restricts
capabilities inside unprivileged user namespaces through AppArmor by default,
which otherwise makes bubblewrap fail while writing its UID map even when the
acceptance container has VibeStack's three explicit Flatpak options. Immediately
before disposable acceptance, the workflow disables that one host sysctl for
the lifetime of the ephemeral, single-job VM. This does not change the image,
the production host, or the normal VibeStack launch; do not copy the CI sysctl
to a persistent multi-user host without accepting the wider host-level kernel
attack surface. See Ubuntu's
[24.04 release notes](https://documentation.ubuntu.com/release-notes/24.04/#unprivileged-user-namespace-restrictions)
and Flatpak's
[user-namespace requirements](https://github.com/flatpak/flatpak/wiki/User-namespace-requirements).

## Start or replace the live container

The normal launcher builds and replaces a container named `vibestack`, binds
nginx only to host loopback port 8080, and mounts persistent state:

```bash
./startup.sh
./startup.sh check
```

New state directories receive a `.vibestack-state-v1` marker. An existing
pre-marker VibeStack state directory must be reviewed and explicitly adopted
once with `--data /absolute/path --adopt-data`. The launcher canonicalizes the
path and rejects `/`, the host home, the repository and paths above or below
it, OS-owned hierarchies, common credential directories, and a path also used
for `--projects` before it creates directories or invokes Docker. Adoption is
limited to VibeStack's known top-level state names; an unrelated entry aborts
without creating the marker.
The projects path independently rejects root, OS-owned hierarchy descendants,
the host home, credential-directory overlap, Git credential/metadata paths,
and the VibeStack repository as the projects root. `--mount-source` is a
separate opt-in nested bind of the exact checkout at `/projects/<repo-name>`,
enabled automatically in Codespaces. It never hides an existing project and
does not recursively change source ownership. Ordinary dedicated user project directories
remain supported.

For a candidate that already passed disposable acceptance, avoid rebuilding it
during rollout:

```bash
./startup.sh --no-build --image vibestack:automation-YYYYMMDD \
  --data /absolute/path/to/vibestack-data \
  --projects /absolute/path/to/projects \
  --ssh-port 2222 --vnc-port 5900
```

Add `--flatpak` to that exact rollout command only when the user accepts the
documented security trade-off. If `flatpak` is already in saved setup state,
the flag is mandatory: without the root-owned capability marker the component
is unsupported, the restore gate fails, and the prior container is restored.
Do not infer opt-in merely because an image contains the helper or marketplace
link.

Before replacing a running container, capture its exact image, port, and mount
sources. Do not assume the launcher defaults match an existing deployment:

```bash
docker inspect vibestack --format \
  'image={{.Config.Image}} ports={{json .HostConfig.PortBindings}} mounts={{range .Mounts}}{{.Source}}=>{{.Destination}};{{end}}'
```

`startup.sh` validates all arguments and the selected image before touching an
existing container. During replacement it stops and renames the prior
container, starts the candidate, waits for Docker health, and then waits for
the saved auto-restore component set to converge. It automatically restores
the prior container if either phase fails. The rollback container is removed
only after base services and saved applications are ready. The restore wait is
bounded by `VIBESTACK_RESTORE_TIMEOUT_SECONDS` (3600 seconds by default).
The restoration probe runs as `vibe` against the fixed private setup listener
at `127.0.0.1:7999/api/state`; it does not bypass authentication on a public API.
Unreadable, structurally invalid, future-version, or catalog-unknown saved
state fails this gate immediately and keeps/restores the rollback container;
it is never treated as an empty successful selection.
Environment equivalents are listed in `.env.example`.
`--bind 0.0.0.0` is an explicit direct-LAN exposure and is not the normal
development configuration.

## Tailscale Serve

Keep container HTTP on `127.0.0.1` and let Tailscale terminate HTTPS. A
non-default HTTPS port avoids disturbing other services on the same host:

```bash
VIBESTACK_PORT=8080 VIBESTACK_TAILSCALE_HTTPS_PORT=9443 \
  bin/vibestack-dev serve
tailscale serve status --json
```

Equivalent current CLI syntax is:

```bash
tailscale serve --bg --https=9443 http://127.0.0.1:8080
```

The resulting URL is `https://<machine>.<tailnet>.ts.net:9443/`. Serve is
tailnet-private and supplies TLS needed by the service worker/PWA. Do not use
Tailscale Funnel: it creates a public-internet boundary that VibeStack v1 is
not designed to accept. Tailscale's current Serve syntax and identity behavior
are documented at <https://tailscale.com/docs/reference/tailscale-cli/serve>
and <https://tailscale.com/docs/features/tailscale-serve>.

## Inspect and debug the running system

```bash
bin/vibestack-dev status
bin/vibestack-dev check
bin/vibestack-dev shell
bin/vibestack-dev logs
bin/vibestack-dev logs vnc
bin/vibestack-dev logs control
bin/vibestack-dev logs automation
bin/vibestack-dev logs automation-audit
bin/vibestack-dev logs desktop-actions
bin/vibestack-dev logs nginx-access
bin/vibestack-dev browser https://<machine>.<tailnet>.ts.net:9443
```

Named log choices are `desktop`, `vnc`, `novnc`, `terminal`, `setup`,
`control`, `automation`, `automation-audit`, `desktop-actions`, `nginx`,
`nginx-access`, and `xvfb`. With no name the helper follows Docker's container
output instead.

`check` is deliberately non-mutating on the live container. The normal
`browser` command skips the one real-service restart case. Disposable
`accept` and CI run the reversible command, shell, screenshot, Desktop-file,
clipboard, application, and window automation checks, then set
`VIBESTACK_ALLOW_MUTATING_BROWSER_TESTS=1` for the full restart/display browser
suite safely away from the live desktop. That gated suite also loads the real
same-origin ttyd iframe, verifies its CSP/resource/WebSocket path and focus,
and executes one harmless arithmetic command through browser keyboard input.

Never put a real user password in `.env`, a Docker environment variable, an
automation command, a command-line argument, or a test fixture. The runtime
acceptance probe generates a throwaway value in a mode-`0600` temporary file,
passes it only through stdin/request bodies, scans persistent logs, and erases
the exact temporary directory during cleanup. Live checks inspect password
status only; they never replace or test the user's credential.

`vibestack-password status` is also an integrity check: it succeeds only when
the durable `vibe.shadow` hash and live `/etc/shadow` field agree (or the hash is
absent and the account is locked). Treat a setup 503 or helper failure as an
inconsistent credential state, not as “password not configured.” Entrypoint
reapplies the durable hash—or locks an account with no durable hash—before
starting unprivileged services. An update rollback that cannot restore both
copies stays detectably inconsistent until that restart reconciliation succeeds.

Inside the container, Supervisor is the process authority and nginx is the
only HTTP entrypoint. Use the fixed Supervisor configuration for process state. All
persistent logs live below `/data/logs/vibestack/`; the same directory appears
on the XFCE desktop as `VibeStack Logs`. The versioned control and automation
APIs are available internally and through nginx:

```bash
curl -fsS http://127.0.0.1:8080/api/v1/status
curl -fsS http://127.0.0.1:8080/AGENTS.md
docker exec -u vibe vibestack bash -lc \
  'source /run/vibestack/session.env; xrandr --query'
docker exec -w / vibestack \
  supervisorctl -c /etc/supervisor/supervisord.conf status
```

Automation is intentionally omitted from unauthenticated health probes. The
normal live check runs authenticated discovery, list, screenshot, and
request-ID log-correlation probes without changing Desktop files, applications,
or clipboard state:

```bash
bin/vibestack-dev check
```

For a direct authenticated request, load the token through the explicit helper
without placing it in a process argument:

```bash
VIBESTACK_TOKEN="$(docker exec -u vibe vibestack vibestack-api-token show)"
printf 'header = "Authorization: Bearer %s"\n' "$VIBESTACK_TOKEN" |
  curl --config - -fsS http://127.0.0.1:8080/api/v1/automation
unset VIBESTACK_TOKEN
```

Use [AUTOMATION.md](AUTOMATION.md) for individual operations, token rotation,
and request-ID log correlation. `vibestack-automation-check --mutating` is for
disposable validation unless deliberately invoked on a live workspace. Shared
logs exclude tokens, commands, clipboard/file bodies, screenshots, and command
output.

Supervisor's control socket is root-only. Inspect it as container root; run
desktop applications and X11 queries as `vibe` instead.

Do not patch files in a running container and treat that as implementation:
container changes disappear at replacement. Diagnose live, edit the checkout,
then build and validate a new image.

For an external-login button that appears inert, compare both layers of the
desktop browser setting and confirm that the click launched a browser:

```bash
docker exec -u vibe vibestack bash -lc '
  source /run/vibestack/session.env
  XDG_CURRENT_DESKTOP=XFCE xdg-settings get default-web-browser
  xdg-mime query default x-scheme-handler/http
  xdg-mime query default x-scheme-handler/https
  wmctrl -lx
'
```

All three handler results should name `google-chrome.desktop` after Chrome is
installed. ChatGPT must not advertise `x-scheme-handler/http` or `https` in
`/usr/share/applications/chatgpt.desktop`. Its Linux desktop profile is
`~/.config/Codex` (persisted at `/data/chatgpt`), not `~/.config/ChatGPT` and
not the separate Codex CLI path `~/.codex`. Before the first rollout that
corrects an older mapping, preserve a live nonempty `.config/Codex` profile in
the empty `/data/chatgpt` target while the app is stopped; abort and inspect
manually if both locations contain data.

XFCE launches preferred browsers through
`/usr/share/xfce4/helpers/google-chrome.desktop`, independently of the
application desktop entry's `Exec` field. That helper must select
`vibestack-app` and pass `/usr/bin/google-chrome-stable` as its first argument;
otherwise a cold Chrome launch can fail in Docker even when every MIME default
is correct.

## Definition of done

- Fast tests pass from the checkout.
- A tagged image passes disposable acceptance.
- Documentation and the specification match every changed route, port,
  package, state path, permission, and trust-boundary decision.
- The real live container reports healthy after rollout.
- Every selected auto-restored application is present before rollback state is
  discarded.
- The loopback HTTP URL and private Tailscale HTTPS URL both work, including
  the RFB WebSocket, terminal WebSocket, control/automation APIs, setup flow,
  PWA assets, exact `/AGENTS.md` and `/AUTOMATION.md` documents, and request-ID
  audit records.
- Direct handshakes to raw websockify without the fixed nginx marker (and with
  a wrong marker) receive 403, direct ttyd without the marker receives 403,
  and both nginx-proxied WebSocket paths still upgrade normally.
- Desktop/iPad Playwright projects pass. Any remaining physical iPad check is
  written down explicitly rather than implied by browser emulation.

## Runner storage acceptance

Runner API 1.1 adds owner-scoped registered file drives, immutable private
environment sets, stopped-state snapshot seeds, and selected host reporting.
See [RUNNER.md](RUNNER.md) for local folder registration, lease/retention rules,
private environment-file input and clone credential exclusions. The launch
contract keeps version 1 and adds optional storage fields. The broker serves a
dynamic `/AGENTS.md` and `/api/runner.openapi.json`; workspace guidance remains
at its separate origin. The client `api` command accepts `--idempotency-key`.

Run `python3 tests/runner_integration.py --baseline OLD_RUNNER --runner NEW_RUNNER
--image ACCEPTED_IMAGE` on the intended Tailscale Docker host after disposable
image acceptance. This uses isolated `/tmp/vibestack-runner-integration-*` state,
loopback listener 18079, private broker HTTPS 12443, and workspace ports
12080–12179. It starts with the original runner, migrates its registry in place,
checks private HTTPS onboarding, uses a random disposable password only in the
setup request body, verifies owner boundaries and host-folder mediation, restarts
the runner/desktop, and checks independent clones and retained storage. Existing
Serve mappings and the standalone desktop are preserved. Failure evidence and
retained test volumes remain local; purging is explicit. This does not replace
user-selected application sign-in reuse acceptance or systemd installation.

## Manual walkthrough and rapid source patches

For an explicitly requested manual development session, use the host-only
`bin/vibestack-walkthrough` helper. The current first-desktop is available at
`https://server.tail14a7e5.ts.net:11080/setup/?walkthrough=1`.
The `walkthrough=1` query enables diagnostics for that browser tab across setup,
Home and the desktop/terminal shell; `walkthrough=0` disables it. It records
page/step transitions, fixed button IDs, request status/timing, connection
changes and error classes. It never records input values, request/response
bodies, clipboard contents, terminal frames, error messages or URL queries.
Third-party application pages and the embedded terminal's internal scripts are
outside the browser instrumentation; their connection/status and existing
service logs remain available.

```bash
bin/vibestack-walkthrough \
  --container vibestack-first-desktop-49962b6d \
  --url https://server.tail14a7e5.ts.net:11080 \
  --directory /home/jarvis/Code/vibestack-runner-local/walkthrough collect
```

Run `collect` in tmux for continuous collection. The private host directory holds
`walkthrough.jsonl` (10 MiB, four rotated backups). It combines sanitized HTTP
request metadata, validated browser events and changing setup/service status.
Container source logs remain under `/data/logs/vibestack`; browser events enter
`services/vibestack-control.log`, also rotated. Collection is best effort: a
container restart/rotation or sustained excess traffic can lose events. This is
a debugging trace, not an audit guarantee. Same-origin callers can submit events;
treat them as untrusted observations, not evidence of user identity.

Use the same flags with `mark password-page-issue`, `deploy`, or `rollback`.
`deploy` syntax-checks and copies the allowlisted desktop/setup assets and Python
modules, catalog, fixed XFCE workspace menu/actions, wallpaper/startup helpers,
Supervisor configuration, health probe, and runtime guides into the explicitly
named runner container. It backs up every destination, updates the service-worker
cache version, restarts the control and setup services, and checks setup/control HTTP
health. A failed patch restores the backup; `rollback` restores the most recent
patch. Reload the browser after either operation. This leaves persistent user
state and other desktops intact, but the patch is ephemeral: a container recreate
returns to its image. It does not install dependencies or reload Supervisor:
the core editor and Pillow must already be installed, and startup/configuration
changes take effect on the next container restart. Dependency, nginx, runner,
or system service changes require the image/service workflow.

The isolated browser instrumentation privacy checks run with
`node --test tests/walkthrough-privacy.test.mjs`; endpoint/schema checks run with
`python3 -m unittest tests.test_walkthrough`. The real transport regression is
`VIBESTACK_BASE_URL=<private-origin> npx playwright test tests/browser/diagnostics-transport.spec.mjs`.
It connects the actual pinned noVNC client with diagnostics enabled and disabled.
Socket instrumentation must preserve the native instance prototype: noVNC checks
its immediate prototype for methods such as `send`, so a subclass wrapper breaks
connection setup even though the socket itself opens.

During the user-authorized manual loop, run focused checks for each change and
reserve the full build/disposable image/browser acceptance for the agreed feature
checkpoint. Record any interim failures. Before releasing a durable image, run
the normal complete workflow above; a source patch is not image acceptance.

The desktop entry point (`/` → `/vnc/`) shows a full canvas and one agent icon.
The icon opens a nonmodal panel for workspace connection, first Linux password,
provider activation/sign-in, conversations, approvals and recovery. Closing it
keeps provider work running and restores focus to the icon. Old `view`/`panel`
query parameters do not reopen retired navigation. No chat text, provider output
or credentials are stored in browser local/session storage. API authorization,
browser CSRF, persistent mounts and provider execution authority remain unchanged.
Standalone `/setup/`, `/terminal/` and `/editor/` services remain during VST-015;
VST-016 owns their complete removal after replacement acceptance. Source editing
remains available in the outer Codespaces editor.

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
See [shared access, password, MCP and rollout contract](RUNNER.md#shared-tailnet-broker-and-remote-mcp).

Run `python3 tests/shared_runner_integration.py --runner NEW_RUNNER --client
NEW_CLIENT --image ACCEPTED_IMAGE --browser` for the disposable shared-access
flow. It owns loopback 18089, private HTTPS 13443 and instance ports 13080–13179,
refuses pre-existing Serve mappings in those ranges, and cleans only its exact
registry resources. Random disposable passwords stay in memory/stdin; the probe
checks actual Linux authentication, replacement, conflicts, helper failure,
disconnect serialization and plaintext absence. It uses two independent CLI
profiles and a separate Python MCP client through the private HTTPS endpoint.
