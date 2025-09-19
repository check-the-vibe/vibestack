# REST API Quick Reference

Endpoint | Method | Description
--- | --- | ---
`/api/docs` | GET | Interactive Swagger UI inside the container or via the proxy.
`/api/sessions` | GET/POST | List sessions or create a new one from a template.
`/api/sessions/{name}` | GET/DELETE | Inspect or terminate a session by name.
`/api/sessions/{name}/input` | POST | Send text to the backing tmux session.
`/api/sessions/{name}/log` | GET | Tail the last N console log lines (`lines` query).
`/api/jobs` | GET/POST | Work with the queued one-off jobs.
`/api/templates` | GET/POST | List or upsert template definitions.
`/api/templates/{name}` | DELETE | Remove a user template (built-ins are protected).

### Curl Cheatsheet
```bash
# Inside container, hit upstream directly
curl http://127.0.0.1:9000/api/jobs

# Through Nginx from a forwarded port
curl http://localhost/api/templates

# Post a one-off job
curl -X POST http://127.0.0.1:9000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"name":"run-once","command":"echo done"}'
```

For expanded examples, consult `docs/fastapi-rest-endpoints.md` in the repository root.
