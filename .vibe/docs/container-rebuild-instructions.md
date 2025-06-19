# Container Rebuild Instructions

## Changes Made

1. **Removed**: pyscreenrec-mcp from supervisord.conf
2. **Added**: electron-clipboard app configuration to supervisord.conf
3. **Created**: /workspaces/vibestack/electron-clipboard/boot.sh - startup script

## Configuration Details

- **Program name**: electron-clipboard
- **Display**: :0 (shared with VNC)
- **User**: vibe
- **Priority**: 900 (runs after window manager)
- **Start delay**: 25 seconds (to ensure X and WM are ready)
- **Auto-restart**: enabled
- **Logs**: /var/log/supervisor/electron-clipboard.log

## To Apply Changes

Since supervisord configuration has been modified, you need to rebuild the container:

1. In GitHub Codespaces, click on the menu (three lines) in the top-left
2. Select "Rebuild Container" 
3. Wait for the rebuild to complete

## What Happens on Boot

1. X server (Xvfb) starts on display :0
2. VNC server connects to display :0
3. Fluxbox window manager starts
4. After 20 seconds, electron-clipboard app launches
5. The app will be visible when accessing VNC

## Verification

After rebuild, you can:
- Access VNC to see the Electron app running
- Check logs: `tail -f /var/log/supervisor/electron-clipboard.log`
- Check status: `supervisorctl status electron-clipboard`