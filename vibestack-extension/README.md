# Vibestack Chrome Extension

A Chrome extension that provides a terminal overlay interface to interact with remote Vibestack sessions via the REST API.

## Features

### 🚀 Vibestack Integration
- **Session Management**: Create, list, and switch between Vibestack sessions
- **Real-time Logs**: Auto-polling session logs (1-second refresh)
- **Command Execution**: Send commands directly to remote sessions
- **API Configuration**: Configurable Vibestack API endpoint

### 🖥️ Terminal Interface
- **Overlay Terminal**: Toggleable terminal at bottom of any webpage (Ctrl+~)
- **Session Selector**: Dropdown to switch between active sessions
- **Command History**: Navigate previous commands with arrow keys
- **Live Updates**: Session logs update in real-time

## Installation & Setup

1. **Load Extension**
   ```
   1. Open Chrome and go to chrome://extensions/
   2. Enable "Developer mode" (toggle in top right)
   3. Click "Load unpacked" and select this directory
   ```

2. **Configure Vibestack API**
   
   **Auto-Configuration (New!)**
   ```
   The extension now auto-detects the Vibestack URL when loaded from
   a Vibestack-served page. If accessing via /extension/ endpoint,
   the URL is automatically configured.
   ```
   
   **Manual Configuration**
   ```
   1. Press Ctrl+~ to open the terminal overlay
   2. Enter the Vibestack API URL (default: https://afeeb1ba4000.ngrok.app)
   3. Click "Save URL"
   ```

3. **Create or Select Session**
   ```
   1. Click "Refresh" to load existing sessions
   2. Or click "New Session" to create a new one
   3. Select a session from the dropdown
   ```

4. **Start Using**
   ```
   1. Type commands in the terminal input
   2. Press Enter to send to the active session
   3. Watch logs update in real-time
   ```

## Usage Examples

### Session Management
- **Refresh Sessions**: Click "Refresh" button to reload session list
- **Create Session**: Click "New Session" and enter name + template (e.g., "bash")
- **Switch Session**: Select from dropdown to change active session

### Command Execution
- Type any command and press Enter
- Commands are sent with Enter key automatically
- View output in real-time log display

## How It Works

1. **API Connection**: Connects to Vibestack REST API at `/admin/api/`
2. **Session Lifecycle**:
   - `GET /api/sessions` - Lists all sessions
   - `POST /api/sessions` - Creates new session
   - `POST /api/sessions/{name}/input` - Sends commands
   - `GET /api/sessions/{name}/log?lines=500` - Fetches logs
3. **Log Polling**: Auto-refreshes logs every 1 second when session is active
4. **Persistence**: Stores API URL and current session in Chrome storage

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Popup UI      │    │  Terminal        │    │  Vibestack API  │
│                 │    │  Overlay         │    │                 │
│ • Toggle Term   │◄──►│                  │◄──►│ • Sessions      │
│                 │    │ • Session Select │    │ • Commands      │
│                 │    │ • Log Display    │    │ • Logs          │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Vibestack API Endpoints

Based on nginx.conf, the API is exposed at `/admin/` which proxies to the FastAPI server on port 9000:

- **Base URL**: `https://afeeb1ba4000.ngrok.app` (API endpoints are at `/admin/api/...`)
- **Sessions**:
  - `GET /api/sessions` - List all sessions
  - `GET /api/sessions/{name}` - Get session details
  - `POST /api/sessions` - Create new session
  - `DELETE /api/sessions/{name}` - Terminate session
- **Commands**:
  - `POST /api/sessions/{name}/input` - Send text to session
- **Logs**:
  - `GET /api/sessions/{name}/log?lines={n}` - Tail session logs

## Development

### File Structure
```
├── manifest.json           # Extension configuration
├── terminal-overlay.js     # Terminal UI and Vibestack integration
├── content-script.js       # Page DOM utilities
├── background.js           # Background service worker
├── popup.html              # Extension popup UI
├── popup.js                # Popup logic
└── README.md               # This file
```

### Configuration
- API URL is stored in `chrome.storage.local.vibestackApiUrl`
- Current session is stored in `chrome.storage.local.vibestackCurrentSession`

## Keyboard Shortcuts
- **Ctrl+~**: Toggle terminal visibility
- **Escape**: Hide terminal
- **Up/Down Arrow**: Navigate command history
- **Enter**: Execute command

## Troubleshooting

### Common Issues
- **"Error fetching sessions"**: Check API URL is correct and server is running
- **"No session selected"**: Create a new session or select one from dropdown
- **Logs not updating**: Session may have ended; check session status
- **CORS errors**: Ensure extension has `<all_urls>` permission in manifest

### Debug Tips
- Open Chrome DevTools on the page to see console logs
- Check Network tab for API request/response details
- Verify ngrok tunnel is active and accessible

## License

This project is provided as-is for educational and development purposes.
