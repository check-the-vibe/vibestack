# VibeStack REST Endpoint Reference

The FastAPI service mirrors the public helpers in `vibestack.api`. All endpoints live beneath the `/api` prefix. This document captures request/response shapes and example curl invocations from inside the container (`http://127.0.0.1:9000`) and through the Nginx proxy (`http://localhost`).

> Tip: Pass `-H 'Content-Type: application/json'` on any request that sends a JSON body.

## Sessions

### List Sessions
- **Method**: `GET /api/sessions`
- **Query Params**: `session_root` (optional override)
- **Response**: `200 OK`, JSON array of session metadata
- **Example**:
  ```bash
  curl http://127.0.0.1:9000/api/sessions
  ```

### Get Session
- **Method**: `GET /api/sessions/{name}`
- **Response**: `200 OK` with metadata or `404` if unknown
- **Example**:
  ```bash
  curl http://localhost/api/sessions/demo
  ```

### Create Session
- **Method**: `POST /api/sessions`
- **Body**:
  ```json
  {
    "name": "demo",
    "template": "bash",
    "command": "echo hello"
  }
  ```
- **Response**: `201 Created` with metadata
- **Example**:
  ```bash
  curl -X POST http://127.0.0.1:9000/api/sessions \
    -H 'Content-Type: application/json' \
    -d '{"name":"demo","template":"bash"}'
  ```

### Delete Session
- **Method**: `DELETE /api/sessions/{name}`
- **Response**: `204 No Content`
- **Example**:
  ```bash
  curl -X DELETE http://localhost/api/sessions/demo
  ```

### Send Session Input
- **Method**: `POST /api/sessions/{name}/input`
- **Body**:
  ```json
  {
    "text": "ls -la",
    "enter": true
  }
  ```
- **Response**: `200 OK` with `{ "message": "input queued" }`
- **Example**:
  ```bash
  curl -X POST http://127.0.0.1:9000/api/sessions/demo/input \
    -H 'Content-Type: application/json' \
    -d '{"text":"ls"}'
  ```

### Tail Session Log
- **Method**: `GET /api/sessions/{name}/log`
- **Query Params**: `lines` (defaults to 200, max 2000)
- **Response**: `200 OK` with `{ "log": "..." }`
- **Example**:
  ```bash
  curl 'http://localhost/api/sessions/demo/log?lines=100'
  ```

## Jobs

### List Jobs
- **Method**: `GET /api/jobs`
- **Response**: `200 OK`, JSON array of job records
- **Example**:
  ```bash
  curl http://127.0.0.1:9000/api/jobs
  ```

### Enqueue One-Off Job
- **Method**: `POST /api/jobs`
- **Body**:
  ```json
  {
    "name": "daily-report",
    "command": "python run_report.py",
    "template": "script"
  }
  ```
- **Response**: `201 Created` with session metadata
- **Example**:
  ```bash
  curl -X POST http://localhost/api/jobs \
    -H 'Content-Type: application/json' \
    -d '{"name":"daily","command":"echo done"}'
  ```

## Templates

### List Templates
- **Method**: `GET /api/templates`
- **Response**: `200 OK`, JSON array
- **Example**:
  ```bash
  curl http://127.0.0.1:9000/api/templates
  ```

### Save Template
- **Method**: `POST /api/templates`
- **Body**:
  ```json
  {
    "payload": {
      "name": "custom",
      "label": "Custom session",
      "command": "bash"
    }
  }
  ```
- **Response**: `201 Created` with `{ "path": "..." }`
- **Example**:
  ```bash
  curl -X POST http://localhost/api/templates \
    -H 'Content-Type: application/json' \
    -d '{"payload":{"name":"custom","command":"bash"}}'
  ```

### Delete Template
- **Method**: `DELETE /api/templates/{name}`
- **Response**: `200 OK` with `{ "message": "template deleted" }` or `400` if disallowed
- **Example**:
  ```bash
  curl -X DELETE http://127.0.0.1:9000/api/templates/custom
  ```

## Health & Tooling

- Interactive API docs (Swagger UI): `GET /api/docs`
  ```bash
  curl http://localhost/api/docs
  ```
- ReDoc reference: `GET /api/redoc`
- Supervisor log path: `/var/log/supervisor/vibestack-api.log`
- Restart command: prefer `python -m vibestack.scripts.supervisor_helper restart vibestack-api`

Keep responses small when tailing logs—`lines=200` remains a good default for tmux sessions.
