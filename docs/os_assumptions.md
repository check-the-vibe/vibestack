OS Assumptions (derived from `Dockerfile`)
===========================================

Overview
- Base image: `ubuntu:22.04` (Debian family, `apt` package manager).
- The container intentionally provides a full desktop environment (Xvfb,
  XFCE4, noVNC) and runs services under `supervisord` (not `systemd`).
- Key runtime expectation: `supervisord` starts GUI helper programs and noVNC
  serves an in-container VNC client to `NOVNC_PORT` (6080 by default).

Environment variables
- `DEBIAN_FRONTEND=noninteractive` — used during apt installs.
- `DISPLAY=:0`, `NOVNC_PORT=6080`, `VNC_PORT=5900`, `RESOLUTION=1280x720` — GUI
  display and ports.
- `VIBESTACK_HOME=/home/vibe` — canonical non-root user home; many files are
  copied into this path and ownerships are set to user `vibe`.
- `PATH` is extended with `/home/vibe/bin`.

Package manager and package list (apt)
- Installer used: `apt-get`.
- Pacakges installed via apt (major items):
  - GUI/X: `xvfb`, `x11vnc`, `xterm`, `xfce4`, `xfce4-terminal`, `xfce4-goodies`, `dbus-x11`, `falkon`.
  - Web + bridging: `novnc`, `websockify`, `nginx`.
  - Utilities: `curl`, `dos2unix`, `git`, `jq`, `menu`, `nano`, `vim`, `wget`.
  - System: `supervisor`, `sudo`, `openssh-server`, `tmux`.
  - Python: `python3`, `python3-pip`.
  - Graphics libs: `libegl1`, `libgl1-mesa-dri`, `libglx-mesa0`, `libgles2`.

Node / Playwright
- Node runtime installed from NodeSource; global npm packages installed:
  - `@anthropic-ai/claude-code`, `@openai/codex`, `playwright`.
- `npx playwright install --with-deps chromium` is run to fetch browser binaries
  and attempt to install system dependencies where possible.
- Note: Playwright and Chromium require additional OS libraries (fonts, KMS/GL,
  libnspr/libnss, etc.). The Dockerfile does not explicitly list all of these; the
  `--with-deps` helper may not be comprehensive across all distros.

Python packages (pip)
- Installs `fastapi`, `uvicorn[standard]`, `streamlit`, `llm`, `mcp[cli]`,
  `beautifulsoup4`, `requests`, `httpx`, `rich`, `typer`, `tui`.

Binaries added directly
- `ttyd` (downloaded binary placed at `/usr/bin/ttyd`).
- VS Code CLI is extracted to `/opt/vscode-cli` with `/usr/local/bin/code` symlink.

User and permissions
- Creates non-root user `vibe` (UID 1000), adds to `sudo` group, and provides
  an `/etc/sudoers.d/vibe` allowing passwordless sudo. The image still runs
  supervisor as the container CMD (default `supervisord` process).

File layout
- Application files copied into `/home/vibe` and ownership transferred to `vibe`.
- `supervisord.conf` is copied into `/etc/supervisor/conf.d/supervisord.conf`.
- `entrypoint.sh` placed at `/entrypoint.sh` and executed as ENTRYPOINT.
- XFCE startup script and Xresources copied under `/home/vibe/`.

Service model assumptions
- Supervisor-based process control: the container expects `supervisord` to be
  the main process. Host-level `systemd` is not used inside the container.
- Healthcheck targets the NOVNC endpoint (`/vnc.html`).
- Scripts and code sometimes call `sudo supervisorctl` (e.g., `assets/...` and
  Streamlit pages). Prefer using the centralized helper `python -m vibestack.scripts.supervisor_helper` which attempts direct `supervisorctl` usage and falls back to `sudo` if available; relying on `sudo` from inside a container is a fragile assumption for other runtimes.

Hardcoded paths and values
- `/home/vibe` hardcoded as user home.
- Log paths in repo `supervisord.conf` reference `/var/log/supervisor`.
- `DISPLAY=:0` assumed for XFCE4/Xvfb sessions.
- `novnc` installation path and `websockify` usage assume package-provided
  binaries (Debian package layout).

Potential portability issues (when changing base image or host integration)
1. Different package managers: `apk` (Alpine), `dnf` (Fedora/RHEL) require
   different package names and possibly rebuilds for some binaries.
2. Musl vs glibc: Alpine uses musl; some prebuilt binaries (ttyd, playwright
   browser binaries) may be incompatible.
3. Missing distro packages: `novnc`, `websockify`, `xvfb`, `xfce4` may not be
   available or named differently on non-Debian distros.
4. Playwright/chromium: system dependency differences can break browser startup.
5. `sudo` inside containers: not necessary in many Docker runtimes; better to run
   necessary commands as the correct user or configure entrypoint to handle
   privilege separation.
6. Relying on `supervisord` vs `systemd`: some teams may prefer `systemd`-based
   management on hosts; inside containers `supervisord` is fine but changing the
   container runtime semantics may be required.

Recommendations and migration guidance
- Parameterize and document: centralize configurable paths, feature flags, and
  “enable GUI” toggles via ENV (e.g., `ENABLE_DESKTOP=true/false`).
- Avoid `sudo` in application code: provide a single privileged entrypoint or
  use proper container runtime user privileges. Add helper that queries
  `supervisord` without requiring `sudo` when possible.
- Split images: maintain at least two Docker variants —
  - `vibestack:desktop` (full GUI stack, XFCE4, novnc, Xvfb) — current image
  - `vibestack:core` (API, Streamlit, CLI) — lighter, for headless or server-only use
- Document package mapping: create `docs/docker_migration.md` with steps to
  convert apt installs to other package managers (apk/dnf) and list native libs
  required by Playwright and Chromium.
- Pin versions and add checks: pin major versions for critical packages (node,
  Playwright, novnc) and add runtime checks in `entrypoint.sh` to verify
  binaries exist and warn/fail fast with actionable messages.
- Playwright specifics: explicitly install the known set of system dependencies
  for Chromium on the target base image (fonts, libnss3, libatk1.0, libcups2,
  libxss1, etc.). Prefer Playwright Docker images or their recommended distro
  deps as a baseline.
- Make GUI optional: add env var gate in `supervisord.conf` (e.g. disable xfce4
  program sections when `ENABLE_DESKTOP` is false) or generate the effective
  `supervisord.conf` from a template in `entrypoint.sh`.

What I will do next (if you want me to continue)
- Produce `docs/docker_migration.md` with concrete package mappings and a small
  checklist to recreate the image on another base OS (Alpine/Fedora).
- Start auditing `Dockerfile` for missing Playwright deps and propose exact
  package names to add for `ubuntu:22.04` and for `Fedora`/`Alpine` variants.

If you want me to start converting the Dockerfile into multiple variants or
prepare the migration checklist now, say "yes" and specify which target base
image(s) to include (e.g., `alpine`, `fedora`, or `ubuntu-minimal`).
