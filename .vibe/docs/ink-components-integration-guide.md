# Ink Components Integration Guide

This guide explains how to connect ink-tab, ink-form, and ink-ascii-image components to create a cohesive vibestack menu interface.

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│           ASCII Art Logo (Top)              │
├─────────────────────────────────────────────┤
│         Tab Navigation (ink-tab)            │
│  [Provider] [Environment] [Tools] [Tasks]   │
├─────────────────────────────────────────────┤
│                                             │
│        Dynamic Content Area                 │
│     (Forms based on selected tab)           │
│                                             │
└─────────────────────────────────────────────┘
```

## State Management Structure

```javascript
const [appState, setAppState] = useState({
  currentTab: 'provider',
  formData: {
    provider: [],
    environment: [],
    tools: [],
    tasks: ''
  },
  isLoading: false
});
```

## Component Connection Pattern

### 1. Main App Component

```javascript
import React, { useState } from 'react';
import { Box, Text } from 'ink';
import { Tab, Tabs } from 'ink-tab';
import { Form } from 'ink-form';
import InkAsciiImage from 'ink-ascii-image';

const VibeStackMenu = () => {
  const [activeTab, setActiveTab] = useState('provider');
  const [formData, setFormData] = useState({
    provider: [],
    environment: [],
    tasks: ''
  });

  // Tab change handler
  const handleTabChange = (name) => {
    setActiveTab(name);
  };

  // Form submission handler
  const handleFormSubmit = (values) => {
    setFormData({
      ...formData,
      [activeTab]: values
    });
  };

  return (
    <Box flexDirection="column">
      {/* Logo */}
      <Box justifyContent="center" marginBottom={1}>
        <InkAsciiImage 
          url="/path/to/vibestack-logo.png" 
          width={40}
        />
      </Box>

      {/* Tabs */}
      <Tabs onChange={handleTabChange}>
        <Tab name="provider">Provider</Tab>
        <Tab name="environment">Environment</Tab>
        <Tab name="tools">Tools</Tab>
        <Tab name="tasks">Tasks</Tab>
      </Tabs>

      {/* Dynamic Content */}
      <Box marginTop={1}>
        <TabContent 
          activeTab={activeTab} 
          onSubmit={handleFormSubmit}
          formData={formData}
        />
      </Box>
    </Box>
  );
};
```

### 2. Dynamic Tab Content Component

```javascript
const TabContent = ({ activeTab, onSubmit, formData }) => {
  switch (activeTab) {
    case 'provider':
      return (
        <Form
          onSubmit={onSubmit}
          form={{
            sections: [{
              title: 'Select LLM Providers',
              fields: [{
                name: 'providers',
                label: 'Providers',
                type: 'multiSelect',
                options: [
                  { label: 'Claude', value: 'claude' },
                  { label: 'LLM', value: 'llm' }
                ],
                initialValue: formData.provider
              }]
            }]
          }}
        />
      );
    
    case 'environment':
      return (
        <Form
          onSubmit={onSubmit}
          form={{
            sections: [{
              title: 'Select Environment',
              fields: [{
                name: 'environments',
                label: 'Environments',
                type: 'multiSelect',
                options: [
                  { label: 'GitHub Codespaces', value: 'codespaces' },
                  { label: 'Docker', value: 'docker' }
                ],
                initialValue: formData.environment
              }]
            }]
          }}
        />
      );
    
    case 'tasks':
      return (
        <Form
          onSubmit={onSubmit}
          form={{
            sections: [{
              title: 'Define Tasks',
              fields: [{
                name: 'taskDescription',
                label: 'Tasks',
                type: 'string',
                multiline: true,
                initialValue: formData.tasks
              }]
            }]
          }}
        />
      );
    
    case 'tools':
      return (
        <Box>
          <Text color="yellow">Coming Soon!</Text>
        </Box>
      );
    
    default:
      return null;
  }
};
```

## Data Flow Pattern

### 1. Tab Selection Flow
```
User presses arrow key → ink-tab onChange → Update activeTab state → Re-render TabContent
```

### 2. Form Submission Flow
```
User fills form → Submit → handleFormSubmit → Update formData → Save to file
```

### 3. Start Button Flow
```javascript
const handleStart = async () => {
  // Save provider selection to ENVIRONMENT.md
  if (formData.provider.length > 0) {
    await saveToEnvironmentFile(formData.provider);
  }
  
  // Save tasks to TASKS.md
  if (formData.tasks) {
    await saveToTasksFile(formData.tasks);
  }
  
  // Launch selected provider
  await launchProvider(formData.provider[0]);
};
```

## File I/O Integration

### Saving to ENVIRONMENT.md
```javascript
const saveToEnvironmentFile = async (providers) => {
  const content = `# Environment Configuration\n\nProviders: ${providers.join(', ')}\n`;
  await fs.writeFile('.vibe/ENVIRONMENT.md', content);
};
```

### Saving to TASKS.md
```javascript
const saveToTasksFile = async (tasks) => {
  const content = `# Tasks\n\n${tasks}\n`;
  await fs.writeFile('.vibe/TASKS.md', content);
};
```

## Navigation Enhancement

### Keyboard Shortcuts
```javascript
import { useInput } from 'ink';

