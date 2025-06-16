-- App loads
Loading Screen:
- Large title, uses ink-text-animation to animate: Vibe Stack
- Single outlined box, center aligned, with text: Get Started

Agent Selection Screen:
- Logo-style text, top-left corner: "VS"
- 5 tabs, across top with Names visible
    - Provider
    Multi-select list: llm, Claude
    - Environment:
    Multi-select list: Github Codespaces, Docker
    Button: Save
    -> On Save: Save value to .vibe/ENVIRONMENT.md
    - Tools
    Text: Coming Soon!
    - Tasks
    Large Text box
    Button: Save
    -> On Save Click: Write contents to .vibe/TASKS.md
- Start "button" (box with text): Start
-> On Start button click, run the chosen provider (llm, claude) in a shell. 
