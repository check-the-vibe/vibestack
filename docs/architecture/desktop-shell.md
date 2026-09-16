# Desktop shell architecture

Status: v1 implementation contract. This document owns the browser-shell and
OS-control boundaries; `docs/SPEC.md` remains the product-level acceptance
source of truth.

## System shape

```text
 iPad/desktop browser (one origin)
 ┌──────────────────────────────────────────────────────────────┐
 │ / default Desktop -> /vnc/ VibeStack shell                     │
 │  ├─ Desktop: RFB adapter ── WebSocket /vnc/websockify        │
 │  ├─ Terminal: same-origin frame ───────────── /terminal/     │
 │  ├─ Controls/Settings/Tools ─ JSON /api/v1/*                 │
 │  └─ PWA manifest + root-scoped service worker               │
 └─────────────────────────────┬────────────────────────────────┘
                               │ HTTP, normally inside tailnet HTTPS
 nginx :80                     │ termination
 ┌─────────────────────────────┴────────────────────────────────┐
 │ static shell + noVNC modules │ WebSocket │ reverse proxies   │
 └──────────────┬───────────────┴─────┬─────┴─────────┬────────┘
                │                     │               │
 noVNC core     │             websockify :6080  control :7998
 (static only)  │                     │               │
                │                x11vnc :5900     fixed helper
                │                     │          (supervisor/logs)
                └────────────────── Xvfb :0 + XFCE ── xrandr
```

Supervisor owns D-Bus, Xvfb, x11vnc, websockify, XFCE, ttyd, setup, the control
service, and nginx. The browser never addresses their internal ports.

## Ownership and module boundaries

### VibeStack shell

The application under `desktop/` is plain HTML, CSS, and JavaScript ES modules.
There is no build tool, runtime Node dependency, framework, or upstream noVNC UI
code. It owns layout, state, accessibility, PWA registration, preferences,
drawers, connection messaging, and user confirmations.

The RFB adapter imports only `/novnc/core/rfb.js` and wraps one live `RFB`
instance. UI code talks to that adapter rather than underscore-prefixed noVNC
members. Creating a connection derives `ws:` or `wss:` from the page protocol
and uses `location.host` plus `/vnc/websockify`.

Exactly these preferences are stored at
`vibestack.desktop.preferences.v1` in `localStorage`:

```json
{
  "scaleMode": "fit",
  "qualityLevel": 7,
  "compressionLevel": 2,
  "viewOnly": false,
  "reconnect": true,
  "autoResize": false
}
```

Invalid, missing, or out-of-range fields fall back independently to defaults.
No credential, clipboard text, log output, API response, display state, or
connection error is persisted.

The connection state machine is:

```text
idle -> connecting -> connected -> disconnecting -> idle
             |            |
             v            v (unclean, reconnect enabled and online)
           failed <-> reconnecting -> connected
```

Only one `RFB` object and one reconnect timer may exist. Security failures and
credential/verification requirements never enter automatic retry. Unexpected
disconnects retry after 1, 2, 4, 8, then 10 seconds; after five failures the
shell remains failed until Retry. Going offline pauses the timer; an `online`
event permits the next attempt. Disconnect, page hide, and object replacement
release latched modifier keys.

### OS control service

`control/server.py` is a Python standard-library HTTP server running as `vibe`
on `127.0.0.1:7998`. It owns parsing, validation, JSON response headers, a
non-blocking process-wide mutation lock, and orchestration. It does not accept
commands or paths.

`control/controllib.py` owns the fixed service/log allowlists, display bounds,
alignment rules, and preset resolutions. It invokes subprocesses with argv
arrays and timeouts, never a shell.
`vibestack-control` is the fixed privileged helper used for supervisor status,
restart, and allowlisted log reads. Display queries and changes run as `vibe`
against `DISPLAY=:0`; the connected output name is parsed and syntax-validated
before use.

Logical service mappings are fixed in code:

