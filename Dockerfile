FROM ubuntu:22.04

LABEL maintainer="VibeStack Project"
LABEL description="VibeStack - Lightweight VNC desktop environment using XFCE4 and noVNC"
LABEL version="1.0"

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:0 \
    NOVNC_PORT=6080 \
    VNC_PORT=5900 \
    RESOLUTION=1920x1200 \
    VNC_PASSWORD="" \
    ROOT_PASSWORD="" \
    VIBE_PASSWORD="coding" \
    VIBESTACK_HOME=/home/vibe \
    CODEX_CALLBACK_PORT=1455 \
    VIBESTACK_MCP_PORT=9100 \
    PATH="/home/vibe/bin:${PATH}"

# Base system + GUI stack
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        dbus-x11 \
        dos2unix \
        xfce4 \
        xfce4-terminal \
        falkon \
        git \
        jq \
        libegl1 \
        libgl1-mesa-dri \
        libglx-mesa0 \
        libgles2 \
        menu \
        nano \
        nginx \
        novnc \
        openssh-server \
        python3 \
        python3-pip \
        supervisor \
        sudo \
        tmux \
        vim \
        websockify \
        wget \
        x11vnc \
        xterm \
        xvfb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Node.js runtime + global CLIs
RUN set -x && \
    curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code @openai/codex opencode-ai@latest playwright && \
    npx playwright install --with-deps chromium && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create global opencode plugin directory
RUN mkdir -p /home/vibe/.config/opencode/plugin

# Visual Studio Code CLI for tunnel support
RUN curl -fsSL "https://update.code.visualstudio.com/latest/cli-linux-x64/stable" -o /tmp/vscode-cli.tar.gz && \
    mkdir -p /opt/vscode-cli && \
    tar -xzf /tmp/vscode-cli.tar.gz -C /opt/vscode-cli && \
    ln -sf /opt/vscode-cli/code /usr/local/bin/code && \
    rm -f /tmp/vscode-cli.tar.gz

# Python CLI tooling
RUN pip install --no-cache-dir \
        fastapi \
        "uvicorn[standard]" \
        streamlit \
        llm \
        "mcp[cli]" \
        beautifulsoup4 \
        requests \
        httpx \
        rich \
        typer \
        tui

# ttyd for web terminal access
RUN wget https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 -O /usr/bin/ttyd && \
    chmod +x /usr/bin/ttyd

# SSH daemon hardening + keys
RUN mkdir -p /var/run/sshd && \
    sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    ssh-keygen -A

# Dedicated non-root user
RUN useradd -m -s /bin/bash -u 1000 vibe && \
    usermod -aG sudo vibe && \
    mkdir -p /home/vibe/.config/xfce4 && \
    echo 'vibe ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/vibe && \
    chmod 440 /etc/sudoers.d/vibe && \
    echo "vibe:${VIBE_PASSWORD}" | chpasswd

WORKDIR /home/vibe

# Configuration and application files
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
COPY --chown=vibe:vibe bin/ /home/vibe/bin/
COPY --chown=vibe:vibe docs/ /home/vibe/docs/
COPY --chown=vibe:vibe streamlit_app/ /home/vibe/streamlit/
COPY --chown=vibe:vibe vibestack/ /home/vibe/vibestack/
COPY --chown=vibe:vibe Xresources /home/vibe/.Xresources
COPY --chown=vibe:vibe AGENTS.md /home/vibe/AGENTS.md
COPY --chown=vibe:vibe xfce-startup /home/vibe/xfce-startup
COPY --chown=vibe:vibe .opencode/plugin/session-logger.js /home/vibe/.config/opencode/plugin/session-logger.js

# Final filesystem tweaks
RUN ln -sf /home/vibe/bin/vibe /usr/local/bin/vibe && \
    ln -sf /home/vibe/bin/vibestack-ttyd-entry /usr/local/bin/vibestack-ttyd-entry && \
    dos2unix \
      /home/vibe/xfce-startup \
      /home/vibe/.Xresources \
      /entrypoint.sh \
      /home/vibe/bin/vibe \
      /home/vibe/bin/vibestack-ttyd-entry \
      /home/vibe/bin/vibestack-code-tunnel && \
    chmod +x \
      /entrypoint.sh \
      /home/vibe/bin/vibe \
      /home/vibe/bin/vibestack-ttyd-entry \
      /home/vibe/bin/vibestack-code-tunnel \
      /home/vibe/xfce-startup && \
    mkdir -p /var/log/supervisor /var/run && \
    chown -R vibe:vibe /home/vibe && \
    chmod 755 /home/vibe && \
    chmod +x /home/vibe/xfce-startup

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${NOVNC_PORT}/vnc.html || exit 1

EXPOSE 80 1456

ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
