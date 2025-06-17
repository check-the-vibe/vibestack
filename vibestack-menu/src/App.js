import React, { useState } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import BigText from 'ink-big-text';
import Gradient from 'ink-gradient';
import { spawn } from 'child_process';

// Construct BASE_URL based on environment
const getBaseUrl = () => {
  if (process.env.CODESPACES === 'true' && process.env.CODESPACE_NAME) {
    // In Codespaces, construct the URL
    return `https://${process.env.CODESPACE_NAME}-80.${process.env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}`;
  }
  // Default to localhost for Docker/local setup
  return 'http://localhost';
};

const BASE_URL = getBaseUrl();

const menuOptions = [
  { label: 'Claude', value: 'claude', action: 'command', command: 'claude' },
  { label: 'LLM CLI', value: 'llm', action: 'command', command: 'llm' },
  { label: 'Exit to Shell', value: 'exit', action: 'exit' }
];

const MenuOption = ({ label, isSelected }) => {
  return React.createElement(Box, {
    borderStyle: isSelected ? 'round' : 'single',
    borderColor: isSelected ? 'cyan' : 'gray',
    paddingX: 2,
    paddingY: 1,
    marginX: 1
  },
    React.createElement(Text, {
      color: isSelected ? 'cyan' : 'white',
      bold: isSelected
    }, label)
  );
};

export const VibeStackMenu = () => {
  const { exit } = useApp();
  const [selectedIndex, setSelectedIndex] = useState(0);

  const executeCommand = (command) => {
    // Exit Ink app first
    exit();
    
    // Spawn the command in a way that gives it control of the terminal
    spawn(command, [], {
      stdio: 'inherit',
      cwd: '/home/vibe',
      shell: true,
      detached: false
    });
  };

  const handleAction = (option) => {
    switch (option.action) {
      case 'command':
        if (option.command) {
          executeCommand(option.command);
        }
        break;
      
      case 'exit':
        exit();
        break;
    }
  };

  useInput((input, key) => {
    if (key.leftArrow || key.upArrow) {
      setSelectedIndex((prev) => (prev - 1 + menuOptions.length) % menuOptions.length);
    } else if (key.rightArrow || key.downArrow) {
      setSelectedIndex((prev) => (prev + 1) % menuOptions.length);
    } else if (key.return) {
      const selected = menuOptions[selectedIndex];
      handleAction(selected);
    } else if (key.escape) {
      exit();
    }
  });

  return React.createElement(Box, {
    flexDirection: 'column',
    alignItems: 'center',
    paddingY: 2
  },
    React.createElement(Box, { marginBottom: 2 },
      React.createElement(Gradient, { name: 'rainbow' },
        React.createElement(BigText, { text: 'Vibe Stack', font: 'block' })
      )
    ),
    
    // Configuration UI link section
    React.createElement(Box, { 
      flexDirection: 'column',
      alignItems: 'center',
      marginBottom: 2,
      borderStyle: 'round',
      borderColor: 'blue',
      paddingX: 2,
      paddingY: 1
    },
      React.createElement(Text, { color: 'blue', bold: true }, 
        'Configure VibeStack at:'
      ),
      React.createElement(Text, { color: 'cyan', underline: true }, 
        `${BASE_URL}/ui`
      )
    ),
    
    React.createElement(Box, { marginBottom: 1 },
      React.createElement(Text, { bold: true }, 'Choose your tool:')
    ),
    
    React.createElement(Box, { 
      flexDirection: 'row', 
      marginBottom: 2 
    },
      menuOptions.map((item, index) =>
        React.createElement(MenuOption, {
          key: item.value,
          label: item.label,
          isSelected: index === selectedIndex
        })
      )
    ),
    
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { dimColor: true },
        'Use ← → arrow keys to navigate, Enter to select, Esc to exit'
      )
    )
  );
};