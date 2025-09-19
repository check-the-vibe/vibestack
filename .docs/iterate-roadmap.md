# Iterate Phase Roadmap

This plan breaks the Iterate phase into concrete milestones with tasks and verification steps.

## Milestone 1 – Short-Run Sessions
Focus: make one-off tasks deterministic: they should execute, capture output, and terminate their shell cleanly. Include research to confirm the best tmux invocation strategy.

### Research
- Compare tmux approaches for short-lived commands (direct `tmux new-session -d '<cmd>'` vs. spawning a login shell and `send-keys`).
- Investigate tmux job-control utilities (`run-shell`, `respawn-pane`, `wait-for`) for signal-safe exits.
- Document how we currently append `exit` in `SessionManager` and identify gaps (race conditions, lingering panes, exit-code capture).

### Implementation
- Introduce a dedicated helper in `SessionManager` (e.g., `run_short_task`) that launches commands with explicit exit behaviour and exit-code propagation.
- Ensure metadata captures the final exit code and last log line for quick inspection.
- Update CLI/Streamlit pathways so “one-off” jobs call the new helper and do not leave detached shells.

### Walkthrough
1. `vibestack-sessions one-off quick-test "echo hi"` → tmux session should vanish automatically; metadata records status `completed` and exit code `0`.
2. Repeat with failing command (`false`) → metadata shows `failed` with non-zero exit code and log captures stderr.
3. Trigger a one-off job from Streamlit → on completion, UI shows the run summary, no lingering session entry in `tmux ls`.

## Milestone 2 – Session Templates & Automation Hooks
Focus: support configurable templates and lifecycle hooks for richer automation.

### Tasks
- Add on-disk template definitions (e.g., `~/.vibestack/templates/*.json` or `templates.yaml`).
- Extend `SessionManager` to load templates dynamically and honour fields like default command, working directory, session type, post-create hook.
- Build Streamlit UI for template CRUD and preview.

### Walkthrough
1. Create a template via Streamlit (e.g., `pytest-short`) → file appears on disk, option shows up in template dropdown.
2. Launch a session with the new template → verify tmux command, workspace scaffold, and post-create hook output.
3. Edit/delete the template from UI → changes reflected immediately in subsequent session creation.

## Milestone 3 – Integration & Automation
Focus: expose programmatic interfaces and delivery of short-run results (tying back to Milestone 1 requirements).

### Tasks
- Package `vibestack.sessions` as an installable module for external scripting.
- Add HTTP/WebSocket endpoints to create sessions, trigger one-off jobs, and fetch their outputs/artifacts.
- Enhance CLI with commands to stream final output (`vibestack-sessions results <job>`).

### Walkthrough
1. Install the built wheel outside the repo and run smoke tests.
2. Use the API to create a short-run job and fetch its output payload.
3. Use the CLI `results` command to display the final log/exit data for a completed job.

## Milestone 4 – Documentation & Release Prep
Focus: polish user-facing docs and release assets after features land.

### Tasks
- Update README and walkthrough guides with new template management, auth-less short-run results, and API usage.
- Capture refreshed screenshots for Streamlit pages (templates, job results).
- Assemble a release checklist (build logs, API docs, CLI examples).

### Walkthrough
1. Follow README from scratch to validate steps (build → run → configure templates → execute short-run tasks).
2. Ensure `.docs/ux-walkthrough.md` and `poc-verification-walkthrough.md` cover new flows.
3. Review release checklist with sample outputs attached.

Use this roadmap to track progress; update `TASKS.md` as milestones complete.
