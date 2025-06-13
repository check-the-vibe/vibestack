# Ink Library Research

## Overview
Ink is a React renderer for building command-line interfaces (CLIs). Created by Vadim Demedes, it brings the component-based UI building experience of React to the terminal.

## Key Features

1. **React-based Development**: All React features are supported, making it immediately familiar to React developers
2. **Flexbox Layout**: Uses Yoga for terminal layouts with CSS-like props (flex, flexDirection, alignItems, justifyContent, margin, padding, width)
3. **Component-based Architecture**: Build and test CLI output using reusable components

## Installation & Setup

### Using create-ink-app (Recommended)
```bash
npx create-ink-app my-ink-app
cd my-ink-app
npm install
```

### Manual Installation
```bash
npm install ink react
```

## Basic Example
```javascript
import React from 'react';
import {render, Text} from 'ink';

const Hello = () => <Text>Hello World</Text>;

render(<Hello />);
```

## Core Components

- **`<Text>`**: Basic text component with chalk support for colors and styles
- **`<Box>`**: Flexbox container (similar to div in React web)
- **`<Color>`**: Component for coloring text
- **`<Spacer>`**: Auto-expanding component to fill available space
- **`<Newline>`**: Insert line breaks (only inside Text components)

## Interactive Features

### useInput Hook
```javascript
import {useInput} from 'ink';

const Component = () => {
  useInput((input, key) => {
    if (key.escape) {
      // Handle escape key
    }
  });
};
```

### useFocus Hook
Enables Tab navigation between focusable components

## Examples for VibeStack Welcome Message

### Simple Welcome
```javascript
import React from 'react';
import {render, Text, Box} from 'ink';
import chalk from 'chalk';

const Welcome = () => (
  <Box flexDirection="column" alignItems="center" padding={1}>
    <Text color="cyan" bold>Welcome to VibeStack</Text>
    <Text dimColor>Your development environment is ready!</Text>
  </Box>
);

render(<Welcome />);
```

### Animated Welcome with Gradient
```javascript
import React, {useState, useEffect} from 'react';
import {render, Text, Box} from 'ink';
import gradient from 'gradient-string';

const AnimatedWelcome = () => {
  const [show, setShow] = useState(false);
  
  useEffect(() => {
    const timer = setTimeout(() => setShow(true), 100);
    return () => clearTimeout(timer);
  }, []);
  
  return (
    <Box flexDirection="column" alignItems="center" padding={1}>
      {show && (
        <>
          <Text>{gradient.pastel('Welcome to VibeStack')}</Text>
          <Text dimColor>🚀 Your development environment is ready!</Text>
        </>
      )}
    </Box>
  );
};

render(<AnimatedWelcome />);
```

### Loading Animation Example
```javascript
import React from 'react';
import {render, Text} from 'ink';
import Spinner from 'ink-spinner';

const LoadingMessage = () => (
  <Text>
    <Text color="green">
      <Spinner type="dots" />
    </Text>
    {' Loading VibeStack environment...'}
  </Text>
);

render(<LoadingMessage />);
```

## Additional Resources

- **GitHub Repository**: https://github.com/vadimdemedes/ink
- **Ink UI Components**: https://github.com/vadimdemedes/ink-ui
- **Examples Directory**: Available in the main repository
- **Testing Library**: ink-testing-library for component testing

## Advantages for VibeStack

1. **Professional Appearance**: Create polished, interactive CLI interfaces
2. **Maintainable Code**: Component-based architecture makes code reusable
3. **Rich Interactivity**: Support for animations, colors, and user input
4. **Developer Experience**: React DevTools support and good error handling
5. **Performance**: Ink 3 offers improved rendering performance

## Implementation Notes

- Ink supports React DevTools (run with `DEV=true` environment variable)
- Has built-in error boundaries for better error display
- Intercepts console.log to display logs above the UI without interference
- Used by major projects: npm, Jest, Gatsby, Cloudflare Wrangler, GitHub Copilot CLI