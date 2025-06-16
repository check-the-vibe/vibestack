import React, { useState } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { Tab, Tabs } from 'ink-tab';
import { spawn } from 'child_process';

export const AgentSelectionScreen = () => {
  const { exit } = useApp();
  const [activeTab, setActiveTab] = useState('provider');
  const [selectedProvider, setSelectedProvider] = useState('');

  const handleTabChange = (name) => {
    setActiveTab(name);
  };

  const handleStart = () => {
    if (selectedProvider) {
      exit();
      spawn(selectedProvider, [], {
        stdio: 'inherit',
        shell: true
      });
    }
  };

  useInput((input, key) => {
    if (input === '1') {
      setSelectedProvider('claude');
    } else if (input === '2') {
      setSelectedProvider('llm');
    } else if (key.return && selectedProvider) {
      handleStart();
    } else if (input === 'q') {
      exit();
    }
  });

  const renderTabContent = () => {
    switch (activeTab) {
      case 'provider':
        return React.createElement(Box, { flexDirection: 'column' },
          React.createElement(Text, { bold: true }, 'Select LLM Provider:'),
          React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
            React.createElement(Text, { color: selectedProvider === 'claude' ? 'cyan' : 'white' },
              '1. Claude ' + (selectedProvider === 'claude' ? '(selected)' : '')
            ),
            React.createElement(Text, { color: selectedProvider === 'llm' ? 'cyan' : 'white' },
              '2. LLM ' + (selectedProvider === 'llm' ? '(selected)' : '')
            )
          )
        );
      
      case 'environment':
        return React.createElement(Box, { flexDirection: 'column' },
          React.createElement(Text, { bold: true }, 'Environment Configuration'),
          React.createElement(Text, { marginTop: 1 }, 'GitHub Codespaces / Docker support')
        );
      
      case 'tools':
        return React.createElement(Box, { paddingY: 2 },
          React.createElement(Text, { color: 'yellow' }, 'Coming Soon!')
        );
      
      case 'tasks':
        return React.createElement(Box, { flexDirection: 'column' },
          React.createElement(Text, { bold: true }, 'Tasks Configuration'),
          React.createElement(Text, { marginTop: 1 }, 'Define your tasks here')
        );
      
      default:
        return null;
    }
  };

  return React.createElement(Box, {
    flexDirection: 'column',
    paddingX: 2,
    paddingY: 1
  },
    // Logo
    React.createElement(Box, { marginBottom: 2 },
      React.createElement(Text, { bold: true, color: 'cyan' }, 'VS')
    ),

    // Tabs
    React.createElement(Box, { marginBottom: 2 },
      React.createElement(Tabs, { onChange: handleTabChange },
        React.createElement(Tab, { name: 'provider' }, 'Provider'),
        React.createElement(Tab, { name: 'environment' }, 'Environment'),
        React.createElement(Tab, { name: 'tools' }, 'Tools'),
        React.createElement(Tab, { name: 'tasks' }, 'Tasks')
      )
    ),

    // Tab Content
    React.createElement(Box, { minHeight: 10 },
      renderTabContent()
    ),

    // Start Button
    selectedProvider && React.createElement(Box, {
      marginTop: 2,
      flexDirection: 'column'
    },
      React.createElement(Box, {
        borderStyle: 'round',
        borderColor: 'green',
        paddingX: 3,
        paddingY: 1,
        alignSelf: 'center'
      },
        React.createElement(Text, { color: 'green', bold: true }, 'Start')
      ),
      React.createElement(Box, { marginTop: 1, alignSelf: 'center' },
        React.createElement(Text, { dimColor: true }, 'Press Enter to start')
      )
    ),

    // Help text
    React.createElement(Box, { marginTop: 2 },
      React.createElement(Text, { dimColor: true },
        'Tab: Switch tabs | 1/2: Select provider | Enter: Start | q: Quit'
      )
    )
  );
};