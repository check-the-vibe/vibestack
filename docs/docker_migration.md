Docker Migration Notes and Checklist
====================================

Purpose
- Capture concrete steps and package mappings to build and run the existing
  `ubuntu:22.04`-based image on other base images or to harden the current image.

Current baseline (from `Dockerfile`)
- Base image: `ubuntu:22.04`.
- Primary package manager: `apt` (`apt-get` used in scripts).
- Key packages installed via apt: `xvfb`, `xfce4`, `xfce4-terminal`, `xfce4-goodies`, 
  `novnc`, `websockify`, `nginx`, `supervisor`, `sudo`, `openssh-server`, 
  `python3`, `python3-pip`, `falkon`, graphics libs (`libegl1`, `libgl1-mesa-dri`, 
  `libglx-mesa0`, `libgles2`), utilities (`curl`, `git`, `jq`, `dos2unix`, `tmux`).
- Node + Playwright installed with NodeSource + `npx playwright install --with-deps chromium`.

Playwright / Chromium prerequisites (Ubuntu 22.04)
- Recommended apt packages to ensure Chromium runs reliably:
  - `libnss3`, `libnss3-tools`, `libatk1.0-0`, `libatk-bridge2.0-0`, `libgtk-3-0`,
    `libxss1`, `libasound2`, `libx11-xcb1`, `libxcomposite1`, `libxcursor1`,
    `libxdamage1`, `libxrandr2`, `libgbm1`, `libpangocairo-1.0-0`, `libgdk-pixbuf2.0-0`,
    `libdrm2`, `libcups2`, `fonts-liberation`, `fonts-noto-color-emoji`.
- Add these explicitly to the Dockerfile before running `npx playwright install`.

Mapping to other base images

1) Fedora / RHEL (dnf)
- Package manager: `dnf` (or `yum` on older systems).
- Example mappings (approximate):
  - `xvfb` -> `xorg-x11-server-Xvfb`
  - `x11vnc` -> `x11vnc` (may be available via EPEL)
  - `xfce4` -> `@xfce-desktop` (group install) or individual packages like `xfce4-panel`, `xfwm4`, `xfdesktop`
  - `xfce4-terminal` -> `xfce4-terminal`
  - `novnc` / `websockify` -> may be packaged differently; consider `npm`-based install or
    use pip/npm packaged versions.
  - `nginx` -> `nginx`
  - `supervisor` -> `supervisord` (not always packaged; use `pip install supervisor` as fallback)
  - Graphics libs: `mesa-dri-drivers`, `mesa-libGL`, `mesa-libEGL` (package names vary)
- Playwright deps: install the Fedora-equivalent libraries (libnss, gtk3, libxss,
  alsa-lib, libXcomposite, libXrandr, libgbm, pango).
- Notes: Fedora images are usually glibc-based so Playwright binaries are compatible.

2) Alpine (apk) — caution: musl vs glibc
- Alpine uses `musl` libc; many prebuilt binary artifacts (Chromium, some node
  modules, and downloaded `ttyd` binary) may be incompatible.
- If considering Alpine:
  - Use `apk add` equivalents (e.g., `xvfb-run` provided by `xvfb` package),
    but many packages like `novnc`/`websockify` may not exist as apk packages.
  - Consider using a glibc-based compatibility layer (`sgerrand` glibc) or use
    the official Playwright Docker images which are based on Debian/Ubuntu.
  - Alternative: keep the image Debian-based for the desktop variant.

3) Recommendation: multi-image approach
- Keep a Debian/Ubuntu-based `vibestack:desktop` image for GUI-enabled workloads
  (Playwright + XFCE4 + noVNC). This reduces friction with Playwright binaries and
  prebuilt third-party binaries.
- Provide a `vibestack:core` lighter image (slim or `python:3.10-slim` base) that
  contains API and Streamlit but omits desktop packages.

Checklist to convert/build on another base image
1. Choose base image and update `FROM`.
2. Replace apt commands with target package manager commands and map packages.
3. Explicitly install Playwright / Chromium dependencies for the target OS.
4. Replace or rebuild any prebuilt binaries (e.g., `ttyd`) with target-arch builds.
5. Run `npx playwright install --with-deps chromium` (verify it completes).
6. Add runtime checks in `entrypoint.sh` to validate presence of critical binaries
   (`supervisord`, `Xvfb`, `websockify`, `chromium`) and print guidance on missing deps.
7. Update healthcheck if service endpoints or ports changed.
8. Run container and exercise desktop features: XFCE4, noVNC, Playwright chromium.

CI / Testing recommendations
- Add CI job(s) that build the Docker image(s) and run the `HEALTHCHECK` target.
- Run a small smoke test script inside container to assert: API started, streamlit
  reachable, noVNC page serves, and a simple Playwright script can launch Chromium.

Examples (snippets)
- Extra apt install line for Playwright deps (Ubuntu):
  apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 libxss1 libasound2 \
    libx11-xcb1 libxcomposite1 libxcursor1 libxdamage1 libxrandr2 libgbm1 \
    libpangocairo-1.0-0 libcups2 fonts-liberation fonts-noto-color-emoji

Notes
- For cross-distro portability, prefer building Playwright in an environment that
  matches the target (or use Playwright's official Docker images as a baseline).
- Keep GUI image as Debian/Ubuntu when possible to avoid musl/glibc binary issues.

Next steps I can take
- Produce a concrete patch to the `Dockerfile` adding Playwright deps and
  splitting the image into `core` and `desktop` variants.
- Add `entrypoint.sh` checks and a small supervisor helper (use `python -m vibestack.scripts.supervisor_helper`) used by Streamlit
  and other components so they no longer call `sudo supervisorctl` directly; prefer `python -m vibestack.scripts.supervisor_helper` which handles privilege detection.

If you want me to proceed, I will: 1) add the Playwright deps to the Ubuntu Dockerfile
and 2) add the supervisor helper script and wire Streamlit helpers to use it.