| Public ID | Supervisor program | Log source |
|---|---|---|
| `desktop` | `xfce4` | `/data/logs/vibestack/services/xfce4.log` |
| `vnc` | `x11vnc` | `/data/logs/vibestack/services/x11vnc.log` |
| `terminal` | `ttyd` | `/data/logs/vibestack/services/ttyd.log` |
| `setup` | `vibestack-setup` | `/data/logs/vibestack/services/vibestack-setup.log` |
| `ssh` | `ssh` | `/data/logs/vibestack/services/ssh.log` |
| `native-vnc` | `native-vnc` | `/data/logs/vibestack/services/native-vnc.log` |
| `editor` | `code-server` | `/data/logs/vibestack/services/code-server.log` |

The helper cannot address nginx, the control/automation services themselves,
arbitrary supervisor names, or arbitrary files. `vibe` has passwordless sudo
only for `vibestack-control`, `vibestack-install`, and `vibestack-password`;
each helper has its own fixed grammar. Once onboarding configures the Linux
password, all other sudo commands require it through PAM.
Native VNC runs as root for PAM access and therefore uses x11vnc's `-noshm`
capture path; Xvfb belongs to `vibe` and rejects a root-owned MIT-SHM segment.

### nginx and routes

| Public route | Behavior and cache policy |
|---|---|
| `/` | Static Desktop/Terminal launcher; incomplete onboarding redirects client-side to `/setup/`; no-cache. |
| `/vnc` | Relative 302 to `/vnc/`. |
| `/vnc/` | VibeStack Desktop/Terminal shell; static files are no-cache. |
| `/vnc/websockify` | WebSocket proxy to websockify/RFB. Never cached. |
| `/novnc/core/`, `/novnc/vendor/` | Pinned upstream runtime modules. No directory listing. |
| `/api/v1/` | Proxy to the loopback control service. Responses are `no-store`. |
| `/api/v1/automation` | Proxy to the separate bearer-authenticated automation service. Never cached. |
| `/terminal/` | Existing ttyd proxy. Never service-worker cached. |
| `/editor/` | Optional code-server proxy. Never service-worker cached. |
| `/setup/` | Password and component setup proxy; redirects to `/` only when both are complete. Never service-worker cached. |
| `/.well-known/vibestack` | Public identity/version/API/pairing discovery without credentials or inventory. |
| `/AGENTS.md`, `/CLI.md`, `/AUTOMATION.md`, `/RUNNER.md` | Version-matched, non-cacheable Markdown guidance. |
| `/cli.sh`, `/skills/vibestack/SKILL.md` | Secret-free client bootstrap and portable skill. |
| `/manifest.webmanifest` | Root-scope install metadata; no-cache for update discovery. |
| `/service-worker.js` | Root-scoped worker; no-cache and `Service-Worker-Allowed: /`. |
| `/icons/` | Versioned application icons. |

The upstream `/novnc/vnc.html` is blocked. Only the pinned `/novnc/core/` and
`/novnc/vendor/` protocol modules are exposed; VibeStack owns every visible UI
route.

Before selecting any route, nginx accepts only loopback Host values, valid
multi-label `.ts.net` names, and exact hostname/IP values validated from the
operator's bounded `VIBESTACK_ALLOWED_HOSTS` list. An optional browser Origin
must be HTTP(S) and match the exact Host authority case-insensitively; its
scheme may differ after Tailscale TLS termination. Missing Origin remains valid for CLI clients, while
malformed, null, duplicate, and cross-authority values are rejected. A safe
top-level `GET`/`HEAD` is the only request allowed to carry exact
`cross-site`/`same-site` and `navigate` metadata, with destination `document`
or extension-generated `empty`; subresources, mutations, and the ttyd and
noVNC WebSocket upgrades remain rejected.

