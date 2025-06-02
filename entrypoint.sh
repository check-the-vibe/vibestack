#!/bin/bash

# If no arguments provided, run supervisord (default behavior)
if [ $# -eq 0 ]; then
    exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
fi

# If 'claude' is the argument, run it as vnc user
if [ "$1" = "claude" ]; then
    exec su - vnc -c "claude"
fi

# If 'bash' is the argument, run interactive shell as vnc user
if [ "$1" = "bash" ]; then
    exec su - vnc
fi

# Otherwise, execute the provided command
exec "$@"