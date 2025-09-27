# AGENTS

This workspace is configured for Codex-driven automation. Use this document to capture agent context, constraints, and handoff notes while working inside the session.

## Objective
- Enable single-prompt Codex sessions that can choose MCP servers, update `mcp.json`, and reload with the selected tooling (starting with Playwright).

## Key Constraints
- Edit files from the workspace root; use provided scripts instead of manual JSON edits when possible.
- `mcp.json` in this directory is the source of truth for Codex reloads—overwrite it intentionally with scripted merges.
- Keep presets ASCII and runnable cross-platform (Node.js 18+ expected for Playwright).

## Resources
- `scripts/mcp_configure.py`: merges MCP presets into `mcp.json`; supports `--list`, `--reset`, and emits setup guidance.
- `mcp-presets/`: JSON fragments per MCP server (currently `playwright`).
- Playwright MCP docs: https://github.com/microsoft/playwright-mcp (command `npx @playwright/mcp@latest`).

## Automation Recipe
- When the user asks to enable MCP tooling (e.g., “Enable Playwright MCP and reload”), run `./scripts/mcp_configure.py --reset <servers>` to build a fresh `mcp.json` for that session.
- Surface the script output so the user knows about follow-up install steps (e.g., `npm install -g playwright`, `npx playwright install --with-deps`).
- Confirm the resulting `mcp.json` content with the user, then instruct them (or perform if available) to execute `reload` in the CLI so Codex picks up the new servers.
- For multiple servers, pass each preset name to the script; extend `mcp-presets/` with new files to grow the catalog.

## Progress Log
- 2025-09-20: Added scripted MCP preset workflow and Playwright example preset.

## Open Questions
- Should we cache browser binaries or let Playwright download per session?
- What additional MCP presets do we expect to support next (filesystem, terminal, docs)?