For the two browser streams nginx also replaces any inbound
`X-VibeStack-Proxy` value with a fixed marker. It preserves the public
authority with `$http_host`, including a non-default Tailscale port. ttyd
requires that marker and enables its WebSocket Origin/Host check. A root-owned
websockify authentication plugin uses `Message.get_all()` to require exactly
one constant-time exact marker match before opening the VNC target. This blocks
a page running in the in-container browser from opening raw loopback
WebSockets: browser WebSocket APIs cannot add the marker. The checked-in marker
is not a credential and does not replace the loopback/private-network boundary.

At image build time, the worker cache name is replaced with a content
fingerprint covering the shell and pinned noVNC runtime. A waiting worker thus
stages into its own cache and cannot replace assets used by the active worker;
old generations are removed only when the new worker activates after consent
or a fresh launch.

Static shell responses set `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, a permissions policy disabling camera,
microphone, and geolocation, and a CSP limited to same-origin scripts/styles,
images plus `data:`/`blob:`, same-origin `ws:`/`wss:` connections, and no
objects, foreign framing, base URL, or foreign form actions.

## Browser information architecture

Desktop is the default landing page (`/` opens `/vnc/`). Navigation retains
Desktop, Terminal, Editor, and Settings. Apps and Settings are contextual
sidebars; `/?panel=apps` and `/?panel=settings` force them open, including when
onboarding was completed earlier. The same parameters work on `/vnc/`.
After a successful password submission, Setup opens `/vnc/?panel=apps`.

Apps opens the full-screen searchable catalog at `/setup/?force=1&screen=apps`.
Packs reuse the existing catalog presets; choosing a pack selects its supported
components, and Install submits the existing durable install operation. Search
never clears the selection. An optional `pack=<catalog-preset-id>` selects a pack
without installing it. Password changes remain available from Settings at
`/setup/?force=1&screen=password`.

Terminal (`/vnc/?view=terminal`) and Editor (`/vnc/?view=editor`) each fill the
workspace beneath its navigation. Their Back control and browser Back return to
Desktop, including on direct entry. The underlying `/terminal/` and `/editor/`
services remain separate same-origin frames. If Editor is unavailable, its view
offers installation instead of loading a broken frame. No new API authority or
storage migration is introduced. Patches and later image updates must preserve
existing `/data`, `/projects`, attached drives, passwords and saved selections.

```text
Landscape / desktop
┌───────────────────────────────────────────────────────────────────────┐
│ VibeStack  [Desktop Terminal Editor Settings] ● Connected       Menu  Focus  Full │
├────────────────────────────────────────────────────────────────────────┤
│ Keyboard Clipboard | Ctrl Alt Super CAD | Match | Settings Tools │
│                                                                       │
│                       remote desktop canvas                           │
│                                                                       │
│                                        ┌─────────────────────────────┐│
│                                        │ active drawer          Close││
│                                        │ apps, settings or tools           ││
│                                        └─────────────────────────────┘│
└───────────────────────────────────────────────────────────────────────┘

