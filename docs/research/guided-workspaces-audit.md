# Guided workspaces experience audit

This audit records the evidence and release gates for the workspace, client,
and host-runner refresh. “Verified” means a checked-in contract or automated
test exists; it does not substitute for the disposable-image, private-HTTPS,
physical-device, or external-agent gates listed at the end.

| Surface | Evidence and customer impact | Severity | Implemented change | Acceptance |
|---|---|---:|---|---|
| Home readiness | The prior launcher offered destinations but did not distinguish degraded services. A nontechnical user could enter a broken Desktop without a recovery cue. | High | `desktop/launcher.js` combines setup state and the four required service states, labels the workspace ready/recoverable, and sends an installed editor to `/editor/`. | Browser tests cover complete/incomplete onboarding, destinations, and editor state; disposable tests must use the real status API. |
| Applications and persistence | Catalog state survived replacement, but durable agent source work was not a first-class API root and Desktop files were easy to mistake for persistent project storage. | Critical | `/projects` now has file semantics equivalent to Desktop, command jobs accept an explicit root, and the client defaults new work to projects while rejecting an older incompatible server. Managed instances use separate named data/project volumes. | Unit/API checks cover confinement and binary behavior; runner acceptance must create two instances and prove independent volume reuse. |
| Settings and recovery | Only restart was exposed and four core services were visible. Optional access methods could fail without an in-product recovery action. | High | The fixed control allowlist now includes SSH, native VNC, and editor, with start/stop/restart and bounded logs. Native VNC is independent of browser VNC. | Helper/API tests prove fixed mappings; Playwright checks all seven cards and confirmation. Real SSH/VNC/editor checks remain candidate gates. |
| Onboarding | Users had to extract and transport a full-authority shared token. That put secrets near prompts and transcripts and made individual revocation impossible. | Critical | Setup now has **Connect your agent**, pending-code approval/denial, and per-client revocation. Verification codes expire and cannot poll without a separate high-entropy secret; stored server records are hashes only. | Pairing expiry, poll-secret, permissions, one-time delivery, and revocation have unit coverage. A real CLI flow must run against the candidate. |
| Agent execution context | Instructions did not make clear whether a desktop agent, SSH agent, or cloud web fetcher could reach the private origin. | High | Packaged guidance and the portable skill identify the execution machine, require explicit profiles/capability discovery, and warn that private Tailscale URLs may be unreachable to cloud fetch tools. | Exact docs are served by workspace and runner. A real Claude Code session remains a release gate. |
| SSH keys and passwords | Password login was available only through desktop terminals; key guidance could invite copying a private key into the workspace. | Critical | OpenSSH accepts the user-created Linux password and public keys. API-managed keys live in a separate authorized-keys file and return fingerprints, never key bodies; password changes remain a browser handoff. | Unit tests prove API/user key-file isolation and reject multiline/private material. Live password/key/Remote-SSH tests remain. |
| Native VNC | Browser VNC does not satisfy native-client workflows, but reusing its local passwordless x11vnc listener would bypass the Linux-password contract. | Critical | A separate PAM-backed x11vnc service uses the full Linux password on container port 5901. Host publication stays loopback and can be disabled independently. | Supervisor/config contracts are automated; a real native client and full-password exchange remain a release gate. |
| Browser editor | The workflow required a separate manual editor choice and gave no persistent browser destination. | Medium | Pinned, checksum-verified code-server is an optional catalog component at `/editor/`, rooted in `/projects`; Home advertises Setup until it is running. | Catalog/install contracts and browser routing are automated. Full install, restart, and project persistence remain disposable gates. |
| Client installation | Requiring a language runtime or sudo would block nontechnical users and a partial upgrade could destroy a working client. | High | `cli.sh` supports Linux/macOS amd64/arm64, HTTPS plus release checksum verification, atomic user-owned installation, and explicit PATH guidance without profile edits. | Shell harness tests cover platform selection, success, checksum/download failure, upgrade preservation, and PATH output. |
| Multiple targets | Implicit target choice can run a command or lifecycle mutation against the wrong workspace. | Critical | Profiles retain server kind and stable identity; compatible commands require `--profile` whenever selection is ambiguous. URLs are origins, custom CAs are explicit, and credentials do not cross origin-changing redirects. | Go tests cover URL/redirect/profile modes; CLI acceptance must exercise multiple profiles and version mismatch. |
| Host provisioning | Giving agents Docker or arbitrary launch flags would grant host authority and make storage/port ownership unverifiable. | Critical | Only the root runner opens Docker. Operators approve immutable image IDs; remote requests contain bounded template/resource/port fields only. SQLite records ownership/intent and Docker establishes observation. | Store/HTTP/manager tests cover permissions and conflicts; disposable two-instance lifecycle and daemon-restart fault tests remain. |
| Updates and recovery | Removing the old container before application restoration could leave an unusable replacement and no fast rollback. | Critical | Candidate replacement shares the recorded volumes, keeps the old generation until health/restoration, commits selection before deleting old, and restarts old on failure. Migration rollback limits are explicit. | Unit reconciliation tests plus disposable failed-provision/restore/update/restart scenarios are required. |
| Ports and origins | Reusing a port or browser origin can steal another listener or collide cookies/PWA state. | Critical | Allocations are transactionally recorded, checked against listeners/Docker/Serve, and finally decided by Docker bind. Every workspace receives distinct loopback ports/origin. | Explicit-port conflict and two-origin browser storage tests remain disposable gates. |
| Installation failures | A zero-exit installer could still leave missing probes, and terse failure state made recovery unclear. | High | Setup requires probe convergence, keeps selected/missing state, exposes bounded logs and retry state, and runner readiness separates restoration from infrastructure health. | Existing setup failure/concurrency tests pass; disposable restoration failure remains. |

