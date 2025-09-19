# Research: Session Templates & Hooks

Goal: allow operators to define reusable session templates (command, working dir, env, hooks) via config files and manage them through the UI.

## Existing behaviour
- `SessionManager.DEFAULT_TEMPLATES` hardcodes `bash`, `claude`, `codex`, `script`.
- No persistence layer for custom templates; Streamlit sidebar uses the static list.

## Requirements
- Templates persisted on disk so they survive rebuilds (`/home/vibe/vibestack/templates/*.json` or YAML file).
- Fields to support:
  - `label` and `command` (mandatory).
  - `session_type` (`long_running` / `one_off`).
  - `working_dir` relative to home or absolute.
  - `env` key/value overrides.
  - Optional `post_create` hook (shell command run after session created).
  - Metadata like description, icon.
- Hot reloading so adding/removing template file updates UI without restart.

## Storage options
1. **One JSON per template** in `~/vibestack/templates/`.
   - Pros: easy to edit manually, simple watch.
   - Cons: need to glob directory each time; but manageable.
2. **Single YAML file** (`templates.yaml`).
   - Pros: centralised.
   - Cons: concurrency issues if editing via UI while user edits manually.
3. **SQLite** (overkill for POC).

Recommendation: start with per-template JSON; directory can be mounted for user customisation.

## UI considerations
- Streamlit page for templates (list existing, add/edit form, delete).
- Validate command/fields before saving.
- Possibly show preview snippet (tmux command) or immediate “test-run” button.

## SessionManager changes
- Load templates at init and merge with defaults.
- Provide helper `resolve_template(name)` returning full config.
- When creating session, apply env/working_dir, and queue `post_create` command (maybe send via short-run helper so exit is captured).

## Hooks
- `post_create`: run after session is up (for long running). For one-off maybe run prior to exit.
- Could also support `pre_launch` for prepping workspace.
- Ensure hooks run via short-run helper to guarantee clean exit and logging.

## Next steps
- Prototype JSON schema and loader.
- Implement watcher/merge logic in `SessionManager`.
- Create Streamlit management page stub.
