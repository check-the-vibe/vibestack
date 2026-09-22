# Agent overlay

VST-015 replaces the browser canvas chrome with one agent icon and a nonmodal
panel. This describes source on its ticket branch; see
[the ticket](../../.context/tickets/VST-015.md) for deployment and acceptance.
The provider contract is [separate](provider-runtimes.md).

## Use the panel

1. Open `/vnc/` or the root URL. Click the agent icon, or focus it and press Enter.
2. Connect with a workspace credential if no browser session exists. This is
   workspace authorization, separate from Linux and provider sign-in.
3. On a new desktop, set the Linux password using its direct form. It never goes
   into chat. Owner authority is required; no default password is introduced.
4. Choose the provider and Activate. Follow installation/process/login state.
   Open sign-in app if needed and complete the provider's own human handoff.
5. Refresh status, select a configured model and existing project folder, then
   send a task. Activation alone does not prove account access or model quota.
6. Review native action details before an explicit Allow once or Decline.
   An incomplete preview can only be declined. Stop turn requests interruption;
   it never claims that previous edits were undone.

Agent setup collapses after sending. Closing/Escape preserves page memory and
native work, returning focus to the icon. Pointer input outside the panel remains
available to the desktop. Switching provider clears the displayed conversation
without forwarding its history. The conversation selector retrieves stored IDs
and available transient events. Reloaded/evicted events display a gap; open the
native application for its saved transcript. The backend currently has no
conversation-delete operation and has explicit retention/capacity limits.

## Security and recovery

All capability calls use the existing instance-bound session/CSRF dispatcher.
The frontend is catalog-driven and passes no executable, installer URL, provider
origin or environment. Provider output uses text nodes, never HTML. Pending human
approvals bind exact server handles to their conversation/operation, and a lost
answer is not automatically retried. Lost submission replies never create a
second operation. Native providers can run commands as the full `vibe` user.

Credentials and Linux passwords are cleared from forms after submission and when
closing the panel; they never enter chat, browser storage or diagnostic payloads.
Prompt/event text is page memory only. The DOM retains at most 160 message nodes,
512 KiB text overall and 64 KiB per message, with an explicit missing-history notice
on truncation. Requests and response parsing are bounded. Browser sign-out closes
the RFB connection. No model/provider account is silently reused from the host.

The desktop renderer uses public noVNC RFB, fit scaling and balanced quality;
`resizeSession` stays off. It handles bounded reconnect after unexpected connection
loss, manual recovery, offline state and fail-closed native security challenges.
The old renderer preference controls are gone; the authenticated control API
remains available. Service-worker caches exclude live API/auth/MCP data.

## Migration and evidence

`desktop/index.html`, `app.js` and `app.css` own the new surface. Old root navigation
parameters no longer reopen terminal/editor/settings/apps views. The VST-016 migration removes
standalone old routes, services and assets; safe bookmarks redirect to the overlay
while authenticated setup APIs and existing data remain.
The outer Codespaces editor and shared `/projects/vibestack` source remain.

Browser fixtures use an additional simulated provider to verify catalog-driven
setup, isolated credentials/password forms, streaming, owner decisions, inert
rendering, uncertain replies, focus and narrow layouts. They use no real accounts
and do not establish model compatibility. Full candidate image/browser checks
and real signed-in provider turns remain separately required. Physical iPad
keyboard/native sign-in behavior is not established by viewport emulation.
