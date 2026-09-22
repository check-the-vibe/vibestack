# VibeStack verification runthrough

The implementation is merged to main at `00f4925` and deployed in the new
Codespace below. This includes the provider adapters, agent overlay, removal of
the old web UI/editor/terminal services, and extension-authoring acceptance.
Automated gates pass locally and in the Codespace. Human provider sign-in, real
model turns and remote private-gateway verification remain open; their tickets
stay `in_review` until those checks have evidence.
The later `f5ea1bc` change repairs the extension test's temporary binary build
and documents it; it does not change runtime service behavior. Its GitHub
source/build/acceptance/publication run passed. A real platform restart then
exposed stale X11 boot state; that repair is being accepted before deployment.

## Current workspace

- [VibeStack desktop](https://congenial-space-telegram-qv7995r69wc4pg9-8080.app.github.dev/vnc/?view=desktop)
- [Codespaces editor](https://congenial-space-telegram-qv7995r69wc4pg9.github.dev/)
- [Agent bootstrap guide](https://congenial-space-telegram-qv7995r69wc4pg9-8080.app.github.dev/AGENTS.md)
- [This runthrough on GitHub](https://github.com/check-the-vibe/vibestack/blob/main/.context/runthrough.md)

The desktop runs accepted integration source `f5ea1bc`, deployed on
2026-09-22 after its independent hosted source/build/full acceptance gate passed.
Running image:
`sha256:7890acabbe508fb613b14aa2c9cf1197b590d5268a52f254a4615d979bce7b27`.
The live check passed **88/0**, Docker reports healthy, and Chrome shows the
agent icon and workspace-credential form. The editor is on
`codex/vst-007-codespaces-integration`. Port 8080 was checked as Private in the
Ports table. The machine has four CPUs and 16,377,436 kB RAM.

The source-mount MCP probe passed status, command argv/output, conditional file
updates visible in the actual Git checkout, stale-write denial and screenshot
capture. It used its own disposable container/credential and removed its probe
file; this is not a live browser-login or external GitHub-gateway test.

Editor checkout and running image are separate state. A Git branch
switch shares source immediately at `/projects/vibestack`, but does not replace
image services. Read [the Codespaces guide](github-codespaces.md) before rebuilding.
Do not discard work to change branches: inspect `git status --short` first.

The older Supreme Space Parakeet Codespace retains its accepted VST-015 image;
it was not replaced or deleted as part of the new deployment.

## Verify the deployed overlay

1. Open the desktop URL. Complete GitHub's private-port authentication if asked.
   The visible browser interface should be the desktop canvas and one agent icon.
   Source editing remains in the Codespaces editor; no embedded editor is needed.
2. Open the icon. Connect using your existing owner workspace credential if the
   browser has no application session. GitHub login and VibeStack authorization
   are separate. If a credential is missing, use the local-operator issuance flow
   in [SERVICE.md](../docs/SERVICE.md). Enter it only in the browser's credential
   form; do not put it in this document or chat.
3. On a fresh desktop, set the Linux password in its separate form. Confirm it
   never appears in chat and that the app offers provider setup afterward.
4. Select Codex and Activate. Installation must happen inside VibeStack, show
   progress and end in a clear login/configuration state. Repeated activation
   must not start duplicate processes. Complete your own provider sign-in via
   Open sign-in app, then Refresh status. Installing it creates no account or quota.
5. Select a configured model and project `vibestack`. Send: “Inspect README.md and
   describe this project in three short sentences. Do not change any files.”
   Check streamed text, the correct project and the final turn outcome. A process
   or model listing alone is not a pass for this step.
6. Close/reopen the panel during a harmless turn. It should retain the same
   conversation without another submission and leave desktop input available.
   Use Stop turn and inspect the outcome; existing edits must never be described
   as rolled back merely because interruption succeeded.
7. Exercise one reviewed native approval. Check the complete action and choose
   Decline first. A repeated or stale handle must not authorize anything, and a
   truncated preview must not offer Allow. Then exercise Allow once on a harmless
   action you understand. This is a human decision, not an MCP tool response.
8. Repeat activation, your own sign-in/configuration and one harmless streamed
   turn with OpenCode. Switching providers must not send the prior conversation
   or prompt to the new provider. Native questions/unsupported actions must show
   explicit recovery guidance rather than invented responses.
9. Check the panel at desktop and narrow-phone widths, keyboard Enter/Escape,
   focus return, scrollable controls and inert rendering of text containing HTML.
   Physical iPad software-keyboard/native-login behavior needs a real device;
   viewport tests alone do not establish it.

For the fresh Codespace's first browser credential, the human local operator can
run this in the Codespaces terminal:

```sh
docker exec -u vibe vibestack-codespaces vibestack-service credential create \
  --label browser --owner --output /data/vibestack/browser.token
```

It creates a protected file and prints metadata, not the token. It will not
overwrite an existing file. Copy the file's contents privately into the panel's
credential form using the local-operator procedure in SERVICE.md. Do not share
the credential or password with the coding agent. This grants owner access to
VibeStack, including credential administration and Linux password setup.

## External agent and CLI

Give a harness the exact `/AGENTS.md` URL above. It should discover the existing
service, explain browser/VS Code access, install a verified CLI and connect using
an explicit workspace profile. Keep private GitHub gateway authorization separate
from the scoped VibeStack credential. Use `capability list`, inspect the schema,
and run a granted read before mutations. The published CLI is 0.3.1.

Confirm REST, CLI and authenticated MCP expose the same allowed operations and
return the same instance identity. Native provider sign-in launching and human
approval answering must be absent from MCP. OAuth-only desktop harness support
is not claimed; use the documented tested bearer or stdio path. Outside-gateway
verification remains pending explicit credential authorization.

## Fresh creation and keeping the same Codespace

Congenial Space Telegram was created from main `4894b2c` through Chrome, then
automatically built and started VibeStack without a manual start command. Static
hosting, the guide, private port, source sharing and the baseline live check
passed. It then switched to the integration branch, built and accepted the final
image, and deployed it while retaining these mounts:

| Codespace path | VibeStack path |
| --- | --- |
| `/vibestack-runtime/vibestack/data` | `/data` |
| `/vibestack-runtime/vibestack/projects` | `/projects` |
| `/workspaces/vibestack` | `/projects/vibestack` |

An additional clean Codespace, `ubiquitous-space-system-4qjggp4w762jqj`, was
created through Chrome directly from integrated main `00f4925`. Its automatic
build/start passed without a manual start command. The live check passed 88/0;
the Ports table confirms Private 8080, and it reports four CPUs/16,377,436 kB RAM.
Fresh image: `sha256:8711bfe058f5eccda339222eb2423e3948cec4970e7b35f9bf55e9997336edc8`.
The shared source hashes match. Its first platform stop/resume retained storage,
identity, keys and source, but failed desktop startup because stale X11 lock/socket
state survived the stop. That validation container is paused pending the accepted
repair; the Congenial workspace above remains available. Repeat stop/resume and
outer rebuild after the repair; account continuity also needs signed-in data.
New workspaces can be created from [the GitHub launch page](https://codespaces.new/check-the-vibe/vibestack).

To continue on a new ticket in that same Codespace, inspect Git state, fetch the
new ticket branch and switch without discarding changes. Verify its `.context`
branch manifest and baseline tests. Follow the documented test → tagged build →
disposable accept → preserving deployment sequence when runtime source changes.
The disposable local and hosted gates passed container restart, rollback to the
accepted VST-013 image and return, preserving identity, grants, source/ETags,
jobs, Linux password, selected providers, protected test data and a real native
OpenCode session. They also verified automatic provider reactivation without
replaying a prompt. Actual signed-in account continuity still needs a human test.

## Final verification record

- Main integration: `00f4925`; deployed source/image and URLs recorded above.
- Local and hosted source/build/full acceptance: passed.
- Extension addition/removal across REST, MCP, CLI and browser: passed.
- Fresh baseline creation, private port and same-Codespace branch upgrade: passed.
- Live check: 88 passed, 0 failed; source-mount MCP probe: passed.
- Fresh Codespace directly from integrated main `00f4925`: passed automatic startup/live checks.
- Final-candidate hosted stop/resume/outer rebuild: pending.
- Remote REST/MCP through the private GitHub gateway: pending scoped authorization.
- Codex signed-in stream, approval and interrupt: pending human verification.
- OpenCode signed-in stream, approval and interrupt: pending human verification.
- Disposable upgrade/restart/rollback with native provider state: passed.
- Legacy standalone UI/services removed: passed image/route/browser checks.
- Physical iPad and signed-in account persistence: pending human verification.
- User verification requested and result: pending.

Current source/image/test evidence lives in [VST-014](tickets/VST-014.md),
[VST-015](tickets/VST-015.md), [VST-016](tickets/VST-016.md) and
[VST-007](tickets/VST-007.md). Replace the pending entries with measured outcomes;
do not infer them from implementation or a build alone.
