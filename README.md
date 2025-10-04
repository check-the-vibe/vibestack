# 🚀 VibeStack

VibeStack is a lightweight, full-featured development environment that runs in GitHub Codespaces or any Docker-compatible platform. It provides a complete Linux desktop environment accessible through your web browser, along with pre-installed development tools and an interactive command center.

## 🌟 Features

- **Web-based Linux Desktop**: Full XFCE4 desktop environment accessible via noVNC
- **Interactive Terminal**: Web-based terminal with ttyd integration
- **Development Tools**: Pre-installed with Node.js, Python, Git, and more
- **AI Development**: Claude Code and LLM CLI tools pre-configured
- **Session Manager**: tmux-backed job queue with Streamlit controls
- **Composable Python API**: Import `vibestack.api` to script sessions and templates
- **Streamlit UI**: Web interface with embedded terminal at `/ui/`
- **REST API Gateway**: FastAPI service exposing the Python session manager at `/api/`
- **MCP Session API**: Streamable HTTP transport mirroring the session manager at `/mcp/`
- **Codex persistence hooks**: mount a host directory and set `CODEX_STATE_DIR` to keep tokens across restarts
- **Multi-user Support**: SSH access with configurable passwords

## 🚀 Quick Start

### GitHub Codespaces (Recommended)

1. Click "Code" → "Codespaces" → "Create codespace on main"
2. Wait for the container to build and start
3. Access the desktop at the forwarded URL (port 80)
### Local Docker

```bash
# Clone the repository
git clone https://github.com/yourusername/vibestack.git
cd vibestack

# Standard startup (auto-detects ngrok if running)
./startup.sh follow

# Or set a custom base URL manually
./startup.sh --base-url=https://your-domain.ngrok.app

# Or manually with docker
docker build -t vibestack .
docker run -p 80:80 -p 22:22 \
  -e VIBESTACK_PUBLIC_BASE_URL=https://your-domain.ngrok.app \
  vibestack
```

#### ngrok Integration

Vibestack automatically detects and configures ngrok tunnels when available.

