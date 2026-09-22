# VibeStack verification runthrough

This is a staged checklist for the final user verification. It is not a claim
that every item is deployed. The stable API/MCP/CLI stack is on main at `4894b2c`.
VST-014 provider runtimes and VST-015 overlay are separate feature branches; their
full image checks and real signed-in turns are recorded in their tickets.
VST-016 legacy-service removal and VST-007 fresh-Codespace acceptance remain open.

## Current workspace

- [Codespaces editor](https://supreme-space-parakeet-p7jgg5v9jqh696v.github.dev/)
- [VibeStack desktop](https://supreme-space-parakeet-p7jgg5v9jqh696v-8080.app.github.dev/vnc/)
- [Stable agent bootstrap guide](https://supreme-space-parakeet-p7jgg5v9jqh696v-8080.app.github.dev/AGENTS.md)

The existing desktop still runs accepted VST-013 until a later deployment is
recorded. Its editor checkout and running image are separate state. A Git branch
switch shares source immediately at `/projects/vibestack`, but does not replace
image services. Read [the Codespaces guide](github-codespaces.md) before rebuilding.
Do not discard work to change branches: inspect `git status --short` first.

## Once the replacement image is deployed

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

After final main integration, create a fresh Codespace from
[the GitHub launch page](https://codespaces.new/check-the-vibe/vibestack).
Check the requested minimum of 4 cores/16 GB, automatic build/start, private port
8080, source editor, shared `/projects/vibestack`, persistent desktop data and the
new overlay. Record the actual branch/commit/image; an existing workspace resume
is not a fresh-creation result.

To continue on a new ticket in that same Codespace, inspect Git state, fetch the
new ticket branch and switch without discarding changes. Verify its `.context`
branch manifest and baseline tests. Follow the documented test → tagged build →
disposable accept → preserving deployment sequence when runtime source changes.
Stop/resume, image upgrade and rollback must retain source, credentials, selected
providers and native histories. Record those outcomes in VST-007/VST-016.

## Final verification record

- Deployed branch, commit and exact image: pending.
- Fresh Codespace/editor/desktop URLs and private port: pending.
- Codex signed-in stream, approval and interrupt: pending human verification.
- OpenCode signed-in stream, approval and interrupt: pending human verification.
- Upgrade/restart/rollback with native provider state: pending.
- Legacy standalone UI/services removed: pending VST-016.
- User verification requested and result: pending.

Current source/image/test evidence lives in [VST-014](tickets/VST-014.md),
[VST-015](tickets/VST-015.md), [VST-016](tickets/VST-016.md) and
[VST-007](tickets/VST-007.md). Replace the pending entries with measured outcomes;
do not infer them from implementation or a build alone.