## Browser-only 403 investigation

The first disposable guided-workspaces candidate reproduced the reported 403
in real Chrome while an ordinary `curl` request returned 200. Its nginx access
record showed a top-level `GET` with `Sec-Fetch-Site: cross-site` and
`Sec-Fetch-Mode: navigate`; Chrome used `Sec-Fetch-Dest: empty` for the
extension-initiated navigation. The global metadata rule rejected the safe
navigation before routing.

The corrected boundary accepts `cross-site` or `same-site` only for an exact
safe `GET`/`HEAD` top-level navigation with destination `document` or the
extension-generated `empty`. Cross-site subresources, API mutations, and
ttyd/noVNC WebSocket upgrades remain rejected;
malformed and duplicate metadata still fails closed. Access records now retain
all three fetch-metadata fields for correlation. Unit and in-container checks
cover both the safe navigation and rejected subresource cases. The release
gate remains empirical: run both Playwright projects against the rebuilt
disposable candidate, inspect the real custom shell with Chrome, confirm no
unexpected 403 in network/console evidence, then repeat through the private
HTTPS origin. Custom hostnames must be explicitly allowlisted; generic client
URL support does not make the root-scoped PWA support arbitrary proxy subpaths.

## Verification ledger

Evidence recorded on 2026-09-11. The occupied host port 18080 was left alone;
disposable image acceptance used 18082. After all candidate gates passed, the
live `vibestack` container was replaced with the accepted digest using its
existing `/data` and `/projects` bind mounts. Saved applications converged
while the prior container remained available for rollback; the post-deployment
live check and existing private HTTPS route then passed.

| Gate | Result and evidence |
|---|---|
| Fast repository tests | **Passed.** `bin/vibestack-dev test` completed 289 Python tests plus all Go tests and vet checks after the final source diff. Final static CLI builds succeeded for Linux and macOS on amd64/arm64; runner builds succeeded for Linux on amd64/arm64. |
| Candidate | **Passed.** `vibestack:guided-20260911` at `sha256:bd03f1229813c80788f746245a7443e2e6e61f618bfdc152f38a32a4851ee54e` passed full disposable acceptance, including password/sudo, pinned editor, Godot, a real stable-Flathub Calculator install, two replacement cycles, and application/password restoration. Flathub's static-delta CDN returned repeat HTTP/2 errors, so the acceptance install used Flatpak's full-object `--no-static-deltas` path. |
| Browser | **Passed for automated and host Chrome surfaces.** All 30 desktop and iPad-sized Playwright cases passed. Real Chrome extension navigation reached the private HTTPS onboarding page and `/vnc/`, reported Connected, and had no console errors, closing the browser-only 403 investigation. |
| Runner | **Passed for the disposable host flow.** A locally paired CLI created two simultaneous instances with separate port triplets, credentials, `/data` volumes, and `/projects` volumes. The run covered idempotent create retry, occupied-port rejection without disturbing port 8080, upload/argv execution/retrieval, stop/start persistence, successful replacement, an interrupted operation across daemon restart, invalid-image rollback to the prior healthy container, retained-on-remove volumes, explicit purge, and client revocation. |
| Access | **Partially passed.** Browser VNC and native-VNC service coexistence, Linux password persistence, editor persistence, and real SSH public-key authentication as `vibe` passed. A native VNC client full-password exchange and desktop VS Code Remote SSH were not run on this host and remain release gates. |
| Client install | **Contract and simulated-platform tests passed.** Download/checksum failure, atomic upgrade preservation, architecture selection, and PATH guidance are automated. Static binaries cross-built for every release target. A real macOS installer execution remains a release gate. |
| Agent | **Passed.** A real Claude Code 2.1.263 session read the exported portable skill, used a temporary paired live-workspace profile, ran doctor/capability discovery, uploaded an 18-byte project file, completed an argv copy job, and retrieved the exact result. The two remote test files were removed, the client was revoked and verified unauthorized, and its temporary profile/skill directory was removed. No credential entered the prompt or output. |
| Private route | **Passed.** A temporary exact Tailscale Serve mapping on HTTPS 9444 targeted only the disposable candidate. Discovery, onboarding, and connected browser desktop checks passed; the exact mapping and disposable data were removed without altering the existing Serve entries. |
| Physical | **Not run; hardware unavailable.** Safari Home Screen install and iPadOS 17+ portrait/landscape/touch/keyboard/background/recovery checks remain release gates. |
