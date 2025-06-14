<!-- This document holds the tasks that have previously been completed, or need to be completed. Please ensure a consistent format for your tasks. Please add to this list when performing a task. You can also choose to add ideas for future work here, even if you are not intending to take those actions currently. -->

## Status: COMPLETED ✓

All tasks have been successfully implemented. The container now:
- Uses vibe user as default when connecting via VS Code/Codespaces
- Has proper user switching logic in entrypoint.sh
- Runs startup initialization from both root and vibe .bashrc files
- All scripts converted to Unix line endings and made executable

## Outcome

We want to be able to repeatably and stable-y boot up and run the following: 
- The container, with supervisord running in the background (works currently)
- A .bashrc file in the appropriate user directory that the container runs with. 
- Currently running as root, should probably move to the user 'vibe' (will need to sudo to run supervisord?). 
- Ensure bash cofiguration, folder mounting, and other permissions-related problems do not exist. 

## Task building
Define your tasks first, write them down here before you take any actions. Whatever your chain of thought is, document it in this file (.vibe/TASKS.md). 

Once complete, we review together, and then you execute. 

## Detailed Task Plan

### Analysis Summary:
1. Currently running as root user in the container
2. Vibe user exists (uid=1000) with sudo permissions
3. Supervisord runs as root but spawns most processes as vibe user
4. devcontainer.json specifies "remoteUser": "root"
5. Both root and vibe have .bashrc files, but only vibe's has the welcome menu

### Migration Plan:

1. **Update devcontainer.json to use vibe user**
   - Change "remoteUser" from "root" to "vibe"
   - This will make VS Code/Codespaces connect as vibe user

2. **Ensure supervisord can run with proper permissions**
   - Keep supervisord running as root (required for system services)
   - All child processes already run as vibe user (good)
   - No changes needed to supervisord.conf

3. **Update entrypoint.sh for better user handling**
   - Modify default behavior to switch to vibe user for interactive shells
   - Keep supervisord running as root when needed
   - Add better user detection and switching logic

4. **Ensure bash configuration works for both users**
   - Copy welcome menu setup to root's .bashrc as fallback
   - Verify permissions on all required files
   - Test both root and vibe user shells

5. **Setup and startup scripts**
   - Ensure setup-vibestack-menu.sh runs only once during container build
   - Create start-vibestack.sh to run on every terminal boot (from .bashrc)
   - Run dos2unix on all shell scripts to prevent line ending issues

6. **Test and verify**
   - Rebuild container after changes
   - Verify vibe user can access all needed resources
   - Ensure supervisord still starts correctly
   - Check that welcome menu appears for vibe user
   - Verify no line ending issues with scripts

