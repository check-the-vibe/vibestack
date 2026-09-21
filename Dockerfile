FROM --platform=$BUILDPLATFORM golang:1.26.4 AS workspace-build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY api/ api/
COPY service/ service/
COPY cmd/vibestack-service/ cmd/vibestack-service/
ARG TARGETARCH
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build -trimpath -ldflags="-s -w" -o /out/vibestack-service ./cmd/vibestack-service

FROM ubuntu:24.04

LABEL maintainer="VibeStack Project"
LABEL description="VibeStack - slim Linux desktop for AI coding tools, with a first-boot setup wizard"

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:0 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    TTYD_PORT=7681 \
    SETUP_PORT=7999 \
    CONTROL_PORT=7998 \
    AUTOMATION_PORT=7997 \
    RESOLUTION=1920x1200

# ---------------------------------------------------------------------------
# Base system only. Everything optional is installed by the setup wizard, so
# individual XFCE parts are named rather than pulling the xfce4 metapackage.
# ---------------------------------------------------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
        dbus dbus-x11 desktop-file-utils xdg-utils \
        gnome-keyring libsecret-1-0 libsecret-tools \
        git nano vim-tiny tmux sudo procps psmisc openssh-server \
        nginx openssl supervisor python3 util-linux \
        websockify x11vnc xvfb xauth \
        xfwm4 xfdesktop4 xfce4-panel xfce4-settings xfce4-terminal thunar \
        fonts-dejavu-core \
        scrot xclip xdotool wmctrl libgtk-3-bin x11-utils x11-xserver-utils xcvt \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# The upstream base has no CA bundle. Once the signed base-package bootstrap
# installs ca-certificates, use verified HTTPS for setup and restoration.
# Keep the official archive, security, and ARM ports repositories unchanged.
RUN sed -Ei 's#http://(archive\.ubuntu\.com/ubuntu|security\.ubuntu\.com/ubuntu|ports\.ubuntu\.com/ubuntu-ports)(/|[[:space:]]|$)#https://\1\2#g' /etc/apt/sources.list.d/ubuntu.sources

# noVNC as static web assets. The Ubuntu novnc package depends on Node 18
# without npm, which the setup catalog would then mistake for a Node runtime.
ARG NOVNC_VERSION=1.7.0
ARG NOVNC_SHA256=b1003a11b6e6e8d8f7f5e5586daae7f8ca651d8aee0aa155ff9ac841c48f52c6
RUN curl -fsSL "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz" -o /tmp/novnc.tar.gz && \
    echo "${NOVNC_SHA256}  /tmp/novnc.tar.gz" | sha256sum -c - && \
    mkdir -p /usr/share/novnc && \
    tar -xzf /tmp/novnc.tar.gz -C /usr/share/novnc --strip-components=1 && \
    rm -f /tmp/novnc.tar.gz && \
    test -f /usr/share/novnc/vnc.html

# ttyd for the browser terminal
ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256_AMD64=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
ARG TTYD_SHA256_ARM64=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
      amd64) ttyd_asset=x86_64; ttyd_sha256="${TTYD_SHA256_AMD64}" ;; \
      arm64) ttyd_asset=aarch64; ttyd_sha256="${TTYD_SHA256_ARM64}" ;; \
      *) echo "unsupported ttyd target architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${ttyd_asset}" -o /tmp/ttyd && \
    echo "${ttyd_sha256}  /tmp/ttyd" | sha256sum -c - && \
    install -m 0755 /tmp/ttyd /usr/bin/ttyd && \
    rm -f /tmp/ttyd

# Editor is a core workspace service, installed and verified while building.
COPY --chmod=755 bin/vibestack-install-editor /usr/local/bin/vibestack-install-editor
RUN apt-get update && apt-get install -y --no-install-recommends python3-pil && \
    /usr/local/bin/vibestack-install-editor && apt-get clean && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 ships an "ubuntu" user on UID 1000; replace it.
RUN userdel -r ubuntu 2>/dev/null || true && \
    useradd -m -s /bin/bash -u 1000 vibe && \
    usermod --lock vibe && \
    printf '%s\n' \
      'vibe ALL=(ALL:ALL) ALL' \
      'vibe ALL=(root) NOPASSWD: /usr/local/bin/vibestack-install, /usr/local/bin/vibestack-control, /usr/local/bin/vibestack-password' \
      > /etc/sudoers.d/vibe && \
    chmod 440 /etc/sudoers.d/vibe && \
    visudo -cf /etc/sudoers.d/vibe

COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY --chown=root:root --chmod=0444 sshd_config /etc/ssh/sshd_config_vibestack
COPY nginx.conf /etc/nginx/nginx.conf
COPY setup/catalog.json /usr/share/vibestack/catalog.json
COPY setup/setuplib.py setup/server.py /usr/share/vibestack/
COPY setup/index.html setup/style.css setup/app.js /usr/share/vibestack/web/
COPY common/ /usr/share/vibestack-common/
COPY control/ /usr/share/vibestack-control/
COPY automation/ /usr/share/vibestack-automation/
COPY --from=workspace-build --chmod=0555 /out/vibestack-service /usr/local/bin/vibestack-service
COPY web/public/ /usr/share/vibestack/public/
COPY docs/SERVICE.md /usr/share/vibestack/public/SERVICE.md
COPY --chmod=0555 cli.sh /usr/share/vibestack/cli.sh
RUN install -d -m 0755 /usr/share/vibestack-proxy
COPY --chown=root:root --chmod=0444 proxy/websockify_auth.py /usr/share/vibestack-proxy/websockify_auth.py
COPY runtime/AGENTS.md runtime/CLAUDE.md docs/AUTOMATION.md /usr/share/doc/vibestack/
COPY docs/CLI.md docs/RUNNER.md /usr/share/doc/vibestack/
COPY skills/vibestack/ /usr/share/doc/vibestack/skills/vibestack/
RUN ln -s /usr/share/doc/vibestack/AGENTS.md /AGENTS.md && \
    ln -s /usr/share/doc/vibestack/AGENTS.md /home/vibe/AGENTS.md && \
    ln -s /usr/share/doc/vibestack/AUTOMATION.md /home/vibe/AUTOMATION.md
COPY desktop-config/etc/xdg/ /etc/xdg/
COPY desktop-config/usr/share/ /usr/share/
RUN update-desktop-database /usr/share/applications && \
    gtk-update-icon-cache -f /usr/share/icons/hicolor
COPY desktop/ /usr/share/vibestack/desktop/
# Isolate every service-worker generation. Hash both the shell and the pinned
# noVNC runtime because they share one exact precache graph.
RUN shell_cache_version="$(find /usr/share/vibestack/desktop /usr/share/vibestack/public /usr/share/novnc/core /usr/share/novnc/vendor -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)" && \
    sed -i "s/__VIBESTACK_SHELL_CACHE_VERSION__/${shell_cache_version}/" /usr/share/vibestack/desktop/service-worker.js && \
    ! grep -q '__VIBESTACK_SHELL_CACHE_VERSION__' /usr/share/vibestack/desktop/service-worker.js
COPY chrome/policy.json /usr/share/vibestack/chrome-policy.json
COPY chrome/google-chrome-xfce-helper.desktop /usr/share/vibestack/google-chrome-xfce-helper.desktop
COPY --chmod=755 bin/vibestack-api-token bin/vibestack-app bin/vibestack-automation-check \
     bin/vibestack-bootstrap bin/vibestack-check bin/vibestack-desktop-action bin/vibestack-install \
     bin/vibestack-flatpak bin/vibestack-healthcheck bin/vibestack-persist bin/vibestack-setup bin/vibestack-welcome \
     bin/vibestack-control bin/vibestack-password bin/vibestack-wallpaper /usr/local/bin/
COPY --chmod=755 bin/vibestack-volume-init /usr/local/bin/vibestack-volume-init
COPY --chmod=755 entrypoint.sh /entrypoint.sh
COPY --chown=vibe:vibe --chmod=755 xfce-startup /home/vibe/xfce-startup

RUN mkdir -p /data/.vibestack-state-v1 /projects /home/vibe/Desktop && \
    chown -R vibe:vibe /home/vibe /projects && \
    chown root:vibe /data && \
    chmod 1770 /data

WORKDIR /home/vibe

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD ["/usr/local/bin/vibestack-healthcheck"]

EXPOSE 80 22 5901

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
