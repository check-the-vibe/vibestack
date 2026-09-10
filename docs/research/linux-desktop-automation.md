# Linux desktop automation research

Date: 2026-09-07

This research covers the first VibeStack automation release: commands,
screenshots, application lifecycle, window state, Desktop files, and the X11
clipboard. It also records the security and observability conditions required
before those operations can be exposed over HTTP.

## Decision

Keep Ubuntu 24.04 LTS, XFCE 4.18, and X11 for this release. Ubuntu 24.04 is
security-maintained through May 2029, and none of the requested automation
requires a distro or display-server migration. The container uses the host
kernel; installing an HWE kernel or GPU driver inside it would not accelerate
the current memory-backed Xvfb display. See Canonical's
[24.04 release notes](https://documentation.ubuntu.com/release-notes/24.04/)
and [kernel lifecycle](https://ubuntu.com/kernel/lifecycle).

The implementation keeps the existing narrow desktop-control service separate
and adds a token-authorized automation service. A bearer token grants the full
authority of the `vibe` account, including command execution, desktop contents,
files, and clipboard. It must be handled like a password.

## Selected Linux primitives

| Capability | Primitive | Reason |
|---|---|---|
| Command execution | Python `subprocess` plus a bounded job runner | Exact argv by default, explicit `/bin/bash -lc` when shell syntax is genuinely wanted, process-group cancellation, and byte-preserving output. |
| Screenshots | `scrot` | Already present, captures the live X display, produces exact PNG files, and supports fixed non-interactive options. |
| Applications | Checked-in application catalog and fixed argv | Prevents HTTP input from becoming an executable or process-match pattern. |
| Window list/state | `wmctrl`, `xdotool`, and `xprop` | XFCE's window manager implements EWMH; these tools cover enumeration, activation, maximize/normal state, minimization, and state confirmation. |
| Desktop files | Descriptor-relative Python filesystem calls | Supports exact text/binary bytes while rejecting traversal, symlinks, hard links, mount crossings, and non-regular files. |
| Clipboard | `xclip` with the `CLIPBOARD` selection | X11 selections require an owner process to remain alive; the service owns and replaces that process deliberately. V1 is UTF-8 text only. |

The [EWMH specification](https://specifications.freedesktop.org/wm/latest-single/)
defines maximized state and explains that minimized/hidden state is maintained
by the window manager. `wmctrl` is the appropriate EWMH interface, while
[`xdotool`](https://github.com/jordansissel/xdotool/blob/main/xdotool.pod)
provides a real minimize operation. [`xclip`](https://github.com/astrand/xclip)
documents the difference between PRIMARY and CLIPBOARD and the need to serve
selection requests. The [`scrot` manual](https://github.com/resurrecting-open-source-projects/scrot/blob/master/man/scrot.txt)
documents non-interactive PNG capture and overwrite behavior.

## Desktop command environment

Setting only `DISPLAY=:0` is insufficient for modern XFCE applications. Every
automation child receives a fixed base environment containing:

- `HOME=/home/vibe`, `USER=vibe`, and `LOGNAME=vibe`;
- a fixed system `PATH`;
- `DISPLAY=:0` and `XAUTHORITY=/run/vibestack/Xauthority`;
- `XDG_RUNTIME_DIR=/run/vibestack/runtime`;
- the session D-Bus and keyring values emitted by `xfce-startup` into the
  protected runtime directory.

Callers may add a small bounded set of environment variables, but cannot
replace those session/security fields.

## Security prerequisites

The prior runtime used Xvfb `-ac -listen tcp`, exposed x11vnc, websockify, and
ttyd on all container interfaces, ran Docker with an unconfined seccomp
profile, and granted `vibe` passwordless sudo for every command. Those choices
were wider than the host-loopback design implied.

The automation release therefore:

- uses MIT-MAGIC-COOKIE authentication and disables X11 TCP listening;
- binds raw VNC, websockify, ttyd, setup, control, and automation listeners to
  container loopback where nginx can reach them;
- requires nginx's overwritten proxy marker on ttyd and websockify WebSockets,
  with ttyd Origin/Host checking and exact duplicate-aware websockify matching,
  so an untrusted in-container browser page cannot directly upgrade either raw
  loopback port;
- uses Docker's default seccomp profile;
- keeps the installer, control, and password helpers on a narrow passwordless
  sudo allowlist, locks the account before onboarding, and requires the
  user-chosen Linux password for every other sudo command;
- requires a persistent 256-bit bearer token on every automation request;
- retains one valid Host, matching optional Origin, no-CORS, body limits,
  timeouts, concurrency caps, and nginx-generated edge request IDs;
- keeps host publishing on `127.0.0.1` and remote access behind private
  Tailscale Serve, never Funnel.

X.Org's [security guidance](https://www.x.org/wiki/Development/Documentation/Security/)
and [server manual](https://www.x.org/docs/man/man.pdf) warn that `-ac` disables
host access control and describe cookie authorization. Tailscale documents
that Serve strips spoofed identity headers and adds verified tailnet identity
only when the backend is kept on localhost; the bearer token remains required
for both human and tagged-machine callers. See
[Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).

## File boundary

The convenience file API exposes only the Desktop root in V1. Paths are UTF-8
relative components with a bounded total encoded length. The implementation walks
parents with directory file descriptors and `O_NOFOLLOW`, checks device,
ownership, type, and link count, and opens the final object relative to the
verified parent. The handler bounds one raw upload body before the file store
writes it to a random same-directory temporary file, hashes and syncs it, then
atomically replaces the target. This follows the race
considerations in the Linux kernel's
[path-lookup documentation](https://www.kernel.org/doc/html/latest/filesystems/path-lookup.html).

Shell access is intentionally more powerful than this convenience boundary.
The file endpoint's restrictions protect callers from accidental path
confusion; they are not claimed to sandbox a command-authorized token holder.

## API and job shape

Commands are asynchronous jobs (`202 Accepted`) with bounded queue/running
counts, timeouts, cancellation, process groups, persisted metadata, and
byte-oriented stdout/stderr pages. Screenshots, clipboard, and window actions
are short synchronous operations. File upload/download uses raw HTTP bodies so
binary data is not inflated or corrupted by JSON encoding.

HTTP semantics follow [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html).
The concrete routes, payloads, limits, and examples live in
`docs/architecture/automation-api.md` and `docs/AUTOMATION.md`.

## Logging and privacy

All logs persist below `/data/logs/vibestack/` and are linked from the desktop
as `VibeStack Logs`. Nginx emits JSON lines for UI and API loads using `$uri`
without query strings. Its source metadata correlates by request ID with the
automation audit's operation, safe target metadata, timing, result, and byte
counts. Each accepted command adds one redacted terminal audit event, tied to
its submission request ID; command output remains in the private job store.

It never records bearer tokens, cookies, command arguments, stdin,
environment values, clipboard text, file bodies, screenshot bytes, or command
stdout/stderr. File paths are audit-visible because they are necessary to
diagnose filesystem activity. Command transcripts are kept separately under a
mode-0700 automation job directory.

Nginx's [`log_format escape=json`](https://nginx.org/en/docs/http/ngx_http_log_module.html)
supports valid structured request logs. Supervisor services use one redirected
stream per rotating file; Supervisor explicitly warns against multiple streams
sharing one rotating file in its
[logging documentation](https://supervisord.org/logging.html).
