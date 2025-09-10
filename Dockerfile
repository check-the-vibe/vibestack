FROM ubuntu:22.04

# Metadata
LABEL maintainer="VibeStack Project"
LABEL description="VibeStack - Streamlit UI + Web Terminal (tmux via ttyd)"
LABEL version="2.0"

# Environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV ROOT_PASSWORD=""
ENV VIBE_PASSWORD="coding"
ENV CODEX_CALLBACK_PORT=1455

# Install base packages (no VNC/desktop, no browsers)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        wget \
        curl \
        ca-certificates \
        gnupg \
        file \
        supervisor \
        nginx \
        git \
        jq \
        nano \
        vim \
        dos2unix \
        sudo \
        openssh-server \
        tmux \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install Node.js (LTS version)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*

# Install ttyd binary from github releases
RUN wget https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 -O /usr/bin/ttyd && chmod +x /usr/bin/ttyd

# Install OpenAI Codex (Node)
RUN npm install -g @openai/codex

# Install Python tooling (no cache, single layer)
RUN pip install --no-cache-dir llm streamlit openai

# Configure SSH server (passwords will be set at runtime)
RUN mkdir -p /var/run/sshd && \
    sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    ssh-keygen -A

# Create non-root user for better security
RUN useradd -m -s /bin/bash -u 1000 vibe && \
    usermod -aG sudo vibe

# Allow vibe to sudo without a password
RUN echo 'vibe ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/vibe && \
    chmod 440 /etc/sudoers.d/vibe

# Note: user passwords are set at runtime by entrypoint.sh

# Copy configuration files
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
COPY --chown=vibe:vibe streamlit_app /home/vibe/streamlit
COPY --chown=vibe:vibe .vibe /home/vibe/.vibe
COPY --chown=vibe:vibe CLAUDE.md /home/vibe/CLAUDE.md

# tmux session wrapper for ttyd (args via URL)
COPY tmux_session.sh /usr/local/bin/tmux_session.sh
RUN dos2unix /usr/local/bin/tmux_session.sh && chmod +x /usr/local/bin/tmux_session.sh
COPY codex_loader.sh /usr/local/bin/codex_loader.sh
RUN dos2unix /usr/local/bin/codex_loader.sh && chmod +x /usr/local/bin/codex_loader.sh


# Copy VibeStack menu (kept installed but no auto-load)
COPY --chown=vibe:vibe vibestack-menu /home/vibe/vibestack-menu

# Install npm dependencies for vibestack-menu
RUN cd /home/vibe/vibestack-menu && npm install && chown -R vibe:vibe node_modules

# Convert line endings to Unix format & set +x
RUN dos2unix /entrypoint.sh && chmod +x /entrypoint.sh

# Create required directories with proper permissions
RUN mkdir -p /var/log/supervisor /var/run && \
    chown -R vibe:vibe /home/vibe

# Health check (nginx/Streamlit)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost/ui/ >/dev/null || exit 1

# Expose nginx + callback proxy ports
#  - 80:    Nginx reverse proxy (HTTP)
#  - 1456:  Internal Nginx listener that proxies to 127.0.0.1:${CODEX_CALLBACK_PORT}
#  - ${CODEX_CALLBACK_PORT}: Document the callback port used by Codex inside the container
EXPOSE 80 22 7681 8501 1456 ${CODEX_CALLBACK_PORT}

RUN chown vibe:vibe /home/vibe/.bashrc || true

# Set entrypoint and default command
# Note: use the same supervisord config path we copied earlier
ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
