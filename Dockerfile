FROM ubuntu:22.04

# Metadata
LABEL maintainer="VibeStack Project"
LABEL description="VibeStack - Lightweight VNC desktop environment using Fluxbox and noVNC"
LABEL version="1.0"

# Environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:0
ENV NOVNC_PORT=6080
ENV VNC_PORT=5900
ENV RESOLUTION=1280x720
ENV VNC_PASSWORD=""
ENV ROOT_PASSWORD=""
ENV VIBE_PASSWORD="coding"

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

# Install Streamlit
RUN pip install streamlit

# Configure SSH server (passwords will be set at runtime)
RUN mkdir -p /var/run/sshd && \
    sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    ssh-keygen -A

# Create non-root user for better security
RUN useradd -m -s /bin/bash -u 1000 vibe && \
    usermod -aG sudo vibe && \
    mkdir -p /home/vibe/.fluxbox

# Allow vibe to sudo without a password
RUN echo 'vibe ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/vibe && \
    chmod 440 /etc/sudoers.d/vibe

# (optional) set the vibe user’s actual login password from your ENV
RUN echo "vibe:${VIBE_PASSWORD}" | chpasswd

# Copy configuration files
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
COPY --chown=vibe:vibe fluxbox-init /home/vibe/.fluxbox/init
COPY --chown=vibe:vibe fluxbox-startup /home/vibe/.fluxbox/startup
COPY --chown=vibe:vibe fluxbox-apps /home/vibe/.fluxbox/apps
COPY --chown=vibe:vibe Xresources /home/vibe/.Xresources
COPY --chown=vibe:vibe streamlit_app /home/vibe/streamlit

# Copy VibeStack menu
COPY --chown=vibe:vibe vibestack-menu /home/vibe/vibestack-menu
COPY setup-vibestack-menu.sh /setup-vibestack-menu.sh

# Convert line endings to Unix format & set +x
RUN dos2unix \
      /home/vibe/.fluxbox/init \
      /home/vibe/.fluxbox/startup \
      /home/vibe/.fluxbox/apps \
      /home/vibe/.Xresources \
      /entrypoint.sh \
      /setup-vibestack-menu.sh \
      /home/vibe/vibestack-menu/vibestack-welcome && \
    chmod +x \
      /entrypoint.sh \
      /setup-vibestack-menu.sh \
      /home/vibe/vibestack-menu/vibestack-welcome

# Create required directories with proper permissions
RUN mkdir -p /var/log/supervisor /var/run && \
    chown -R vibe:vibe /home/vibe && \
    chmod 755 /home/vibe/.fluxbox && \
    chmod +x /home/vibe/.fluxbox/startup

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${NOVNC_PORT}/vnc.html || exit 1

# Expose noVNC, SSH, and Streamlit ports
EXPOSE ${NOVNC_PORT} 22 8501

RUN /bin/bash -c "/setup-vibestack-menu.sh"

# Set entrypoint and default command
ENTRYPOINT ["sudo", "/entrypoint.sh"]
CMD []