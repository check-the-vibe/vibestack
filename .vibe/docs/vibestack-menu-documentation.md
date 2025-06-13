# VibeStack Command Center Menu

## Overview
The VibeStack Command Center is an interactive menu system built with Ink that provides quick access to commonly used development tools. It automatically appears when you open a new terminal.

## Automatic Launch
The menu automatically launches when you open a new terminal session. To disable this behavior:
```bash
export VIBESTACK_NO_MENU=true
```

## Manual Usage
Run the menu anytime by typing:
```bash
vibestack-menu
```

## Features
- **Arrow Key Navigation**: Use ↑/↓ arrows to navigate through options
- **Enter to Select**: Press Enter to execute the selected command
- **Escape/Q to Exit**: Press Escape or Q to exit the menu

## Menu Options
1. **Run Claude**: Launches the Claude AI assistant
2. **LLM Help**: Shows help for the LLM command-line tool
3. **Skip to Shell**: Exits the menu and continues to the shell prompt
4. **Exit Menu**: Exits the current terminal session

## Implementation Details

### File Structure
- `/opt/vibestack-ink/menu.js` - Interactive menu implementation
- `/opt/vibestack-ink/menu-simple.js` - Non-interactive display version
- `/opt/vibestack-menu.sh` - Wrapper script that detects terminal type
- `/usr/local/bin/vibestack-menu` - Symlink for easy access

### Technical Notes
- Built using Ink React CLI framework
- Requires interactive terminal for full functionality
- Falls back to display-only mode in non-interactive environments
- Commands are executed using child_process after menu exits

## Troubleshooting
If the menu doesn't work interactively:
1. Ensure you're in an interactive terminal (not a script or pipe)
2. Try running directly: `node /opt/vibestack-ink/menu.js`
3. Check that Node.js and dependencies are installed

## Future Enhancements
- Add more menu items as needed
- Implement submenus for grouped commands
- Add configuration file for custom commands
- Include command history and favorites