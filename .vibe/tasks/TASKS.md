# Outcome
I would like to modify the current vibestack-welcome loading screen to provide a link on the 'configure' tab, instead of the inputs, to the url that the container is running on (either localhost, or if running in codespaces, the endpoint that is exposed at port 80). Set the base url progromatically before based on where the user is running, either via .devcontainer/devcontainer.json or another means. 

In addition, the streamlit app should allow the user to read and modify the following files found in the root of the project -> .vibe/ 
- TASKS.md
- ENVIRONMENT.md
- ERRORS.md
- PERSONA.md

The user should be able to save these files, then return to the terminal, and execute claude/llm based on their preference. 

## Research 
- Understand the current repo, its structure, how it is built in Docker (see Dockerfile), and where you should be making changes so that they persist in the new container. 
- Search for the right docs for how to build the url exposed by a codespace, how to determine whether you are in a codespace or not, and then how to set a variable appropriately. 
- You will need to allow the Streamlit app to access the .vibe/ folder of files, think through how you are going to accomplish this. 

## Development 
- Implement the startup script/environment variable setting the url path. 
- Change the vibestack-welcome process (menu-new.js) to remove the inputs on the configure screen, showing a link (based on the environment variable) to edit the appropriate files. The endpoint will be at /ui. 
- Modify the streamlit app, add a pages/ folder, put the current app.py as a subpage called "VibeStack". 
- Add a page for each file in .vibe that should be editable. Allow the user to read the current file state, edit the file, and save to these files. 
- Modify the home page (app.py) to welcome the user to VibeStack, and tell them what files are available. 