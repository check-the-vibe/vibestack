<!-- This document holds the tasks that have previously been completed, or need to be completed. Please ensure a consistent format for your tasks. Please add to this list when performing a task. You can also choose to add ideas for future work here, even if you are not intending to take those actions currently. -->

1. ✅ COMPLETED - Research the project https://github.com/vadimdemedes/ink?tab=readme-ov-file, document a brief overview of how we can create a welcome login message when a user logs in to a shell. Add your documentation in .vibe/docs/* in a filename of your choosing. 
   - Created: /workspaces/vibestack/.vibe/docs/ink-overview.md
   
2. ✅ COMPLETED - Research the best way to add a starting script for a bash shell, currently devcontainer is using the 'root' user to launch terminals. Document your recommended method in .vibe/docs
   - Created: /workspaces/vibestack/.vibe/docs/bash-startup-scripts.md
   
3. ✅ COMPLETED - Implement a basic welcome message (echo'ing "hello")
   - Created: /workspaces/vibestack/vibestack-welcome
   - Added to /root/.bashrc
   
4. ✅ COMPLETED - Add the ink file to the docker file build process
   - Updated Dockerfile to install ink and react via npm
   - Added vibestack-welcome script to Docker build
   - Configured bashrc for both root and vibe users
   
5. ✅ COMPLETED - Create a "welcome" script that says: 
VibeStack
type "claude", "codex" or "help" to get started
   - Updated vibestack-welcome script with the specified message
