---
name: vibestack
description: Operate an explicitly selected VibeStack workspace or Docker-host runner through the paired vibestack CLI.
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
