# Security policy

VibeStack is a single-user private desktop with command execution, file access,
clipboard access, password setup, and graphical remote control. It is intended
to bind to host loopback and be shared only through a trusted private tailnet.
It is not designed for Tailscale Funnel, an unauthenticated public reverse
proxy, or a multi-tenant host.

## Reporting a vulnerability

Please do not publish exploitable details in a GitHub issue. Use the
repository's **Security → Report a vulnerability** flow when available. If
private vulnerability reporting is unavailable, contact the maintainers
through their GitHub profiles and request a private channel without including
the vulnerability details in the initial public message.

Include the affected commit or image, reproduction conditions, expected and
observed behavior, and whether the issue crosses the documented loopback,
tailnet, bearer-token, container, or `vibe`-user boundary. Never include a real
automation token, Linux password, browser profile, or persistent `/data`
archive.

## Supported version

Until versioned releases are published, the latest commit on `main` is the only
supported source version. Security fixes may require rebuilding the image and
replacing the running container; persistent state should remain on the
separate `/data` and `/projects` mounts.

The current trust model, limitations, and validation workflow are documented
in [README.md](README.md), [docs/SPEC.md](docs/SPEC.md), and
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
