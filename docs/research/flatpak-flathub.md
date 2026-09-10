# Flatpak and Flathub integration research

Research date: 2026-09-08. This note records the ecosystem, runtime, trust,
desktop-integration, and container-security decisions behind VibeStack's
Flatpak support. It distinguishes upstream behavior from local experiments so
future maintainers can revisit the trade-off without rediscovering it.

## Decision

VibeStack supports per-user Flatpak applications on amd64 and arm64 through an
explicit `--flatpak` container mode. The optional `flatpak` setup component
installs Ubuntu's Flatpak package, the portal frontend, and the Xapp portal
backend for XFCE. It configures exactly one default remote: stable Flathub.

The user experience has four layers:

1. **Flathub Marketplace** opens `https://flathub.org` from the curated XFCE
   menu for rich browsing, screenshots, publisher information, and permission
   review.
2. Flathub's current **Install** action uses the
   `x-scheme-handler/flatpak+https` URL scheme. A hidden VibeStack handler opens
   the exact stable appstream URL in a held terminal, downloads at most 64 KiB
   over HTTPS without following redirects, validates that the reference's app
   ID matches the URL, and retains the interactive permission/install
   confirmation. A separate `application/vnd.flatpak.ref` MIME handler applies
   the same reference validation to downloaded files.
3. **Manage Flatpak Apps** opens a terminal with `vibestack-flatpak`, a small
   helper for status, search, inspection, install, run, update, removal,
   remotes, and history.
4. Flatpak's exported `.desktop` files and icons are added to XFCE's
   `XDG_DATA_DIRS`, so installed applications join VibeStack's category-driven
   Applications/Coding/Create & Review menus.

Flatpak itself is not baked into the slim base. The marketplace link and helper
are present, while Setup visibly marks the component unavailable unless the
host selected the required mode. This keeps the default Docker boundary intact
and avoids claiming that a package which cannot launch sandboxes is usable.

## Ecosystem model

Flatpak is decentralized. Applications and runtimes live in OSTree-backed
repositories; a local name such as `flathub` points to one configured remote.
Search spans configured remotes, an application is selected by an ID such as
`org.gnome.Calculator`, and branches distinguish stable or testing variants.
Required runtimes are installed alongside applications and different runtime
versions can coexist. Updates use repository deltas rather than replacing a
whole image.

Relevant source families include:

| Source | Intended use | VibeStack default |
|---|---|---|
| Flathub stable | Broad cross-distribution application catalog | Yes, the sole automatic remote |
| Flathub Beta | Alpha/beta and secondary builds; upstream warns these can be unstable, experimental, or stale | No |
| GNOME Nightly | Current development builds from GNOME CI | No |
| Distribution or vendor remotes | A distro/vendor's builds and policies; may overlap IDs from another source | No |
| A user-provided `.flatpakrepo` or `.flatpakref` | Explicit third-party source or application reference | Only after specific user approval |

Adding a remote establishes another software trust root and can make a search
result ambiguous. An agent must therefore list remotes, report the exact remote
and application ID, and obtain approval before adding anything beyond stable
Flathub. It must never silently add beta, nightly, Fedora, vendor, or arbitrary
URL-based remotes to make a query succeed.

VibeStack intentionally registers only the application-reference MIME type and
the narrowly validated Flathub install-link scheme, not
`application/vnd.flatpak.repo`. The file handler parses a downloaded reference
without following symlinks, bounds it to 64 KiB, and rejects non-stable or
foreign repository URLs and runtime references. The URL handler accepts only
`dl.flathub.org/repo/appstream/<app-id>.flatpakref`, forbids queries, fragments,
redirects, and encoded path substitutions, and requires the downloaded
reference ID to match. Both discard repository/key material: installation uses
the validated app ID against VibeStack's existing exact-URL `flathub` remote.
A `.flatpakrepo` still requires a separate explicit trust decision.

Flatpak's official CLI supports remote listing/addition, search, exact
installation, execution, update, listing, removal, repair, permission reset,
and history. VibeStack wraps the common per-user operations, checks that an
existing remote named `flathub` still points to the exact stable repository,
and deliberately leaves installation interactive. External automation may use
`--noninteractive` only after the user has approved the exact reviewed ID.

