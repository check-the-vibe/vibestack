# Desktop rendering and noVNC performance audit

Date: 2026-09-07

## Current stack

The deployed system was inspected before changes:

- Ubuntu 24.04.4 LTS, XFCE 4.18, Xorg/Xvfb 21.1.12;
- x11vnc 0.9.16, websockify 0.10.0, pinned noVNC 1.7.0;
- one 24-bit Xvfb framebuffer with XDamage, XFixes, MIT-SHM, and XRandR;
- XFCE compositing disabled;
- no `/dev/dri` mapping or GPU-capable X server;
- noVNC JPEG quality 7 and compression 2 by default;
- a live 1280x800 mode inside a 1920x1200 framebuffer bound.

Ubuntu 24.04 is the correct production base for this tranche: it remains an
LTS through May 2029 and supplies a coherent XFCE/X11 package set. Container
graphics use the host kernel but a software framebuffer, so changing in-image
kernel or Mesa drivers alone cannot improve output.

## Improvements adopted

1. Keep compositor-off, XDamage, XFixes, MIT-SHM, 24-bit color, and the 1 GiB
   shared-memory allocation. These are appropriate for a software VNC desktop.
2. Bind websockify to loopback and send a 30-second heartbeat so idle private
   HTTPS/WebSocket sessions survive proxy and network timeouts.
3. Replace the Docker health check that downloaded the ttyd application and
   triggered four privileged service probes plus XRandR every 30 seconds with
   a cheap nginx/Supervisor health check. This removes avoidable CPU, HTTP log,
   and response traffic.
4. Keep viewport matching opt-in and debounced. Matching the Linux framebuffer
   to the rendered canvas reduces encoded pixels; local fit scaling remains the
   safe fallback.
5. Offer explicit client rendering profiles: balanced, clarity, and constrained
   link. The noVNC API defines quality 0–9 and compression 0–9; higher
   compression trades server CPU for bandwidth and is intended for slower
   links. See the pinned
   [noVNC 1.7 API](https://github.com/novnc/noVNC/blob/v1.7.0/docs/API.md).
6. Keep shell/runtime assets revalidated and content in the versioned service
   worker cache; never cache API, logs, clipboard, screenshots, terminal, setup,
   or WebSocket traffic. Static caching improves launch latency, not RFB frame
   quality.
7. Compress CSS, JavaScript, SVG, manifest, and sufficiently large text/JSON
   responses at nginx for faster cold shell loads. The upgraded RFB WebSocket is
   unaffected, and the 1 KiB threshold avoids spending CPU on tiny control
   responses.
8. Store XFCE's compositor preference as disabled as well as starting
   `xfwm4 --compositor=off`, so a later window-manager replacement cannot
   silently re-enable compositing.
9. Raise the bounded Docker task limit from 512 to 1024. A representative live
   desktop reached 426 tasks (83% of the old cap) with Electron applications
   installed, leaving too little launch headroom even though CPU and shared
   memory remained healthy.

## Changes deliberately not adopted without measurement

- **x11vnc `-ncache`:** upstream calls it experimental, expands the framebuffer
  by a multiple, and can expose the cache area to a viewer. It is unsuitable as
  an unmeasured default.
- **Server-side scaling or 16-bit color:** both reduce pixel fidelity, contrary
  to VibeStack's desktop/code-review use case.
- **`-threads` and `-snapfb`:** upstream does not recommend them for this normal
  single-client workload; full-frame copying can make performance worse.
- **Disabling wireframe/ScrollCopyRect globally:** those heuristics can create
  painting artifacts, but disabling them costs bandwidth and CPU. A clarity
  benchmark should decide, not intuition.
- **GPU passthrough:** it needs `/dev/dri`, compatible host/container drivers,
  and a DRI-capable X stack, while VNC encoding and transport remain the likely
  bottleneck. It also reduces portability and isolation.

The x11vnc project documents its polling limitation and the workload-specific
wireframe/CopyRect optimizations in its
[project notes](https://github.com/libvnc/x11vnc) and
[option reference](https://github.com/LibVNC/x11vnc/blob/master/doc/OPTIONS.md).

## Strongest future experiment: TigerVNC Xvnc

TigerVNC's Xvnc combines the X server and VNC server around one virtual
framebuffer. That removes the Xvfb-to-screen-scraper stage and is the most
plausible architectural performance gain. TigerVNC describes Xvnc as both an X
server and VNC server and accelerates Tight JPEG with libjpeg-turbo. This makes
an improvement likely, but it remains an inference until measured in this
product. See the [TigerVNC project](https://github.com/TigerVNC/tigervnc) and
[Xvnc manual](https://tigervnc.org/doc/Xvnc.html).

Do not migrate the default until a candidate preserves dynamic XRandR sizing,
XFCE startup, noVNC clipboard, application automation, PNG screenshots,
expected reconnects, and the security boundary.

## Benchmark gate

Compare Xvfb+x11vnc and Xtigervnc at 1280x800 and 1920x1080 with noVNC quality
7/9 and compression 0/2/6. Use four workloads: static editor, terminal scroll,
window drag, and high-motion content. Capture:

- server CPU/RSS and browser CPU/memory;
- WebSocket bytes per second;
- input-to-visible-pixel latency;
- reconnect time and dropped-session behavior;
- pixel differences from a server-side PNG reference.

Run locally and over the private tailnet, then repeat with shaped latency and
bandwidth. Adopt a new server or fidelity flag only when it wins a documented
use case without breaking correctness.
