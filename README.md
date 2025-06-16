# 🚀 VibeStack

VibeStack is a lightweight, full-featured development environment that runs in GitHub Codespaces or any Docker-compatible platform. It provides a complete Linux desktop environment accessible through your web browser, along with pre-installed development tools and an interactive command center.

## 🌟 Features

- **Web-based Linux Desktop**: Full Fluxbox desktop environment accessible via noVNC
- **Interactive Terminal**: Web-based terminal with ttyd integration
- **Development Tools**: Pre-installed with Node.js, Python, Git, and more
- **AI Development**: Claude Code and LLM CLI tools pre-configured
- **Interactive Menu**: Custom command center with quick access to development tools
- **Streamlit UI**: Web interface with embedded terminal at `/ui/`
- **Multi-user Support**: SSH access with configurable passwords

## 🚀 Quick Start

### GitHub Codespaces (Recommended)

1. Click "Code" → "Codespaces" → "Create codespace on main"
2. Wait for the container to build and start
3. Access the desktop at the forwarded URL (port 80)
4. Use the interactive menu or type `vibestack-menu` in any terminal

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

### SSH Access

```bash
# Default user
ssh vibe@localhost -p 22
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
- **Claude Code** (`claude`) - Anthropic's AI coding assistant
- **LLM CLI** (`llm`) - Command-line interface for language models
- **Playwright MCP** - Browser automation server

### Desktop Applications
- **XTerm** - Terminal emulator
- **Fluxbox** - Lightweight window manager

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

- `VNC_PASSWORD` - Set VNC password (default: none)
- `ROOT_PASSWORD` - Set root password (default: none)
- `VIBE_PASSWORD` - Set vibe user password (default: "coding")
- `RESOLUTION` - Desktop resolution (default: 1280x720)
- `VIBESTACK_NO_MENU` - Disable interactive menu (set to 1)

### Ports

- **80**: Nginx proxy (desktop, terminal, UI)
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

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is open source and available under the MIT License.

## 🐛 Troubleshooting

### Menu doesn't appear
- Ensure you're in an interactive terminal
- Check if `VIBESTACK_NO_MENU` is set
- Try running `vibestack-menu` manually

### Desktop not loading
- Check if services are running: `sudo supervisorctl status`
- Ensure port 80 is accessible
- Try accessing `/terminal/` directly

### Can't connect via SSH
- Ensure SSH service is running
- Check firewall/port forwarding settings
- Verify password is set correctly