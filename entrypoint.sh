#!/bin/bash

# Ensure script is running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "Error: entrypoint.sh must be run as root to set user passwords. Exiting."
    exit 1
fi

# Set up passwords at startup
setup_passwords() {
    # Set root password (randomize if not provided via environment)
    if [ -z "$ROOT_PASSWORD" ]; then
        # Optionally generate a random password here if desired
        echo "Warning: ROOT_PASSWORD not set. Using default 'root'."
        ROOT_PASSWORD="root"
    fi
    echo "root:$ROOT_PASSWORD" | chpasswd
    
    # Set vibe user password (use environment variable or default to 'coding')
    if [ -z "$VIBE_PASSWORD" ]; then
        VIBE_PASSWORD="coding"
    fi
    echo "vibe:$VIBE_PASSWORD" | chpasswd
    echo "Set vibe user password"
}

# Set up passwords on first run
setup_passwords

touch /home/vibe/.sudo_as_admin_successful

# Ensure Python tooling can import the vibestack package
export VIBESTACK_HOME="${VIBESTACK_HOME:-/home/vibe}"
if [[ -z "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="${VIBESTACK_HOME}"
else
    export PYTHONPATH="${VIBESTACK_HOME}:${PYTHONPATH}"
fi

# Configure optional Codex state directory
setup_codex_state() {
    local candidate_dirs=()
    if [[ -n "${CODEX_STATE_DIR:-}" ]]; then
        candidate_dirs+=("${CODEX_STATE_DIR}")
    fi
    candidate_dirs+=("/projects/codex" "${VIBESTACK_HOME}/codex")

    local source_dir=""
    for dir in "${candidate_dirs[@]}"; do
        if [[ -n "${dir}" && -d "${dir}" ]]; then
            source_dir="${dir}"
            break
        fi
    done

    if [[ -n "${source_dir}" ]]; then
        mkdir -p "${source_dir}"
        if [[ -e /home/vibe/.codex && ! -L /home/vibe/.codex ]]; then
            rm -rf /home/vibe/.codex
        fi
        ln -snf "${source_dir}" /home/vibe/.codex
        chown -h vibe:vibe /home/vibe/.codex
        echo "Using Codex state directory: ${source_dir}"
    else
        mkdir -p /home/vibe/.codex
        chown vibe:vibe /home/vibe/.codex
    fi
}

# Prepare session workspace
mkdir -p "${VIBESTACK_HOME}/sessions"
chown vibe:vibe "${VIBESTACK_HOME}/sessions"
setup_codex_state


configure_codex_callback() {
    local port
    port="${CODEX_CALLBACK_PORT:-1455}"
    mkdir -p /etc/nginx/conf.d
    cat > /etc/nginx/conf.d/codex_callback_upstream.conf <<EOF
upstream codex_callback {
    server 127.0.0.1:${port};
    keepalive 16;
}
EOF
}

configure_codex_callback

# If no arguments provided, run supervisord (default behavior)
if [ $# -eq 0 ]; then
    exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
fi

# If 'claude' is the argument, run it as vibe user
if [ "$1" = "claude" ]; then
    exec su - vibe -c "claude"
fi

# If 'bash' is the argument, run interactive shell as vibe user
if [ "$1" = "bash" ]; then
    exec su - vibe
fi

# Otherwise, execute the provided command
exec "$@"