const NavigationEnhancer = ({ onStart }) => {
  useInput((input, key) => {
    // Tab navigation
    if (key.tab) {
      // Move to next tab
    }
    
    // Start shortcut
    if (key.ctrl && input === 's') {
      onStart();
    }
    
    // Quit
    if (input === 'q') {
      process.exit(0);
    }
  });
};
```

## Complete Integration Example

```javascript
// vibestack-menu.js
import React, { useState } from 'react';
import { render, Box, Text } from 'ink';
import { Tab, Tabs } from 'ink-tab';
import { Form } from 'ink-form';
import InkAsciiImage from 'ink-ascii-image';
import fs from 'fs/promises';
import { spawn } from 'child_process';

const VibeStackMenu = () => {
  const [screen, setScreen] = useState('loading');
  const [activeTab, setActiveTab] = useState('provider');
  const [formData, setFormData] = useState({
    provider: [],
    environment: [],
    tasks: ''
  });

  // Loading screen
  if (screen === 'loading') {
    return (
      <LoadingScreen onComplete={() => setScreen('menu')} />
    );
  }

  // Main menu
  return (
    <Box flexDirection="column" padding={1}>
      <Box justifyContent="center" marginBottom={1}>
        <Text>VS</Text>
      </Box>

      <Tabs onChange={setActiveTab}>
        <Tab name="provider">Provider</Tab>
        <Tab name="environment">Environment</Tab>
        <Tab name="tools">Tools</Tab>
        <Tab name="tasks">Tasks</Tab>
      </Tabs>

      <Box marginTop={2}>
        <TabContent 
          activeTab={activeTab}
          formData={formData}
          onUpdate={(data) => setFormData({ ...formData, ...data })}
        />
      </Box>

      <Box marginTop={2}>
        <StartButton 
          formData={formData}
          onStart={handleStart}
        />
      </Box>
    </Box>
  );
};

// Render the app
render(<VibeStackMenu />);
```

## Best Practices

### 1. State Management
- Keep form state centralized
- Use callbacks for child-to-parent communication
- Persist state to files immediately after changes

### 2. Error Handling
```javascript
try {
  await saveToEnvironmentFile(data);
} catch (error) {
  setError(`Failed to save: ${error.message}`);
}
```

### 3. Visual Feedback
- Show loading states during file operations
- Highlight active tab clearly
- Display validation errors inline

### 4. Performance
- Lazy load tab content
- Debounce file writes
- Use React.memo for static components

## Testing Integration

```javascript
// Test file structure
describe('VibeStack Menu Integration', () => {
  it('should update form data when tab changes', () => {
    // Test tab switching preserves form data
  });

  it('should save provider selection to ENVIRONMENT.md', () => {
    // Test file writing
  });

  it('should launch selected provider', () => {
    // Test process spawning
  });
});
```

## Troubleshooting Common Issues

### 1. Tab Navigation Not Working
- Ensure ink-tab is properly imported
- Check that onChange handler is bound correctly

### 2. Form Data Not Persisting
- Verify state updates are happening
- Check file write permissions

### 3. ASCII Art Not Displaying
- Confirm image path is correct
- Check terminal supports UTF-8

## Next Steps

1. Implement loading animations with ink-text-animation
2. Add validation for form inputs
3. Create transition animations between screens
4. Implement keyboard shortcut hints
5. Add progress indicators for long operations