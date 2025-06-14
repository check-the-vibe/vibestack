#!/bin/bash
# Setup script for VibeStack menu

# Create .bashrc for vibe user if it doesn't exist
if [ ! -f /home/vibe/.bashrc ]; then
    cp /etc/skel/.bashrc /home/vibe/.bashrc 2>/dev/null || echo "# .bashrc" > /home/vibe/.bashrc
fi

# Add menu to bashrc if not already present
if ! grep -q "vibestack-welcome" /home/vibe/.bashrc; then
    cat >> /home/vibe/.bashrc << 'EOF'

# VibeStack Welcome Menu
if [ -f /home/vibe/vibestack-menu/vibestack-welcome ]; then
    /home/vibe/vibestack-menu/vibestack-welcome
fi
EOF
fi

# Create symlink for easy access
ln -sf /home/vibe/vibestack-menu/vibestack-welcome /usr/local/bin/vibestack-menu 2>/dev/null || true

# Ensure correct permissions
chown vibe:vibe /home/vibe/.bashrc
chmod 644 /home/vibe/.bashrc