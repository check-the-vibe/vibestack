# Development Service Proxies

## Purpose
Expose a handful of fixed HTTP pass-through routes so agents can surface ad-hoc development services (for example local web apps or API prototypes) running inside the container. Each proxy maps a URL path on Nginx to a corresponding localhost port.

## Routing & Access
- Internal listeners: bind your app to `http://localhost:3000` … `3004` inside the container.
- Exposed paths (Nginx): `/services/3000/` … `/services/3004/`.
  - From host with `./startup.sh`: `http://localhost:3000/services/<port>/`.
  - From inside container: `http://localhost/services/<port>/`.
- Supported methods: any HTTP verbs supported by the upstream service (Nginx simply forwards the request).
- WebSocket support: upgrade headers are forwarded so frameworks like Vite or Next.js hot reload work as expected.

## Usage Notes
- Bind your development server to one of the allocated ports (3000-3004) when launching the process.
- Access the service through the proxy path (for example `https://<host>/services/3000/`) to reach it from a browser.
- Each path preserves sub-routes, so `/services/3001/api/status` becomes `http://localhost:3001/api/status` upstream.
- Need additional slots? Update `nginx.conf` with a new `location /services/<port>/` block and document the change here.

## Troubleshooting
- `404` or connection refused → confirm the service is listening on the expected port and bound to `0.0.0.0` or `127.0.0.1` inside the container.
- Mixed content warnings → ensure the upstream service respects the `X-Forwarded-Proto` header when constructing absolute URLs.
- Unexpected caching → disable caching in your dev server; Nginx does not cache responses for these paths.
