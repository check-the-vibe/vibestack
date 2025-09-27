# Repository Layout Guide

This document explains how the VibeStack repository is organized after the `container-home` symlink bundle was inlined. New contributors should use this as the primary reference for where runtime artifacts live and how they flow into the container image.

## Why the change?

Previously, most application code sat under `container-home/` and the repo exposed convenience symlinks (for example `streamlit_app/ -> container-home/streamlit`). Git on some hosts refused to stage paths that resolved through those links, producing errors such as `fatal: pathspec 'bin/vibestack-sessions' is beyond a symbolic link`. The current layout keeps everything as first-class directories in the repo root, eliminating those pathspec issues while keeping the container build reproducible.

## Directory map

| Path | Purpose |
| --- | --- |
| `bin/` | Helper CLI scripts (`vibe`, `vibestack-code-tunnel`, `vibestack-ttyd-entry`) that are linked into `/usr/local/bin` inside the container. |
| `docs/` | End-user and service documentation (this folder). Individual service guides live in `docs/services/`. |
| `.docs/` | Internal playbooks, prompting notes, and long-form references used by Codex agents. |
| `streamlit_app/` | Streamlit UI entrypoint (`app.py`), shared UI utilities (`common.py`, `onboarding.py`), and page modules under `streamlit_app/pages/`. |
| `vibestack/` | Python package that implements the session manager, REST API bindings, and MCP server. |
| `examples/` | Smoke-test and integration scripts (for example `examples/mcp_runner.py`). |
| `tests/` | Pytest-based functional and unit tests. |
| `fluxbox-apps`, `fluxbox-init`, `fluxbox-startup` | Fluxbox window manager configuration copied to `/home/vibe/.fluxbox/` at image build time. |
| `Xresources` | X11 resource defaults for desktop applications. |
| `AGENTS.md` | Orientation guide for human/agent collaborators, copied to `/home/vibe/AGENTS.md`. |
| `Dockerfile` | Builds the runtime image and copies the directories above into `/home/vibe`. |
| `supervisord.conf` | Defines all long-lived services (Streamlit UI, API, ttyd, MCP, VS Code tunnel, etc.). |
| `nginx.conf` | HTTP routing for desktop, terminal, Streamlit UI, REST API, and MCP endpoints. |
| `startup.sh` | Local development helper that rebuilds the Docker image and launches a container with the expected port mappings. |

## Build and runtime flow

1. `docker build` executes the `COPY` directives in the Dockerfile to stage application assets directly into `/home/vibe/` inside the image:
   - `bin/` → `/home/vibe/bin/`
   - `docs/` → `/home/vibe/docs/`
   - `streamlit_app/` → `/home/vibe/streamlit/`
   - `vibestack/` → `/home/vibe/vibestack/`
   - Fluxbox and X11 configs → `/home/vibe/.fluxbox/` and `/home/vibe/.Xresources`
   - `AGENTS.md` → `/home/vibe/AGENTS.md`
2. A post-copy `RUN` step normalizes line endings, marks scripts executable, and sets ownership/permissions for the `vibe` user.
3. At runtime, Supervisor launches services that directly reference these paths (for example the Streamlit program runs `streamlit run /home/vibe/streamlit/app.py`).

Because the assets are first-class directories, editing `streamlit_app/common.py` or `vibestack/api.py` in the repo automatically flows into the next image build. There is no indirection layer to keep in sync.

## Local development checklist

1. Rebuild and start the dev container:
   ```bash
   ./startup.sh
   # or ./startup.sh follow to stream logs
   ```
2. Once the container is up, visit `http://localhost:3000/ui/` for the Streamlit control plane or `http://localhost:3000/terminal/` for ttyd.
3. When you modify repo files, rerun `./startup.sh` (or `docker buildx build`) to bake the changes into a fresh image. There is no longer a bind-mounted `container-home` bundle, so hot reloading relies on rebuilds.
4. To confirm the symlink cleanup, run `find . -type l -ls`. Only virtualenv links under `.venv/` should appear.

## Tips for new contributors

- Documentation now references the real paths (`streamlit_app/pages/…`, `vibestack/mcp/server.py`, etc.). If you encounter an older guide that still mentions `container-home/`, substitute the path with its repo-root equivalent.
- When adding new assets that must ship in the container (for example an additional supervisor script or desktop config), place them at the repo root alongside the existing directories and extend the Dockerfile `COPY` block accordingly.
- Avoid reintroducing symlinks at the repo root; they can trigger the same `pathspec beyond a symbolic link` error on hosts that resolve git paths strictly.
- Keep `docs/repo-layout.md` updated whenever new top-level directories or runtime resources are added so future developers understand where to look.

