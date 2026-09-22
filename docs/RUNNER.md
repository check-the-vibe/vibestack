# VibeStack runner operations

`vibestack-runner` is a Linux-only host service for approved VibeStack images.
It is separate from the in-workspace command-job runner. It has a JSON API,
remote MCP and local administrative CLI, but no dashboard. Authentication defaults
to paired credentials; explicit trusted-tailnet mode shares authority among all
reachable callers. See [shared access](#shared-tailnet-broker-and-remote-mcp). Docker socket access
grants substantial host authority, so only this root service receives it;
workspace containers never mount or proxy the Docker socket.

## Supported hosts and installation

Release packages support Ubuntu 24.04 and 26.04 with systemd. Other Linux hosts
with an existing Docker Engine may run `vibestack-runner serve --config FILE`
in the foreground. The ordinary `cli.sh` client installer never installs or
starts this service.

```bash
sudo ./install-runner.sh
sudoedit /etc/vibestack-runner/config.json
sudo systemctl enable --now vibestack-runner
sudo vibestack-runner doctor
```

The installer preserves an existing Docker installation. If Docker is absent,
either follow Docker's official Ubuntu instructions or explicitly run
`sudo ./install-runner.sh --install-docker`. That opt-in configures Docker's
official HTTPS apt repository and installs Docker Engine; package conflicts are
reported and are never removed automatically. Existing Docker source
configuration is preserved. `doctor` checks
daemon/API connectivity, host architecture, CPU, memory, state-filesystem free
space, and the configured private listener. Review HTTPS/Tailscale Serve and
port ownership separately before exposing the runner URL.

Private state is mode 0700 under `/var/lib/vibestack-runner`. `runner.db` is a
SQLite WAL database containing stable identity, approved templates, instance
intent/ownership, ports, resource settings, pairing hashes, client credential
hashes, and operation history. Per-instance workspace credentials, when needed
for bounded mediation, live as separate mode-0600 files below `credentials/`.

## Local administration

```text
vibestack-runner init [--config FILE] [--state-dir DIRECTORY]
vibestack-runner doctor [--config FILE]
vibestack-runner templates list
vibestack-runner templates add [--flatpak] NAME IMAGE
vibestack-runner pairings list
vibestack-runner pairings approve CODE
vibestack-runner pairings deny CODE
vibestack-runner clients list
vibestack-runner clients revoke ID
vibestack-runner serve
```

Template registration inspects a host-local accepted image and records its
immutable Docker image ID. Remote clients can select only those templates;
they cannot submit a Dockerfile, build context, bind mount, capability, or raw
Docker flag. `--flatpak` is the operator's explicit opt-in to the same three
security relaxations as the legacy launcher and never adds capabilities or
`--privileged`.

In paired mode, pairing approval displays the device label and exact requested permissions.
Codes expire after ten minutes and cannot retrieve credentials without the
separate polling secret. Credentials are individually revocable.

## Launch contract and storage

Managed instances carry labels for the instance UUID, runner ownership, and
launch-contract version. Each gets independent named volumes for `/data` and
`/projects`, a bounded PID/memory/CPU configuration, and loopback-only HTTP,
SSH, and native-VNC host ports. Docker's final bind is authoritative. Explicit
occupied ports fail without altering the existing owner.

The database establishes ownership and desired state; Docker inspection
establishes observed state. Reconciliation updates known instances and refuses
to adopt unknown labeled or unlabeled containers. Removing a container retains
volumes by default. An explicit operator purge is required to delete them.
Never recursively change `/data` ownership and never copy credentials between
instances.

Create and update require idempotency keys. Conflicting operations serialize
per instance, operations survive client disconnects, and operation records are
bounded structured metadata. Readiness distinguishes container health,
onboarding/password status, restored applications, and advertised connections.

The source launcher and runner share `contracts/launch-v1.json`. Replacement
keeps the prior container until the candidate becomes healthy and saved
application restoration succeeds. Container rollback cannot undo arbitrary
application-data migrations; use a compatible image or a restorable backup.

## Networking and trust

The service listener must remain loopback. Terminate HTTPS with private
Tailscale Serve; never use Funnel for runner or workspace routes. The runner
manages only mappings recorded in its own state. Each workspace receives a
distinct origin (normally a unique port or hostname) so cookies, PWA scope,
and browser storage do not collide.

Runner-mediated workspace access resolves an instance from the authenticated
registry and allows only published VibeStack workspace paths. A caller can
never supply a proxy destination. Raw Docker HTTP is never exposed.

See `api/runner.openapi.json` for the machine-readable API and `docs/CLI.md`
for client commands.

## Reusable local storage (API 1.1)

`GET /api/v1/runner/host` requires `instances:read`. It returns selected Docker
availability/version, available host memory, state-filesystem free disk,
approved images, and only the caller's managed instances, ports, readiness and
storage attachments. Docker inspection, host folder paths, environment values,
workspace credentials and other owners' resources are never reported.

Named drives are owner-scoped IDs. `POST /api/v1/runner/drives` with
`{"name":"projects"}` registers a managed file volume. Register an existing,
dedicated canonical host folder only through local administration:

```text
vibestack-runner drives register NAME OWNER_CLIENT_ID /dedicated/folder
vibestack-runner drives create NAME OWNER_CLIENT_ID
vibestack-runner drives list OWNER_CLIENT_ID
```

Use an existing dedicated folder such as `/home/USER/runner-projects`; broad
system/home roots, hidden credential paths, symlink aliases, and overlapping
registered folder trees are rejected. Keep its path stable after registration.
The systemd unit allows read-only inspection of home directories; Docker's daemon
mounts the registered folder into a workspace with the selected access mode.
Initializers change only writable volume roots, never project-tree contents.

Create accepts optional `project_drive`, `file_drives`, `environment_set`, and
`state_seed` alongside the existing name/template/ports/resources fields:

```json
{
  "name": "workbench",
  "template": "desktop",
  "project_drive": "REGISTERED_DRIVE_ID",
  "file_drives": [{"drive_id": "FILES_ID", "name": "assets", "read_only": true}],
  "environment_set": "PRIVATE_ENVIRONMENT_SET_ID",
  "state_seed": "READY_SNAPSHOT_ID"
}
```

Omit the optional fields for a fresh private `/data` volume and a fresh projects
volume. File drives mount beneath `/mnt/drives/<name>`; private desktop state
cannot be selected as a file drive. A transactional writer lease permits one
active desktop per writable drive. Stop and remove release leases only after
Docker confirms stop/removal. A stopped desktop may select a drive already
attached elsewhere, but cannot start until its writer lease is available.
Read-only attachments do not reserve the writer lease.

`PUT /instances/ID/attachments` (relative to the runner API root) accepts only
`project_drive` and `file_drives`, and requires a stopped desktop. It prepares a
stopped replacement container and commits the selected container and attachments
in one database transaction. The next start initializes new managed roots.

Environment sets are immutable and private to their owner. POST
`/api/v1/runner/environment-sets` with `{"name":"tools","values":{"SERVICE_TOKEN":"..."}}`
through a private request body. Local administration accepts a mode-0600 JSON
string-map file with `environment-sets add NAME OWNER_CLIENT_ID FILE`.
GET/list responses contain only IDs, names and keys. Values are held in the
root-private SQLite registry and supplied to Docker's private container config;
Docker host administrators retain access. Values are never copied into operation
requests, reporting, or shared logs. Runtime settings including `VIBESTACK_*`,
loader/Python/XDG/D-Bus variables, HOME, PATH, display/session and shell startup
settings cannot be overridden.

Stop a desktop and poll its operation before POSTing `{"name":"configured"}`
with an `Idempotency-Key` to `/instances/ID/snapshot`. Poll that operation and
select its ready snapshot ID as `state_seed` for later desktops. Snapshots copy
persistent app state and keyrings, preserve the Linux password hash, and exclude
workspace automation tokens/jobs, paired-client state, identity, SSH host keys,
authorized agent SSH keys, shared logs, history, runtime locks, sockets and PIDs.
Application-managed sign-in caches and user outbound SSH credentials remain
private application state. Every clone gets an independent writable copy;
future app logins are not synchronized. Authentication reuse must be checked
with each service, which can require signing in again. Flatpak state requires
an approved Flatpak-enabled destination template. Choose compatible app images;
a filesystem snapshot is not a promise of cross-version app migration support.

Copies run in a bounded, network-disabled helper using an approved image and a
read-only source volume. An interrupted copy remains failed and cannot be used
as a seed. Partial volumes are retained for explicit local cleanup. Storage
operations survive client disconnects; an interrupted snapshot operation is
reported failed after runner restart. Create replay fails closed if interrupted
copy output is nonempty rather than merging unverified partial state.

Remove retains all drives and snapshots. `instances purge ID` deletes only a
removed desktop's private state. `drives purge ID` removes an unattached managed
file volume, or unregisters a host folder **without deleting its contents**.
`snapshots purge ID` deletes a snapshot unless a create is copying it. These
purges are local administrative actions; no remote purge API exists. Existing
instance volumes are registered in place on database open, without moving data.

The broker now serves its own `/AGENTS.md`, with the configured public origin
and concrete pairing, provisioning, mediation and snapshot steps. It also serves
`/api/runner.openapi.json`. A remote harness must explicitly fetch or locally
reference the broker guide; merely hosting it does not make harnesses load it.

## Shared tailnet broker and remote MCP

The broker configuration has `authentication_mode`: `paired` (default) or
`trusted-tailnet`. In trusted mode **everyone who can reach the private broker
can inspect and manipulate every managed desktop, drive, snapshot, environment
set and operation**. One persistent shared principal owns these resources.
Caller headers and device labels never identify separate owners. Paired mode
continues to require valid, non-revoked bearer credentials and owner isolation.
Switching modes requires an empty registry, including credentials, templates,
retained resources and operation history; deploy with clean managed state.
Existing development state is not automatically reassigned.

Keep the broker on loopback behind private Tailscale Serve, never Funnel.
Docker access stays in the host runner. Discovery at `/.well-known/vibestack`
advertises `authentication_mode` and `mcp_url`. Connect explicitly:

```bash
vibestack connect --url https://HOST:10443 --name shared
vibestack --profile shared capabilities
vibestack --profile shared instances create --name desk --template desktop --idempotency-key desk-v1
vibestack --profile shared operations wait OPERATION_ID
vibestack --profile shared instances inspect INSTANCE_ID
vibestack --profile shared --instance INSTANCE_ID exec -- /usr/bin/pwd
vibestack --profile shared --instance INSTANCE_ID screenshot --output desktop.png
vibestack --profile shared instances password INSTANCE_ID
```

Trusted profiles store the authentication mode without a bearer token or pairing.
Authentication errors never downgrade a profile. Workspace commands through a
runner require `--instance ID` before the command. Tokens remain private to the
broker; it injects the selected desktop's automation credential.

`instances password ID` uses a hidden terminal prompt with confirmation.
`--password-stdin` explicitly reads one password, with an optional final newline.
No password argument or environment variable is supported. `instances create`
accepts `--prompt-password` or `--password-stdin`: provisioning and operation
polling finish first, then a separate synchronous password request runs.
If that step fails, the desktop remains and the CLI reports its ID and incomplete
credential setup. Never automatically retry a credential request after a lost
connection; completion may be uncertain. Read status and explicitly decide.

REST `POST /api/v1/runner/instances/{id}/password` accepts only
`{"password":"<private input>"}` with a 2048-byte body limit. Passwords must be
12–256 UTF-8 bytes without control characters or only whitespace. The desktop
must be running and healthy; busy/stopped desktops return actionable conflicts.
The fixed root helper receives stdin, never argv, Docker environment/config,
SQLite, operation payloads or shared logs. Only its existing Linux-compatible
hash persists in the desktop's private `/data/.vibestack-auth-v1` state.
The Linux username remains `vibe`; credentials are independent per desktop.
Restart and replacement restore the hash. Snapshot clones inherit the documented
password hash and can be reset independently. Linux password changes do not
synchronize application logins or keyring encryption.

Connection metadata includes `linux_username`, `password_status`,
`infrastructure_ready`, `applications_restored`, `onboarding_required`, and
`reachability`. Infrastructure readiness does not mean application onboarding is
finished. `urls.password_setup` is the human password handoff; after password
setup use `urls.desktop` for the desktop and agent overlay. Retired terminal/editor
URLs are no longer advertised. Tailnet reachability grants desktop access: the Linux
password is not a web-login gate. SSH and native VNC are explicitly `host-local`
and their loopback addresses are not advertised as remote links. Without managed
Serve, browser URLs are also marked host-local.

Remote MCP uses **Streamable HTTP at `https://HOST:10443/mcp`**, stateless with
JSON responses, using the official Go SDK pinned to `v1.7.0`. Go 1.25 is the
minimum; CI uses supported Go 1.26.x. The harness itself must have tailnet
connectivity; a cloud connector without it cannot reach this private endpoint.
MCP and REST share principal resolution, source checks and service dispatch.
Requests are capped at 1 MiB and tool results at 16 MiB. No request bodies,
command text, output or credentials are logged by the MCP handler.

Tools: `host_inspect`, `templates_list`, `instances_list`, `instance_inspect`,
`instance_create`, `instance_action`, `operation_get`, `workspace_command`,
`workspace_job`, `workspace_output`, `workspace_screenshot`. Provisioning and
lifecycle tools return durable operation IDs; poll `operation_get` until terminal.
Workspace tools require an explicit `instance_id`; commands return job IDs.
Poll `workspace_job`, then read bounded `workspace_output` pages with cursors.
Password submission, arbitrary Docker commands/proxy destinations and remote
volume purge are excluded. Return the password status and human setup URL.

Deployment gates: baseline/full `bin/vibestack-dev test`, all client and runner
release cross-builds, tagged image build, disposable image acceptance and isolated
runner integration. Inventory exact registry-owned containers, volumes and Serve
mappings before resetting development state. Preserve host-folder contents and
unrelated Docker workloads/mappings; never use global Docker prune or Serve reset.
Use tmux for sudo authentication. Provision two clean desktops, validate shared
access from two independent clients, MCP initialize/discovery/provision/poll/job
flows, password persistence and Linux authentication, and the real HTTPS desktop/agent overlay and authenticated automation. Record physical-device checks separately.
