# Ink Horizontal Menu Research

## Overview
This document contains research findings for implementing a horizontal selection menu using the Ink React CLI library.

## Key Libraries

### 1. ink-select-input-horizontal
- **Purpose**: A modified version of ink-select-input specifically designed for horizontal menus
- **GitHub**: https://github.com/H3RSKO/ink-select-input-horizontal
- **NPM**: `npm install ink-select-input-horizontal`
- **Features**:
  - Horizontal layout support
  - Color customization
  - Arrow key navigation
  - Compatible with Ink's component system

### 2. Core Ink Components
- **Box**: Flexbox container for layouts
- **Text**: Text rendering with styling
- **useInput**: Hook for handling keyboard input
- **useFocus**: Hook for managing focus state

## Implementation Example

```jsx
import React from 'react';
import {render, Box, Text} from 'ink';
import SelectInput from 'ink-select-input-horizontal';

const VibeStackMenu = () => {
  const handleSelect = item => {
    // Handle selection
    console.log(`Selected: ${item.value}`);
  };

  const items = [
    { label: 'Start Project', value: 'start' },
    { label: 'Documentation', value: 'docs' },
    { label: 'Settings', value: 'settings' },
    { label: 'Exit', value: 'exit' }
  ];

  return (
    <Box flexDirection="column" alignItems="center">
      <Text>Vibe StacK</Text>
      <SelectInput items={items} onSelect={handleSelect} />
    </Box>
  );
};

render(<VibeStackMenu />);
```

## Styling Techniques

### 1. Large Text
For creating large text, we can use:
- ASCII art generators
- Figlet library for Node.js
- Custom box-drawing characters

### 2. Box Borders
Using Box component with borderStyle prop:
```jsx
<Box borderStyle="round" padding={1}>
  <Text>Menu Item</Text>
</Box>
```

### 3. Color and Gradient
Using chalk or ink-gradient for styling:
```jsx
import gradient from 'ink-gradient';
import bigText from 'ink-big-text';

<gradient name="rainbow">
  <bigText text="Vibe StacK" />
</gradient>
```

## Navigation Patterns

### Horizontal Navigation
- Arrow keys (← →) for horizontal movement
- Enter/Return for selection
- Escape for exit/cancel
- Tab for alternative navigation

### Visual Feedback
- Highlight selected item with different color
- Add borders or brackets around selected item
- Use cursor indicators (>, →, etc.)

## Additional Resources
- Ink Examples: https://github.com/vadimdemedes/ink/tree/master/examples
- Ink UI Components: https://github.com/vadimdemedes/ink-ui
- React + Ink Tutorial: https://www.freecodecamp.org/news/react-js-ink-cli-tutorial/

## Next Steps
1. Set up project structure with create-ink-app
2. Install required dependencies (ink-select-input-horizontal, ink-big-text, ink-gradient)
3. Implement basic horizontal menu
4. Add styling and visual enhancements
5. Test keyboard navigation