# VibeStack in GitHub Codespaces

Maintained project context. Last checked against official documentation:
21 September 2026. Read this before changing Codespaces configuration.

## Open and use

Create a Codespace from the branch containing this configuration using GitHub's
**Code → Codespaces → Create codespace**, or use
[the VibeStack creation page](https://codespaces.new/check-the-vibe/vibestack).
Choose that branch under the creation options until these changes reach main.
An existing Codespace needs **Codespaces: Rebuild Container** to apply changes.

The configuration requests at least **4 CPU cores and 16 GB RAM**. GitHub normally
selects the smallest eligible machine; larger choices remain available, subject
to account and organization policy. This is a minimum, not a hard-coded SKU or
a guarantee that every account offers that size. See [GitHub's machine requirement
documentation](https://docs.github.com/en/codespaces/setting-up-your-project-for-codespaces/configuring-dev-containers/setting-a-minimum-specification-for-codespace-machines).

The Codespaces editor opens the VibeStack repository. Development tools and the
desktop image prepare in the background, then VibeStack starts automatically.
A fresh uncached build takes several minutes: editor access can precede desktop
readiness. The **Ports** panel lists **VibeStack (private)** on **8080**. Open it
in a browser if automatic opening is blocked. Wait for the lifecycle log's
`VibeStack ready` message. On first use, set your Linux password in Setup;
Desktop, Terminal, Editor, Apps and Settings are then available.

The two editors serve different purposes: the Codespaces editor edits this
repository; VibeStack's embedded editor edits its own persistent `/projects`.
The repository and Codespaces credentials are not mounted into the desktop.

## Copilot and desktop development

GitHub supports Copilot in the Codespaces VS Code web editor; access depends on
account entitlement and organization policy. Install the official `GitHub.copilot`
extension if it is not already available. See [Copilot in Codespaces](https://docs.github.com/en/codespaces/reference/using-github-copilot-in-github-codespaces).
If VS Code starts in Restricted Mode, the human must review the workspace-trust
prompt before enabling terminal execution or agent tools; do not disable trust
globally. Copilot may also ask the human to sign in.

Copilot's terminal is in the **outer Codespace**, not the graphical desktop.
For application projects, add
`/workspaces/.vibestack-codespaces/vibestack/projects` to the Codespaces editor
(or substitute the actual repository-directory name). This is the same tree as
`/projects` inside VibeStack. Run desktop-side tools as `vibe`, for example:

```bash
docker exec -u vibe -w /projects vibestack-codespaces /usr/bin/pwd
```

Graphical commands also need the desktop session environment from
`/run/vibestack/session.env`, as described in `runtime/AGENTS.md`. The authenticated
automation API supplies commands, jobs and screenshots when an agent needs to
inspect the desktop. Copilot does not automatically see the graphical screen.
Keep its commands scoped to this container. The embedded VibeStack editor is
still supported; removing it would be a separate product change.

## Configuration and lifecycle

- `.devcontainer/devcontainer.json` supplies Ubuntu 24.04 tooling, Node 22,
  Go 1.26.4 and an isolated Docker-in-Docker daemon.
- `onCreateCommand` installs Ubuntu’s complete `python3` package; the base image
  only supplies a minimal interpreter without modules such as `json`.
- `updateContentCommand` installs browser-test dependencies and runs
  `python3 .devcontainer/codespaces.py prepare`, building `vibestack:codespaces`
  from the checked-out source with Docker's layer cache.
- `waitFor: onCreateCommand` lets the editor connect before that preparation
  finishes. `postStartCommand` subsequently runs the helper's `start` action.
- Startup waits for Docker, uses a lifecycle lock, creates the desktop through
  the existing launcher, and checks Docker health plus HTTP with the forwarded
  hostname. It resumes an unchanged container; a changed image or hostname uses
  the launcher's replacement/rollback flow. Unexpected mounts stop the operation.
- Reattaching the editor alone does not recreate the desktop. Local Dev
  Containers still install test tools but skip Codespaces-specific startup.

The helper only runs automatically when `CODESPACES=true` and the repository is
directly under `/workspaces`. The dedicated container is `vibestack-codespaces`.
Source changes copied into the desktop image require an explicit rebuild:

```bash
python3 .devcontainer/codespaces.py rebuild
```

Retry startup after a transient failure with:

```bash
python3 .devcontainer/codespaces.py start
docker ps --filter name=vibestack-codespaces
docker logs --tail 100 vibestack-codespaces
VIBESTACK_CONTAINER=vibestack-codespaces bin/vibestack-dev check
```

Use **Codespaces: View Creation Log** for dependency/build failures. Do not run
the default `startup.sh` manually: its standalone name, paths and native ports
are different. Do not change a port to public to fix a connection failure.

## Networking and authentication

Only `127.0.0.1:8080` is published by the nested desktop. GitHub forwards it over
HTTPS to `https://CODESPACE_NAME-8080.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`.
The helper derives this exact hostname from GitHub's environment and passes it
to the existing Host allowlist and public-URL configuration. No wildcard
`*.app.github.dev` allowance, Tailscale setup or native SSH/VNC forwarding is
needed. Nginx and the WebSocket origin checks remain enabled.

GitHub forwarded ports default to **Private**, protected by GitHub authentication.
Keep port 8080 private, including in resumed Codespaces where users may previously
have changed its visibility. The JSON's port label is descriptive; it is not an
access-control mechanism. Organization policy may additionally restrict sharing.
See [forwarding and visibility](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace).

The Linux password protects Linux authentication, not web access. The entire web
desktop relies on GitHub's private port boundary. VibeStack automation still
requires its own bearer credential. Agents inside the Codespace should use
loopback port 8080; remote API clients also need GitHub's forwarding authentication.
Never copy GitHub or VibeStack tokens into source, prompts or logs, or inject the
Codespaces environment into the desktop. No default password is created. Entrypoint sets a predictable `0022` umask;
the unprivileged persistence helper restricts `.vibestack` and `.ssh` to `0700`,
including state left by a previous permissive Docker-in-Docker boot. Token
validation remains strict.

## Persistence and fast creation

State lives outside the repository at
`/workspaces/.vibestack-codespaces/<repository-directory>/data`, with a sibling
`projects` directory. They are bind-mounted as `/data` and `/projects`. Files under
`/workspaces` survive stopping and rebuilding a Codespace; deleting the Codespace
deletes its storage. Commit source and export important desktop work separately.
Docker images/cache are rebuildable; the helper rebuilds a missing image. See
[Codespaces persistence](https://docs.github.com/en/codespaces/developing-in-a-codespace/persisting-environment-variables-and-temporary-files).

For shorter creation times, configure **Settings → Codespaces → Prebuilds** for
the intended branch and region. GitHub runs through `updateContentCommand` during
prebuilds, while desktop startup belongs in `postStartCommand`. Prebuilds are a
repository setting, not enabled by committing JSON. Nested Docker cache retention
must be checked on a real prebuild; a missing image safely rebuilds on startup.
See [GitHub prebuilds](https://docs.github.com/en/codespaces/prebuilding-your-codespaces/about-github-codespaces-prebuilds).

## Agent verification checklist

1. Preserve unrelated dirty work. Run `bin/vibestack-dev test` before/after edits.
2. Validate the devcontainer JSON and lifecycle tests. Build a tagged image and
   run the repository's disposable acceptance; never target personal desktops.
3. On a real Codespace, verify the selected 4-core/16-GB machine, repository editor,
   automatic desktop startup, private port 8080, setup, noVNC WebSocket, ttyd and
   embedded editor. Confirm an unsigned-in browser cannot access the desktop.
4. Create a harmless project file, stop/reopen, then rebuild the Dev Container;
   verify it persists. Check source edits reach the desktop after explicit rebuild.
5. Record local simulation, real Codespaces and prebuild checks separately. A local
   Docker test cannot establish GitHub's proxy/authentication or prebuild behavior.

Additional primary references: [default environment variables](https://docs.github.com/en/codespaces/developing-in-a-codespace/default-environment-variables-for-your-codespace),
[Dev Container lifecycle specification](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md#lifecycle-scripts),
[Codespaces security](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces).
