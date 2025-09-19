# Admin REST API (FastAPI)

## Purpose
Wraps the `vibestack` Python session manager with a documented HTTP interface for automation, external tooling, and the Streamlit UI. Provides CRUD access to sessions, templates, and one-off jobs.

## Startup & Lifecycle
- Supervisor program: `vibestack-api`.
- Command: `/usr/bin/python3 -m uvicorn vibestack.rest.app:app --host 0.0.0.0 --port 9000`.
- Working directory: `/home/vibe` so relative paths resolve inside the runtime home.
- Logs: `/var/log/supervisor/vibestack-api.log`.

## Routing & Access
- Internal port: `9000`.
- Nginx proxy: `/admin/` prefix forwards to the FastAPI app; use `/admin/docs` for the interactive OpenAPI UI.
- Direct access inside the container: `http://127.0.0.1:9000/api/...`.

## API Surface (selected)
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/sessions` | List all tracked sessions. |
| `POST` | `/api/sessions` | Create a session. Body mirrors `SessionCreateRequest`. |
| `GET` | `/api/sessions/{name}` | Inspect a single session. |
| `DELETE` | `/api/sessions/{name}` | Terminate a session. |
| `POST` | `/api/sessions/{name}/input` | Send keystrokes/text to the tmux pane. |
| `GET` | `/api/sessions/{name}/log` | Tail recent log lines (`lines` query parameter). |
| `GET` | `/api/jobs` | Show queued/active jobs. |
| `POST` | `/api/jobs` | Enqueue one-off commands (`OneOffJobRequest`). |
| `GET` | `/api/templates` | List templates (built-in + user). |
| `POST` | `/api/templates` | Persist/update a template using arbitrary JSON payload. |
| `DELETE` | `/api/templates/{name}` | Remove a user-defined template. |

Refer to `docs/fastapi-rest.md` in the source tree for historical design notes.

## Key Source Files
- `vibestack/rest/app.py` – FastAPI application, Pydantic models, and router definitions.
- `vibestack/api.py` – Python session manager façade invoked by the REST endpoints.

## Common Tasks
- **Smoke test:** `curl http://localhost/admin/api/sessions | jq` after the container starts.
- **Schema changes:** update Pydantic models in `vibestack/rest/app.py` and adjust downstream clients (UI, CLI, docs).
- **Error diagnosis:** watch `/var/log/supervisor/vibestack-api.log` for stack traces; FastAPI surfaces 4xx/5xx status codes.

## Troubleshooting
- 404 on `/admin/...` paths → check the Nginx location block and confirm the service is running (`supervisorctl status vibestack-api`).
- JSON validation errors → payload does not match request schema. Inspect error body for detailed messages.
- Hanging requests → ensure the underlying session operation is not blocked (tmux or filesystem). Consider lowering concurrency or checking for lock contention.
