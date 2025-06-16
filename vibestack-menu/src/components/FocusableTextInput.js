import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';

export const FocusableTextInput = ({ 
  label, 
  value, 
  onChange, 
  placeholder = '', 
  multiline = false,
  isActive = true 
}) => {
  const [localValue, setLocalValue] = useState(value || '');
  const [cursorPosition, setCursorPosition] = useState(localValue.length);

  // Sync with parent value when it changes
  React.useEffect(() => {
    setLocalValue(value || '');
    setCursorPosition((value || '').length);
  }, [value]);

  useInput((input, key) => {
    // Only handle input if this field is active
    if (!isActive) return;

    if (key.return && !multiline) {
      // Single line - Enter submits
      onChange(localValue);
    } else if (key.return && multiline && key.shift) {
      // Multiline - Shift+Enter adds new line
      const newValue = localValue.slice(0, cursorPosition) + '\n' + localValue.slice(cursorPosition);
      setLocalValue(newValue);
      setCursorPosition(cursorPosition + 1);
      onChange(newValue);
    } else if (key.backspace || key.delete) {
      if (cursorPosition > 0) {
        const newValue = localValue.slice(0, cursorPosition - 1) + localValue.slice(cursorPosition);
        setLocalValue(newValue);
        setCursorPosition(cursorPosition - 1);
        onChange(newValue);
      }
    } else if (key.leftArrow) {
      setCursorPosition(Math.max(0, cursorPosition - 1));
    } else if (key.rightArrow) {
      setCursorPosition(Math.min(localValue.length, cursorPosition + 1));
    } else if (input && !key.ctrl && !key.upArrow && !key.downArrow) {
      const newValue = localValue.slice(0, cursorPosition) + input + localValue.slice(cursorPosition);
      setLocalValue(newValue);
      setCursorPosition(cursorPosition + input.length);
      onChange(newValue);
    }
  }, { isActive });

  // Show cursor only if active
  const displayValue = localValue || placeholder;
  let content;
  
  if (isActive) {
    const beforeCursor = displayValue.slice(0, cursorPosition);
    const atCursor = displayValue[cursorPosition] || ' ';
    const afterCursor = displayValue.slice(cursorPosition + 1);
    
    content = React.createElement(React.Fragment, {},
      beforeCursor,
      React.createElement(Text, { inverse: true }, atCursor),
      afterCursor
    );
  } else {
    content = displayValue;
  }

  return React.createElement(Box, { 
    flexDirection: 'column',
    opacity: isActive ? 1 : 0.5
  },
    label && React.createElement(Text, { bold: true }, label),
    React.createElement(Box, {
      borderStyle: 'single',
      borderColor: isActive ? 'cyan' : 'gray',
      paddingX: 1,
      minHeight: multiline ? 5 : 1
    },
      React.createElement(Text, {}, content)
    ),
    multiline && isActive && React.createElement(Text, { dimColor: true, fontSize: 11 }, 
      'Shift+Enter for new line, Ctrl+S to save'
    )
  );
};