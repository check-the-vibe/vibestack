# noVNC Desktop Stack

## Purpose
Delivers a lightweight Linux desktop (Fluxbox) through the browser so users can interact with graphical tools alongside the text-based interfaces.

## Components & Startup Order
Managed via Supervisor:
1. `xvfb` – starts a virtual framebuffer on display `:0` at `RESOLUTION` (default `1280x720`).
2. `x11vnc` – exposes the Xvfb display over the VNC protocol on `VNC_PORT` (default `5900`).
3. `novnc` – wraps VNC traffic with `websockify` and serves the web client on `NOVNC_PORT` (default `6080`).
4. `fluxbox` – window manager launched once the display is ready; runs `/home/vibe/.fluxbox/startup`.

## Routing & Access
- Direct noVNC client: `http://localhost:6080/vnc.html` (used by the Docker health check).
- Nginx exposes the experience at `/computer/`, including static assets under `/computer/<subpath>` and the WebSocket bridge at `/computer/websockify`.

## Configuration Touchpoints
- Environment variables: `RESOLUTION`, `NOVNC_PORT`, `VNC_PORT` can be overridden at runtime.
- Fluxbox UI tweaks: edit the repo-root files `fluxbox-init`, `fluxbox-startup`, and `fluxbox-apps`; they are copied to `/home/vibe/.fluxbox/` during the build.
- X resources: the root-level `Xresources` file controls fonts and colors for X11 applications.

## Logs & Diagnostics
- Supervisor logs:
  - `/var/log/supervisor/xvfb.log`
  - `/var/log/supervisor/x11vnc.log`
  - `/var/log/supervisor/novnc.log`
  - `/var/log/supervisor/fluxbox.log`
- Browser console: inspect for WebSocket errors if the page fails to load.
- Command-line checks: `supervisorctl status novnc` and `ss -ltnp | grep 6080` to confirm listeners.

## Troubleshooting
- Black screen: confirm `fluxbox` ran (check log) and that the Xvfb display matches the resolution expected by the MCP service.
- Connection refused on `/computer/websockify`: ensure `websockify` is listening and that `NOVNC_PORT` is not blocked.
- High CPU usage: consider lowering resolution or reducing background applications in the Fluxbox startup script.
