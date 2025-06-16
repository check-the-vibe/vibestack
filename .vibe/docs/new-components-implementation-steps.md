# New Components Implementation Steps

## Overview
This document outlines the step-by-step implementation process for creating new components in the VibeStack menu system, particularly focusing on LLM CLI integrations.

## Component Types

### 1. LLM CLI Integration Components

These components integrate external LLM command-line interfaces into the VibeStack menu system.

#### Implementation Pattern

```javascript
// src/providers/LLMProvider.js
class LLMProvider {
  constructor(name, command, args = []) {
    this.name = name;
    this.command = command;
    this.args = args;
  }

  async checkAvailability() {
    // Check if command exists
  }

  async launch(options = {}) {
    // Launch the CLI
  }
}
```

### 2. Adding a New LLM CLI

#### Step 1: Create Provider Definition
```javascript
// src/providers/definitions/openai-cli.js
export const OpenAICLI = {
  name: 'OpenAI CLI',
  value: 'openai',
  command: 'openai',
  checkCommand: 'openai --version',
  installCommand: 'pip install openai-cli',
  requiresAuth: true,
  authEnvVar: 'OPENAI_API_KEY',
  documentation: 'https://github.com/openai/openai-cli'
};
```

#### Step 2: Add to Provider Registry
```javascript
// src/providers/registry.js
import { ClaudeCLI } from './definitions/claude-cli.js';
import { OpenAICLI } from './definitions/openai-cli.js';
import { OllamaCLI } from './definitions/ollama-cli.js';

export const providerRegistry = {
  claude: ClaudeCLI,
  openai: OpenAICLI,
  ollama: OllamaCLI
};
```

#### Step 3: Create Availability Checker
```javascript
// src/utils/checkProviders.js
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

export async function checkProviderAvailability(provider) {
  try {
    await execAsync(provider.checkCommand);
    return {
      available: true,
      provider: provider.value
    };
  } catch (error) {
    return {
      available: false,
      provider: provider.value,
      installCommand: provider.installCommand
    };
  }
}
```

#### Step 4: Update Provider Selection UI
```javascript
// src/tabs/ProviderTab.js
import { providerRegistry } from '../providers/registry.js';
import { checkProviderAvailability } from '../utils/checkProviders.js';

const ProviderTab = ({ onSave }) => {
  const [availableProviders, setAvailableProviders] = useState([]);
  
  useEffect(() => {
    // Check all providers on mount
    const checkAll = async () => {
      const results = await Promise.all(
        Object.values(providerRegistry).map(checkProviderAvailability)
      );
      setAvailableProviders(results.filter(r => r.available));
    };
    checkAll();
  }, []);
  
  const options = availableProviders.map(p => ({
    label: providerRegistry[p.provider].name,
    value: p.provider
  }));
  
  return (
    <Form
      form={{
        sections: [{
          title: 'Select LLM Providers',
          fields: [{
            name: 'providers',
            type: 'multiSelect',
            options
          }]
        }]
      }}
    />
  );
};
```

#### Step 5: Implement Launch Logic
```javascript
// src/utils/launchProvider.js
import { spawn } from 'child_process';
import { providerRegistry } from '../providers/registry.js';

export function launchProvider(providerName, options = {}) {
  const provider = providerRegistry[providerName];
  
  if (!provider) {
    throw new Error(`Unknown provider: ${providerName}`);
  }
  
  // Check for required auth
  if (provider.requiresAuth && !process.env[provider.authEnvVar]) {
    throw new Error(`${provider.name} requires ${provider.authEnvVar} to be set`);
  }
  
  // Launch the provider
  const args = [...provider.args, ...(options.additionalArgs || [])];
  const child = spawn(provider.command, args, {
    stdio: 'inherit',
    env: process.env
  });
  
  return child;
}
```

### 3. Custom UI Components

#### Creating a New Form Field Type

