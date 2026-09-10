# Claude Code project memory

Read and follow `AGENTS.md` in this directory before making changes. It is the
canonical repository instruction file for every coding agent. The complete
host development, disposable acceptance, rollout, Tailscale Serve, and
debugging workflow is in `docs/DEVELOPMENT.md`.

VibeStack itself is the system under development, not a generic host. Commands
that inspect or operate its graphical session must run as the container's
`vibe` user after sourcing `/run/vibestack/session.env`. Preserve the private
loopback-plus-Tailscale deployment boundary and the existing persistent
mounts. Read `docs/AUTOMATION.md` before changing or using the privileged
automation surface.

There is no default `vibe` password. Users create it through `/setup/`; never
place a password in source, environment variables, commands, logs, or prompts.
Normal sudo is password-authenticated, while the fixed VibeStack setup helpers
remain non-interactive for catalog installation and recovery.
