import React, { useState } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { Tab, Tabs } from 'ink-tab';
import { spawn } from 'child_process';
import fs from 'fs/promises';
import path from 'path';
import { FocusableTextInput } from './FocusableTextInput.js';

export const AgentSelectionScreen = () => {
  const { exit } = useApp();
  const [activeTab, setActiveTab] = useState('provider');
  const [selectedProvider, setSelectedProvider] = useState('');
  const [environmentText, setEnvironmentText] = useState('');
  const [tasksText, setTasksText] = useState('');
  const [saveStatus, setSaveStatus] = useState({});
  const [activeField, setActiveField] = useState('environment'); // Which field is active in config tab

  const handleTabChange = (name) => {
    setActiveTab(name);
    if (name === 'configuration') {
      setActiveField('environment');
    }
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

  const handleSaveConfiguration = async () => {
    try {
      // Save environment
      const envPath = path.join(process.cwd(), '.vibe', 'ENVIRONMENT.md');
      await fs.mkdir(path.dirname(envPath), { recursive: true });
      await fs.writeFile(envPath, `# Environment Configuration\n\n${environmentText}\n`);
      
      // Save tasks
      const tasksPath = path.join(process.cwd(), '.vibe', 'TASKS.md');
      await fs.writeFile(tasksPath, `# Tasks\n\n${tasksText}\n`);
      
      setSaveStatus({ configuration: 'Both saved!' });
      setTimeout(() => setSaveStatus({}), 2000);
    } catch (error) {
      setSaveStatus({ configuration: 'Error saving' });
    }
  };

  useInput((input, key) => {
    // Global shortcuts
    if (input === 'q' && activeTab === 'provider') {
      exit();
    } else if (key.ctrl && input === 's') {
      // Save based on active tab
      if (activeTab === 'configuration') {
        handleSaveConfiguration();
      } else if (activeTab === 'provider' && selectedProvider) {
        handleStart();
      }
    }
    
    // Tab navigation with arrow keys in configuration tab
    if (activeTab === 'configuration') {
      if (key.upArrow || key.downArrow) {
        setActiveField(activeField === 'environment' ? 'tasks' : 'environment');
      }
    }
    
    // Provider tab specific
    if (activeTab === 'provider') {
      if (input === '1') {
        setSelectedProvider('claude');
      } else if (input === '2') {
        setSelectedProvider('llm');
      } else if (key.return && selectedProvider) {
        handleStart();
      }
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
      
      case 'configuration':
        return React.createElement(Box, { flexDirection: 'column' },
          React.createElement(Box, { marginBottom: 2 },
            React.createElement(FocusableTextInput, {
              label: 'Environment Configuration',
              value: environmentText,
              onChange: setEnvironmentText,
              placeholder: 'Enter environments (e.g., GitHub Codespaces, Docker)',
              multiline: false,
              isActive: activeField === 'environment'
            })
          ),
          React.createElement(Box, {},
            React.createElement(FocusableTextInput, {
              label: 'Tasks',
              value: tasksText,
              onChange: setTasksText,
              placeholder: 'Enter your tasks here...',
              multiline: true,
              isActive: activeField === 'tasks'
            })
          ),
          saveStatus.configuration && React.createElement(Text, { 
            color: saveStatus.configuration === 'Both saved!' ? 'green' : 'red',
            marginTop: 1 
          }, saveStatus.configuration),
          React.createElement(Box, { marginTop: 1 },
            React.createElement(Text, { dimColor: true }, 
              '↑↓ Switch fields | Type to edit active field | Ctrl+S to save both'
            )
          )
        );
      
      case 'tools':
        return React.createElement(Box, { paddingY: 2 },
          React.createElement(Text, { color: 'yellow' }, 'Coming Soon!')
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
        React.createElement(Tab, { name: 'configuration' }, 'Configuration'),
        React.createElement(Tab, { name: 'tools' }, 'Tools')
      )
    ),

    // Tab Content
    React.createElement(Box, { minHeight: 12 },
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
        activeTab === 'provider' 
          ? 'Tab: Switch tabs | 1/2: Select provider | Enter: Start | q: Quit'
          : 'Tab: Switch tabs | Type to edit | Ctrl+S: Save | q: Back to provider tab'
      )
    )
  );
};