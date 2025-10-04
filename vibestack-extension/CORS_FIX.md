# CORS Fix Applied

## Issue
Chrome extension was getting `405 Method Not Allowed` on OPTIONS requests to `/admin/api/sessions` because the Vibestack REST API didn't have CORS middleware configured.

## Solution Applied
Added CORS middleware to `/Users/neal/Projects/vibestack/vibestack/rest/app.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Next Steps - RESTART THE API

**On your Vibestack server, restart the API service:**

```bash
# If running in Docker:
docker exec -it <container_name> supervisorctl restart vibestack-api

# Or if running directly:
sudo supervisorctl restart vibestack-api

# Check the status:
sudo supervisorctl status vibestack-api
```

## Verify the Fix

After restarting, the Chrome extension should be able to:
1. Fetch sessions: `GET /admin/api/sessions`
2. Create sessions: `POST /admin/api/sessions`
3. Send commands: `POST /admin/api/sessions/{name}/input`
4. Fetch logs: `GET /admin/api/sessions/{name}/log`

The OPTIONS preflight requests will now return `200 OK` instead of `405`.
