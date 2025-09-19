# Progress Summary

This document captures the Iterate-phase work completed so far.

## Milestone 1 – Short-Run Sessions
- Added tmux-based `run-once.sh` wrapper so one-off sessions exit cleanly, write `result.json`, and log exit codes.
- Metadata now records `exit_code`, `last_message`, and updates job status to `completed`/`failed` automatically.
- Short-run jobs start in their session workspace so artifacts and logs stay together.

## Template & Asset Foundations
- SessionManager now loads templates from built-in (`vibestack/templates/`) and user (`~/.vibestack/templates/`) directories, tracks sources, and supports `save_template`/`delete_template`/`list_templates`.
- Added default assets (`TASKS.md`, `AGENTS.md`, `CLAUDE.md`, `AGENTS-writing.md`) plus templates for `codex`, `claude`, and `codex-research` (writing assistant).
- Template `include_files` automatically copy files into each session workspace.

## Streamlit UI Enhancements
- Sidebar now lists live templates (with descriptions and included files).
- Workspace tab exposes session artifacts; templates page provides management tooling.

Future work: template creation from active sessions, improved workspace editor, automation APIs.

## Milestone 3 – Integration & Automation (initial)
- Entry point now supports `CODEX_STATE_DIR` (or `/projects/codex`) so Codex tokens persist between runs.
- Introduced `vibestack.api` module with helper functions for session CRUD, jobs, logs, and templates.
- Documented usage in `.docs/api-usage.md` so external services (FastAPI, MCP, etc.) can reuse the same primitives as the Streamlit UI.