##### Step 1: Define Field Component
```javascript
// src/components/fields/CodeEditor.js
import React, { useState } from 'react';
import { Box, Text } from 'ink';
import { useInput } from 'ink';

export const CodeEditor = ({ value, onChange, label }) => {
  const [content, setContent] = useState(value || '');
  const [cursorPosition, setCursorPosition] = useState(0);
  
  useInput((input, key) => {
    if (key.return && key.shift) {
      // New line
      const newContent = content.slice(0, cursorPosition) + '\n' + content.slice(cursorPosition);
      setContent(newContent);
      setCursorPosition(cursorPosition + 1);
      onChange(newContent);
    } else if (key.backspace) {
      // Delete character
      if (cursorPosition > 0) {
        const newContent = content.slice(0, cursorPosition - 1) + content.slice(cursorPosition);
        setContent(newContent);
        setCursorPosition(cursorPosition - 1);
        onChange(newContent);
      }
    } else if (input) {
      // Add character
      const newContent = content.slice(0, cursorPosition) + input + content.slice(cursorPosition);
      setContent(newContent);
      setCursorPosition(cursorPosition + 1);
      onChange(newContent);
    }
  });
  
  return (
    <Box flexDirection="column">
      <Text>{label}</Text>
      <Box borderStyle="single" padding={1}>
        <Text>{content}</Text>
      </Box>
    </Box>
  );
};
```

##### Step 2: Register Field Type
```javascript
// src/components/fields/registry.js
import { CodeEditor } from './CodeEditor.js';

export const fieldTypes = {
  string: StringField,
  integer: IntegerField,
  multiSelect: MultiSelectField,
  codeEditor: CodeEditor  // New field type
};
```

##### Step 3: Use in Form
```javascript
// Example usage
<Form
  form={{
    sections: [{
      title: 'Configure Script',
      fields: [{
        name: 'script',
        type: 'codeEditor',
        label: 'Startup Script'
      }]
    }]
  }}
/>
```

### 4. Animation Components

#### Creating Loading Animations

##### Step 1: Define Animation Component
```javascript
// src/components/animations/PulseLoader.js
import React, { useState, useEffect } from 'react';
import { Box, Text } from 'ink';

export const PulseLoader = ({ text = 'Loading' }) => {
  const [dots, setDots] = useState(0);
  
  useEffect(() => {
    const interval = setInterval(() => {
      setDots((d) => (d + 1) % 4);
    }, 300);
    
    return () => clearInterval(interval);
  }, []);
  
  return (
    <Box>
      <Text>
        {text}{'.'.repeat(dots)}{' '.repeat(3 - dots)}
      </Text>
    </Box>
  );
};
```

##### Step 2: Create Complex Animations
```javascript
// src/components/animations/WaveText.js
import React, { useState, useEffect } from 'react';
import { Text } from 'ink';

export const WaveText = ({ text, delay = 100 }) => {
  const [offset, setOffset] = useState(0);
  
  useEffect(() => {
    const interval = setInterval(() => {
      setOffset((o) => (o + 1) % text.length);
    }, delay);
    
    return () => clearInterval(interval);
  }, [text.length, delay]);
  
  const renderChar = (char, index) => {
    const isHighlighted = index === offset;
    return (
      <Text key={index} color={isHighlighted ? 'cyan' : 'white'}>
        {char}
      </Text>
    );
  };
  
  return (
    <Text>
      {text.split('').map(renderChar)}
    </Text>
  );
};
```

### 5. Data Persistence Components

#### Creating a Settings Manager

```javascript
// src/utils/SettingsManager.js
import fs from 'fs/promises';
import path from 'path';

export class SettingsManager {
  constructor(settingsPath = '.vibe/settings.json') {
    this.settingsPath = settingsPath;
    this.cache = null;
  }
  
  async load() {
    try {
      const content = await fs.readFile(this.settingsPath, 'utf8');
      this.cache = JSON.parse(content);
      return this.cache;
    } catch (error) {
      // Default settings
      this.cache = {
        theme: 'default',
        lastProvider: null,
        shortcuts: {}
      };
      return this.cache;
    }
  }
  
  async save(settings) {
    this.cache = { ...this.cache, ...settings };
    await fs.mkdir(path.dirname(this.settingsPath), { recursive: true });
    await fs.writeFile(this.settingsPath, JSON.stringify(this.cache, null, 2));
  }
  
  get(key) {
    return this.cache?.[key];
  }
  
  set(key, value) {
    if (!this.cache) {
      this.cache = {};
    }
    this.cache[key] = value;
    return this.save(this.cache);
  }
}
```

