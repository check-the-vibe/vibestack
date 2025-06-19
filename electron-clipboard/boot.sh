#!/bin/bash
# Boot script for Electron app in supervisord

# Wait for X server and window manager to be ready
sleep 20

# Change to app directory
cd /workspaces/vibestack/electron-clipboard

# Check if node_modules exists, install if not
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Set required environment variables
export ELECTRON_DISABLE_SANDBOX=1
export DISPLAY=:0

# Start the Electron app
npm start