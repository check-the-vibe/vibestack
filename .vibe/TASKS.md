[COMPLETED] Simplify the current loading screen (vibestack-menu/menu.js), Remove all the sub-menus, keep the loading screen, allow the user to choose from Claude, llm CLI, and Exit to Shell. In a section above this, provide a link to BASE_URL/ui, tell the user this is where they can configure vibestack. 

You will need to construct the BASE_URL, based on whether you are running in a Codespace, or if you are running in a normal docker setup. Default should be localhost, unless you are in Codespaces then this should be the url that is exposed on the port (80). 

Think through your approach. 