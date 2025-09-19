# 🚀 VibeStack

VibeStack is a lightweight, full-featured development environment that runs in GitHub Codespaces or any Docker-compatible platform. It provides a complete Linux desktop environment accessible through your web browser, along with pre-installed development tools and an interactive command center.

## 🌟 Features

- **Web-based Linux Desktop**: Full Fluxbox desktop environment accessible via noVNC
- **Interactive Terminal**: Web-based terminal with ttyd integration
- **Development Tools**: Pre-installed with Node.js, Python, Git, and more
- **AI Development**: Claude Code and LLM CLI tools pre-configured
- **Session Manager**: tmux-backed job queue with Streamlit controls
- **Composable Python API**: Import `vibestack.api` to script sessions and templates
- **Streamlit UI**: Web interface with embedded terminal at `/ui/`
- **REST API Gateway**: FastAPI service exposing the Python session manager at `/api/`
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

# Build and run
docker build -t vibestack .
docker run -p 80:80 -p 22:22 vibestack
```

## 🖥️ Accessing VibeStack

### Web Interfaces

- **Desktop Environment**: `http://localhost/` - Full Linux desktop via noVNC
- **Terminal UI**: `http://localhost/ui/` - Streamlit app with embedded terminal
- **Direct Terminal**: `http://localhost/terminal/` - Standalone web terminal
- **REST API**: `http://localhost/api/` - FastAPI-powered HTTP endpoints (see below)

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
- **LLM CLI** (`llm`) - Command-line interface for language models
- **Playwright MCP** - Browser automation server

### Desktop Applications
- **XTerm** - Terminal emulator
- **Fluxbox** - Lightweight window manager

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
- `RESOLUTION` - Desktop resolution (default: 1280x720)
- `CODEX_STATE_DIR` - Optional path that will be symlinked to `/home/vibe/.codex` for Codex tokens

### Ports

- **80**: Nginx proxy (desktop, terminal, UI)
- **9000**: FastAPI REST service (internal)
- **22**: SSH server
- **5900**: VNC server (internal)
- **6080**: noVNC web server (internal)
- **7681**: ttyd terminal server (internal)
- **7777**: Playwright MCP server (internal)
- **8501**: Streamlit app (internal)

## 🏗️ Architecture

VibeStack uses a layered architecture:

1. **Base Layer**: Ubuntu 22.04 with X11 and VNC
2. **Services Layer**: Supervisor manages all services
3. **Proxy Layer**: Nginx routes web traffic
4. **Application Layer**: Desktop, terminal, and web apps

### Service Management

All services are managed by Supervisor. Check status with:

```bash
sudo supervisorctl status
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

If you need to restart just the API without touching other services, run `sudo supervisorctl restart vibestack-api`.

Detailed design notes live in `docs/fastapi-rest.md`; endpoint specifics and curl recipes are documented in `docs/fastapi-rest-endpoints.md`.

Need a ready-to-use workspace? Launch a session with the `rest-api-lab` template—it ships with `AGENTS.md` instructions and the endpoint reference preloaded in the session artifacts.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is open source and available under the MIT License.

## 🐛 Troubleshooting

### Desktop not loading
- Check if services are running: `sudo supervisorctl status`
- Ensure port 80 is accessible
- Try accessing `/terminal/` directly

### Can't connect via SSH
- Ensure SSH service is running
- Check firewall/port forwarding settings
- Verify password is set correctly
