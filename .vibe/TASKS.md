<!-- This document holds the tasks that have previously been completed, or need to be completed. Please ensure a consistent format for your tasks. Please add to this list when performing a task. You can also choose to add ideas for future work here, even if you are not intending to take those actions currently. -->

Outcome or work iteration: Users who access a shell in this Docker container are greeted with a loading message powered by the Ink library. 

## Research
For all research tasks, document your findings in .vibe/docs/, in a markdown file titled whatever you think is most appropriate. Carry out your queries using web searches and document anything that is potentially needed for future development
1. ✅ COMPLETED - Research Ink, the CLI library: https://github.com/vadimdemedes/ink. How would you implement it, what are some examples of interesting interfaces? (Documented in .vibe/docs/ink-library-research.md)
2. ✅ COMPLETED - What is the best way to start up a script after a user starts a shell. Think about working this in with the current Docker configuration, as well as the devcontainer and supporting files. Document your recommended approach. (Documented in .vibe/docs/shell-startup-research.md)

## POC
1. ✅ COMPLETED - Set up a basic echo script as a startup. Check that this works by asking the user to open new terminals to see if the configuration takes effect. (Created /opt/vibestack-welcome.sh and added to /root/.bashrc)

## Development
1. ✅ COMPLETED - Implement the phrase "Welcome to VibeStack" in the Ink library as a startup message. Remove the original echo and just use an interesting ink implementation. (Implemented at /opt/vibestack-ink/simple.js with gradient styling and informative messages) 
2. ✅ COMPLETED - Create a selection menu, first item will simply run the "claude" command, second item will run the "llm --help" command. Allow the user to navigate with arrow keys. (Implemented at /opt/vibestack-ink/menu.js, accessible via "vibestack-menu" command)