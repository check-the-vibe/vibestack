# VibeStack environment

Read and follow `/usr/share/doc/vibestack/AGENTS.md`. The complete automation
API, authentication, logging, and inside/outside-container examples are in
`/usr/share/doc/vibestack/AUTOMATION.md`. A session executing on a customer's
computer should instead use the paired `vibestack` CLI and an explicitly named
profile. An SSH-hosted session needs its own CLI installation and private
network access; a cloud web-fetch tool may not reach the workspace URL.

VibeStack's live graphical session is X11 display `:0`. Source
`/run/vibestack/session.env` before running a graphical command directly, or
prefer the authenticated automation API for an auditable interaction. Put new
durable work below `/projects`; Desktop is for user-visible handoff files.
Never print or disclose `~/.vibestack/automation.token` or any paired client
credential.

The Linux password is user-created in the agent panel at `/vnc/`, is not retrievable by an
agent, and must never be requested in a command or prompt. Use catalog installs
where possible; leave an interactive sudo prompt for the user otherwise.
For desktop applications outside the catalog, use `vibestack-flatpak` only
when the setup state reports nested-sandbox support; stable Flathub is the
default remote and every third-party install still needs the user's approval.
