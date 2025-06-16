import React, { useState } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import BigText from 'ink-big-text';
import Gradient from 'ink-gradient';
import { spawn } from 'child_process';

const MenuState = {
  MAIN: 'main',
  CLAUDE_CODE: 'claude_code',
  LLM_CLI: 'llm_cli'
};

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
      { label: 'Start', value: 'start_claude', action: 'command', command: 'claude' },
      { label: 'Back to Main Menu', value: 'back', action: 'back' }
    ]
  },
  llm_cli: {
    title: 'LLM CLI Options:',
    options: [
      { label: 'Start', value: 'start_llm', action: 'command', command: 'llm' },
      { label: 'Back to Main Menu', value: 'back', action: 'back' }
    ]
  }
};

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
  const [currentMenu, setCurrentMenu] = useState(MenuState.MAIN);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [menuHistory, setMenuHistory] = useState([]);
  const [message, setMessage] = useState('');

  const activeMenu = menus[currentMenu];
  const menuOptions = activeMenu.options;

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
      case 'navigate':
        setMenuHistory([...menuHistory, currentMenu]);
        setCurrentMenu(option.value);
        setSelectedIndex(0);
        break;
      
      case 'back':
        if (menuHistory.length > 0) {
          const previousMenu = menuHistory[menuHistory.length - 1];
          setMenuHistory(menuHistory.slice(0, -1));
          setCurrentMenu(previousMenu);
          setSelectedIndex(0);
        }
        break;
      
      case 'command':
        if (option.command) {
          executeCommand(option.command);
        }
        break;
      
      case 'placeholder':
        setMessage(`${option.label} - Coming soon!`);
        setTimeout(() => setMessage(''), 2000);
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
      if (menuHistory.length > 0) {
        handleAction({ action: 'back' });
      } else {
        exit();
      }
    }
  });

  // Determine if we should use horizontal or vertical layout based on option count
  const useVerticalLayout = menuOptions.length > 3;

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
    
    React.createElement(Box, { marginBottom: 1 },
      React.createElement(Text, { bold: true }, activeMenu.title)
    ),
    
    React.createElement(Box, { 
      flexDirection: useVerticalLayout ? 'column' : 'row', 
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
    
    message && React.createElement(Box, { marginBottom: 1 },
      React.createElement(Text, { color: 'yellow' }, message)
    ),
    
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { dimColor: true },
        useVerticalLayout 
          ? 'Use ↑ ↓ arrow keys to navigate, Enter to select, Esc to go back'
          : 'Use ← → arrow keys to navigate, Enter to select, Esc to go back'
      )
    )
  );
};