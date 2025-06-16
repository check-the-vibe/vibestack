import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';

export const TextInput = ({ label, value, onChange, placeholder = '', multiline = false }) => {
  const [localValue, setLocalValue] = useState(value || '');
  const [cursorPosition, setCursorPosition] = useState(localValue.length);

  useInput((input, key) => {
    if (key.return && !multiline) {
      // Single line - Enter submits
      onChange(localValue);
    } else if (key.return && multiline && key.shift) {
      // Multiline - Shift+Enter adds new line
      const newValue = localValue.slice(0, cursorPosition) + '\n' + localValue.slice(cursorPosition);
      setLocalValue(newValue);
      setCursorPosition(cursorPosition + 1);
    } else if (key.backspace || key.delete) {
      if (cursorPosition > 0) {
        const newValue = localValue.slice(0, cursorPosition - 1) + localValue.slice(cursorPosition);
        setLocalValue(newValue);
        setCursorPosition(cursorPosition - 1);
      }
    } else if (key.leftArrow) {
      setCursorPosition(Math.max(0, cursorPosition - 1));
    } else if (key.rightArrow) {
      setCursorPosition(Math.min(localValue.length, cursorPosition + 1));
    } else if (input && !key.ctrl) {
      const newValue = localValue.slice(0, cursorPosition) + input + localValue.slice(cursorPosition);
      setLocalValue(newValue);
      setCursorPosition(cursorPosition + input.length);
    }
  });

  // Show cursor
  const displayValue = localValue || placeholder;
  const beforeCursor = displayValue.slice(0, cursorPosition);
  const atCursor = displayValue[cursorPosition] || ' ';
  const afterCursor = displayValue.slice(cursorPosition + 1);

  return React.createElement(Box, { flexDirection: 'column' },
    label && React.createElement(Text, { bold: true }, label),
    React.createElement(Box, {
      borderStyle: 'single',
      borderColor: 'cyan',
      paddingX: 1,
      minHeight: multiline ? 5 : 1
    },
      React.createElement(Text, {},
        beforeCursor,
        React.createElement(Text, { inverse: true }, atCursor),
        afterCursor
      )
    ),
    multiline && React.createElement(Text, { dimColor: true, fontSize: 11 }, 
      'Shift+Enter for new line, Ctrl+S to save'
    )
  );
};