## Trust and permissions

A repository file includes repository metadata and its signing key. That
authenticates content as coming from the configured repository; it does not
make every application benign. Flathub's verified status means the maintainer
proved control of an associated app identity or website. It is useful publisher
evidence, not a substitute for reviewing requested access.

Before installation, the workflow is:

1. `vibestack-flatpak search '<terms>'` and retain the exact ID and remote.
2. `vibestack-flatpak info <app-id>` to inspect declared sandbox permissions.
3. Open the printed `https://flathub.org/apps/<app-id>` page and check publisher
   verification, description, ownership, activity, and expected download.
4. Explain broad filesystem, device, socket, bus, or network access and ask the
   user to approve the specific install.
5. Install from the explicitly named stable `flathub` remote.

Applications still run as `vibe`; Flatpak is defense in depth, not a boundary
against a deliberately over-permissioned or malicious app. Portals mediate
common host interactions such as file selection and URI opening. VibeStack uses
`xdg-desktop-portal` plus Ubuntu's `xdg-desktop-portal-xapp`, whose package is
specifically the Cinnamon, MATE, and XFCE backend. The existing D-Bus session,
`XDG_CURRENT_DESKTOP=XFCE`, X11 authorization, and keyring environment are
published in `/run/vibestack/session.env`.

## Why per-user installation

Upstream supports both system-wide and per-user installations and remotes.
VibeStack has one desktop user, an immutable/replaced container layer, and one
durable `/data` mount, so `--user` is the better lifecycle match:

- no sudo is needed for app search/install/update/removal;
- apps and runtimes persist at `/data/flatpak` through
  `~/.local/share/flatpak`;
- app data persists at `/data/flatpak-apps` through `~/.var/app`;
- exported launchers are discovered from
  `~/.local/share/flatpak/exports/share`;
- replacing the image need only reinstall the small host-side Flatpak/portal
  packages selected in the setup catalog.

This differs from arbitrary apt work. Apt is correct for Ubuntu libraries,
drivers, compilers, development headers, daemons, and unsandboxed command-line
tools, but a manual `sudo apt-get install` changes only the current container.
A reviewed VibeStack catalog component is the durable apt route. Flatpak is the
preferred discovery/install route for an otherwise uncataloged desktop app.

## Container sandbox experiments

The host kernel allowed unprivileged user namespaces, but Docker's outer
security layers prevented Flatpak's nested bubblewrap sandbox. Tests used the
same Ubuntu 24.04 base and a non-root user; success meant bubblewrap could
create user, PID, UTS, and IPC namespaces, bind the root read-only, mount fresh
`proc` and `dev`, and execute `/usr/bin/true`.

| Docker configuration | Result |
|---|---|
| Default seccomp/AppArmor/system paths | `unshare(CLONE_NEWUSER)` denied |
| `seccomp=unconfined` only | user namespace allowed; mount propagation denied by AppArmor |
| seccomp + AppArmor unconfined | protected-system-path masking blocked the nested root/proc setup |
| seccomp + AppArmor + system paths unconfined | bubblewrap preflight passed |
| Added `SYS_ADMIN` experiments | Did not produce a clean least-authority path and increased privilege |
| `--privileged` | Not needed and rejected as too broad |

Docker documents its default seccomp profile as an allowlist and specifically
denies namespace-related `clone`, `setns`, and `unshare` operations. Flatpak's
namespace documentation explains why unprivileged user namespaces are the
preferred bubblewrap mechanism. The required VibeStack mode is therefore:

```text
-e VIBESTACK_FLATPAK_ENABLED=1
--security-opt seccomp=unconfined
--security-opt apparmor=unconfined
--security-opt systempaths=unconfined
```

This is a meaningful weakening of the **outer Docker** boundary even though
the Flatpak application receives an inner sandbox. It does not add capabilities
and does not use `--privileged`. VibeStack consequently keeps the normal launch
confined and adds these options only for `./startup.sh --flatpak`. The entrypoint
converts the host-selected environment into a fresh root-owned mode-`0444`
marker at `/run/vibestack/host/flatpak-enabled`. Setup and the privileged
installer trust that marker, not a user-set environment variable. The
`vibestack-flatpak check` bubblewrap preflight must also pass before setup
records convergence.

