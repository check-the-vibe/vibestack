# Codex MCP Server Configuration

This guide documents how we manage Model Context Protocol (MCP) servers for Codex-driven sessions. Codex stores its runtime settings in `config.toml` under `CODEX_HOME` (default `~/.codex`). We scope that directory to each session workspace so configs stay isolated and reproducible.

- The session manager places `CODEX_HOME` at `<workspace>/.codex` for Codex templates.
- `config.toml` is generated on demand by `vibestack.sessions.codex_config.CodexConfigManager`.
- Entries live under `[mcp_servers.<name>]` following the [Codex config specification](https://github.com/openai/codex/blob/main/docs/config.md#mcp_servers).

## Default Playwright Server

`ensure-defaults` creates `config.toml` and guarantees the Playwright MCP server is present with STDIO transport:

```toml
[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest", "--browser", "chromium"]
```

The `--browser chromium` flag aligns with the Chromium bundle installed by our Docker image (`npx playwright install --with-deps chromium`). If you update the base image to install a different browser, pass `--playwright-browser <name>` to regenerate the defaults.

## Managing Servers via CLI

Use the helper module inside the repository to add, list, or remove servers. All commands operate on the current `CODEX_HOME` (and accept `--home` to override):

```bash
# Ensure default presets (runs automatically when Codex sessions are created)
python -m vibestack.sessions.codex_config ensure-defaults

# Add another MCP server named "docs" that launches over STDIO
python -m vibestack.sessions.codex_config add docs -- my-docs-server --flag value

# Include environment variables or timeouts as needed
python -m vibestack.sessions.codex_config add search-bot -- ./search-mcp \
  --port 4000 \
  --env API_TOKEN=example \
  --startup-timeout 20

# Inspect configured servers
python -m vibestack.sessions.codex_config list

# Remove a server you no longer need
python -m vibestack.sessions.codex_config remove docs
```

- Separate CLI options from the server command with `--`; everything after the sentinel is passed to the STDIO launcher.
- Provide additional launcher arguments in-line after the command (for example `-- ./server --flag value`).
- MCP servers rely on STDIO by default; no additional transport flags are required unless the server supports HTTP through a proxy.

## Implementation Notes

- Source of truth: `<workspace>/.codex/mcp_servers.json` (generated alongside `config.toml`).
- The CLI refuses malformed `KEY=VALUE` pairs for the `--env` option to avoid invalid TOML.
- All outputs are deterministically ordered so diffs stay compact.
- Avoid editing `config.toml` manually—regenerate it via the helper to keep the JSON and TOML views in sync.
- Adjust the Streamlit link base (used by `session_url`) from the **MCP** Streamlit page; this writes to `~/.vibestack/settings.json` and keeps Codex, Streamlit, and MCP aligned.

Consider updating `TASKS.md` when new servers require manual provisioning (credentials, REST endpoints, etc.) so future Codex sessions stay reproducible.
