# noVNC Desktop Stack

## Purpose
Delivers a full-featured Linux desktop (XFCE4) through the browser so users can interact with graphical tools alongside the text-based interfaces. XFCE4 provides a complete desktop environment with panel, file manager, and window manager optimized for both interactive use and programmatic automation via MCP/Playwright.

## Components & Startup Order
Managed via Supervisor:
1. `xvfb` – starts a virtual framebuffer on display `:0` at `RESOLUTION` (default `1920x1200`, optimized for tablets and high-DPI displays).
2. `x11vnc` – exposes the Xvfb display over the VNC protocol on `VNC_PORT` (default `5900`).
3. `novnc` – wraps VNC traffic with `websockify` and serves the web client on `NOVNC_PORT` (default `6080`).
4. `xfce4` – desktop environment launched once the display is ready; runs `/home/vibe/xfce-startup` which starts:
   - D-Bus session daemon
   - XFCE4 settings daemon (xfconfd)
   - XFCE4 panel (taskbar)
   - XFCE4 desktop manager (xfdesktop)
   - Window manager (xfwm4, compositor disabled for performance)
   - Terminal emulator (xfce4-terminal)

## Routing & Access
- Internal listener: `http://localhost:6080/` (e.g., `http://localhost:6080/vnc.html`).
- Exposed paths (Nginx):
  - Inside container: `http://localhost/computer/` (and `/computer/websockify` for WS).
  - From host with `./startup.sh`: `http://localhost:3000/computer/`.

### NoVNC Client Parameters
The default `/computer/` endpoint includes optimized parameters for high-DPI displays (iPad Pro, retina displays):
- `resize=scale` - Scale display to fit browser viewport
- `autoconnect=true` - Automatically connect on page load
- `reconnect=true` - Automatically reconnect if connection drops
- `quality=9` - Highest JPEG quality (0-9 scale) for sharp text on retina displays
- `compression=0` - Minimal compression for best performance (suitable for local/fast networks)

**For slow connections:** You can manually adjust by visiting:
```
http://localhost/computer/?resize=scale&autoconnect=true&quality=6&compression=2
```
Lower quality (6) and higher compression (2) reduce bandwidth at the cost of image quality.

## Configuration Touchpoints
- Environment variables: `RESOLUTION`, `NOVNC_PORT`, `VNC_PORT` can be overridden at runtime.
  - **Resolution options:**
    - `1920x1200` (default) - Optimal for tablets/iPad Pro, 16:10 aspect ratio
    - `2048x1536` - iPad Pro native resolution, 4:3 aspect ratio
    - `1920x1080` - Standard Full HD, 16:9 aspect ratio
    - `2560x1440` - QHD/2K displays
    - `3840x2160` - 4K displays (high bandwidth required)
    - `1280x720` - Lower resolution for bandwidth-constrained connections
- XFCE4 UI tweaks: edit the repo-root file `xfce-startup`; it is copied to `/home/vibe/` during the build.
- X resources: the root-level `Xresources` file controls fonts and colors for X11 applications.
- XFCE4 settings: stored in `/home/vibe/.config/xfce4/` inside the container.

## Features for Automation
The XFCE4 environment is optimized for both interactive use and programmatic control:
- **Screensaver disabled**: Prevents screen blanking during long automation tasks
- **Power management disabled**: Ensures display stays active
- **Accessibility enabled**: GTK accessibility modules improve Playwright element detection
- **Compositor disabled**: Reduces CPU/memory usage, faster rendering
- **D-Bus integration**: Proper session bus for GUI application control

## Logs & Diagnostics
- Supervisor logs:
  - `/var/log/supervisor/xvfb.log`
  - `/var/log/supervisor/x11vnc.log`
  - `/var/log/supervisor/novnc.log`
  - `/var/log/supervisor/xfce4.log`
- Browser console: inspect for WebSocket errors if the page fails to load.
- Command-line checks: prefer `python -m vibestack.scripts.supervisor_helper status` and `ss -ltnp | grep 6080` to confirm listeners.

## Troubleshooting
- Black screen: confirm the desktop environment ran (check `/var/log/supervisor/xfce4.log`) and that the Xvfb display matches the resolution expected by the MCP service.
- Connection refused on `/computer/websockify`: ensure `websockify` is listening and that `NOVNC_PORT` is not blocked.
- High CPU usage: consider lowering resolution. The compositor is already disabled for performance.
- Panel not showing: Check if `xfce4-panel` process is running. It may need a manual restart via the log viewer or terminal.
- Applications not launching: Verify D-Bus session is running with `ps aux | grep dbus-daemon`.

### iPad Pro / Safari-Specific Issues
- **Small display area:** The default 1920x1200 resolution should fill 70-85% of iPad Pro screen. For full screen, try 2048x1536 by setting `-e RESOLUTION=2048x1536` when starting the container.
- **Touch not working:** Use Safari's full-screen mode (tap share icon → Add to Home Screen, or use reader mode).
- **Performance issues:** If experiencing lag, reduce quality/increase compression in the URL or lower the resolution to 1280x720.
- **Keyboard not appearing:** Tap on input fields; Safari should show keyboard. For persistent keyboard, use an external Bluetooth keyboard.
- **Pinch-to-zoom interfering:** NoVNC captures touch events; use the noVNC menu (top-left) to adjust settings or switch to remote cursor mode.
