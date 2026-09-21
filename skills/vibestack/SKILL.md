---
name: vibestack
description: Operate an explicitly selected VibeStack workspace or Docker-host runner through the vibestack CLI or private remote MCP.
---

# VibeStack agent workflow

Use this skill only for the VibeStack profile named by the user. If no profile
was named and several exist, stop and ask which one; never choose an instance
silently.

1. Run `vibestack --profile NAME doctor`.
2. Run `vibestack --profile NAME capabilities --json` and use only advertised
   operations.
3. Put new durable project work in the default projects root. Use `--desktop`
   only when the user explicitly wants a Desktop file.
4. Prefer argv-based `exec`; use `shell` only when pipes, redirection, or shell
   expansion is intentional. A disconnect does not cancel the job. Do not
   resubmit an uncertain mutation automatically—inspect its job or operation.
5. Retrieve changed files explicitly and report remote request, job, and
   operation IDs when useful.

Never print, read back, copy, or ask for a profile credential, automation token,
Linux password, or private SSH key. `vibestack account` is the password-page
handoff. Public SSH keys may be managed; private keys stay on the customer's
device. Do not install blanket permission bypasses or execution hooks.

Read [CLI reference](references/CLI.md), [workspace automation](references/AUTOMATION.md),
or [runner operations](references/RUNNER.md) when the task uses those surfaces.
A web-fetch tool outside the execution environment may not reach a private
Tailscale URL; run the CLI where the agent session actually executes.

## Shared broker and MCP

Discover `authentication_mode` before connecting. `trusted-tailnet` uses a
persistent shared principal and no pairing/token: every reachable caller can
control all desktops and storage. `paired` retains bearer and owner isolation.
The harness itself needs tailnet connectivity. Never downgrade after auth failure.

For remote MCP, connect Streamable HTTP to the broker's advertised `mcp_url`
(`/mcp`). Call `templates_list`, then `instance_create` with name, approved
template and idempotency_key; poll `operation_get`, then `instance_inspect`.
Use explicit instance_id for workspace_command, workspace_job, workspace_output
and workspace_screenshot. No password tool exists. Hand off urls.password_setup
to the human, or have them use `vibestack --profile NAME instances password ID`
with its hidden confirmation prompt or explicit --password-stdin. Never request
the secret in chat. Create optionally prompts after provisioning; failed credential
setup retains the desktop. Never automatically retry uncertain password changes.

CLI example: `vibestack --profile NAME --instance ID exec -- /usr/bin/pwd`.
Separate infrastructure readiness from password/application onboarding. After
password setup, open urls.desktop for desktop/apps. Tailnet reachability grants
browser access; Linux passwords are independent per desktop and are not web-login
gates. SSH/native VNC remain host-local. Password changes do not synchronize
application logins or keyring encryption. Snapshot clones retain the source hash
but can be reset independently.
