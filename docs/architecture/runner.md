# Host runner architecture

## Authority boundary

`vibestack-runner` is one persistent Linux daemon per Docker host. It alone
opens the local Docker Unix socket and therefore has substantial host
authority. Workspaces never receive that socket, Docker HTTP, an arbitrary
proxy, or a runner credential. This is a single-operator development system,
not hostile multi-tenant isolation.

The daemon listens on loopback and is intended to sit behind private HTTPS via
Tailscale Serve. Funnel and public binds are outside the contract. There is no
runner dashboard: remote clients use the authenticated structured API, while
template approval, pairing approval/revocation, destructive volume purge, and
service setup remain local administrative commands.

## Identity, pairing, and state

Private state lives in a mode-0700 directory, normally
`/var/lib/vibestack-runner`. A stable random runner identity, SQLite WAL
database, and mode-0600 per-instance workspace credential files are kept
separate. The database stores only client/polling credential hashes, plus:

- approved image names resolved to immutable local Docker image IDs;
- instance UUID, owner, desired and observed state, Docker identifiers,
  volumes, resources, loopback ports, and connection URLs;
- durable operation state, idempotency ownership, safe error text, and the
  runner's recorded Tailscale Serve mappings.

Pairing uses a short operator code and separate high-entropy polling secret.
Requests expire after ten minutes and are bounded. The local approval command
shows the device label and requested permissions. Each delivered client
credential is independently revocable and can see or mutate only instances
owned by that principal.

## Docker reconciliation and launch contract

The official Docker Go SDK uses API-version negotiation. Docker inspection is
the source of observed runtime state; SQLite is the source of ownership and
intent. Containers use launch-contract and instance labels from
`contracts/launch-v1.json`. Reconciliation inspects only recorded instances,
does not adopt unknown containers, resumes unambiguous interrupted creates,
and safely resolves leftover update candidates against the database-selected
generation.

Each new instance gets separate named volumes mounted at `/data` and
`/projects`; the volume initializer creates only the required roots and never
recursively changes `/data` ownership. Remove retains both volumes. A separate
local `instances purge` operation deletes the recorded retained volumes and is
never available to a remote provisioner.

Approved templates are registered locally after image inspection. Remote
create/update requests cannot provide Dockerfiles, contexts, mounts,
capabilities, security options, networks, or raw Docker flags. Resources are
bounded by operator defaults and maxima for instance count, memory, CPUs, PID
count, provisioning concurrency, and minimum free space. Ordinary Docker
volumes do not provide a portable hard size quota, so the runner makes no such
claim.

## Operations and replacement

Create and update require owner-scoped idempotency keys. Conflicting work is
serialized per instance and durable operations outlive client connections.
Create allocates ports transactionally, prepares volumes, starts a container,
waits for Docker health, captures its workspace credential privately, and
waits for saved application restoration before reporting readiness.

Update prepares a candidate against the existing volumes while the old
container remains available. It then stops the old generation, starts and
validates the candidate, commits the database selection, and only then removes
the old container. On failure it removes the candidate and restarts the old
generation. This protects container rollback and user data, but cannot reverse
arbitrary application-data migrations; operators must select compatible
images or maintain a restorable data backup.

Readiness is structured rather than binary: infrastructure health,
password/onboarding requirement, application restoration, and browser/SSH/VNC
connection availability are distinct fields. Start, stop, restart, remove,
inspect, and operation history use the same recorded ownership boundary.

## Ports, origins, and mediation

HTTP, SSH, and native-VNC ports are always published on host loopback. Port
selection checks runner reservations, current listeners, Docker bindings, and
recorded/visible Tailscale Serve state, then treats Docker's bind result as
authoritative. An explicitly requested occupied port fails without altering its
owner. Every browser workspace has its own origin so cookies, PWA scope, and
storage do not collide.

With `manage_tailscale_serve` enabled, the runner creates only the exact Serve
endpoint for that workspace and records it transactionally. It refuses an
unrecorded conflicting endpoint and removes only its own exact mapping using
the corresponding `off` command; it never resets unrelated Serve state.

The mediated workspace route resolves an owned instance from the registry,
injects its private server-side workspace credential, and forwards only the
published workspace API path allowlist. No request can supply a destination or
obtain the credential. Raw desktop and terminal WebSockets remain direct
browser/native-client interfaces rather than runner proxies.

## Registered storage extension

The additive API 1.1 contract is documented in `docs/RUNNER.md`. SQLite now also
owns drive registrations, instance storage selections, active writer leases,
immutable environment sets and stopped-state snapshots. Migration registers
existing volumes without moving their contents. File drives and snapshots outlive
instance removal; instance purge deletes private state only. Attachment swaps
commit the selected container and storage together while stopped. Private
snapshot copies exclude machine authority and runtime history while preserving
the user's password hash, keyrings and application-managed authentication caches.

Host reporting selects metadata rather than returning raw Docker inspection.
The broker guide is generated from `public_url`; the workspace guide remains
specific to its own origin. Remote harness loading is explicit.
