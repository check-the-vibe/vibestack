# VibeStack repository instructions

VibeStack is a single-user, Docker-hosted Ubuntu/XFCE desktop for coding agents.
The browser-facing entrypoint is nginx on container port 80. It routes the
custom noVNC shell, ttyd terminal, setup wizard, and versioned control API. A
separate bearer-authenticated automation API has the full command authority of
the `vibe` account.

Read `docs/DEVELOPMENT.md` before changing or deploying the project, and update
that guide plus `README.md` and `docs/SPEC.md` whenever a command, route, port,
runtime path, dependency, security boundary, or operator workflow changes.

For the next API/MCP phase, read
[`docs/architecture/agent-access-redesign.md`](docs/architecture/agent-access-redesign.md).
It is a proposal: distinguish existing interfaces from planned adapters.

## Source map

For GitHub Codespaces work, first read
[`.context/github-codespaces.md`](.context/github-codespaces.md). It defines the
4-core/16-GB minimum, automatic desktop lifecycle, private forwarded-port boundary,
persistent paths, shared source mount, and the checks that require a real Codespace. Keep it aligned
with `.devcontainer/`; never infer private visibility from a port label.

- `Dockerfile`, `entrypoint.sh`, `supervisord.conf`, `nginx.conf`: image and
  long-running service topology.
- `desktop/`: dependency-free browser shell using upstream noVNC RFB modules.
- `control/`: Python standard-library API and its OS-facing backend.
- `automation/`: privileged REST API, Desktop file boundary, and job runner.
- `desktop-config/`: curated XFCE menu and fixed desktop actions.
- `runtime/`: default global guidance seeded for in-container coding agents.
- `setup/`: setup wizard and catalog state.
- `bin/`: in-image helpers plus the host-only `vibestack-dev` workflow helper.
- `xfce-startup`: X11, D-Bus, keyring, display-mode, and XFCE session setup.
- `tests/`: Python contract/unit tests and Playwright browser tests.
- `docs/architecture/`, `docs/research/`: design contracts and evidence.

## Required workflow

1. Inspect `git status --short`; this repository may contain intentional
   in-progress changes. Never discard or overwrite unrelated work.
2. Run `bin/vibestack-dev test` before and after source changes.
3. Build a tagged candidate with `bin/vibestack-dev build vibestack:<tag>`.
4. Validate it without touching the live container using
   `bin/vibestack-dev accept vibestack:<tag>`.
5. Only replace the live `vibestack` container after the candidate passes.
   Reuse the existing `/data` and `/projects` mounts; inspect them first.
6. Run `bin/vibestack-dev check` and the Tailscale HTTPS browser path after
   deployment. Record any physical-device-only verification explicitly.

The live service normally binds to host loopback port 8080 and is shared
privately with Tailscale Serve. Do not change it to `0.0.0.0`, use Funnel, or
publish it to the public internet without explicit authorization. The
terminal, setup, desktop stream, and narrow control API rely on that private
network boundary. Automation additionally requires its persistent bearer
token. The setup surface can set or replace `vibe`'s Linux password without the
old value; ordinary sudo is password-authenticated, while only the three fixed
VibeStack helpers are `NOPASSWD`.

## Implementation rules

- Target Ubuntu 24.04 and Python 3.12 from the image; use only the Python
  standard library in the setup/control services unless the image contract is
  deliberately changed.
- Keep browser/HTTP input out of shell strings. Prefer fixed executable paths,
  argv arrays, strict schemas, bounded bodies/output, timeouts, and explicit
  allowlists or scoped roots.
- Run desktop commands as `vibe` after sourcing
  `/run/vibestack/session.env`; it provides `DISPLAY=:0`, Xauthority, D-Bus,
  keyring, and the established XDG runtime directory.
- Preserve the loopback nginx boundary and same-origin checks. Treat any new
  automation endpoint as privileged remote code execution and document its
  trust model before exposing it.
- Never recursively change ownership of `/data`; `/data/projects` may be a
  host source tree with ownership that must remain unchanged.
- Keep logs and API responses bounded. Avoid credentials, clipboard/file
  contents, command text/output, and request bodies in shared logs; render
  remote text with text-safe DOM APIs. The canonical persistent log tree is
  `/data/logs/vibestack`.
- Never add a default password or pass one through an environment variable,
  argv, log, agent prompt, or source fixture. The user sets it through the
  same-origin setup body; only the root-private hash below
  `/data/.vibestack-auth-v1` may persist. Live validation is status-only.
- Keep the shell dependency-free and use only public noVNC APIs. Do not expose
  upstream `vnc.html` or enable noVNC `resizeSession` without revisiting the
  architecture contract.
- Keep `/usr/share/doc/vibestack/AGENTS.md`, the root `/AGENTS.md` HTTP route,
  and `docs/AUTOMATION.md` aligned whenever the web, menu, automation, logging,
  package-install, or persistence contract changes. Default local-agent files
  should link to the immutable packaged guide so new images cannot leave stale
  instructions in persistent state; never replace an existing user override.
- Flatpak support is an explicit runtime policy, not a base-container default.
  Stable Flathub is the only automatically configured remote. The setup
  catalog and privileged installer must require the fresh root-owned marker at
  `/run/vibestack/host/flatpak-enabled`; an environment variable alone is not
  authority. Keep the default launcher confined, and keep `--flatpak` free of
  `--privileged` and added Linux capabilities.

## Validation

Fast checks:

```bash
bin/vibestack-dev test
```

Full disposable image checks:

```bash
npm ci
npx playwright install chromium
bin/vibestack-dev build vibestack:dev
bin/vibestack-dev accept vibestack:dev
```

Use focused tests while iterating, but finish with the full commands above.
For UI work, verify both desktop and iPad-sized Playwright projects and inspect
the real custom shell through the private HTTPS Tailscale URL.

## Host broker access

The runner supports paired ownership and an explicit trusted-tailnet shared
principal. In trusted mode every reachable caller controls all managed resources.
REST and `/mcp` must share authorization and registry-bound mediation. Password
submission is REST/CLI only, via fixed root-helper stdin under the lifecycle lock;
never put plaintext in durable operations. See docs/RUNNER.md for the full shared
broker contract and independent-client verification.
