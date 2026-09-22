# Desktop shell and service boundary

The current UI contract is [agent overlay](agent-overlay.md); provider lifecycle
and native protocols are defined in [provider runtimes](provider-runtimes.md).
The shell is dependency-free JavaScript/CSS around noVNC's public RFB class.

`/` opens `/vnc/`: one desktop canvas, one agent icon and a nonmodal setup/chat
panel. There are no old navigation tabs, Apps/Settings drawers, wizard pages or
embedded terminal/editor frames. The Linux XFCE desktop and its native terminal,
apps, menus and provider sign-in windows remain working content beneath the shell.
Code editing is available through the outer Codespaces editor or Remote SSH.

| Surface | Boundary |
| --- | --- |
| `/vnc/`, `/vnc/websockify` | Private origin, Host/Origin checks and nginx-only raw transport marker |
| `/api/*`, `/setup/api/*`, `/mcp`, `/auth/*` | One Go workspace service; shared authentication, grants, schema limits and browser CSRF |
| `/setup/`, `/terminal/`, `/editor/` | Safe bookmark redirects to `/vnc/`; queries dropped; mutations rejected |
| Retired UI assets and terminal/editor WebSockets | 404; no installed ttyd/code-server services |
| `/AGENTS.md`, `/cli.sh`, other published docs/files | Explicit static publish surface; no repository/data traversal |

Supervisor retains D-Bus, Xvfb, x11vnc, websockify, XFCE, private setup/control/
automation, the workspace service and nginx. SSH and native VNC retain their
existing lifecycle and Linux-password boundary. Logical service IDs are desktop,
vnc, setup, ssh and native-vnc. Ports 7681/8443 have no managed listeners.

Default rendering uses quality 7/compression 2, viewport scaling and
`resizeSession=false`. Unexpected disconnects after an established session have
bounded reconnect attempts; security/identity failures require explicit human
recovery. The panel does not capture input outside its bounds. Credentials and
provider content never enter browser storage or shared diagnostics.

The image fingerprints the complete shell/noVNC static graph for its service
worker. API/auth/MCP/WebSocket responses are never cached. Old navigation code is
removed from both the image and precache. A browser holding an earlier worker
must close old tabs/reload to activate the new generation after upgrade.

No migration deletes persistent data. Native provider auth/history uses its
existing mappings. Saved catalog selections restore through the setup service;
provider process selection restores through the workspace service. Restoration
never resubmits prompts or approvals. Previous code-server config/data remains
under `/data` for explicit image rollback. Keep exact mounts and source ownership.
See [development acceptance](../DEVELOPMENT.md) and the
[user runthrough](../../.context/runthrough.md) for evidence and pending live checks.
