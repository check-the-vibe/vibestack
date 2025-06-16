import React, { useState } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { Tab, Tabs } from 'ink-tab';
import { spawn } from 'child_process';
import fs from 'fs/promises';
import path from 'path';
import { TextInput } from './TextInput.js';

export const AgentSelectionScreen = () => {
  const { exit } = useApp();
  const [activeTab, setActiveTab] = useState('provider');
  const [selectedProvider, setSelectedProvider] = useState('');
  const [environmentText, setEnvironmentText] = useState('');
  const [tasksText, setTasksText] = useState('');
  const [saveStatus, setSaveStatus] = useState({});

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

  const handleSaveEnvironment = async () => {
    try {
      const envPath = path.join(process.cwd(), '.vibe', 'ENVIRONMENT.md');
      await fs.mkdir(path.dirname(envPath), { recursive: true });
      await fs.writeFile(envPath, `# Environment Configuration\n\n${environmentText}\n`);
      setSaveStatus({ ...saveStatus, environment: 'Saved!' });
      setTimeout(() => setSaveStatus({ ...saveStatus, environment: null }), 2000);
    } catch (error) {
      setSaveStatus({ ...saveStatus, environment: 'Error saving' });
    }
  };

  const handleSaveTasks = async () => {
    try {
      const tasksPath = path.join(process.cwd(), '.vibe', 'TASKS.md');
      await fs.mkdir(path.dirname(tasksPath), { recursive: true });
      await fs.writeFile(tasksPath, `# Tasks\n\n${tasksText}\n`);
      setSaveStatus({ ...saveStatus, tasks: 'Saved!' });
      setTimeout(() => setSaveStatus({ ...saveStatus, tasks: null }), 2000);
    } catch (error) {
      setSaveStatus({ ...saveStatus, tasks: 'Error saving' });
    }
  };

  useInput((input, key) => {
    // Global shortcuts
    if (input === 'q' && activeTab === 'provider') {
      exit();
    } else if (key.ctrl && input === 's') {
      // Save current tab
      if (activeTab === 'environment') {
        handleSaveEnvironment();
      } else if (activeTab === 'tasks') {
        handleSaveTasks();
      } else if (activeTab === 'provider' && selectedProvider) {
        handleStart();
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
      
      case 'environment':
        return React.createElement(Box, { flexDirection: 'column' },
          React.createElement(TextInput, {
            label: 'Environment Configuration',
            value: environmentText,
            onChange: setEnvironmentText,
            placeholder: 'Enter environments (e.g., GitHub Codespaces, Docker)',
            multiline: false
          }),
          saveStatus.environment && React.createElement(Text, { 
            color: saveStatus.environment === 'Saved!' ? 'green' : 'red',
            marginTop: 1 
          }, saveStatus.environment)
        );
      
      case 'tools':
        return React.createElement(Box, { paddingY: 2 },
          React.createElement(Text, { color: 'yellow' }, 'Coming Soon!')
        );
      
      case 'tasks':
        return React.createElement(Box, { flexDirection: 'column' },
          React.createElement(TextInput, {
            label: 'Tasks Configuration',
            value: tasksText,
            onChange: setTasksText,
            placeholder: 'Enter your tasks here...',
            multiline: true
          }),
          saveStatus.tasks && React.createElement(Text, { 
            color: saveStatus.tasks === 'Saved!' ? 'green' : 'red',
            marginTop: 1 
          }, saveStatus.tasks)
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
        activeTab === 'provider' 
          ? 'Tab: Switch tabs | 1/2: Select provider | Enter: Start | q: Quit'
          : 'Tab: Switch tabs | Type to edit | Ctrl+S: Save | q: Back to provider tab'
      )
    )
  );
};