### 6. Theme Components

#### Creating a Theme System

```javascript
// src/themes/ThemeProvider.js
import React, { createContext, useContext } from 'react';

const themes = {
  default: {
    primary: 'cyan',
    secondary: 'yellow',
    error: 'red',
    success: 'green',
    border: 'single'
  },
  dark: {
    primary: 'blue',
    secondary: 'magenta',
    error: 'red',
    success: 'green',
    border: 'double'
  }
};

const ThemeContext = createContext(themes.default);

export const ThemeProvider = ({ theme = 'default', children }) => {
  return (
    <ThemeContext.Provider value={themes[theme] || themes.default}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);

// Usage in component
const ThemedBox = ({ children }) => {
  const theme = useTheme();
  
  return (
    <Box borderStyle={theme.border} borderColor={theme.primary}>
      {children}
    </Box>
  );
};
```

### 7. Error Boundary Components

```javascript
// src/components/ErrorBoundary.js
import React from 'react';
import { Box, Text } from 'ink';

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  
  render() {
    if (this.state.hasError) {
      return (
        <Box flexDirection="column" borderStyle="round" borderColor="red" padding={1}>
          <Text color="red" bold>Error occurred:</Text>
          <Text>{this.state.error?.message || 'Unknown error'}</Text>
          <Text color="yellow">Press Ctrl+C to exit</Text>
        </Box>
      );
    }
    
    return this.props.children;
  }
}
```

## Testing New Components

### Unit Test Template
```javascript
// src/components/__tests__/NewComponent.test.js
import React from 'react';
import { render } from 'ink-testing-library';
import { NewComponent } from '../NewComponent.js';

describe('NewComponent', () => {
  it('renders correctly', () => {
    const { lastFrame } = render(<NewComponent />);
    expect(lastFrame()).toMatchSnapshot();
  });
  
  it('handles user input', () => {
    const { lastFrame, stdin } = render(<NewComponent />);
    stdin.write('test input');
    expect(lastFrame()).toContain('test input');
  });
});
```

## Integration Checklist

When adding a new component:

1. **Planning**
   - [ ] Define component purpose and API
   - [ ] Create interface mockups
   - [ ] Plan state management

2. **Implementation**
   - [ ] Create component file
   - [ ] Add to component registry
   - [ ] Implement business logic
   - [ ] Add error handling

3. **Testing**
   - [ ] Write unit tests
   - [ ] Test keyboard navigation
   - [ ] Test error scenarios
   - [ ] Test with real data

4. **Documentation**
   - [ ] Add JSDoc comments
   - [ ] Create usage examples
   - [ ] Update component catalog
   - [ ] Add to troubleshooting guide

5. **Integration**
   - [ ] Import in parent components
   - [ ] Wire up state management
   - [ ] Test full user flow
   - [ ] Update deployment scripts

## Performance Guidelines

1. **Minimize Re-renders**
   - Use React.memo for static components
   - Implement shouldComponentUpdate logic
   - Use useCallback for event handlers

2. **Optimize State Updates**
   - Batch related state changes
   - Use reducers for complex state
   - Avoid deep object mutations

3. **Lazy Loading**
   - Dynamic imports for large components
   - Load providers on-demand
   - Cache expensive computations

## Accessibility Considerations

1. **Keyboard Navigation**
   - All interactive elements reachable via keyboard
   - Logical tab order
   - Clear focus indicators

2. **Screen Reader Support**
   - Descriptive labels
   - Status announcements
   - Error message associations

3. **Color Contrast**
   - Test with different terminal themes
   - Avoid color-only information
   - Provide text alternatives