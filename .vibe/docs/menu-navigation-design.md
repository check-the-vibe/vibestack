# Menu Navigation Design

## Overview
This document outlines the design approach for implementing a multi-level navigation menu system using React and Ink for the VibeStack platform selector.

## Menu Structure

### Level 1: Main Menu
```
Choose your platform:
- Claude Code
- LLM CLI
- Exit to Shell
```

### Level 2A: Claude Code Submenu
```
Claude Code Options:
- Add MCP Server (placeholder)
- Configure Settings (placeholder)
- Start (launches "claude" command)
- Back to Main Menu
```

### Level 2B: LLM CLI Submenu
```
LLM CLI Options:
- Start (launches "llm" command)
- Back to Main Menu
```

## React Component Structure

### State Management
Using React hooks to manage:
- `currentMenu`: Tracks which menu level/screen is active
- `selectedIndex`: Tracks which option is selected in current menu
- `menuHistory`: Stack for navigation history (for back functionality)

### Component Architecture
```
App
├── MainMenu
├── ClaudeCodeMenu
├── LLMMenu
└── MenuOption (reusable component)
```

### Navigation Flow
1. **Forward Navigation**: Select an option → Update currentMenu state
2. **Back Navigation**: "Back" option or Escape key → Pop from menuHistory
3. **Exit**: "Exit to Shell" → Exit the application

## Implementation Approach

### 1. Menu State Enum
```javascript
const MenuState = {
  MAIN: 'main',
  CLAUDE_CODE: 'claude_code',
  LLM_CLI: 'llm_cli'
};
```

### 2. Menu Configuration
Each menu level defined as a configuration object:
```javascript
const menus = {
  main: {
    title: 'Choose your platform:',
    options: [
      { label: 'Claude Code', value: 'claude_code', action: 'navigate' },
      { label: 'LLM CLI', value: 'llm_cli', action: 'navigate' },
      { label: 'Exit to Shell', value: 'exit', action: 'exit' }
    ]
  },
  claude_code: {
    title: 'Claude Code Options:',
    options: [
      { label: 'Add MCP Server', value: 'add_mcp', action: 'placeholder' },
      { label: 'Configure Settings', value: 'settings', action: 'placeholder' },
      { label: 'Start', value: 'start_claude', action: 'command' },
      { label: 'Back to Main Menu', value: 'back', action: 'back' }
    ]
  },
  llm_cli: {
    title: 'LLM CLI Options:',
    options: [
      { label: 'Start', value: 'start_llm', action: 'command' },
      { label: 'Back to Main Menu', value: 'back', action: 'back' }
    ]
  }
};
```

### 3. Action Handlers
- `navigate`: Switch to a different menu
- `command`: Execute a shell command
- `placeholder`: Show "Coming soon" message
- `back`: Return to previous menu
- `exit`: Exit the application

## Visual Design

### Consistent Layout
- Keep the "Vibe StacK" title at top
- Show current menu title
- Display options horizontally when space permits
- Fall back to vertical layout for longer menus

### Visual Feedback
- Highlight selected option with cyan color and rounded border
- Dim inactive options
- Show navigation hints at bottom

### Transitions
- Clear screen between menu changes
- Maintain visual consistency across all menus

## Extensibility Considerations

1. **Menu Configuration**: Easy to add new menus or options
2. **Action System**: New action types can be added without changing core logic
3. **Styling**: Centralized styling configuration
4. **Command Execution**: Flexible command execution system

## Error Handling

1. **Invalid Navigation**: Prevent navigation to non-existent menus
2. **Command Failures**: Gracefully handle failed commands
3. **Terminal Compatibility**: Handle raw mode issues

## Integration Points

1. **Bashrc**: Add to shell startup
2. **Docker**: Include in container image
3. **Environment Variables**: Support VIBESTACK_NO_MENU to skip menu