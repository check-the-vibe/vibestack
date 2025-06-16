# Customer Journey Implementation Plan

## Overview
This document outlines the implementation plan for each stage of the VibeStack menu customer journey, from initial loading to launching the selected development environment.

## Customer Journey Map

```
1. App Launch → 2. Loading Screen → 3. Agent Selection → 4. Configuration → 5. Launch Environment
```

## Journey 1: First-Time User Setup

### Stage 1: App Launch
**User Action**: Run `vibestack-welcome` command
**Implementation**:
```javascript
// vibestack-welcome.js entry point
#!/usr/bin/env node
import { render } from 'ink';
import VibeStackApp from './src/VibeStackApp.js';

render(<VibeStackApp />);
```

### Stage 2: Loading Screen
**User Experience**: See animated "Vibe Stack" title with "Get Started" button
**Implementation Steps**:
1. Create `LoadingScreen.js` component
2. Use `ink-text-animation` for title animation
3. Add fade-in effect for "Get Started" button
4. Handle Enter key to proceed

```javascript
// src/components/LoadingScreen.js
import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import TextAnimation from 'ink-text-animation';

const LoadingScreen = ({ onComplete }) => {
  const [showButton, setShowButton] = useState(false);
  
  useEffect(() => {
    // Show button after animation
    setTimeout(() => setShowButton(true), 2000);
  }, []);
  
  useInput((input, key) => {
    if (key.return && showButton) {
      onComplete();
    }
  });
  
  return (
    <Box flexDirection="column" alignItems="center" justifyContent="center">
      <TextAnimation>
        <Text fontSize={2}>Vibe Stack</Text>
      </TextAnimation>
      {showButton && (
        <Box borderStyle="round" marginTop={2} paddingX={2}>
          <Text>Get Started</Text>
        </Box>
      )}
    </Box>
  );
};
```

### Stage 3: Agent Selection Screen
**User Experience**: Navigate tabs to configure environment
**Implementation Steps**:
1. Create `AgentSelectionScreen.js` component
2. Implement tab navigation with `ink-tab`
3. Add VS logo in corner
4. Create dynamic content area

### Stage 4: Configuration
**User Actions**: Select providers, environments, and define tasks
**Implementation for each tab**:

#### Provider Tab
```javascript
// src/tabs/ProviderTab.js
const ProviderTab = ({ onSave, currentValues }) => {
  return (
    <Form
      onSubmit={(values) => {
        onSave('provider', values.providers);
      }}
      form={{
        sections: [{
          fields: [{
            name: 'providers',
            type: 'multiSelect',
            options: [
              { label: 'Claude', value: 'claude' },
              { label: 'LLM', value: 'llm' }
            ],
            initialValue: currentValues
          }]
        }]
      }}
    />
  );
};
```

