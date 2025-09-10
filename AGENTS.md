# Repository Guidelines

## Project Structure & Module Organization
- `streamlit_app/`: Streamlit UI. `app.py` is the landing page; pages live in `pages/` (naming: `<order>_<emoji>_<Title>.py`, e.g., `1_✏️_Editor.py`).
- `vibestack-menu/`: Node + Ink CLI for the terminal menu. Entry is `menu.js`; UI in `src/`.
- `.vibe/`: Runtime docs and config used by the UI (`TASKS.md`, `ERRORS.md`, `LOG.txt`, `PERSONA.md`, `docs/`).
- Container & services: `Dockerfile`, `nginx.conf`, `supervisord.conf`, `entrypoint.sh`, `.devcontainer/devcontainer.json`.

## Build, Test, and Development Commands
- Docker build: `docker build -t vibestack .`
- Docker run: `docker run -p 80:80 -p 22:22 vibestack`
- Streamlit (local dev): `streamlit run streamlit_app/app.py` (the “Code” page’s terminal iframe expects the Nginx proxy; other pages work standalone).
- Menu app: `cd vibestack-menu && npm install && npm start`.
- Services (in container): `sudo supervisorctl status` to inspect running processes.

## Coding Style & Naming Conventions
- Python: PEP 8, 4‑space indent, snake_case. Keep Streamlit pages small and declarative; set `st.set_page_config` at top.
- JavaScript: ES modules, 2‑space indent, React + Ink patterns as in `src/App.js`. Prefer functional components.
- Filenames: Streamlit pages follow `<order>_<emoji>_<Title>.py`; Node files use `.js`.
- Formatters: None enforced. Match existing style. Propose Black/Prettier in a separate PR if adding.

## Testing Guidelines
- No formal test suite yet. Validate changes by:
  - Running Streamlit locally and verifying Editor/File Browser behavior with files in `/home/vibe/.vibe`.
  - Running the menu via `npm start` and exercising commands.
  - In container builds, check endpoints: `/` (desktop), `/ui/` (Streamlit), `/terminal/`.
- If adding JS code, prefer colocated tests under `vibestack-menu/` using Jest/Vitest (`*.test.js`). Keep PR coverage focused on changed areas.

## Commit & Pull Request Guidelines
- Commits: concise, imperative summaries (e.g., “fix editor layout”, “update menu”). Group related changes.
- PRs must include:
  - Clear description and rationale; link issues if applicable.
  - Run/validation steps (Docker and/or local Streamlit/Node). 
  - Screenshots/GIFs for UI changes (Streamlit pages, terminal embed).
  - Note if `Dockerfile` or `.devcontainer` changes require a rebuild.

## Security & Configuration Tips
- Do not commit secrets. Use `.env` (see `.env.example`) or `--env-file` when running Docker.
- Relevant env vars: `VNC_PASSWORD`, `ROOT_PASSWORD`, `VIBE_PASSWORD`, `RESOLUTION`.
- Keep scripts executable and portable; avoid hard‑coding user paths.

