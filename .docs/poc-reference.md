# vibestack-poc Reference Snapshot

The `vibestack-poc/` directory is about to be removed. This note captures the pieces we may want to port or refer back to later.

## Networking & Codex Callback
- Environment variable `CODEX_CALLBACK_PORT` seeded in Dockerfile / `.env` (default 1455).
- `entrypoint.sh` writes `/etc/nginx/conf.d/codex_callback_upstream.conf`.
- `nginx.conf` constructs two front doors:
  - `/codex-callback/` path → `upstream codex_callback`.
  - Dedicated server listening on container port 1456 that proxies to the Codex upstream.
- `scripts/start.sh` maps host `$CODEX_CALLBACK_PORT` to container `1456` and mounts project directories.
  - Good template for a future `start` helper in `vibestack-current`.

## CLI & Session Helpers
- `tmux_session.sh` demonstrates forwarding extra args into codex loader scripts.
- `scripts/show-codex-paths.sh` hunts through the repo and container for Codex/OpenAI config spills.
- `scripts/codex-login.sh` wraps `docker exec` for login convenience.

## Streamlit Experiments
- `streamlit_app/app.py` contains richer Codex integration examples (prompt builders, config controls).
- `streamlit_app/experiments/sessions.py` includes early experiments with session templating and codex automation; useful for Iterate phase inspirations.

## Docs in `.vibe/`
- Numerous markdown files capturing research: menu navigation, terminal iframe, draft workflow, etc. Consider migrating the most relevant ones into `.docs/` after the cleanup.

## Docker Notes
- `DOCKER.md` documents the previous stack, port mappings, and login flows—good comparison for README rewrite.
- `Dockerfile` includes alternative service wiring (e.g., `codex_loader.sh`) that may still be applicable.

Keep this around until we finish extracting any last pieces; once the poc folder is deleted this will serve as a pointer for future iterations.
