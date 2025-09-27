# Repository Guidelines

## Project Structure & Module Organization
The Python application lives in `vibestack/`, with `api.py` exposing session helpers, `rest/` wrapping the FastAPI gateway, `mcp/` enabling Model Context Protocol adapters, and `sessions/` managing tmux-backed jobs. The Streamlit control surface sits in `streamlit_app/` (`app.py`, shared utilities in `common.py`, feature pages under `pages/`). Operational scripts reside in `bin/`, documentation in `docs/`, reusable examples in `examples/`, and automated checks in `tests/`—use `tests/test_api_functional.py` as the reference layout when adding suites.

## Build, Test & Development Commands
- `./startup.sh [follow]` rebuilds the Docker image, restarts supervised services, and optionally tails logs.
- `python -m streamlit run streamlit_app/app.py` launches the UI locally without the rest of the stack.
- `bin/vibe list|create|attach` executes the session CLI against the in-repo code without installing a package.
- `pytest -q` runs all automated tests; add `-k pattern` or `tests/<file>.py::test_case` for focused runs.

## Coding Style & Naming Conventions
Target Python 3.10 with four-space indentation, docstrings for public helpers, and type hints on new code (mirroring `vibestack/api.py`). Modules, functions, and files stay snake_case; classes use PascalCase; CLI flags use kebab-case. Format Python with a PEP 8–compatible tool (Black or Ruff-format) before sending a review.

## Testing Guidelines
Place new tests in `tests/` using `test_<feature>.py`; prefer descriptive function names such as `test_queue_job__returns_metadata`. Pair functional additions to the REST or Streamlit layers with at least one integration assertion, and capture edge cases with unit tests near the helper you touched. Document any manual verification steps in `TASKS.md` when automation is not feasible.

## Commit & Pull Request Guidelines
Write concise, imperative commit subjects (`add streamlit session filter`). In pull requests, describe the user-facing impact, list validation commands (e.g., `pytest -q`), and attach screenshots or log excerpts for UI or service changes. Link related TASKS.md items or external issues so handoffs stay traceable, and update docs (`docs/README.md`, `docs/services/...`) whenever defaults, ports, or env vars move.

## Configuration & Security Tips
Never commit real credentials; add new settings to `.env.example` and mention them in the README. After editing `configure-user.sh` or `supervisord.conf`, confirm ports still match `nginx.conf`. Keep persistent state under `/projects` or `/data/codex` so container rebuilds do not discard it.

## Codex MCP Servers
See `.docs/codex-mcp-servers.md` for the workflow that adds STDIO MCP servers (including the default Playwright integration) to session-scoped `config.toml` files. Configure the public base URL exposed to MCP via the Streamlit **MCP** page when tunnels or hostnames change.
