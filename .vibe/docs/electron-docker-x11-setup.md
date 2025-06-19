# Electron App in Docker with X11 and Supervisord

## Key Findings

1. **Display Configuration**: 
   - The container already has Xvfb running on :0 (from supervisord.conf)
   - VNC is serving display :0
   - Fluxbox window manager is running on :0

2. **Electron Requirements**:
   - Needs DISPLAY=:0 environment variable
   - Requires --no-sandbox flag (already in start.sh)
   - Must run after X server and window manager are ready

3. **Supervisord Priority Order**:
   - 100: xvfb (X server)
   - 200: x11vnc 
   - 300: novnc
   - 400: fluxbox (window manager)
   - 900: electron-clipboard (should run after WM)

4. **Required Environment Variables**:
   - DISPLAY=:0
   - HOME=/home/vibe
   - ELECTRON_DISABLE_SANDBOX=1

5. **Working Directory**:
   - Must be set to /workspaces/vibestack/electron-clipboard
   - Needs access to node_modules

## Implementation Plan

1. Remove pyscreenrec-mcp entry from supervisord.conf
2. Add electron-clipboard entry with proper configuration
3. Ensure startup delay to wait for X and WM
4. Set correct user, environment, and working directory