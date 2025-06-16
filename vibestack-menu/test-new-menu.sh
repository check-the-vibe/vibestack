#!/bin/bash
echo "Testing new vibestack menu design..."
echo "The menu will show:"
echo "1. Loading screen with animated title"
echo "2. Agent selection screen with tabs"
echo ""
echo "Press Ctrl+C to exit at any time"
echo ""
read -p "Press Enter to start the menu..." 

cd /workspaces/vibestack/vibestack-menu
node menu-new.js