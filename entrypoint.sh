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