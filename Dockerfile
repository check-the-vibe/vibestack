FROM ubuntu:22.04

# Metadata
LABEL maintainer="NoVNC Docker Project"
LABEL description="Lightweight VNC desktop environment using Fluxbox and noVNC"
LABEL version="1.0"

# Environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:0
ENV NOVNC_PORT=6080
ENV VNC_PORT=5900
ENV RESOLUTION=1280x720
ENV VNC_PASSWORD=""

# Install packages for VNC and desktop environment
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        # Core VNC and display packages
        xvfb \
        x11vnc \
        novnc \
        websockify \
        # Desktop environment
        fluxbox \
        xterm \
        # Programming languages and tools
        python3 \
        python3-pip \
        # Utilities
        wget \
        curl \
        supervisor \
        dbus-x11 \
        menu \
        nginx \
        git \
        jq \
        nano \
        vim \
        dos2unix \
        # Security and user management
        sudo \
        openssh-server \
        # Cleanup in same layer
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/* \
        && rm -rf /tmp/* \
        && rm -rf /var/tmp/*


# Install Node.js (LTS version)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*

# Install Claude Code
RUN npm install -g @anthropic-ai/claude-code

# Install playwright MCP
RUN npm install -g playwright-mcp

# Install Chrome browser for Playwright
RUN npx -y playwright install chrome

# Install llm cli
RUN pip install llm

# Configure SSH server
RUN mkdir -p /var/run/sshd && \
    echo 'root:root' | chpasswd && \
    sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    ssh-keygen -A

# Create non-root user for better security
RUN useradd -m -s /bin/bash -u 1000 vnc && \
    echo "vnc:vnc" | chpasswd && \
    usermod -aG sudo vnc && \
    mkdir -p /home/vnc/.fluxbox

# Copy configuration files
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
COPY --chown=vnc:vnc fluxbox-init /home/vnc/.fluxbox/init
COPY --chown=vnc:vnc fluxbox-startup /home/vnc/.fluxbox/startup
COPY --chown=vnc:vnc fluxbox-apps /home/vnc/.fluxbox/apps
COPY --chown=vnc:vnc Xresources /home/vnc/.Xresources

# Convert line endings to Unix format to prevent Windows compatibility issues
RUN dos2unix /home/vnc/.fluxbox/init /home/vnc/.fluxbox/startup /home/vnc/.fluxbox/apps /home/vnc/.Xresources /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Create required directories with proper permissions
RUN mkdir -p /var/log/supervisor /var/run && \
    chown -R vnc:vnc /home/vnc && \
    chmod 755 /home/vnc/.fluxbox && \
    chmod +x /home/vnc/.fluxbox/startup

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${NOVNC_PORT}/vnc.html || exit 1

# Expose noVNC and SSH ports
EXPOSE ${NOVNC_PORT} 22

# Set entrypoint and default command
ENTRYPOINT ["/entrypoint.sh"]
CMD []