#### Environment Tab
```javascript
// src/tabs/EnvironmentTab.js
const EnvironmentTab = ({ onSave, currentValues }) => {
  const handleSave = async (values) => {
    // Save to ENVIRONMENT.md
    const content = `# Environment Configuration\n\nEnvironments: ${values.environments.join(', ')}\n`;
    await fs.writeFile('.vibe/ENVIRONMENT.md', content);
    onSave('environment', values.environments);
  };
  
  return (
    <Form
      onSubmit={handleSave}
      form={{
        sections: [{
          fields: [{
            name: 'environments',
            type: 'multiSelect',
            options: [
              { label: 'GitHub Codespaces', value: 'codespaces' },
              { label: 'Docker', value: 'docker' }
            ],
            initialValue: currentValues
          }]
        }]
      }}
    />
  );
};
```

#### Tasks Tab
```javascript
// src/tabs/TasksTab.js
const TasksTab = ({ onSave, currentValue }) => {
  const handleSave = async (values) => {
    // Save to TASKS.md
    await fs.writeFile('.vibe/TASKS.md', `# Tasks\n\n${values.tasks}\n`);
    onSave('tasks', values.tasks);
  };
  
  return (
    <Form
      onSubmit={handleSave}
      form={{
        sections: [{
          fields: [{
            name: 'tasks',
            type: 'string',
            multiline: true,
            initialValue: currentValue
          }]
        }]
      }}
    />
  );
};
```

### Stage 5: Launch Environment
**User Action**: Click "Start" button
**Implementation**:
```javascript
// src/components/StartButton.js
const StartButton = ({ formData }) => {
  const handleStart = async () => {
    const selectedProvider = formData.provider[0];
    
    if (selectedProvider === 'claude') {
      // Launch claude
      spawn('claude', { stdio: 'inherit' });
    } else if (selectedProvider === 'llm') {
      // Launch llm
      spawn('llm', { stdio: 'inherit' });
    }
    
    process.exit(0);
  };
  
  useInput((input, key) => {
    if (key.return) {
      handleStart();
    }
  });
  
  return (
    <Box borderStyle="round" paddingX={2}>
      <Text>Start</Text>
    </Box>
  );
};
```

## Journey 2: Returning User Flow

### Quick Start Path
1. Load saved configuration from `.vibe/` files
2. Pre-populate forms with previous selections
3. Allow immediate "Start" without navigation

**Implementation**:
```javascript
// src/utils/loadConfiguration.js
const loadConfiguration = async () => {
  const config = {
    provider: [],
    environment: [],
    tasks: ''
  };
  
  // Load from ENVIRONMENT.md
  try {
    const envContent = await fs.readFile('.vibe/ENVIRONMENT.md', 'utf8');
    // Parse providers and environments
  } catch (e) {
    // Use defaults
  }
  
  // Load from TASKS.md
  try {
    const tasksContent = await fs.readFile('.vibe/TASKS.md', 'utf8');
    config.tasks = tasksContent;
  } catch (e) {
    // Use empty
  }
  
  return config;
};
```

## Journey 3: Configuration Update Flow

### Partial Update Path
1. User navigates directly to specific tab
2. Updates only that configuration
3. Other settings remain unchanged

**Implementation considerations**:
- Persist tab state between saves
- Show visual confirmation of saved state
- Prevent accidental overwrites

## Error Handling Journeys

### File Write Error
```javascript
const handleFileError = (error, fileName) => {
  return (
    <Box flexDirection="column">
      <Text color="red">Failed to save {fileName}</Text>
      <Text color="yellow">{error.message}</Text>
      <Text>Press 'r' to retry or 'c' to continue</Text>
    </Box>
  );
};
```

### Missing Provider Selection
```javascript
const validateBeforeStart = (formData) => {
  if (formData.provider.length === 0) {
    return {
      valid: false,
      message: 'Please select at least one provider'
    };
  }
  return { valid: true };
};
```

## Navigation Patterns

### Keyboard Shortcuts
- `Tab` / `Shift+Tab`: Navigate between tabs
- `Enter`: Select/Submit
- `Space`: Toggle multi-select options
- `Ctrl+S`: Quick save current tab
- `Ctrl+Enter`: Quick start with current config
- `q`: Quit application

### Visual Feedback
1. Active tab highlighting
2. Form validation indicators
3. Save status messages
4. Loading spinners during file operations

## State Management Architecture

```javascript
// src/state/appState.js
const initialState = {
  screen: 'loading', // loading | menu
  activeTab: 'provider',
  formData: {
    provider: [],
    environment: [],
    tasks: ''
  },
  saveStatus: {
    provider: 'unsaved',
    environment: 'unsaved',
    tasks: 'unsaved'
  },
  errors: {}
};

const appReducer = (state, action) => {
  switch (action.type) {
    case 'SCREEN_CHANGE':
      return { ...state, screen: action.screen };
    case 'TAB_CHANGE':
      return { ...state, activeTab: action.tab };
    case 'FORM_UPDATE':
      return {
        ...state,
        formData: {
          ...state.formData,
          [action.field]: action.value
        },
        saveStatus: {
          ...state.saveStatus,
          [action.field]: 'saved'
        }
      };
    case 'ERROR':
      return {
        ...state,
        errors: {
          ...state.errors,
          [action.field]: action.error
        }
      };
    default:
      return state;
  }
};
```

## Testing Strategy

### Unit Tests
1. Component rendering tests
2. Form validation tests
3. File I/O operation tests
4. State management tests

### Integration Tests
1. Full journey flow tests
2. Tab navigation tests
3. Configuration persistence tests
4. Error recovery tests

### E2E Tests
1. Complete user journey from launch to environment start
2. Configuration update and reload
3. Error handling scenarios

## Performance Considerations

1. **Lazy Loading**: Load tab content only when selected
2. **Debouncing**: Debounce file writes to prevent excessive I/O
3. **Caching**: Cache file reads for quick navigation
4. **Optimistic Updates**: Update UI before file writes complete

## Accessibility Features

1. **Screen Reader Support**: Clear labels and navigation announcements
2. **Keyboard Navigation**: Full keyboard support, no mouse required
3. **High Contrast**: Ensure readability in various terminal themes
4. **Focus Indicators**: Clear visual focus indicators

## Deployment Checklist

- [ ] Create npm package structure
- [ ] Add to Dockerfile
- [ ] Update entrypoint.sh
- [ ] Add to vibestack-welcome script
- [ ] Create systemd service (if needed)
- [ ] Update documentation
- [ ] Add telemetry hooks
- [ ] Test in Docker environment
- [ ] Test in Codespaces environment