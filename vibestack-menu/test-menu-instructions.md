# Testing the New VibeStack Menu

## How to Test

1. Run the menu:
   ```bash
   cd /workspaces/vibestack/vibestack-menu
   node menu-new.js
   ```

2. **Loading Screen**:
   - You'll see the animated "Vibe Stack" title
   - After 2 seconds, "Get Started" button appears
   - Press Enter to continue

3. **Agent Selection Screen**:
   
   ### Provider Tab (default):
   - Press 1 to select Claude
   - Press 2 to select LLM
   - Press Enter or Ctrl+S to start with selected provider
   
   ### Environment Tab:
   - Press Tab to navigate to Environment tab
   - Type your environment configuration (e.g., "GitHub Codespaces, Docker")
   - Press Ctrl+S to save to .vibe/ENVIRONMENT.md
   
   ### Tasks Tab:
   - Press Tab to navigate to Tasks tab
   - Type your tasks
   - For multiline: Shift+Enter adds a new line
   - Press Ctrl+S to save to .vibe/TASKS.md
   
   ### Tools Tab:
   - Shows "Coming Soon!" message

## Navigation Keys:
- Tab: Switch between tabs
- Arrow keys: Move cursor in text inputs
- Backspace: Delete characters
- Ctrl+S: Save current tab content
- q: Quit (only works in Provider tab)

## Testing Checklist:
- [ ] Loading screen appears and transitions after 2 seconds
- [ ] Can navigate between all tabs using Tab key
- [ ] Provider selection works with keys 1 and 2
- [ ] Environment text input accepts typing and saves
- [ ] Tasks text input accepts multiline text and saves
- [ ] Files are created in .vibe/ directory after saving