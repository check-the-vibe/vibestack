# Bash Shell Startup Scripts

## Overview
When a bash shell starts, it reads and executes commands from various startup files. The specific files depend on whether the shell is a login shell, interactive shell, or both.

## Startup Files Order

### For Login Shells
1. `/etc/profile` - System-wide configuration
2. `~/.bash_profile` - User-specific (if exists)
3. `~/.bash_login` - User-specific (if .bash_profile doesn't exist)
4. `~/.profile` - User-specific (if neither above exist)

### For Interactive Non-Login Shells
1. `/etc/bash.bashrc` - System-wide (on some systems)
2. `~/.bashrc` - User-specific

## Current VibeStack Setup
- DevContainer runs as `root` user
- Shell type: `/bin/bash`
- Existing files:
  - `/root/.bashrc` - Present
  - `/root/.profile` - Present
  - No `.bash_profile` exists

## Recommended Approach for VibeStack

### Option 1: Modify .bashrc (Recommended)
Add the welcome script to `/root/.bashrc`. This ensures it runs for every new interactive shell session.

```bash
# Add to end of ~/.bashrc
if [ -f /usr/local/bin/vibestack-welcome ]; then
    /usr/local/bin/vibestack-welcome
fi
```

### Option 2: Use postStartCommand in devcontainer.json
The current setup already uses `postStartCommand`. We can modify it to include the welcome message.

### Option 3: Create a custom entrypoint
Create a script that runs the welcome message and then starts the shell.

## Implementation Strategy

1. **Create Welcome Script**: `/usr/local/bin/vibestack-welcome`
2. **Make it Executable**: `chmod +x /usr/local/bin/vibestack-welcome`
3. **Add to .bashrc**: Append execution command to `/root/.bashrc`
4. **Update Dockerfile**: Ensure the script is copied and permissions are set

## Benefits of .bashrc Approach
- Runs for every new terminal session
- Easy to enable/disable
- User can customize their experience
- Works with VS Code integrated terminal
- Persists across container rebuilds (if bashrc is preserved)