# VibeStack CLI reference

The `vibestack` client runs beside an agent on Linux or macOS. It does not
require Docker, Go, Python, Node, sudo, or agent-specific configuration. Every
command supports human-readable output; structured commands accept global
`--json`. Diagnostics go to stderr and binary file, screenshot, clipboard, and
job output is written unchanged to stdout or the requested file.

## Install and connect

```bash
curl -fsSL 'https://workspace.example/cli.sh' | \
  sh -s -- --version 0.2.0 --server 'https://workspace.example'
vibestack connect --name studio --url 'https://workspace.example'
```

The installer detects Linux/macOS and amd64/arm64, downloads the versioned
release binary over HTTPS, checks the separately published SHA-256, and uses an
atomic rename into `~/.local/bin`. It never edits a shell profile. A failed
download or checksum leaves an existing binary untouched. HTTPS authenticates
the delivery channel; the checksum detects corruption or substitution inside
that channel and is not described as an independent publisher signature.

`connect` reads `/.well-known/vibestack`. For trusted-tailnet runners it records
the advertised mode without credentials or pairing. For paired servers it displays a short verification code,
and polls with a separate high-entropy secret. Approve workspace requests in
Setup. Approve runner requests locally with `vibestack-runner pairings approve
CODE`. The returned credential is stored only in the mode-0600 profile file.
For migration only, `--token-stdin` accepts an existing workspace automation
token without placing it in argv.

Global options must precede the command:

```text
--instance ID    select a desktop for mediated runner workspace commands
--profile NAME   select an exact target (required when several match)
--json           stable JSON output where the operation is structured
--ca FILE        explicit custom certificate authority
```

HTTP is accepted only for loopback development. HTTPS certificates are always
validated. Credentials are never followed across an origin-changing redirect,
and server URLs cannot contain reverse-proxy subpaths.

## Connection and diagnostics

```text
connect --name NAME --url ORIGIN [--label LABEL] [--token-stdin]
profiles list | show NAME | remove NAME
doctor
capabilities
```

`doctor` verifies discovery identity, API compatibility, certificate trust,
authentication, and the selected target kind. A command may select the only
compatible profile; it never guesses when several profiles exist.

## Workspace work

```text
exec [--async] [--desktop] [--cwd PATH] [--timeout SECONDS] -- ABSOLUTE-ARGV...
shell [--async] [--desktop] [--cwd PATH] [--timeout SECONDS] 'COMMAND'
jobs get ID | wait ID | output ID [stdout|stderr] | cancel ID
files [--desktop] [--if-match ETAG] [--if-none-match ETAG] get REMOTE [LOCAL]
files [--desktop] [--if-match ETAG] [--if-none-match ETAG] put REMOTE LOCAL|-
files [--desktop] head REMOTE
screenshot [--output LOCAL.png] [--remote Desktop-relative.png]
apps list | start ID | stop ID
windows list | state ID minimized|maximized|normal
clipboard get | set
```

New project workflows default to the `/projects` API root. `--desktop` selects
the older Desktop root. The client reports an incompatible older server rather
than silently writing new project work to Desktop. `exec` uses an argv array
and waits by default. `shell` is explicit. `--async` returns the durable remote
job ID; disconnecting the client does not cancel it and an uncertain command
submission is never automatically retried.

`files put ... -` and `clipboard set` read stdin. ETags, ranges, size limits,
and conditional writes are enforced by the server. Passwords are deliberately
not accepted by any CLI command.

## Workspace status and recovery

```text
status
display get | set WIDTHxHEIGHT
services start|stop|restart desktop|vnc|terminal|setup|ssh|native-vnc|editor
logs SERVICE [CURSOR]
setup
account
ssh-keys list | add 'ssh-ed25519 ...' | remove ID
```

`account` prints the same-origin browser handoff for creating or replacing the
Linux password. Public keys may be added, but private keys remain on the
customer device. Removing a local profile does not revoke its remote client;
revoke it in workspace Setup or with the runner's local admin command first.

## Runner lifecycle

```text
instances list | inspect ID
instances create --name NAME --template APPROVED --idempotency-key KEY [resource/port flags]
instances update ID --template APPROVED --idempotency-key KEY [resource flags]
instances start|stop|restart|remove ID
operations list | operations ID | operations wait ID
```

Create returns a durable operation. Reuse the same idempotency key after a
transport failure; the runner returns the original operation. Removing an
instance retains its `/data` and `/projects` volumes. Data purge is a separate
local operator action. Create accepts `--http-port`, `--ssh-port`, `--vnc-port`,
`--memory-bytes`, `--nano-cpus`, and `--pids`; zero/omitted values use runner
allocation/defaults. Update accepts the three resource flags and retains the
previous container until the candidate is healthy and application restoration
has converged.

The runner can mediate only its allowlisted workspace routes at
`/api/v1/runner/instances/{id}/workspace/api/...`. It resolves the destination
and workspace credential from private runner state; a caller cannot provide a
proxy host or retrieve that credential. The `api` escape hatch can address
documented mediated paths while remaining bound to the selected runner profile.

## Agent and low-level commands

```text
skill install --claude
skill export DIRECTORY
docs agents|cli|automation|runner
api --method METHOD [--data-file FILE|-] /api/relative/path
```

Skill installation refuses to overwrite an existing skill directory. The
relative-path `api` command remains bound to the selected profile and accepts
only documented API/setup paths; it cannot become an arbitrary authenticated
proxy.

Exit status 2 is a local usage/transport failure, 3 a remote service failure,
4 authentication/authorization, 5 not found, and 6 a conflict/precondition.
Responses include request IDs; job and lifecycle responses include their
remote IDs.

Runner storage routes are available through the existing generic `api` command.
Request files keep private values out of argv and shell history:

```bash
vibestack --profile runner api /api/v1/runner/host
vibestack --profile runner api /api/v1/runner/drives
vibestack --profile runner api --method POST --data-file private-env.json /api/v1/runner/environment-sets
vibestack --profile runner api --method POST --data-file create.json --idempotency-key create-one /api/v1/runner/instances
vibestack --profile runner api --method PUT --data-file attachments.json /api/v1/runner/instances/ID/attachments
vibestack --profile runner api --method POST --data-file snapshot.json --idempotency-key saved-one /api/v1/runner/instances/ID/snapshot
vibestack --profile runner operations wait OPERATION_ID
```

`create.json` may select `project_drive`, `file_drives`, `environment_set` and
`state_seed` IDs; `snapshot.json` contains a name. Read [RUNNER.md](RUNNER.md)
for precise schemas, stopped-state requirements and local administrative purge.

## Shared broker access

The runner supports default `paired` and explicit `trusted-tailnet` modes.
Trusted mode grants every reachable caller shared control of all managed
desktops and storage, without pairing. Remote MCP is at `/mcp`; the harness
itself needs tailnet connectivity. Use `--profile NAME --instance ID` for
workspace commands through the broker. `instances password ID` prompts privately;
`--password-stdin` is explicit. Create optionally accepts `--prompt-password`
or `--password-stdin`, applying the password only after provisioning. Linux
passwords are per-desktop and do not gate browser access. SSH/native VNC remain
host-local. Go 1.25 is required, CI uses Go 1.26.x and MCP SDK v1.7.0.
See [shared access, password, MCP and rollout contract](RUNNER.md#shared-tailnet-broker-and-remote-mcp).
