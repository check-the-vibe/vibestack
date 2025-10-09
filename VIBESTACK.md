# VibeStack Container Reference

> Complete guide to the VibeStack development environment - architecture, installed software, folder structure, session management, and MCP integration.

## Table of Contents

- [Container Overview](#container-overview)
- [Installed Software](#installed-software)
- [Folder Structure](#folder-structure)
- [Session Management](#session-management)
- [MCP Tools Reference](#mcp-tools-reference)
- [Environment Variables](#environment-variables)
- [Accessing Services](#accessing-services)
- [Working with Sessions](#working-with-sessions)
- [Template Configuration](#template-configuration)
- [Troubleshooting](#troubleshooting)

---

## Container Overview

VibeStack is a Docker-based development environment that provides a complete Linux workspace with AI coding assistants, web-based interfaces, and session management capabilities.

### Container Variants

**Base/Desktop** (`Dockerfile`): Full GUI environment with XFCE4 desktop
- Ubuntu 22.04 base
- XFCE4 desktop via noVNC
- Full Playwright browser automation support
- 1.2GB+ image size

**Core** (`Dockerfile.core`): Headless variant without GUI
- Python 3.10-slim base
- API and terminal services only
- Lightweight for server deployments
- ~500MB image size

**Desktop Enhanced** (`Dockerfile.desktop`): Full GUI with extended tools
- Same as base with additional XFCE4 goodies
- Enhanced browser automation dependencies
- Optimized for visual development workflows

### Default User Configuration

- **User**: `vibe` (UID 1000)
- **Password**: `coding` (configurable via `VIBE_PASSWORD`)
- **Home**: `/home/vibe`
- **Sudo**: Passwordless sudo access enabled
- **Shell**: bash with login configuration

### Process Management

All services run under **Supervisor** (`/etc/supervisor/conf.d/supervisord.conf`):
- Ensures services restart on failure
- Centralized logging to `/var/log/supervisor/`
- Managed via `supervisorctl` or Python helper

---

## Installed Software

### System Utilities

| Tool | Purpose | Location |
|------|---------|----------|
| `tmux` | Terminal multiplexer (session backend) | `/usr/bin/tmux` |
| `git` | Version control | `/usr/bin/git` |
| `jq` | JSON processor | `/usr/bin/jq` |
| `curl` / `wget` | HTTP clients | `/usr/bin/` |
| `nano` / `vim` | Text editors | `/usr/bin/` |
| `nginx` | HTTP proxy/router | `/usr/sbin/nginx` |
| `supervisor` | Process manager | `/usr/bin/supervisord` |
| `ttyd` | Web-based terminal | `/usr/bin/ttyd` |
| `openssh-server` | SSH daemon | `/usr/sbin/sshd` |

### Development Runtimes

**Node.js**
- Version: LTS (20.x+)
- Package manager: npm
- Global packages: `claude`, `codex`, `opencode`, `playwright`

**Python**
- Version: 3.10+ (3.12 on slim base)
- Package manager: pip
- Virtual environments: Supported via `venv`

**VS Code CLI**
- Location: `/opt/vscode-cli/code` → `/usr/local/bin/code`
- Purpose: Remote development tunnels
- Usage: `code tunnel` for VS Code remote access

### AI Coding Assistants

| CLI | Package | Command | Model/Provider |
|-----|---------|---------|----------------|
| **Claude Code** | `@anthropic-ai/claude-code` | `claude` | Anthropic Claude 3.5 Sonnet+ |
| **Codex** | `@openai/codex` | `codex` | OpenAI GPT-5-Codex |
| **OpenCode** | `opencode-ai` | `opencode` | Multi-provider (configurable) |
| **LLM CLI** | `llm` (Python) | `llm` | Pluggable LLM interface |

**Playwright Browser Automation**
- Package: `playwright` (npm global)
- Browsers: Chromium installed with dependencies
- Usage: Automated browser testing, web scraping

### Python Packages

**Web Frameworks:**
- `fastapi` - REST API framework
- `uvicorn[standard]` - ASGI server
- `streamlit` - Web UI framework

**MCP & HTTP:**
- `mcp[cli]` - Model Context Protocol SDK
- `httpx` - Async HTTP client
- `requests` - Sync HTTP client
- `beautifulsoup4` - HTML parsing

**CLI & Terminal:**
- `rich` - Terminal formatting
- `typer` - CLI framework
- `tui` - Terminal UI utilities

### Desktop Applications (Full/Desktop Variants)

- **XFCE4** - Lightweight desktop environment
- **Falkon** - Lightweight web browser
- **xfce4-terminal** - Modern terminal emulator
- **Thunar** - File manager (included with XFCE4)
- **noVNC** - Browser-based VNC client
- **x11vnc** - VNC server for X11

---

## Folder Structure

### Runtime Directory Tree

\`\`\`
/home/vibe/                          # User home directory (VIBESTACK_HOME)
│
├── bin/                              # Helper CLI scripts
│   ├── vibe                          # Session manager CLI → /usr/local/bin/vibe
│   ├── vibestack-code-tunnel         # VS Code tunnel launcher
│   ├── vibestack-ttyd-entry          # ttyd shell wrapper with menu
│   └── vibestack-startup-sessions    # Autostart session handler
│
├── docs/                             # Documentation
│   ├── services/                     # Service-specific guides
│   │   ├── admin-api.md              # REST API documentation
│   │   ├── mcp.md                    # MCP server guide
│   │   ├── novnc.md                  # Desktop access
│   │   ├── streamlit-ui.md           # UI documentation
│   │   ├── ttyd.md                   # Terminal guide
│   │   └── vscode-tunnel.md          # VS Code remote access
│   ├── README.md                     # Main documentation hub
│   ├── repo-layout.md                # Repository structure
│   └── fastapi-rest-endpoints.md     # REST API reference
│
├── streamlit/                        # Streamlit UI application
│   ├── app.py                        # Main entrypoint
│   ├── common.py                     # Shared utilities and helpers
│   ├── onboarding.py                 # First-run wizard
│   └── pages/                        # Feature pages
│       ├── 1_📋_Sessions.py          # Session management UI
│       ├── 2_📚_Docs.py              # Documentation browser
│       ├── 3_⚙️_Templates.py         # Template editor
│       ├── 4_🧑‍💻_Code.py            # Code tunnel integration
│       ├── 5_🛠️_Services.py          # Service status dashboard
│       ├── 6_🖥️_Desktop.py           # Desktop access (if available)
│       └── 7_🧩_MCP.py                # MCP configuration
│
├── vibestack/                        # Python SDK & services
│   ├── __init__.py
│   ├── api.py                        # High-level public API
│   ├── settings.py                   # Configuration management
│   │
│   ├── rest/                         # FastAPI REST service
│   │   ├── __init__.py
│   │   └── app.py                    # REST endpoints
│   │
│   ├── mcp/                          # MCP server
│   │   ├── __init__.py
│   │   └── server.py                 # Streamable HTTP MCP server
│   │
│   ├── sessions/                     # Session manager core
│   │   ├── __init__.py
│   │   ├── cli.py                    # CLI implementation (vibe command)
│   │   ├── manager.py                # Session lifecycle management
│   │   ├── storage.py                # Persistence layer
│   │   ├── models.py                 # Data models
│   │   └── codex_config.py           # Codex MCP integration
│   │
│   ├── templates/                    # Built-in session templates
│   │   ├── bash.json
│   │   ├── codex.json
│   │   ├── claude.json
│   │   ├── opencode.json
│   │   └── script.json
│   │
│   ├── assets/                       # Template artifacts
│   │   └── startup/                  # Startup scripts
│   │       └── supervisor_log_viewer.py
│   │
│   ├── scripts/                      # Utility scripts
│   │   ├── supervisor_helper.py      # Service management
│   │   └── supervisor_tail.py        # Log streaming
│   │
│   └── startup/                      # Startup automation
│       ├── __init__.py
│       ├── run.py
│       └── sessions.py               # Auto-launch sessions
│
├── sessions/                         # Session storage (created at runtime)
│   ├── queue.json                    # Job queue tracking
│   └── <session-name>/               # Per-session directory
│       ├── metadata.json             # Session configuration & state
│       ├── console.log               # Full terminal output capture
│       ├── artifacts/                # Workspace files (working directory)
│       │   ├── AGENTS.md             # Copied from template
│       │   ├── TASKS.md              # Copied from template
│       │   └── ...                   # Other template files
│       ├── run-once.sh               # One-off job script (if applicable)
│       └── result.json               # Exit code & completion data (one-off jobs)
│
├── .codex/                           # Codex CLI state directory
│   ├── config.toml                   # Session-specific or global Codex config
│   └── mcp/                          # Codex MCP server configs (per-session)
│       └── endpoints.json            # MCP server registry
│
├── .config/                          # User configuration
│   ├── xfce4/                        # XFCE4 desktop settings
│   └── github-copilot/               # Copilot MCP config (if using)
│       └── mcp.json
│
├── .vibestack/                       # VibeStack user settings
│   ├── settings.json                 # Persistent configuration
│   ├── templates/                    # User-defined templates
│   └── assets/                       # User template artifacts
│
├── AGENTS.md                         # Agent collaboration guide
├── TASKS.md                          # Task tracking (if exists)
└── xfce-startup                      # XFCE4 desktop startup script

/projects/                            # Optional persistent mount point (host folder via ./startup.sh --projects <path>)
└── vibestack/                        # Repository (if bind-mounted)
    └── ...

/var/log/supervisor/                  # Service logs
├── vibestack-api.log                 # REST API logs
├── vibestack-mcp.log                 # MCP server logs
├── streamlit.log                     # Streamlit UI logs
├── ttyd.log / ttyd.err               # Terminal service logs
├── vscode-tunnel.log                 # VS Code tunnel logs
├── startup-sessions.log              # Autostart session logs
├── xvfb.log                          # Virtual display logs
├── x11vnc.log                        # VNC server logs
├── novnc.log                         # noVNC web client logs
├── xfce4.log                         # Desktop environment logs
├── nginx.log                         # HTTP proxy logs
├── sshd.log                          # SSH daemon logs
└── supervisord.log                   # Supervisor master log

/etc/supervisor/conf.d/
└── supervisord.conf                  # Service definitions

/etc/nginx/
├── nginx.conf                        # HTTP routing configuration
└── conf.d/
    └── codex_callback_upstream.conf  # Codex callback proxy config
\`\`\`

### Key Location Patterns

**Session Data:**
- Default root: `~/sessions/` (`/home/vibe/sessions/`)
- Override: Set `VIBESTACK_SESSION_ROOT` environment variable
- Structure: `<root>/<session-name>/{metadata.json, console.log, artifacts/}`

**Templates:**
- Built-in: `/home/vibe/vibestack/templates/*.json`
- User-defined: `~/.vibestack/templates/*.json`
- Search order: User templates override built-in templates

**Logs:**
- Service logs: `/var/log/supervisor/<service>.log`
- Session logs: `~/sessions/<name>/console.log`
- Nginx access: `/var/log/nginx/access.log`

**Persistent State:**
- Codex tokens: `~/.codex/` (symlink to `CODEX_STATE_DIR` if set)
- VS Code tunnel: `~/.vscode/` (created on first tunnel auth)
- User settings: `~/.vibestack/settings.json`

---

## Session Management

### What is a Session?

A **session** is a tmux-backed workspace that runs a command (shell, script, or AI CLI) and captures all terminal I/O. Sessions can be:
- **Interactive** (long-running CLIs like `codex`, `claude`, `opencode`, `bash`)
- **Non-interactive** (one-off scripts that exit after completion)

### Session Lifecycle

\`\`\`
┌──────────────┐
│   CREATE     │  vibe create <name> --template <template>
│              │  OR: MCP create_session / REST POST /api/sessions
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   RUNNING    │  Session active, accepting input
│              │  - send_input: Queue commands/text
│              │  - tail_log: Monitor output
│              │  - attach: Direct tmux connection
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  STOPPED/    │  Session terminated (manual kill or script exit)
│  COMPLETED   │  Logs and artifacts preserved
└──────────────┘
\`\`\`

### Session Storage Schema

**`~/sessions/<name>/metadata.json`**
\`\`\`json
{
  "schema_version": 2,
  "name": "my-session",
  "command": "codex --model gpt-5-codex",
  "template": "codex",
  "session_type": "long_running",
  "status": "running",
  "created_at": "2025-01-01T12:00:00.000Z",
  "updated_at": "2025-01-01T12:05:30.000Z",
  "log_path": "/home/vibe/sessions/my-session/console.log",
  "workspace_path": "/home/vibe/sessions/my-session/artifacts",
  "description": "Debugging API endpoints",
  "job_id": "abc123...",
  "exit_code": null,
  "last_message": null
}
\`\`\`

**`~/sessions/<name>/console.log`**
- Raw terminal output (ANSI codes preserved)
- Continuously appended via tmux `pipe-pane`
- Read via `tail_log` API or `vibe tail <name>`

**`~/sessions/<name>/artifacts/`**
- Working directory for the session
- Template files copied on creation (AGENTS.md, TASKS.md, etc.)
- Writable by session commands
- Browsable via Streamlit Workspace tab

### Session Types

**`long_running`** - Interactive sessions
- Runs indefinitely until manually killed
- Examples: `bash`, `codex`, `claude`, `opencode`
- Use case: Interactive development, chat with AI assistants

**`one_off`** - Script execution
- Exits automatically after command completes
- Exit code captured in `result.json`
- Use case: Automated tasks, batch jobs, CI/CD scripts

### Session Commands

**Create Session:**
\`\`\`bash
vibe create my-session --template codex --description "Debug API"
\`\`\`

**List Sessions:**
\`\`\`bash
vibe list
# External via Nginx: curl http://localhost:3000/admin/api/sessions
# Internal direct:  curl http://127.0.0.1:9000/api/sessions
\`\`\`

**Attach to Session:**
\`\`\`bash
vibe attach my-session
# Enters tmux session (Ctrl+B, D to detach)
\`\`\`

**Send Input:**
\`\`\`bash
vibe send my-session "ls -la"
# OR: Use MCP send_input tool
# OR: Use Streamlit Terminal tab
\`\`\`

**Tail Logs:**
\`\`\`bash
vibe tail my-session --lines 100
# External via Nginx: curl 'http://localhost:3000/admin/api/sessions/my-session/log?lines=100'
# Internal direct:  curl 'http://127.0.0.1:9000/api/sessions/my-session/log?lines=100'
\`\`\`

**Kill Session:**
\`\`\`bash
vibe kill my-session
# External via Nginx: curl -X DELETE http://localhost:3000/admin/api/sessions/my-session
# Internal direct:  curl -X DELETE http://127.0.0.1:9000/api/sessions/my-session
\`\`\`

### Working Directory Behavior

**Default:** Session's `artifacts/` directory
\`\`\`
working_dir: ~/sessions/<name>/artifacts/
\`\`\`

**Override:** Specify at creation
\`\`\`json
{
  "name": "repo-work",
  "template": "bash",
  "working_dir": "/projects/vibestack"
}
\`\`\`

**Template Default:** Defined in template JSON
\`\`\`json
{
  "name": "my-template",
  "working_dir": "/home/vibe/custom-path"
}
\`\`\`

---

## MCP Tools Reference

The VibeStack MCP server (`/mcp/`) exposes session management as Model Context Protocol tools. Connect via streamable HTTP transport.

### Connection Details

**Endpoint:** `http://localhost/mcp/` (inside container)  
**External:** `http://localhost:3000/mcp` (via docker port mapping)  
**Protocol:** MCP Streamable HTTP  
**Authentication:** None (local/trusted network only)

### Tool Catalog


#### `list_sessions`

**Purpose:** List all known sessions

**Parameters:**
- `session_root` (optional, string) - Override default session storage location

**Returns:** Array of session metadata objects

**Example Request:**
```json
{
  "method": "tools/call",
  "params": {
    "name": "list_sessions",
    "arguments": {}
  }
}
```

**Example Response:**
```json
[
  {
    "name": "codex-debug",
    "template": "codex",
    "status": "running",
    "created_at": "2025-01-01T12:00:00.000Z",
    "session_url": "https://example.com/ui/Sessions?session=codex-debug"
  }
]
```

---

#### `get_session`

**Purpose:** Fetch detailed metadata for a specific session

**Parameters:**
- `name` (required, string) - Session name
- `session_root` (optional, string) - Override session storage

**Returns:** Session metadata object or null if not found

---

#### `create_session`

**Purpose:** Create and launch a new session, optionally with an initial prompt

**Parameters:**
- `name` (required, string) - Unique session identifier
- `template` (optional, string, default: "codex") - Template to use
  - Built-in: `"bash"`, `"codex"`, `"claude"`, `"opencode"`, `"script"`
- `command` (optional, string) - Override template command
- `command_args` (optional, array) - Additional command arguments
- `working_dir` (optional, string) - Starting directory path
- `description` (optional, string) - Human-readable session purpose
- `prompt` (optional, string) - **Initial prompt sent after CLI initialization**
- `session_root` (optional, string) - Override session storage location

**Returns:** Session metadata with `session_url`

**Prompt Behavior:**
- If `prompt` is provided, the system waits for CLI startup (configured in template via `prompt_delay_ms`)
- **Codex:** 3 second delay before sending prompt
- **Claude:** 2.5 second delay
- **OpenCode:** 2 second delay
- Prompt is sent with Enter key press automatically
- Session remains interactive after prompt delivery

**Example - Create Codex session with prompt:**
```json
{
  "name": "create_session",
  "arguments": {
    "name": "api-debug-20250101",
    "template": "codex",
    "prompt": "Help me debug the FastAPI /sessions endpoint that's returning 500 errors. Start by examining /home/vibe/vibestack/rest/app.py",
    "working_dir": "/home/vibe/vibestack",
    "description": "Debugging REST API endpoints"
  }
}
```

---

#### `send_input`

**Purpose:** Send text or commands to a running session's terminal

**Parameters:**
- `name` (required, string) - Session name
- `text` (required, string) - Text/command to send
- `enter` (optional, boolean/string, default: true) - Press Enter after text
  - Accepts: `true`, `false`, `"press"`, `"enter"`, `"return"`, `"skip"`
- `session_root` (optional, string) - Override session storage

**Returns:** Confirmation message

**Example:**
```json
{
  "name": "send_input",
  "arguments": {
    "name": "my-session",
    "text": "ls -la",
    "enter": true
  }
}
```

---

#### `tail_log`

**Purpose:** Retrieve recent terminal output from a session

**Parameters:**
- `name` (required, string) - Session name
- `lines` (optional, integer, default: 200, range: 1-2000) - Number of log lines
- `session_root` (optional, string) - Override session storage

**Returns:** Object with `log` field containing output string

---

#### `kill_session`

**Purpose:** Terminate a running session

**Parameters:**
- `name` (required, string) - Session name
- `session_root` (optional, string) - Override session storage

**Returns:** Confirmation message

**Effect:**
- Kills the tmux session
- Sets status to "stopped"
- Preserves logs and artifacts
- Session can be recreated with same name

---

#### `list_jobs`

**Purpose:** List queued one-off jobs (session type: "one_off")

**Parameters:**
- `session_root` (optional, string) - Override session storage

**Returns:** Array of job records with status tracking

---

#### `enqueue_one_off`

**Purpose:** Queue a one-off command (script that exits after completion)

**Parameters:**
- `name` (required, string) - Job identifier (used as session name)
- `command` (required, string) - Command to execute
- `template` (optional, string, default: "script") - Template to use
- `description` (optional, string) - Job description
- `session_root` (optional, string) - Override session storage

**Returns:** Session metadata

---

#### `get_session_url`

**Purpose:** Get the Streamlit UI URL for a session (for sharing/linking)

**Parameters:**
- `name` (required, string) - Session name
- `session_root` (optional, string) - Override session storage

**Returns:** Object with `session_url` field

---

#### `list_templates`

**Purpose:** List available session templates

**Parameters:** None

**Returns:** Array of template configurations

---

#### `save_template`

**Purpose:** Persist a new template definition to user template directory

**Parameters:**
- `payload` (required, object) - Template JSON configuration
- `include_sources` (optional, array of strings) - File paths to include

**Returns:** Object with `path` field pointing to saved template

---

#### `delete_template`

**Purpose:** Remove a user-defined template (built-in templates cannot be deleted)

**Parameters:**
- `name` (required, string) - Template name

**Returns:** Confirmation message

---

### MCP Workflow Examples

**Workflow 1: Debug with Codex**
```
1. create_session(name="debug-api", template="codex", prompt="Review the REST API logs")
2. tail_log(name="debug-api", lines=100)
3. send_input(name="debug-api", text="Show me the error in app.py line 145")
4. get_session_url(name="debug-api")
5. kill_session(name="debug-api")
```

**Workflow 2: Batch Processing**
```
1. enqueue_one_off(name="process-logs", command="python process_logs.py")
2. list_jobs()
3. tail_log(name="process-logs")
```

---

## Environment Variables

### Core Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `VIBESTACK_HOME` | `/home/vibe` | Home directory and Python package root |
| `VIBESTACK_SESSION_ROOT` | `~/sessions` | Session storage location |
| `VIBESTACK_NO_MENU` | (unset) | Set to `1` to disable terminal startup menu |
| `PYTHONPATH` | `$VIBESTACK_HOME` | Python module search path |

### User Authentication

| Variable | Default | Purpose |
|----------|---------|---------|
| `VIBE_PASSWORD` | `coding` | Password for `vibe` user |
| `ROOT_PASSWORD` | `root` | Password for root user |

### Service Ports (Internal)

| Variable | Default | Service |
|----------|---------|---------|
| `VIBESTACK_MCP_PORT` | `9100` | MCP server |
| `CODEX_CALLBACK_PORT` | `1455` | Codex OAuth callback |
| `NOVNC_PORT` | `6080` | noVNC web interface |
| `VNC_PORT` | `5900` | VNC server |

### Display Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `DISPLAY` | `:0` | X11 display number |
| `RESOLUTION` | `1920x1200` | Desktop resolution (WIDTHxHEIGHT) |

**Resolution Recommendations:**
- Tablets/iPad Pro: `1920x1200` (default) or `2048x1536`
- Desktop: `1920x1080` or `2560x1440`
- 4K displays: `3840x2160`
- Low bandwidth: `1280x720`

### Persistence

| Variable | Default | Purpose |
|----------|---------|---------|
| `CODEX_STATE_DIR` | (unset) | Path symlinked to `~/.codex` for token persistence |

**Example:** Mount host directory for Codex state
```bash
docker run -v $(pwd)/codex-data:/data/codex \
           -e CODEX_STATE_DIR=/data/codex \
           vibestack
```

### MCP Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `VIBESTACK_MCP_DEFAULT_TEMPLATE` | `codex` | Default template for MCP create_session |
| `VIBESTACK_SESSION_FOLLOW_BASE` | (unset) | Override base URL for session links |
| `VIBESTACK_MCP_ALLOW_ORIGINS` | `*` | CORS allowed origins (comma-separated) |

---

## Accessing Services

### External Access (via Nginx on Port 80)

| Path | Service | Description |
|------|---------|-------------|
| `/` | ttyd terminal | Web-based terminal interface |
| `/ui/` | Streamlit | Session management UI |
| `/terminal/` | ttyd terminal | Direct terminal access |
| `/admin/api/` | FastAPI REST | REST API endpoints |
| `/admin/docs` | Swagger UI | Interactive API documentation |
| `/mcp` and `/mcp/` | MCP server | Model Context Protocol endpoint |
| `/computer/` | noVNC | Desktop environment (full/desktop variants) |
| `/services/3000-3004/` | Dev proxy | HTTP passthrough for dev servers |

### Internal Service Ports

| Port | Service | Usage |
|------|---------|-------|
| `9000` | FastAPI | `http://127.0.0.1:9000/api/` (bypasses Nginx) |
| `8501` | Streamlit | `http://localhost:8501/` (direct access) |
| `9100` | MCP server | `http://127.0.0.1:9100/` (direct access) |
| `7681` | ttyd | `http://localhost:7681/` (web terminal) |
| `6080` | noVNC | `http://localhost:6080/vnc.html` (desktop) |
| `5900` | VNC | VNC protocol (use VNC client) |
| `22` | SSH | `ssh vibe@localhost -p 22` |

### SSH Access

```bash
# Connect as vibe user
ssh vibe@<host> -p 22
# Password: coding (or $VIBE_PASSWORD)
```

---

## Working with Sessions

### Best Practices

1. **Use Descriptive Session Names** - `api-debug-20250101` not `test`
2. **Leverage Templates** - Use pre-configured environments
3. **Set Working Directories** - Start sessions in the right context
4. **Include Context in Prompts** - Provide file paths and error details
5. **Monitor Sessions Regularly** - Use `tail_log` before sending more input
6. **Clean Up Finished Sessions** - Kill sessions to free resources

### Persistence Strategies

**Session Artifacts:** Files in `~/sessions/<name>/artifacts/` persist until session deleted

**Codex State:** Mount volume to preserve login tokens
```bash
docker run -v $(pwd)/codex-data:/data/codex -e CODEX_STATE_DIR=/data/codex vibestack
```

**Project Workspace:** Mount your project directory
```bash
docker run -v $(pwd)/my-project:/projects/my-project vibestack
```

---

## Template Configuration

### Template Schema

```json
{
  "name": "my-template",
  "label": "My Custom Template",
  "command": "bash",
  "command_args": ["--login"],
  "session_type": "long_running",
  "prompt_delay_ms": 2000,
  "working_dir": "/home/vibe",
  "description": "Custom environment",
  "env": {
    "MY_VAR": "value"
  },
  "include_files": [
    {"source": "AGENTS.md", "target": "AGENTS.md"}
  ]
}
```

### Key Fields

- `prompt_delay_ms`: Wait time before sending initial prompt (CLI startup)
- `session_type`: `"long_running"` or `"one_off"`
- `include_files`: Files copied to session artifacts/ on creation

**Built-in Prompt Delays:**
- Codex: 3000ms, Claude: 2500ms, OpenCode: 2000ms, Bash: 0ms

---

## Troubleshooting

### Service Management

**Check Service Status:**
```bash
python -m vibestack.scripts.supervisor_helper status
```

**View Service Logs:**
```bash
tail -f /var/log/supervisor/vibestack-mcp.log
```

**Restart a Service:**
```bash
python -m vibestack.scripts.supervisor_helper restart vibestack-api
```

### Common Issues

**Session Not Appearing:**
- Check tmux: `tmux list-sessions`
- Check metadata: `cat ~/sessions/<name>/metadata.json`
- Check logs: `tail -f /var/log/supervisor/vibestack-api.log`

**Prompt Not Delivered:**
- Increase `prompt_delay_ms` in template (try 3000ms+)
- Check session log: `tail ~/sessions/<name>/console.log`
- Manually send prompt via `send_input`

**Session Exits Immediately:**
- Check logs: `cat ~/sessions/<name>/console.log`
- Verify command exists: `which codex`
- Test manually: `bash -c "<command>"`

**Codex State Lost:**
- Mount persistent volume with `CODEX_STATE_DIR`
- Verify symlink: `ls -la ~/.codex`

**MCP Connection Fails:**
- Check service: `python -m vibestack.scripts.supervisor_helper status vibestack-mcp`
- Test endpoint: `curl http://localhost/mcp/`
- Check logs: `tail -f /var/log/supervisor/vibestack-mcp.log`

---

## Appendix: Quick Reference

### Command Cheat Sheet

```bash
# Session Management
vibe list                           # List all sessions
vibe create NAME --template TMPL    # Create session
vibe attach NAME                    # Attach to session
vibe tail NAME                      # View logs
vibe kill NAME                      # Terminate session

# Service Management
python -m vibestack.scripts.supervisor_helper status
python -m vibestack.scripts.supervisor_helper restart SERVICE

# Logs
tail -f /var/log/supervisor/vibestack-mcp.log
tail -f ~/sessions/NAME/console.log
```

### REST API Quick Reference

```bash
# List sessions
# External via Nginx
curl http://localhost:3000/admin/api/sessions
# Internal direct
curl http://127.0.0.1:9000/api/sessions

# Create session
# External via Nginx
curl -X POST http://localhost:3000/admin/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"name":"test","template":"bash"}'
# Internal direct
curl -X POST http://127.0.0.1:9000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"name":"test","template":"bash"}'

# Send input
# External via Nginx
curl -X POST http://localhost:3000/admin/api/sessions/test/input \
  -H 'Content-Type: application/json' \
  -d '{"text":"ls -la","enter":true}'
# Internal direct
curl -X POST http://127.0.0.1:9000/api/sessions/test/input \
  -H 'Content-Type: application/json' \
  -d '{"text":"ls -la","enter":true}'

# Tail log
# External via Nginx
curl 'http://localhost:3000/admin/api/sessions/test/log?lines=100'
# Internal direct
curl 'http://127.0.0.1:9000/api/sessions/test/log?lines=100'

# Kill session
# External via Nginx
curl -X DELETE http://localhost:3000/admin/api/sessions/test
# Internal direct
curl -X DELETE http://127.0.0.1:9000/api/sessions/test
```

### File Locations

| Path | Contents |
|------|----------|
| `/home/vibe/sessions/` | Session storage |
| `/home/vibe/vibestack/templates/` | Built-in templates |
| `/var/log/supervisor/` | Service logs |
| `/home/vibe/.codex/` | Codex CLI state |

---

**End of VibeStack Container Reference**

*For updates, visit the repository or check `/home/vibe/docs/README.md`.*
