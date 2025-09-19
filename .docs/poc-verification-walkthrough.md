# VibeStack POC Verification Walkthrough

This guide outlines the manual verification flow for confirming the POC milestones delivered in the current iteration. Follow the steps in order; each section calls out what to test, what to expect, and which milestone it covers. The final section lists the next scope areas to tackle once the walkthrough passes.

## Prerequisites
- Docker Desktop running with enough resources (>= 6 GB RAM recommended).
- Local repository synced to the latest changes in `vibestack-current`.
- Network access for npm/PyPI downloads during the Docker build.

---

## 1. Build the container image
**Milestones:** container plumbing (Dockerfile, entrypoint, supervisor) and Python package install.

1. `docker build -t vibestack-current ./vibestack-current`
2. Expect the build to:
   - Install tmux alongside existing desktop tooling.
   - Copy the `vibestack` Python package and `bin/` utilities into `/home/vibe`.
   - Create symlinks for `vibestack-sessions` and `vibestack-ttyd-entry` under `/usr/local/bin`.
   - Run `dos2unix` over the new scripts without error.
3. Failures here indicate image plumbing regressions—resolve before moving forward.

## 2. Run the container
**Milestones:** Supervisor configuration, entrypoint environment bootstrap.

1. `docker run --rm -p 80:80 -p 8501:8501 -p 7681:7681 vibestack-current`
2. On startup, confirm logs show Supervisor launching xvfb, x11vnc, ttyd, streamlit, nginx, and playwright.
3. Inside the container (`docker exec -it <container> bash`):
   - `echo $VIBESTACK_HOME` should output `/home/vibe`.
   - `echo $PYTHONPATH` should include `/home/vibe`.
   - `ls /home/vibe/sessions` should exist (may be empty initially).

## 3. Validate CLI session manager
**Milestones:** Python session library, CLI tooling, tmux orchestration, storage layout.

_Run inside the container shell as `vibe` user (`su - vibe`)._

1. `vibestack-sessions list` → returns `[]` initially.
2. `vibestack-sessions create demo-bash --template bash`
   - Expect JSON metadata with `status: "running"` and log/workspace paths under `/home/vibe/sessions/demo-bash/`.
   - `tmux ls` should include `demo-bash`.
3. `vibestack-sessions logs demo-bash --lines 20` → shows shell greeting.
4. `vibestack-sessions kill demo-bash` → session disappears from `tmux ls`; metadata status updates to `stopped`.
5. `vibestack-sessions one-off demo-job "echo hello && sleep 1"`
   - Logs should contain `[vibestack] session exited with code 0`.
   - `vibestack-sessions list` should mark `demo-job` as `completed` after the command finishes.

Filesystem confirmation:
- `tree -L 2 /home/vibe/sessions` should show per-session directories containing `metadata.json`, `console.log`, and `artifacts/`.

## 4. Validate ttyd entry routing
**Milestones:** ttyd entry wrapper, nginx routing changes.

1. From a browser, open `http://localhost/terminal/` → expects VibeStack terminal UI.
2. Launch a named session via URL args:
   - `http://localhost/terminal/?arg=session&arg=workspace&arg=bash` attaches to the default workspace session (auto-created if missing).
3. For a new session: `http://localhost/terminal/?arg=create&arg=claude&arg=claude-dev`
   - Should display creation message, then attach to the `claude-dev` tmux session running `claude`.
4. Confirm nginx fallback (`/`) still proxies to ttyd (legacy behavior).

## 5. Validate Streamlit control center
**Milestones:** revamped UI tied to session manager, embedded terminals, file explorer.

1. Open `http://localhost/ui/`.
2. On the main dashboard:
   - Launch a session via sidebar (e.g., template `codex`). Expect success toast and table entry.
   - Queue a one-off job (e.g., `echo from streamlit`). `Job queue` table should reflect the new job and status transitions.
   - Switch to the newly created session; the Terminal tab should embed ttyd with the correct session via query args.
   - Logs tab should stream the same `console.log` content as the CLI.
   - Workspace tab lists files under `/home/vibe/sessions/<name>/artifacts` (create a file inside tmux to test).
   - Streamlit tab lists and edits files under `/home/vibe/streamlit` in-place; saving should persist to disk (verify via `git diff`).
3. Visit `Session Storage` (sidebar page `🗂️ Session Storage`):
   - Inspect metadata, download logs, terminate sessions.
4. Visit `💻 Terminal` page: ensures full-screen embedded terminal bound to currently selected session.
5. Visit `📁 Workspace Explorer`: browse `Streamlit`, `Vibestack package`, and `Sessions` directories; download assets as needed.

## 6. Validate persistence and cleanup
**Milestones:** session storage artifacts, job queue tracking.

1. After killing a session, check `/home/vibe/sessions/<name>/metadata.json` to confirm `status` reflects `stopped` or `completed`.
2. Verify `/home/vibe/sessions/queue.json` accumulates job history with updated timestamps.
3. Restart the container (`docker restart <id>`): list sessions again and confirm metadata reloads even if tmux sessions aren’t active (statuses should remain `stopped`/`completed`).

---

## Next scope after walkthrough success
1. **Documentation phase** – update `README.md` (or dedicated docs) with developer-facing instructions for the new session workflow, CLI usage, and Streamlit capabilities.
2. **Iterate phase** – design authentication/authorization for ttyd and session endpoints, expand session templates, and tighten automation hooks.
3. **Release preparation** – draft the release checklist, outline Docker registry publishing steps, and capture required screenshots/logs for review.

Complete this walkthrough before moving to the Iterate/Release tasks to ensure the POC foundation is stable.
