# FastAPI REST Integration Plan

## Research Notes
- Existing Python interface is `vibestack.api` which proxies `SessionManager` functionality from `vibestack.sessions`.
- Session workflow relies on `SessionManager` (tmux orchestration) and `SessionStorage` (filesystem persistence) located in `vibestack/sessions`.
- Deployment stack uses Supervisor (`supervisord.conf`) to run long-lived services and Nginx (`nginx.conf`) as the public HTTP entry point.
- Container image (Dockerfile) installs Python 3, Streamlit, and other tooling but currently lacks FastAPI/Uvicorn.
- No REST interface exists today; Streamlit UI likely calls Python API directly.

## Design Goals
- Expose every helper in `vibestack.api` through a REST interface without altering existing Python consumers.
- Provide predictable, documented request/response schemas using FastAPI + Pydantic.
- Keep session/template data models close to the shapes returned by `SessionMetadata.to_dict()` to avoid duplication.
- Surface informative HTTP errors (404 for missing sessions/templates, 400 for validation issues, 500 otherwise).
- Support optional `session_root` overrides through query parameters where the Python API already accepts them.
- Maintain compatibility with future services (gRPC, WebSocket) by encapsulating the FastAPI app under `vibestack.rest.app`.

## API Surface Mapping
| HTTP Method & Path | Description | Underlying Call |
| --- | --- | --- |
| `GET /api/sessions` | List sessions | `vibestack.api.list_sessions` |
| `POST /api/sessions` | Create session | `vibestack.api.create_session` |
| `GET /api/sessions/{name}` | Fetch session metadata | `vibestack.api.get_session` |
| `DELETE /api/sessions/{name}` | Kill session | `vibestack.api.kill_session` |
| `POST /api/sessions/{name}/input` | Send text to session | `vibestack.api.send_text` |
| `GET /api/sessions/{name}/log` | Tail session log | `vibestack.api.tail_log` |
| `GET /api/jobs` | List queued/completed jobs | `vibestack.api.list_jobs` |
| `POST /api/jobs` | Enqueue one-off command | `vibestack.api.enqueue_one_off` |
| `GET /api/templates` | List templates | `vibestack.api.list_templates` |
| `POST /api/templates` | Create/update template | `vibestack.api.save_template` |
| `DELETE /api/templates/{name}` | Remove template | `vibestack.api.delete_template` |

## Data Model Outline
- **SessionCreateRequest**: `name`, optional `template`, `command`, `description`, optional `session_root`, optional `working_dir`, optional `env` map.
- **SessionResponse**: Mirrors `SessionMetadata.to_dict()` plus `schema_version`.
- **OneOffRequest**: reuse SessionCreateRequest but require `command` and allow `template` defaulting to `script`.
- **SendTextRequest**: `text` + optional `enter` flag.
- **TailLogResponse**: simple JSON wrapper `{ "log": str }` to keep response structured.
- **TemplatePayload**: pass-through JSON body accepted by `save_template`.

## Service Configuration Plan
1. **FastAPI App**: new module `vibestack/rest/app.py` exporting `FastAPI` instance and Pydantic schemas. Include lifespan handler to reuse `SessionManager`.
2. **Server Port**: run Uvicorn on `0.0.0.0:9000` (open port internally; proxied via Nginx).
3. **Process Supervision**: add `program:vibestack-api` entry to `supervisord.conf` running `uvicorn vibestack.rest.app:app` as `vibe` user with `PYTHONPATH=/home/vibe`.
4. **Nginx Proxy**: add `/admin/` location block forwarding to `http://127.0.0.1:9000/` with standard headers (external endpoints appear as `/admin/api/...`, docs at `/admin/docs`).
5. **Dependencies**: update Dockerfile to `pip install fastapi uvicorn[standard]` alongside existing Python packages.
6. **Documentation**: extend `README.md` with REST usage overview and reference this document.

## Implementation Notes
- Added `vibestack/rest/` package with `app.py` defining the FastAPI router and Pydantic models mirroring `vibestack.api` semantics. All endpoints perform defensive existence checks and translate Python exceptions into HTTP error codes.
- Introduced `vibestack/rest/__init__.py` so the app is importable as `vibestack.rest.app:app` for Uvicorn.
- Docker image now installs `fastapi` and `uvicorn[standard]` so the REST service runs out-of-the-box.
- Supervisor manages the API process via the new `program:vibestack-api` entry, logging to `/var/log/supervisor/vibestack-api.log` and starting before Nginx.
- Nginx gained an `/admin/` location proxying to the FastAPI service with buffering disabled to support streaming responses in the future.
- README documents the API surface, quick curl examples, and points to these implementation notes.
- External access goes through Nginx at `http://localhost:3000/admin/api/...` (docs at `http://localhost:3000/admin/docs`). Inside the container you can also reach the upstream directly at `http://127.0.0.1:9000/api/...`. The direct port is useful for smoke-testing before touching proxy configuration.
- A `rest-api-lab` template preloads `AGENTS.md` guidance and endpoint cheat-sheets so agents can curl the service immediately after the session starts.

## Verification Checklist
- [ ] Run `uvicorn vibestack.rest.app:app --reload` locally (optional) to ensure the module imports cleanly.
- [ ] `curl http://localhost:3000/admin/docs` (via Nginx) and `curl http://127.0.0.1:9000/api/docs` (direct) once the container rebuilds to confirm the docs render as expected.
- [ ] Exercise representative endpoints (`/sessions`, `/jobs`, `/templates`) after rebuilding the Docker image to ensure Supervisor and Nginx routing function together.

## Testing Strategy
- Unit-level confidence via FastAPI's dependency on existing API module; rely on Pydantic validation to enforce request structure.
- Manual smoke tests post-implementation:
  - `curl` session lifecycle (create/list/get/delete).
  - Template CRUD round-trip.
  - Log tail endpoint with varying `lines` parameter.
- Future work: add pytest-based API tests once testing harness exists.

## Open Questions / Future Considerations
- Authentication is currently absent; FastAPI app will be unauthenticated behind Nginx.
- Rate limiting or CSRF protection may be required before exposing publicly.
- SSE/WebSocket endpoints (e.g., live logs) can layer atop existing session manager in subsequent iterations.