Once `flatpak` is in saved setup state, every replacement must retain
`--flatpak`. Starting without it makes the saved component explicitly
unsupported and the rollback-aware launcher refuses to discard the prior
container.

## Why no local graphical software center

Upstream correctly notes that GNOME Software and KDE Discover can browse
Flatpak repositories. Neither is a good default for this image today:

- GNOME Software plus its Flatpak plugin added approximately 108 MB and 123
  packages in an Ubuntu 24.04 `apt-get --simulate --no-install-recommends`
  audit, including PackageKit and systemd-oriented services.
- The lean Flatpak, portal frontend, and XFCE/Xapp backend set added about
  21 MB and 33 packages in the same audit.
- VibeStack is an XFCE session supervised without a normal systemd user
  session. A GNOME software center would add a second package-management UI and
  background-service assumptions while apt catalog selections still need the
  VibeStack setup workflow for restoration.

The stable Flathub web catalog provides the richer discovery page without that
runtime cost; the helper makes the source, exact ID, permissions, and consent
step visible. KDE Discover would pull a similarly mismatched KDE stack. A
future native VibeStack catalog UI could consume Flathub metadata directly, but
must preserve source identity, bounded network work, permission review, and the
explicit install approval.

## Agent operating policy

The packaged `/usr/share/doc/vibestack/AGENTS.md`, root `/AGENTS.md` endpoint,
and default Codex/Claude/OpenCode instructions teach the same order:

- use a VibeStack catalog component when one exists;
- for an uncataloged desktop app, check Flatpak mode, search stable Flathub,
  inspect the exact ID and permissions, and ask before installing;
- never invent an app ID or infer publisher trust from a similar display name;
- never add another remote without explicit approval;
- use apt/catalog rather than Flatpak for system integration and development
  libraries;
- note that Flatpak app/runtime and `~/.var/app` state persist, while arbitrary
  apt packages do not;
- use the web terminal for an interactive confirmation, or the authenticated
  command API for discovery and an explicitly approved noninteractive install.

## Verification contract

Fast tests verify catalog gating, exact stable-remote URL validation, root-owned
capability evidence, persistence links, XFCE export paths/menu categories,
helper allowlists, external guide routes, and the absence of `--privileged` or
added capabilities. Disposable image acceptance additionally:

1. starts every fresh/replacement container with the three explicit security
   options;
2. installs `flatpak`, `xdg-desktop-portal`, and
   `xdg-desktop-portal-xapp` through the real setup catalog;
3. requires the bubblewrap namespace/mount preflight;
4. verifies the exact stable Flathub URL and a real metadata search;
5. installs `org.gnome.Calculator` only in disposable state;
6. launches its actual XFCE window inside a Flatpak sandbox;
7. replaces the container against the same `/data`, waits for catalog
   restoration, and repeats the installed-app/window checks.

## Primary sources

- [Flatpak basic concepts](https://docs.flatpak.org/en/latest/basic-concepts.html)
- [Using Flatpak](https://docs.flatpak.org/en/latest/using-flatpak.html)
- [Flatpak repositories](https://docs.flatpak.org/en/latest/repositories.html)
- [XDG Desktop Portal](https://flatpak.github.io/xdg-desktop-portal/docs/)
- [Portal backend selection](https://flatpak.github.io/xdg-desktop-portal/docs/portals.conf.html)
- [Ubuntu Noble Xapp portal package](https://packages.ubuntu.com/search?keywords=xdg-desktop-portal)
- [Flathub installation and Beta warning](https://docs.flathub.org/docs/for-users/installation)
- [Flathub verified-app model](https://docs.flathub.org/docs/for-users/verification)
- [Flathub permissions guidance](https://docs.flathub.org/docs/for-users/permissions)
- [GNOME Nightly applications](https://nightly.gnome.org/)
- [Flatpak user-namespace requirements](https://github.com/flatpak/flatpak/wiki/User-namespace-requirements)
- [Docker default seccomp profile](https://docs.docker.com/engine/security/seccomp/)
