#!/bin/bash

# VibeStack Terminal Initialization Script
# This script runs every time a new terminal is opened
# It should be called from .bashrc

# Function to check if supervisord is running
check_supervisord() {
    if pgrep -x "supervisord" > /dev/null; then
        return 0
    else
        return 1
    fi
}

# Function to start supervisord if not running
ensure_supervisord() {
    if ! check_supervisord; then
        if [ "$(id -u)" = "0" ]; then
            # We're root, can start supervisord directly
            /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf &
        else
            # We're vibe user, need sudo
            sudo /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf &
        fi
        # Give services time to start
        sleep 2
    fi
}

# Main startup sequence
main() {
    # Ensure supervisord is running (only if we're in the container)
    if [ -f /etc/supervisor/conf.d/supervisord.conf ]; then
        ensure_supervisord
    fi
    
    # Run the welcome menu
    if [ -f /workspaces/vibestack/vibestack-menu/vibestack-welcome ]; then
        /workspaces/vibestack/vibestack-menu/vibestack-welcome
    fi
}

# Only run if we're in an interactive shell
if [[ $- == *i* ]]; then
    main
fi