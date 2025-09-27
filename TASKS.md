# Task Tracker

## Startup sessions bootstrap
Goal: Allow the stack to launch predefined tmux sessions automatically once core services are available.
Plan:
1. Define a canonical list of startup sessions and helper code that can materialize them via the existing session manager.
2. Add a runnable entry point (and supervisor integration) that waits for the REST API to come online, then seeds the startup sessions idempotently.
3. Cover the helper with unit-level validation so future change detection is easy.
Status: Completed

## Supervisor log viewer startup session
Goal: Provide the first startup session that launches a TUI for browsing supervisor logs with left/right navigation.
Plan:
1. Build a repo-managed TUI script that shells out to `supervisorctl` for status and log tails while handling arrow-key input.
2. Ship a dedicated session template that bundles the script into the workspace and invokes it, marking it for startup execution.
3. Extend tests (or at least helper coverage) around the non-interactive parts of the TUI so behaviour stays reliable.
Status: Completed

## Streamlit onboarding copy
Goal: Simplify the first-visit onboarding message on `/ui`.
Plan:
1. Replace the existing instructional block with the short welcome sentence while preserving dismissal controls.
Status: Completed
