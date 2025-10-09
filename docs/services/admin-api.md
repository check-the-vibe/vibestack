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
- Nginx proxy: `/admin/` prefix forwards to the FastAPI app; external via host mapping at `http://localhost:3000/admin/api/...` (docs at `http://localhost:3000/admin/docs`).
- Direct access inside the container: `http://127.0.0.1:9000/api/...`.
- ChatGPT compatibility paths: `/VibeStack/<link_id>/tail_log` and `/VibeStack/<link_id>/send_input` forward to helper endpoints that proxy to the same API (see below).

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
- **Smoke test:**
  - External via Nginx: `curl http://localhost:3000/admin/api/sessions | jq`
  - Internal direct: `curl http://127.0.0.1:9000/api/sessions | jq`
- **Schema changes:** update Pydantic models in `vibestack/rest/app.py` and adjust downstream clients (UI, CLI, docs).
- **Error diagnosis:** watch `/var/log/supervisor/vibestack-api.log` for stack traces; FastAPI surfaces 4xx/5xx status codes.
- **ChatGPT link bridge:** tail a session log via `curl "http://localhost/VibeStack/link_test/tail_log?name=<session>&lines=100"` or send input with `curl -X POST "http://localhost/VibeStack/link_test/send_input" -d '{"name":"<session>","text":"echo hi","enter":true}' -H 'Content-Type: application/json'`.

## Troubleshooting
- 404 on `/admin/...` paths → check the Nginx location block and confirm the service is running (prefer `python -m vibestack.scripts.supervisor_helper status`).
- 404 on `/VibeStack/...` paths → ensure the compatibility rewrite exists in `/etc/nginx/nginx.conf` and the service restarted; the helper endpoints live under `/link/{link_id}/...` inside FastAPI.
- JSON validation errors → payload does not match request schema. Inspect error body for detailed messages.
- Hanging requests → ensure the underlying session operation is not blocked (tmux or filesystem). Consider lowering concurrency or checking for lock contention.
