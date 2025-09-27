# Launching Sessions with `vibestack-sessions`

Use the VibeStack CLI to spin up repeatable tmux workspaces from templates and attach to them for interactive work. This guide walks through the typical flow and highlights optional variations for local shells and ttyd.

## Prerequisites
- VibeStack environment is running (supervisor has `sessions` service online).
- Desired template is present in the catalog (`vibestack/templates/` or `~/.vibestack/templates/`).
- You have shell access either via local terminal (`tmux attach`) or ttyd (`/terminal/`).

## 1. Inspect available templates
```bash
vibestack-sessions list | jq '.[].name'
```
List all templates and pick the one you want. Add `| jq '.'` to view full metadata including default command and description.

## 2. Launch a session from a template
```bash
SESSION_NAME="docs-refresh"
TEMPLATE_NAME="codex"
vibestack-sessions create "${SESSION_NAME}" --template "${TEMPLATE_NAME}" \
  --description "Docs refresh run"
```
- `--template` selects the template key.
- `--description` is optional but surfaces in Streamlit/REST clients.
- Add `--command` or `--workdir` to override template defaults for one-off experiments.

The command prints JSON metadata with the workspace path, tmux session name, and status fields. The workspace lives under `/home/vibe/sessions/<SESSION_NAME>/workspace`.

## 3. Verify the session
```bash
vibestack-sessions show "${SESSION_NAME}" | jq '.status, .workspace_path'
```
Confirm the session is `running` and note the workspace directory. Use `vibestack-sessions logs "$SESSION_NAME" --lines 50` if you need to tail startup output.

## 4. Attach for interactive work
Choose the option that matches how you are connecting:

1. **Local shell (recommended):**
   ```bash
   tmux attach -t "${SESSION_NAME}"
   ```
   Detach with `Ctrl-b d` when finished; the session stays active.

2. **Browser terminal (ttyd):**
   ```bash
   vibestack-ttyd-entry session "${SESSION_NAME}"
   ```
   This wrapper ensures ttyd attaches with the correct environment when you run it via `/terminal/`.

3. **Create-and-attach in one step (ttyd helpers):**
   ```bash
   vibestack-ttyd-entry create "${TEMPLATE_NAME}" "${SESSION_NAME}"
   ```
   Useful when you are already in a ttyd shell and want to bootstrap + attach without switching contexts.

## 5. Wrap up
- Detach (`Ctrl-b d`) to leave the session running for Streamlit or collaborators.
- Send quick commands without attaching via `vibestack-sessions send "${SESSION_NAME}" "ls"`.
- Terminate the session explicitly with `vibestack-sessions kill "${SESSION_NAME}"` when the workspace is no longer needed.

## Troubleshooting
- `session 'NAME' not found`: confirm you typed the session name exactly as created; use `vibestack-sessions list` to double-check.
- No templates visible: ensure `vibestack-sessions list` shows built-in templates. If not, restart the supervisor-managed services or inspect `docs/services/` for debugging steps.
- `tmux attach` hangs: the session might have exited. Run `vibestack-sessions show NAME` and inspect the `status` and `exit_code` fields.