**Prerequisites:**
- `ngrok` installed ([download](https://ngrok.com/download))
- `jq` installed (for JSON parsing)

**Workflow:**

```bash
# Terminal 1: Start ngrok
ngrok http 3000

# Terminal 2: Start Vibestack (auto-detects ngrok URL)
./startup.sh follow

# Or use the helper script
./bin/vibestack-with-ngrok
```

**What happens automatically:**
1. `startup.sh` queries ngrok API at `http://127.0.0.1:4040/api/tunnels`
2. Finds HTTPS tunnel for port 3000
3. Configures all services with detected URL
4. Chrome extension, REST API, MCP endpoints all auto-configure
5. No manual URL configuration needed!

## 🖥️ Accessing VibeStack

### Web Interfaces

- **Desktop Environment**: `http://localhost/` - Full Linux desktop via noVNC
- **Terminal UI**: `http://localhost/ui/` - Streamlit app with embedded terminal
- **Direct Terminal**: `http://localhost/terminal/` - Standalone web terminal
- **REST API**: `http://localhost/api/` - FastAPI-powered HTTP endpoints (see below)
- **MCP Session API**: `http://localhost/mcp/` - Streamable HTTP endpoint for Model Context Protocol clients

### SSH Access

```bash
# Default user
ssh vibe@localhost -p 22
# Password: coding

# Root access (if enabled)
ssh root@localhost -p 22
```

## 🛠️ Pre-installed Tools

> Tip: To persist Codex login state across container restarts, create a `codex/` folder next to this repository and run the container with `-v $(pwd)/codex:/data/codex -e CODEX_STATE_DIR=/data/codex`. The entrypoint will symlink `/home/vibe/.codex` to that directory.

### Development Tools
- **Node.js** (LTS) with npm
- **Python 3** with pip
- **Git** for version control
- **Nano & Vim** text editors

### AI/ML Tools
- **Claude Code** (`claude`) - Anthropic's AI coding assistant
- **OpenCode** (`opencode`) - Open source AI coding agent for the terminal
- **Codex** (`codex`) - OpenAI's Codex CLI
- **LLM CLI** (`llm`) - Command-line interface for language models

### Desktop Applications
- **XFCE4 Terminal** - Modern terminal emulator
- **XFCE4** - Feature-rich desktop environment
- **Thunar** - File manager (included with XFCE4)
- **Falkon** - Lightweight web browser

### Disabling the Menu

To disable the automatic menu on terminal startup:

```bash
export VIBESTACK_NO_MENU=1
```

Or run the menu manually anytime with:

## 🔧 Configuration

### Environment Variables

- `VNC_PASSWORD` - Set VNC password (default: none)
- `ROOT_PASSWORD` - Set root password (default: none)
- `VIBE_PASSWORD` - Set vibe user password (default: "coding")
- `RESOLUTION` - Desktop resolution (default: 1920x1200, optimized for tablets/high-DPI displays)
- `CODEX_STATE_DIR` - Optional path that will be symlinked to `/home/vibe/.codex` for Codex tokens
- `VIBESTACK_PUBLIC_BASE_URL` - Public-facing URL for session links, MCP endpoints, and chrome extension (e.g., `https://example.ngrok.app`)

**Resolution Recommendations:**
- Tablets/iPad Pro: 1920x1200 (default) or 2048x1536 for native resolution
- Desktop: 1920x1080 or 2560x1440
- 4K displays: 3840x2160
- Low bandwidth: 1280x720

### Ports

- **80**: Nginx proxy (desktop, terminal, UI)
- **9000**: FastAPI REST service (internal)
- **22**: SSH server
- **5900**: VNC server (internal)
- **6080**: noVNC web server (internal)
- **7681**: ttyd terminal server (internal)
- **8501**: Streamlit app (internal)
- **9100**: MCP Session API (internal)

## 🏗️ Architecture

VibeStack uses a layered architecture:

1. **Base Layer**: Ubuntu 22.04 with X11 and VNC
2. **Services Layer**: Supervisor manages all services
3. **Proxy Layer**: Nginx routes web traffic
4. **Application Layer**: Desktop, terminal, and web apps

### Service Management

All services are managed by Supervisor. Check status with:

```bash
# Prefer the centralized helper from Python when possible:
python -m vibestack.scripts.supervisor_helper status
```

### REST API

The FastAPI service exposes the `vibestack.api` helpers over HTTP at `/api/`. Interactive docs are available at `/api/docs`. A few common workflows:

```bash
# List sessions
curl http://localhost/api/sessions

# Create a new session
curl -X POST http://localhost/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"name": "demo", "template": "bash"}'

# Tail the last 100 log lines
curl 'http://localhost/api/sessions/demo/log?lines=100'
```

Inside the container the service also listens directly on `http://127.0.0.1:9000`, which bypasses Nginx. For example:

```bash
# Run from within the container shell
curl http://127.0.0.1:9000/api/docs
```

If you need to restart just the API without touching other services, run `python -m vibestack.scripts.supervisor_helper restart vibestack-api`.

Detailed design notes live in `docs/fastapi-rest.md`; endpoint specifics and curl recipes are documented in `docs/fastapi-rest-endpoints.md`.

Need a ready-to-use workspace? Launch a session with the `rest-api-lab` template—it ships with `AGENTS.md` instructions and the endpoint reference preloaded in the session artifacts.

### Complete Container Reference

For a comprehensive guide to the VibeStack container, installed software, folder structure, session management, and MCP integration, see **[VIBESTACK.md](./VIBESTACK.md)**.

## 🧩 Chrome Extension

Vibestack includes a Chrome extension for remote session management via terminal overlay.

### Installation

1. **Access the extension files:**
   ```
   https://your-vibestack-url/extension/
   ```

2. **Download the extension:**
   - Option A: Clone this repository and use the `chrome-extension/` folder
   - Option B: Download files from the `/extension/` endpoint

3. **Load in Chrome:**
   - Open Chrome and navigate to `chrome://extensions/`
   - Enable **Developer mode** (toggle in top-right)
   - Click **Load unpacked**
   - Select the `chrome-extension` directory

4. **Configure (if needed):**
   - Press `Ctrl+~` to open the terminal overlay
   - The extension should auto-detect your Vibestack URL
   - If not, manually enter: `https://your-vibestack-url`
   - Click "Save URL"

### Features

- **Terminal Overlay**: Press `Ctrl+~` on any webpage to access Vibestack sessions
- **Session Management**: Create, list, and switch between sessions
- **Command Execution**: Send commands directly to remote sessions
- **Real-time Logs**: Auto-polling session logs with 1-second refresh
- **Auto-Configuration**: Automatically detects Vibestack API endpoint

### Usage

1. Open terminal overlay with `Ctrl+~`
2. Select or create a session
3. Type commands and press Enter
4. View real-time session output

For detailed documentation, see [`chrome-extension/README.md`](chrome-extension/README.md)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

Before opening changes, review the [Repository Guidelines](AGENTS.md) for structure, testing, and PR expectations.

## 📄 License

This project is open source and available under the MIT License.

## 🐛 Troubleshooting

### Desktop not loading
- Check if services are running: `python -m vibestack.scripts.supervisor_helper status`
- Ensure port 80 is accessible
- Try accessing `/terminal/` directly

### Can't connect via SSH
- Ensure SSH service is running
- Check firewall/port forwarding settings
- Verify password is set correctly
