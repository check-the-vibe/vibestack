# VibeStack in GitHub Codespaces

The launcher declares the shared checkout through `VIBESTACK_SOURCE_PROJECT`.
Project file APIs and command working directories therefore support that one
immediate source mount even on a different filesystem from `/projects`. Its
opened directory defines the device boundary; ownership, no-symlink and deeper
mount checks remain in force. No recursive ownership change is required.

Maintained project context. Last checked against official documentation:
21 September 2026. Read this before changing Codespaces configuration.

## Open and use

Create a Codespace from `main` using GitHub's
**Code → Codespaces → Create codespace**, or use
[the VibeStack creation page](https://codespaces.new/check-the-vibe/vibestack).
The automatic startup configuration is checked into main.
An existing Codespace needs **Codespaces: Rebuild Container** when its Dev Container configuration changes.

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
`VibeStack ready` message. The authenticated service additionally needs a browser
credential handoff: follow [the service guide](../docs/SERVICE.md) to create an
owner credential from the Codespace terminal and connect using the agent icon at `/vnc/` (`/connect.html` also remains available).
Then set your Linux password in Setup. Workspace credentials, the Linux password
and provider sign-in are separate. Desktop, Terminal, Editor, Apps and Settings
remain available during the UI migration.

The Codespaces repository is bind-mounted read/write at
`/projects/<repository-directory>` inside VibeStack (`/projects/vibestack` for
this repository). The outer editor and native desktop tools see the same source files and Git metadata;
changes are immediate in both directions. Other projects remain in the separate
persistent projects directory. This shares the checkout, including any files
you put in it; it does not forward Codespaces environment credentials, the
outer home directory, or the Docker socket. Git authentication remains in the
outer Codespace.

## Reuse this Codespace for the next ticket

Keep the same Codespace when moving between ticket branches. Its checkout remains
at `/workspaces/vibestack` and the nested desktop sees that same Git repository
at `/projects/vibestack`. Inspect and commit or otherwise preserve any in-flight
changes before switching; never reset them to make a switch succeed.

For a ticket branch, substitute its registered branch and ticket below:

```bash
git status --short --branch
git fetch origin
git switch codex/vst-017-codespaces-resume
code .context/tickets/VST-017.md
```

Git tracks the existing remote branch automatically if it is not yet local.
Create later branches from the intended base under the [ticket workflow](workflow.md).
A branch switch changes source files immediately in both environments and does
not recreate the Codespace or desktop container. Existing desktop state and
installed applications remain in the same persistent paths.

Running image services still use the code copied into the existing image.
After source/runtime changes, follow `docs/DEVELOPMENT.md` to test, build and
accept a disposable candidate, then deliberately rebuild the desktop with
`python3 .devcontainer/codespaces.py rebuild`. Documentation-only branch changes
need no image rebuild. Changes to `.devcontainer/devcontainer.json` or its
features require the outer **Codespaces: Rebuild Container** operation.
Never treat switching Git branches alone as deploying new server behavior.

## Copilot and desktop development

GitHub supports Copilot in the Codespaces VS Code web editor; access depends on
account entitlement and organization policy. Install the official `GitHub.copilot`
extension if it is not already available. See [Copilot in Codespaces](https://docs.github.com/en/codespaces/reference/using-github-copilot-in-github-codespaces).
If VS Code starts in Restricted Mode, the human must review the workspace-trust
prompt before enabling terminal execution or agent tools; do not disable trust
globally. Copilot may also ask the human to sign in.

Copilot's terminal is in the **outer Codespace**, not the graphical desktop.
The current checkout is already visible inside VibeStack at `/projects/vibestack`;
use `docker exec -u vibe -w /projects/vibestack vibestack-codespaces ...` to
run tools against that source in the desktop environment. For other projects, add
`/vibestack-runtime/vibestack/projects` to the Codespaces editor
(or substitute the actual repository-directory name). This is the same tree as
`/projects` inside VibeStack. Run desktop-side tools as `vibe`, for example:

```bash
docker exec -u vibe -w /projects vibestack-codespaces /usr/bin/pwd
```

Graphical commands also need the desktop session environment from
`/run/vibestack/session.env`, as described in `runtime/AGENTS.md`. The authenticated
automation API supplies commands, jobs and screenshots when an agent needs to
inspect the desktop. Copilot does not automatically see the graphical screen.
Keep its commands scoped to this container. The embedded VibeStack browser editor
is retired; use the outer source editor, Remote SSH or native desktop tools.

## Configuration and lifecycle

- `.devcontainer/devcontainer.json` supplies Ubuntu 24.04 tooling, Node 22,
  Go 1.26.4 and an isolated Docker-in-Docker daemon.
- `onCreateCommand` installs Ubuntu’s complete `python3` package; the base image
  only supplies a minimal interpreter without modules such as `json`. It checks
  the runtime volume is mounted and sets ownership on its mount root only.
- `updateContentCommand` installs browser-test dependencies and runs
  `python3 .devcontainer/codespaces.py prepare`, building `vibestack:codespaces`
  from the checked-out source with Docker's layer cache. Preparation creates no
  runtime identity, credentials or desktop state; prebuilds must not clone them.
- `waitFor: onCreateCommand` lets the editor connect before that preparation
  finishes. `postStartCommand` subsequently runs the helper's `start` action.
- Startup waits for Docker, uses a lifecycle lock, creates the desktop through
  the existing launcher with `--mount-source`, and checks Docker health plus public `/healthz` with the forwarded
  hostname. It resumes an unchanged container; a changed image or hostname uses
  the launcher's replacement/rollback flow. Unexpected mounts stop the operation. Older containers without the source
  mount are replaced once; a nonempty or symlinked destination is rejected so
  an existing project cannot be hidden by the mount.
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

The outer Dev Container mounts the named volume
`vibestack-runtime-${devcontainerId}` at `/vibestack-runtime`. State lives at
`/vibestack-runtime/<repository-directory>/data`, with a sibling `projects`
directory, bind-mounted into the desktop as `/data` and `/projects`. The source
checkout remains in `/workspaces` and is a separate nested bind at
`/projects/<repository-directory>`. Runtime data is kept outside the workspace
tree so its root-private ownership does not depend on workspace ownership changes.
The variable/mount pattern follows the official
[Docker-in-Docker feature](https://github.com/devcontainers/features/blob/main/src/docker-in-docker/devcontainer-feature.json);
actual Codespaces stop/resume and outer rebuild persistence must still be tested.

The volume has a non-secret `.volume-id`; a matching witness remains at
`/workspaces/.vibestack-codespaces/<repository-directory>/runtime-volume-id`.
If the volume is missing, empty, or different after a rebuild, startup stops
instead of generating replacement credentials or silently losing user state.
Restore the original volume; do not delete the witness to suppress the check.
The volume is Codespace storage, not a backup. Commit source and export important
desktop work separately before deleting a Codespace. Docker images/cache are
rebuildable; the helper builds a missing image. GitHub separately documents
[workspace persistence](https://docs.github.com/en/codespaces/developing-in-a-codespace/persisting-environment-variables-and-temporary-files).

### Existing Codespaces: migrate once

An old workspace-backed installation deliberately stops with an explicit
migration message. First rebuild the outer Dev Container to install the volume.
Inspect the existing container's mounts and the original data before continuing:

```bash
docker inspect vibestack-codespaces --format '{{json .Mounts}}'
python3 .devcontainer/codespaces.py migrate
python3 .devcontainer/codespaces.py start
```

`migrate` checks the original directories, state marker and container mounts,
stops the old container, and copies `data` and `projects` with `sudo cp -a`,
preserving ownership, permissions and secrets. It records the volume identity
and the exact original location. The original tree is retained, and source is
never copied or recursively chowned. Startup replaces the old bind through the
launcher's normal rollback path. A failed/partial copy is left for inspection;
the command refuses to overwrite any existing destination or identity.

Migration does **not** repair credential ownership. If bootstrap reports unsafe
state, inspect only file types, owners and modes first. In particular,
`/data/.vibestack-auth-v1` and its private files must be root-owned; do not
recursively chown `/data`, adopt user-owned credentials automatically, display
private keys/password hashes, or reset the desktop to bypass a failure.
An operator must establish the provenance of affected files before a targeted
repair. Record that repair separately from automatic startup evidence.

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
   automatic desktop startup, private port 8080, agent setup/chat and the noVNC
   WebSocket. Verify retired UI bookmarks redirect without old assets/services. Confirm an unsigned-in browser cannot access the desktop.
4. Create a harmless project file, stop/reopen, then rebuild the Dev Container;
   verify it persists. Check source edits reach the desktop after explicit rebuild.
5. Record local simulation, real Codespaces and prebuild checks separately. A local
   Docker test cannot establish GitHub's proxy/authentication or prebuild behavior.

Additional primary references: [default environment variables](https://docs.github.com/en/codespaces/developing-in-a-codespace/default-environment-variables-for-your-codespace),
[Dev Container lifecycle specification](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md#lifecycle-scripts),
[Codespaces security](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces).
