# 🚀 VibeStack

VibeStack is a lightweight, full-featured development environment that runs in GitHub Codespaces or any Docker-compatible platform. It provides a web terminal (tmux via ttyd), a Streamlit UI, pre-installed dev tools, and an interactive command center.

## 🌟 Features

- **Web Terminal**: Browser terminal powered by ttyd + tmux
- **Development Tools**: Pre-installed with Node.js, Python, Git, and more
- **AI Development**: Codex CLI and LLM CLI tools available
- **Interactive Menu**: Custom command center with quick access to development tools
- **Streamlit UI**: Web interface with embedded terminal at `/ui/`
- **Multi-user Support**: SSH access with configurable passwords

## 🚀 Quick Start

### GitHub Codespaces (Recommended)

1. Click "Code" → "Codespaces" → "Create codespace on main"
2. Wait for the container to build and start
3. Open the terminal at the forwarded URL (port 3000)
4. Use the interactive menu or type `vibestack-menu` in any terminal

### Local Docker

```bash
# Clone the repository
git clone https://github.com/yourusername/vibestack.git
cd vibestack

# Build and run with correct ports (3000, 2222, Codex callback)
./scripts/start.sh
```

## 🖥️ Accessing VibeStack

### Web Interfaces

- **Web Terminal**: `http://localhost:3000/` (or `http://localhost:3000/terminal/`) – tmux sessions
- **Streamlit UI**: `http://localhost:3000/ui/`

### SSH Access

```bash
# Default user
ssh vibe@localhost -p 2222
# Password: coding

# Root access (if enabled)
ssh root@localhost -p 22
```

## 🛠️ Pre-installed Tools

### Development Tools
- **Node.js** (LTS) with npm
- **Python 3** with pip
- **Git** for version control
- **Nano & Vim** text editors

### AI/ML Tools
- **Codex CLI** (`codex`) - OpenAI Codex CLI
- **LLM CLI** (`llm`) - Command-line interface for language models

## 📱 Interactive Command Center

When you open a terminal, you'll see the VibeStack interactive menu with options to:

- Launch Claude Code
- Use LLM CLI
- Skip to shell
- Exit menu

### Disabling the Menu

To disable the automatic menu on terminal startup:

```bash
export VIBESTACK_NO_MENU=1
```

Or run the menu manually anytime with:

```bash
vibestack-menu
```

## 🔧 Configuration

### Environment Variables

- `ROOT_PASSWORD` - Set root password (default: none)
- `VIBE_PASSWORD` - Set vibe user password (default: "coding")
- `CODEX_CALLBACK_PORT` - Port used by Codex login callback (default: 1455)
- `VIBESTACK_NO_MENU` - Disable interactive menu (set to 1)

### Ports

- **3000**: Host port mapped to Nginx in container (80)
- **22**: SSH server
- **7681**: ttyd terminal server (internal)
- **8501**: Streamlit app (internal)
- **1455**: Codex login callback (host<->container; configurable). Host `:1455` maps to container `:1456` (nginx), which proxies to `127.0.0.1:1455` inside the container.

### Tmux + Codex via URL
- Attach/create default session: `http://localhost/terminal/`
- Attach/create named session: `http://localhost/terminal/?arg=projectA`
- Create and run Codex with prompt/flags on first load:
  - `http://localhost/terminal/?arg=projectA&arg=Build%20a%20CLI%20tool`
  - Additional flags as more args: `...&arg=--model&arg=gpt-4.1`
  - On first create, tmux runs `codex ...` then drops to a shell; future visits just attach.

### Codex Login Flow
- Start the container: `./scripts/start.sh` (maps CODEX_CALLBACK_PORT from `.env` or defaults to 1455)
- Option A (browser terminal): open `http://localhost:3000/` and run `codex login` (append flags as needed per Codex advanced docs).
- Option B (host shell): run `./scripts/codex-login.sh [flags...]` to execute login inside the container.
- Option C (URL trigger): `http://localhost:3000/terminal/?arg=main&arg=login` runs `codex login` on first session creation.

### Simple Install Walkthrough (Port 3000 + Codex 1455)

1. Clone and enter the repo:
   - `git clone https://github.com/yourusername/vibestack.git && cd vibestack`
2. Create `.env` (optional, recommended):
   - Copy `.env.example` → `.env`
   - Ensure these values (defaults shown):
     - `HOST_HTTP_PORT=3000`
     - `CODEX_CALLBACK_PORT=1455`
     - `VIBE_PASSWORD=coding` (change if desired)
3. Start services:
   - `./scripts/start.sh`
4. Open the web terminal:
   - `http://localhost:3000/` (ttyd + tmux)
5. Log in to Codex:
   - In the terminal, run `codex login` (use flags as needed). The login callback works at `http://localhost:1455` (or your `CODEX_CALLBACK_PORT`). The host port maps to container `:1456` (nginx), which forwards to the loopback server inside the container.
6. Access Streamlit UI:
   - `http://localhost:3000/ui/`
- If a local web callback is used, it’s already forwarded from container to host.

## 🏗️ Architecture

VibeStack uses a layered architecture:

1. **Base Layer**: Ubuntu 22.04 with dev tools (no VNC/desktop, no browsers)
2. **Services Layer**: Supervisor manages ttyd, streamlit, nginx, sshd
3. **Proxy Layer**: Nginx routes web traffic
4. **Application Layer**: Terminal (tmux) and web UI

### Service Management

All services are managed by Supervisor. Check status with:

```bash
sudo supervisorctl status
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is open source and available under the MIT License.

## 🐛 Troubleshooting

### Menu doesn't appear
- Ensure you're in an interactive terminal
- Check if `VIBESTACK_NO_MENU` is set
- Try running `vibestack-menu` manually

### Terminal not loading
- Check if services are running: `sudo supervisorctl status`
- Ensure port 80 is accessible
- Verify ttyd is listening internally on 7681

### Can't connect via SSH
- Ensure SSH service is running
- Check firewall/port forwarding settings
- Verify password is set correctly