Portrait / software keyboard
┌───────────────────────────────────┐
│ VibeStack [D T] ●       Menu … │
├───────────────────────────────────┤
│ Keyboard Clipboard Ctrl Alt       │
│ Super CAD Match Settings Tools    │
│                                   │
│        scaled desktop canvas      │
│                                   │
└───────────────────────────────────┘
The Menu popover overlays from below the top bar and wraps without changing
the desktop-stage dimensions. It is collapsed by default, closes on Escape or
an outside action, and returns focus to its trigger. There is no persistent
bottom control dock. A drawer overlays from the safe-area edge and scrolls
independently.
```

The `view` query parameter selects the initial tab and defaults safely to
Desktop. Tab changes use `pushState`, respond to back/forward navigation, and
retain unrelated query parameters. A terminal-first launch avoids opening RFB;
switching from Desktop releases input and disconnects RFB, while returning to
Desktop starts a fresh connection. The terminal iframe remains loaded while it
is hidden so the ttyd/tmux interaction is immediately available on return.

The permanent status area shows connecting/connected/reconnecting/offline/
failed state with text as well as color. A non-modal banner carries recoverable
errors and Retry; a blocking card covers the canvas only when no connection is
usable. Opening a drawer moves focus to its heading/close action, traps focus,
closes on Escape, and returns focus to the invoker. Touch targets are at least
44 CSS pixels.

Settings contains:

- Fit and 1:1 scaling (`scaleViewport`; 1:1 uses clipping and drag-to-pan).
- JPEG quality 0–9 and compression 0–9.
- View-only and automatic reconnect toggles.
- An automatic **Match screen** toggle, off by default, plus current remote
  resolution and the API's available fixed/current modes.

The top Menu popover contains:

- the software-keyboard trigger and memory-only Clipboard dialog;
- latched Ctrl/Alt/Super buttons and Ctrl-Alt-Delete;
- one-shot **Match screen**, which is usable without enabling automatic mode;
- the Settings and Tools drawer launchers.

Tools contains:

- Four service cards with status, a confirmation-gated Restart action, and a
  bounded text log viewer.
- Same-origin links to Terminal and Setup, opening predictably in a new browser
  tab outside installed standalone mode.

Focus and fullscreen are permanent top-bar actions. Disconnect is in Settings;
connection failures expose Retry in recovery UI. Clipboard text received from
Linux never writes the device clipboard without an explicit gesture.

Restarting `vnc` is a special recovery flow: after the successful API response,
the RFB disconnect is expected and the normal reconnect state machine resumes.
Restarting `desktop` may blank or redraw the framebuffer but should not create a
second RFB object. Restarting `terminal` or `setup` does not affect RFB.

## Control API v1

All responses are UTF-8 JSON with `Cache-Control: no-store`. Errors use:

```json
{"code": "stable_machine_code", "message": "Safe user-facing summary."}
```

### `GET /api/v1/status`

Returns aggregate status. A failed individual probe does not fail the whole
request; that entry has `state: "UNKNOWN"` or a nested `error`.

```json
{
  "apiVersion": "1",
  "uptimeSeconds": 4812,
  "disk": {
    "path": "/home/vibe",
    "totalBytes": 1000000000,
    "usedBytes": 400000000,
    "availableBytes": 600000000
  },
  "display": {
    "resolution": "1920x1200",
    "availableResolutions": ["1280x800", "1440x900", "1920x1200"],
    "supportedResolutions": ["1280x800", "1368x768", "1440x900", "1600x900", "1600x1200", "1920x1200"],
    "dynamicResize": true,
    "bounds": {
      "minWidth": 640,
      "minHeight": 480,
      "maxWidth": 1920,
      "maxHeight": 1200,
      "widthStep": 8,
      "heightStep": 2
    }
  },
  "services": {
    "desktop": {"service": "desktop", "state": "RUNNING", "detail": "pid 40, uptime 0:02:00"},
    "vnc": {"service": "vnc", "state": "RUNNING"},
    "terminal": {"service": "terminal", "state": "RUNNING"},
    "setup": {"service": "setup", "state": "RUNNING"}
  }
}
```

Unavailable numeric disk or uptime fields are `null`; unavailable display data
has `resolution: null`, empty availability, and an `error`.

### `GET /api/v1/display`

Returns `resolution`, `availableResolutions`, the complete preset
`supportedResolutions`, `dynamicResize`, and `bounds`. Availability contains
advertised presets plus the active resolution when it is a generated dynamic
mode. The maximum bounds are capped by XRandR's reported framebuffer maximum.

### `PUT /api/v1/display`

Requires `Content-Type: application/json` and exactly:

```json
{"resolution": "1256x600"}
```

Width must be 640–1920 and divisible by 8; height must be 480–1200 and
divisible by 2. For a valid mode not already advertised, the backend runs
`cvt`, accepts only parsed numeric timing/sync tokens, creates and attaches the
mode with argv-only XRandR commands, switches to it, and re-queries before
reporting success. The previous non-preset mode is removed after it becomes
inactive.

On success, the response has the same shape as `GET /display`. Invalid bounds,
alignment, or syntax return 400 `unsupported_resolution`; a size above the
actual framebuffer maximum returns 409 `display_mode_unavailable`; generation,
command, or confirmation failures return a structured 502 error.

The browser calculates Match-screen requests from the desktop stage's CSS-pixel
rectangle, without multiplying by `devicePixelRatio`. It scales and aligns the
pair within the returned bounds while retaining landscape or portrait shape as
closely as the constraints permit. Automatic mode observes stage/visual
viewport changes with a 650 ms debounce, but is disabled by default and
suspended while hidden or while a browser text editor/software keyboard owns
the viewport. The RFB adapter always sets `resizeSession = false`; local
`scaleViewport` remains independent.

### `GET /api/v1/logs/{service}?cursor=&limit=`

`service` is one of the seven fixed logical IDs. `limit` defaults to 100 and must be
1–200. `cursor` is an optional non-negative byte offset. Without a cursor the
newest `limit` lines are returned; with one, reading continues from that byte.

```json
{
  "service": "vnc",
  "lines": ["07/09/2026 10:00:00 client connected"],
  "nextCursor": 3812,
  "reset": false,
  "truncated": false
}
```

If rotation makes the supplied cursor larger than the file, reading restarts
at byte zero and `reset` is true. Each line is capped at 4096 bytes, pages at
64 KiB, ANSI escape sequences are stripped, nonprinting controls are escaped,
and UI renders every line as text.

### `POST /api/v1/services/{service}/{operation}`

Requires JSON `{}`, one logical service ID, and `start`, `stop`, or `restart`.
Extra fields are rejected. Core shell UI exposes the safe actions relevant to
its current state; CLI clients can manage all published services. Stopping
native VNC leaves browser VNC running. A restart success response is:

```json
{"service": "vnc", "state": "RUNNING", "restarted": true}
```

The browser must ask for confirmation, name the impact, disable the action
while pending, and not optimistically report success.

### Validation and concurrency

- Mutation bodies are JSON objects, at most 4096 bytes, with Content-Length,
  no transfer encoding, no duplicate keys, and exactly the documented fields.
- Mutations require one valid `Host`. If an `Origin` is present its host and
  effective port must match; browser mutations marked `cross-site` or
  `same-site` rather than `same-origin` are rejected. Only safe top-level
  `GET`/`HEAD` document navigations receive the narrow exception. No CORS
  headers exist.
- Missing `Origin` is supported for same-host scripts and is not an auth
  bypass because the private network remains the authorization boundary.
- Only one mutation runs at once. A concurrent mutation receives 409
  `mutation_in_progress`; the browser keeps its existing state and may retry
  after a new status fetch.
- Unknown routes return 404; unsupported methods return 405; unknown queries,
  services, fields, or malformed bodies are rejected rather than ignored.

## Trust boundary and threat model

VibeStack is a single-user development machine, not a public multi-tenant
service. Tailscale or another private network controls who can reach nginx;
Tailscale Serve (or an equivalent trusted reverse proxy) terminates HTTPS. The
container itself is HTTP-only and has no application login. `startup.sh`
publishes nginx on `127.0.0.1` by default; a wider bind requires the explicit
`--bind` option.

Consequences:

- possession of network access permits interactive `/vnc/`, `/terminal/`, and
  setup access, including replacing the Linux password without its old value;
  never publish port 80 directly to the public internet. The full-user
  automation API additionally requires its bearer token;
- the control API still minimizes drive-by/browser abuse through same-origin
  mutation checks, strict body/query parsing, fixed mappings, bounded reads,
  serialized writes, subprocess timeouts, safe error text, and no CORS;
- `Host` and `Origin` remain validation inputs, and a fixed nginx-only marker
  is a browser-direct-access guard for ttyd/websockify rather than a user
  credential; the backends bind loopback and nginx preserves the public
  authority for comparison;
- logs and desktop-provided strings are untrusted output; render with
  `textContent`, and never place them in markup, URLs, CSS, or commands;
- the service worker must not turn dynamic or sensitive responses into durable
  browser storage.

Explicitly out of scope for the narrow control API are arbitrary commands,
paths, processes, logs, power control, package installation, public exposure,
multi-user permissions, or browser-issued RFB SetDesktopSize resizing. An
interactive terminal user may run password-authenticated sudo; the separate
automation contract is documented in `automation-api.md`.

## Failure behavior

| Failure | Required user-visible behavior | Recovery |
|---|---|---|
| Initial WebSocket/RFB failure | Blocking failed state with short reason and Retry; Settings remains reachable. | Manual retry; automatic only for unclean network disconnects. |
| Network offline | Offline label, no retry storm, cached explanatory shell. | Resume attempts on `online` or Retry. |
| Security/identity failure | Blocking security error; never auto-approve or loop. | Fix deployment/server identity, then Retry. |
| VNC restart | Reconnecting state; preserve preferences and drawer state. | Bounded reconnect schedule. |
| Control service unavailable | Desktop remains usable; Tools shows unavailable and keeps mutating actions disabled. | Refresh status; supervisor restarts service. |
| One status probe fails | Only that card/display section is unknown. | Subsequent status fetch. |
| Log rotates | Clear existing streamed view when `reset` is true, then append returned lines. | Continue from `nextCursor`. |
| Display change fails | Keep last confirmed resolution and show API message. | Refresh display; retry Match screen or select an available fixed mode. |
| Mutation collision | Show busy state, do not queue secretly. | Refetch status then user retries. |
| Clipboard permission denied | Keep text editable; explain manual copy/paste. | Explicit user gesture. |
| Service worker update | Never reload an active session automatically. | User accepts update or next fresh launch. |

## Verification contract

Automated unit tests cover API route/method/query/body validation, origin and
Host checks, fixed service/log mappings, cursor/rotation/bounds/sanitization,
argv-only helper calls, status degradation, display parsing and mode
confirmation, timeouts, and mutation serialization.

Container/browser acceptance covers:

- the custom shell (not stock `vnc.html`) loads with no console error, imports
  the pinned RFB engine, and reaches ServerInit through `/vnc/websockify`;
- connection state, clean disconnect, bounded reconnect, focus, modifiers,
  Ctrl-Alt-Delete, clipboard, scaling, quality/compression, view-only, and
  preference restore;
- status/log rendering treats payloads as text; invalid API input is rejected;
- every service restart requires confirmation, reports the real result, and
  VNC restart reconnects automatically;
- all six advertised display presets and representative bounded/aligned dynamic
  modes change and confirm the framebuffer in a disposable container; invalid,
  unavailable, and unconfirmed modes fail truthfully;
- Menu starts collapsed, does not create a bottom overlay, and exposes the
  keyboard, clipboard, modifiers, Ctrl-Alt-Delete, one-shot Match screen,
  Settings, and Tools without separate top-level drawer buttons;
  automatic matching remains opt-in and coalesces viewport changes;
- manifest fields, icon responses, service-worker scope/cache exclusions,
  offline shell, keyboard navigation, drawer focus trap, and color-independent
  status presentation.
- root-launcher destinations and responsive layout, Desktop/Terminal tab
  selection, terminal-first deferred RFB, same-origin iframe loading, and
  back/forward view restoration.

Physical iPadOS 17+ acceptance over a private HTTPS URL covers Home Screen
installation and standalone launch, portrait/landscape/safe areas, touch and
scroll gestures, software and Bluetooth keyboards, clipboard, rotation,
background/resume, network loss/reconnect, display modes, and a two-version
service-worker update. It also covers one-shot and automatic screen matching in
both orientations, including software-keyboard viewport changes. That checklist
is a release gate, not an automated-test substitute.
