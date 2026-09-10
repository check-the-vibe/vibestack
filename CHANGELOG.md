# Changelog

This file records notable user-visible changes. VibeStack has not published a
versioned release yet; changes below describe the next release from `main`.

## Unreleased

### Added

- A dependency-free workspace launcher and installable noVNC shell with
  Desktop/Terminal switching, mobile input controls, bounded display resizing,
  service status, logs, and safe restarts.
- First-run onboarding for a user-created Linux password and a durable optional
  application catalog, including Node-based coding agents, browsers, editors,
  native build tools, and a pinned Godot editor.
- A bearer-authenticated automation REST API for commands, screenshots,
  allowlisted applications, window state, arbitrary Desktop files, and the X11
  clipboard, with bounded jobs and correlated audit logging.
- Curated XFCE menus, desktop actions, persistent logs linked from the Desktop,
  and version-matched internal and external agent instructions.
- Explicit `--flatpak` mode with persistent per-user stable Flathub support,
  application discovery, permission review, exported launchers, and guarded
  handlers for downloaded `.flatpakref` files and Flathub `flatpak+https`
  install links.
- A host development helper, disposable image acceptance, desktop/iPad browser
  tests, safe live replacement with rollback, and private Tailscale Serve
  guidance.

### Changed

- Replaced the earlier Streamlit, MCP-session, browser-extension, and split
  image prototype with one smaller Ubuntu 24.04/XFCE runtime and one nginx
  entrypoint.
- Made Chrome the ordinary HTTP/HTTPS handler while preserving ChatGPT's own
  callback scheme so external sign-in opens reliably inside the container.
- Made manual apt installs explicitly ephemeral and catalog installs
  auto-restoring across image replacement.
- Updated the release workflow to current Node 24-based GitHub Actions and made
  disposable acceptance portable across host UIDs, with bounded failure
  diagnostics before one clean CI retry.
- Pinned release acceptance to Ubuntu 24.04 and scoped Noble's unprivileged
  user-namespace relaxation to its ephemeral CI VM so real Flatpak sandbox
  tests can run without weakening normal VibeStack hosts.

### Security

- Kept browser-facing services loopback-only by default with strict Host,
  Origin, fetch-metadata, WebSocket proxy-marker, body-size, and schema checks.
- Added root-private password-hash persistence, fixed `NOPASSWD` helper
  boundaries, safe state-path adoption, bounded redacted logs, atomic Desktop
  file handling, and process-group cleanup for automation jobs.
- Restricted Flatpak web links to exact stable-Flathub appstream URLs, bounded
  HTTPS downloads, matching application IDs, and an interactive final consent
  step; arbitrary remotes and `.flatpakrepo` handlers remain excluded.
