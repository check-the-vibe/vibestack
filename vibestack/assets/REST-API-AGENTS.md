# REST API Agent Guide

Use this template to exercise the FastAPI layer from inside the container.

## Quick Start
1. Verify the API process is healthy:
   ```bash
   sudo supervisorctl status vibestack-api
   ```
2. Hit the docs directly on the upstream port:
   ```bash
   curl http://127.0.0.1:9000/api/docs
   ```
3. Create a disposable session and review its metadata:
   ```bash
   curl -X POST http://127.0.0.1:9000/api/sessions \
     -H 'Content-Type: application/json' \
     -d '{"name":"rest-test","template":"bash"}'
   curl http://127.0.0.1:9000/api/sessions/rest-test
   ```
4. Tear it down once finished:
   ```bash
   curl -X DELETE http://127.0.0.1:9000/api/sessions/rest-test
   ```

## Helpful Endpoints
- Session lifecycle endpoints live under `/api/sessions`.
- Job queue helpers live under `/api/jobs`.
- Template management endpoints live under `/api/templates`.

See `docs/fastapi-rest-endpoints.md` for a complete reference and additional curl snippets. Use `lines` query parameters conservatively when tailing logs over HTTP.
