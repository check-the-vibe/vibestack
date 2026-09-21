# VibeStack CLI reference

Release 0.3.1 bounds MCP request identifiers before local forwarding. Generic
registered-capability calls and the workspace MCP stdio bridge are available
since 0.3.0. [The agent guide](https://github.com/check-the-vibe/vibestack/blob/main/runtime/AGENTS.md)
is the one-URL entry point; use the deployed service's `/AGENTS.md` for its version.
The CLI runs beside an agent on Linux/macOS, amd64/arm64. It needs no Docker, Go,
Python, Node or sudo after installation. JSON goes to stdout; diagnostics go to
stderr, and binary file/screenshot/job output retains its documented raw format.

## Install and connect

Download and inspect the release installer before running it:

```sh
curl -q -fLsS --proto '=https' --proto-redir '=https' \
  https://github.com/check-the-vibe/vibestack/releases/download/v0.3.1/cli.sh \
  -o /tmp/vibestack-cli.sh
sh /tmp/vibestack-cli.sh --version 0.3.1 --server "$SERVICE_ORIGIN"
vibestack version
vibestack connect --name studio --url "$SERVICE_ORIGIN" \
  --token-stdin < /path/to/protected/workspace.token
vibestack --profile studio capability list
vibestack --profile studio capability call workspaceStatus
```

`SERVICE_ORIGIN` is the origin of the supplied `/AGENTS.md` URL. A compatible
existing CLI can skip installation. Installation requires curl 8.4+, a SHA-256
utility and a POSIX shell; it checks bounded HTTPS downloads and redirects,
explicit MAJOR.MINOR.PATCH versions and a published checksum. It atomically
replaces `~/.local/bin/vibestack`, without sudo or shell-profile edits. Failure
preserves the prior binary. An existing destination directory or symlink is
rejected. Native CI runs the real HTTPS installer and native executable for all
four release platforms; cross-compilation alone is not installation evidence.

The release owner is `check-the-vibe/vibestack`; assets and checksums are tied to
`v0.3.1`. The workflow refuses to overwrite an existing release and attaches
GitHub Actions build provenance to the exact tested binaries. The default
installer trusts GitHub HTTPS and checksums; it does not independently verify a
compromised publisher. For the stronger provenance check, download the binary
and use GitHub CLI's
[attestation verifier](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
before installing it:

```sh
gh attestation verify ./vibestack_0.3.1_linux_amd64 \
  --repo check-the-vibe/vibestack \
  --signer-workflow check-the-vibe/vibestack/.github/workflows/publish-client.yml
```

Review the attested source commit against the release/tag you selected. GitHub
identity and its Sigstore-backed attestation are the trust roots; no unconfigured
private signing key or independent signature service is implied. Published
release delivery and its verification are recorded in VST-009.

Workspace credentials are issued by the local operator, can expire and carry
capability grants. Follow [SERVICE.md](SERVICE.md). The current workspace does
not advertise anonymous pairing; `connect --token-stdin` privately reads an
issued credential, validates access to the current catalog and saves the profile
as mode 0600 in a protected directory. No token belongs in argv, environment,
chat or a URL. An existing profile is preserved until explicitly removed.

For an **outside** private Codespaces origin, add
`--gateway-token-file /absolute/protected/github-gateway.token` to `connect`.
The file is a distinct user-supplied GitHub gateway credential, not a VibeStack
credential. Only its absolute path is saved in the profile; REST, discovery,
document downloads and MCP read it afresh per request. It must be a regular,
single-link file owned by the current user with no group/other access. The client
accepts it only for the selected HTTPS `*.app.github.dev` origin on port 443,
never follows redirects and never reads ambient GitHub tokens. Gateway tokens
may need replacement after a Codespace restart. Use the Codespace-local
`http://127.0.0.1:8080` profile when external gateway access is unavailable.
Actual outside-gateway compatibility is separate from local SDK verification.

Optional runners retain their advertised pairing or explicit trusted-tailnet
flow. They have their own profile, identity and authority; workspace bootstrap
does not require a runner or automatically select one.

Global options must precede the command:

```text
--instance ID    select a desktop for mediated runner workspace commands
--profile NAME   select an exact target (required when several match)
--json           stable JSON output where the operation is structured
--ca FILE        explicit custom certificate authority
```

HTTP is accepted only for loopback development. HTTPS certificates are always
validated. HTTP redirects are not followed,
and server URLs cannot contain reverse-proxy subpaths.

## Connection and diagnostics

```text
connect --name NAME --url ORIGIN [--label LABEL] [--token-stdin] [--gateway-token-file FILE]
profiles list | show NAME | remove NAME
doctor
capabilities
```

`doctor` verifies discovery identity, API compatibility, certificate trust,
authentication, and the selected target kind. A command may select the only
compatible profile; it never guesses when several profiles exist.

## Registered capabilities and MCP

```text
capability list
capability schema
capability call ID [--input FILE|-]
mcp [--gateway-token-file FILE]
```

Use a direct workspace profile. The generic commands discover authorized
capabilities, fetch their current input/output schemas and invoke their registered
IDs without maintaining another operation table in the CLI. Omitted input is `{}`;
provided input must be one JSON object of at most 24 MiB. The service applies the
smaller declared limit and strict schema. JSON responses are bounded at 24 MiB.
Unknown input and duplicate keys reach strict server validation without being
silently normalized. No request is automatically replayed. The JSON result retains
the shared instance/request/capability envelope; service failures retain stable
codes and exit statuses. The older plural `capabilities` command retains its
legacy automation/runner behavior.
Grant denial is `forbidden` across the generic CLI, REST, browser session and MCP
surfaces. The CLI reports the safe code on stderr and returns the existing exit
status mapping; it never turns a rejected or uncertain mutation into a replay.

`mcp` is launched by a stdio-capable harness and uses the same protected workspace
profile. No credentials belong in harness JSON. Its optional gateway-file override
has the same destination/file checks as the saved path. See [MCP.md](MCP.md) for
client versions, coverage, transport limits and explicit unsupported cases.

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
and conditional writes are enforced by the server. Workspace password entry
uses the human browser handoff. The separate runner has explicit private password
commands documented below; no password is accepted in argv or an environment variable.

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
