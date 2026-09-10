# noVNC shell, resize, and iPad PWA research

Status: implementation decision record, 2026-09-07. VibeStack pins noVNC
1.7.0. Browser/device observations that still require a physical iPad are
called out as acceptance work rather than presented as completed research.

## Decision

VibeStack owns the complete browser UI and imports noVNC's public `RFB` class.
It does **not** fork the RFB implementation or customize upstream `vnc.html`.
The image retains the pinned upstream `core/` tree and its relative `vendor/`
dependencies, served read-only from `/novnc/core/` and `/novnc/vendor/`; the VibeStack application is a
dependency-free set of HTML, CSS, and JavaScript ES modules served at `/vnc/`.

This is the narrowest maintained seam. The [noVNC 1.7 API document][novnc-api]
defines a single `RFB` object per connection, constructed with a target element
and a WebSocket URL. The tagged [`rfb.js` source][novnc-rfb] exports that class,
imports its engine dependencies by relative path, and warns that modern APIs
may fail outside a secure context. Upstream UI files are therefore neither the
integration surface nor a source of application state.

```js
import RFB from "/novnc/core/rfb.js";

const scheme = location.protocol === "https:" ? "wss" : "ws";
const socket = `${scheme}://${location.host}/vnc/websockify`;
const rfb = new RFB(document.querySelector("#screen"), socket, { shared: true });
```

The same-origin URL is intentional: it works with a non-default host port and
with an HTTPS terminator without injecting a hostname into the page.
Nginx forwards the public authority with `$http_host` and overwrites a fixed
`X-VibeStack-Proxy` marker on the upgrade. Ubuntu 24.04's websockify 0.10 auth
plugin API receives an `HTTPMessage`; VibeStack's root-owned plugin uses
`get_all()` so a missing, wrong, or duplicate marker is rejected before the
VNC connection. This closes direct-loopback WebSocket access from an untrusted
page in the in-container browser. The marker is intentionally not described as
a secret because it is checked into both proxy and backend configuration.

## noVNC 1.7 integration surface

Only documented public members may be called by VibeStack:

| Concern | noVNC API | VibeStack behavior |
|---|---|---|
| Lifecycle | `connect`, `disconnect` | Drive connecting, connected, reconnecting, offline, and failed UI states. `disconnect.detail.clean === false` is eligible for automatic reconnect. |
| Authentication | `credentialsrequired`, `sendCredentials()` | Show a transient credential prompt if a future VNC server asks. Never store credentials. The current passwordless x11vnc path should not emit this event. |
| Security | `securityfailure`, `serververification`, `approveServer()` | Stop automatic retries on a security failure. Do not automatically approve an identity; show a blocking error until a deliberate verification UI exists. |
| Naming | `desktopname` | Use the supplied name as text only, never HTML. |
| Clipboard | `clipboard`, `clipboardPasteFrom(text)` | Put received text in the Controls clipboard dialog and send only after a user action. Clipboard text is memory-only. |
| Keyboard | `focus()`, `blur()`, `sendKey()`, `sendCtrlAltDel()` | Provide focus, explicit modifier keys, and Ctrl-Alt-Delete controls. Release any latched modifier when Controls closes, on disconnect, or on page hide. |
| Display | `scaleViewport`, `clipViewport`, `dragViewport` | “Fit” sets local scaling; “1:1” disables scaling and enables clipping/panning. |
| Encoding | `qualityLevel`, `compressionLevel` | Integer controls from 0 through 9. VibeStack's balanced default is quality 7 and compression 2; clarity is 9/2 and constrained-link is 5/6. |
| Safety | `viewOnly` | Prevent remote pointer and keyboard events while leaving observation and shell controls available. |
| Remote resize | `resizeSession` | Keep false. One-shot and opt-in automatic screen matching use the bounded OS control API and XRandR, not RFB SetDesktopSize. |
| Capture | `toBlob()`, `toDataURL()`, `getImageData()` | Available for a later screenshot tool; not required in v1. |

The relevant property ranges and event detail shapes are fixed by the tagged
API. Shell code must not read underscore-prefixed fields or import UI modules.
Upgrade review must compare this table against the new tag before changing the
pinned version.

## Input and iPad findings

noVNC 1.7 contains its own keyboard and gesture handlers, and `focusOnClick`
defaults to true. This is useful groundwork, not evidence that every iPad
interaction is correct. Safari can reserve gestures, change the visual viewport
when the software keyboard opens, suspend a backgrounded web app, and restrict
clipboard APIs to secure contexts and user gestures. Therefore:

- the remote canvas occupies `100dvh`, with a `100vh` fallback, and the page
  uses `viewport-fit=cover` plus all four `env(safe-area-inset-*)` values;
- shell controls use at least 44 by 44 CSS pixel hit targets and do not depend
  on hover;
- the root launcher and shell expose touch-sized Desktop/Terminal choices; the
  shell embeds ttyd from the same origin instead of forking or rewriting it;
- keyboard, clipboard, modifiers, Ctrl-Alt-Delete, and one-shot screen matching
  live in a top **Menu** disclosure alongside Settings and Tools instead of a
  persistent bottom dock or separate top-level drawer buttons;
- portrait and landscape each keep the status bar and drawer close button
  reachable; the desktop may letterbox rather than crop;
- a visible keyboard/focus control gives the user an intentional way to summon
  the software keyboard, while Bluetooth keyboard events continue to target
  the RFB element;
- `visibilitychange`, `online`, and `offline` update UI state; returning to the
  foreground reconnects only when the connection is no longer live;
- browser clipboard reads/writes must be initiated by a button and failure must
  leave editable text available for manual copy or paste.

Physical iPadOS 17+ testing remains a release gate. Desktop responsive mode and
an iOS simulator are useful prechecks but do not satisfy the gate.

## Resize findings and decision

There are two independent resize mechanisms:

1. **Local scaling** changes only browser presentation through
   `RFB.scaleViewport`. It is the safe default and requires no server support.
2. **Remote framebuffer sizing** changes Xvfb/XFCE dimensions. noVNC's
   `resizeSession` sends the RFB SetDesktopSize extension, whose effect depends
   on server support. VibeStack does not rely on that implicit path in v1.

The earlier live spike showed that the virtual display could move to 1280x800
and 1440x900 and that x11vnc could observe XRandR changes. The implementation
spike also confirmed a generated 1256x600 mode without stopping x11vnc or XFCE.
Physical-device validation remains open, so the shipped mechanism is bounded
and conservative:

- install `x11-xserver-utils`, start x11vnc with `-xrandr resize`, and keep the
  six boot-time presets, including the 1920x1200 default;
- accept widths from 640 through 1920 aligned to 8 pixels and heights from 480
  through 1200 aligned to 2 pixels, further capped by the framebuffer maximum
  reported by XRandR;
- for a valid missing mode, run `cvt`, parse only its numeric timings and sync
  flags, then use argv-only `xrandr --newmode` and `--addmode` calls against the
  parsed connected output;
- apply the requested mode as `vibe`, re-query XRandR to confirm it, and discard
  the prior generated mode after it is inactive so viewport changes do not
  accumulate modes indefinitely;
- derive **Match screen** dimensions from the rendered desktop stage in CSS
  pixels, not physical device pixels. Preserve its orientation and aspect as
  far as the bounds/alignment permit, then keep local `scaleViewport` fitting
  as a presentation fallback;
- expose the one-shot action in the top Menu popover. The Settings toggle
  makes viewport matching automatic only after the user opts in; it defaults
  off, debounces changes for 650 ms, ignores transient viewport changes while
  hidden or editing text, and retries after a resize-related VNC disconnect;
- retain the last confirmed resolution when a command fails and return a
  structured error; the UI does not infer success from HTTP status alone.

`RFB.resizeSession` remains false. Keeping browser observation and OS mutation
as separate steps avoids relying on x11vnc's RFB SetDesktopSize behavior and
lets VibeStack validate every requested dimension before creating a mode.

## PWA findings and cache policy

The [Web App Manifest specification][manifest] defines `start_url`, `scope`,
and presentation modes. WebKit documents that a site added to the iOS/iPadOS
Home Screen is promoted to a web app when manifest display is `standalone` or
`fullscreen` ([WebKit Home Screen guidance][webkit-home]). VibeStack uses:

- `start_url: "/"`, `scope: "/"`, and `display: "standalone"`, so every fresh
  launch offers the Desktop/Terminal chooser;
- application name, short name, theme/background colors, and 192px/512px icons,
  including maskable purpose where the asset has a safe zone;
- a root-scoped `/service-worker.js` with `Service-Worker-Allowed: /`;
- versioned static caches and network-first navigation for `/` and `/vnc/`;
- network-first VibeStack HTML/CSS/JavaScript (with cached fallback), so an
  online launch cannot pair fresh markup with stale application code, and
  cache-first pinned noVNC modules and versioned icons;
- no caching for `/api/`, `/terminal/`, `/setup/`, WebSockets, logs, clipboard,
  or any non-GET request;
- a cached offline shell that clearly says the remote desktop needs a network.

Service workers and noVNC's modern browser APIs require a secure context for
remote-device use. VibeStack stays HTTP-only inside the container. The
recommended deployment is HTTPS on the tailnet via [Tailscale Serve][serve],
which proxies to the local HTTP port. Plain HTTP remains a desktop-development
mode and is not PWA acceptance on an iPad.

The service worker may cache only the exact VibeStack shell files and noVNC
modules required by the pinned tag. It must delete prior named caches during
activation. An update must not take control mid-session: install in the
background, present an “update available” action, and reload only after the
user accepts or on the next fresh launch.

Cache generations use an image-build content fingerprint of both the shell and
noVNC module trees. This prevents a waiting worker from writing new responses
into the active worker's cache before the user accepts the update.

## Security and update conclusions

- The deployed private network is the authentication boundary in v1. Neither
  VNC, terminal, setup, nor control routes may be exposed to the public web.
- Same-origin checks reduce cross-site mutation risk but are not authentication.
- The OS bridge must accept logical IDs and presets only. No request-controlled
  executable, shell fragment, supervisor program, file path, display output,
  or log path crosses the privilege boundary.
- Static responses use a restrictive Content Security Policy and disallow
  embedding by foreign origins. Dynamic log and desktop names are assigned as
  text, never `innerHTML`.
- The noVNC source is MPL-2.0. Preserve its license and source notices. Pin the
  release and verify the downloaded archive with a recorded SHA-256 before
  extraction; a version string alone protects against drift, not a replaced
  artifact.
- For an upstream upgrade: read tagged release notes and API docs, update the
  compatibility table, verify the archive hash, build a disposable image, run
  unit/browser/RFB checks, then repeat physical iPad acceptance. Never merge an
  upstream UI change into the custom shell.

## Release research checklist

- [ ] Fresh HTTPS Home Screen install launches `/vnc/` without Safari chrome.
- [ ] Portrait, landscape, rotation, safe areas, and software-keyboard viewport
      changes leave all recovery controls reachable.
- [ ] Tap, drag, right-click gesture, scroll, Bluetooth keyboard, on-screen
      keyboard, modifiers, Ctrl-Alt-Delete, and clipboard are verified.
- [ ] Network loss, foreground/background, x11vnc restart, and container restart
      recover without an infinite retry loop or stuck modifiers.
- [ ] All six display presets plus representative landscape and portrait
      Match-screen sizes update the framebuffer or return a truthful error;
      repeated automatic changes do not materially leak CPU or memory.
- [ ] A service-worker update is observed across two versions and never reloads
      an active remote session without consent.
- [ ] Direct HTTP clearly remains a non-installable development path; the
      documented tailnet HTTPS path passes install and reconnect tests.

[novnc-api]: https://github.com/novnc/noVNC/blob/v1.7.0/docs/API.md
[novnc-rfb]: https://github.com/novnc/noVNC/blob/v1.7.0/core/rfb.js
[manifest]: https://www.w3.org/TR/appmanifest/
[webkit-home]: https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/
[serve]: https://tailscale.com/docs/reference/tailscale-cli/serve
