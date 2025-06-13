# Shell Startup Script Research for Docker/Devcontainer

## Overview
When working with Docker containers and devcontainers, shell startup scripts behave differently than traditional Linux environments. This document outlines the best approaches for running startup scripts when users open new terminals.

## Shell Initialization Order

### Login Shells (bash -l)
1. `/etc/profile`
2. `~/.bash_profile` (first found)
3. `~/.bash_login` (if bash_profile doesn't exist)
4. `~/.profile` (if neither above exist)

### Non-Login Interactive Shells
1. `/etc/bash.bashrc`
2. `~/.bashrc`

## Current Environment Analysis

Our devcontainer.json uses:
- `postStartCommand`: Runs `/entrypoint.sh` when container starts
- `remoteUser`: "root"
- No specific shell configuration

## Recommended Approaches for VibeStack

### Option 1: Using .bashrc (Recommended)
Since VS Code opens non-login interactive shells by default:

1. Create/modify `/root/.bashrc` (since remoteUser is root)
2. Add startup script execution at the end of .bashrc
3. This will run every time a new terminal is opened

### Option 2: Using /etc/bash.bashrc
For system-wide configuration:
1. Modify `/etc/bash.bashrc`
2. Affects all users
3. Runs for all interactive bash shells

### Option 3: Using postCreateCommand
In devcontainer.json:
```json
"postCreateCommand": "echo 'source /opt/vibestack/welcome.sh' >> /root/.bashrc"
```

### Option 4: Using Custom SHELL
In Dockerfile:
```dockerfile
SHELL ["/bin/bash", "-c"]
```

## Implementation Strategy for VibeStack

### Recommended Approach:
1. Create a welcome script at `/opt/vibestack/welcome.sh`
2. Add execution to `/root/.bashrc` during container build
3. This ensures the script runs when:
   - User opens new terminal in VS Code
   - User runs `bash` command
   - User connects via SSH

### Example Implementation:

#### In Dockerfile:
```dockerfile
# Create welcome script
COPY welcome.sh /opt/vibestack/welcome.sh
RUN chmod +x /opt/vibestack/welcome.sh

# Add to bashrc
RUN echo '# VibeStack Welcome Message' >> /root/.bashrc && \
    echo '[ -f /opt/vibestack/welcome.sh ] && /opt/vibestack/welcome.sh' >> /root/.bashrc
```

#### Alternative: Using postCreateCommand
```json
"postCreateCommand": "[ ! -f /root/.vibestack_configured ] && echo '[ -f /opt/vibestack/welcome.sh ] && /opt/vibestack/welcome.sh' >> /root/.bashrc && touch /root/.vibestack_configured"
```

## Considerations

1. **Performance**: Keep startup scripts lightweight to avoid slow terminal opens
2. **Idempotency**: Ensure scripts can run multiple times without issues
3. **Error Handling**: Scripts should fail gracefully if dependencies are missing
4. **User Experience**: Consider showing the message only on first terminal or with a timeout

## Testing

To test shell startup:
1. Open new terminal in VS Code
2. Run `docker exec -it <container> bash`
3. SSH into container
4. Run `bash` from existing shell

## References
- VS Code Dev Container documentation
- Docker SHELL instruction documentation
- Bash startup files documentation