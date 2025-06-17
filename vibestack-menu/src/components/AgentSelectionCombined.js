import React, { useState, useEffect } from 'react';
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
  const [baseUrl, setBaseUrl] = useState('');

  // Detect base URL on component mount
  useEffect(() => {
    const isCodespaces = process.env.CODESPACES === 'true';
    if (isCodespaces) {
      const codespaceName = process.env.CODESPACE_NAME || '';
      const domain = process.env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN || 'app.github.dev';
      setBaseUrl(`https://${codespaceName}-80.${domain}/ui`);
    } else {
      setBaseUrl('http://localhost/ui');
    }
  }, []);

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
      if (activeTab === 'provider' && selectedProvider) {
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
      
      case 'configuration':
        return React.createElement(Box, { flexDirection: 'column' },
          React.createElement(Text, { bold: true, marginBottom: 2 }, 'Configuration'),
          React.createElement(Box, { marginBottom: 1 },
            React.createElement(Text, {}, 'To configure your environment and tasks, visit:')
          ),
          React.createElement(Box, { marginBottom: 2 },
            React.createElement(Text, { color: 'cyan', underline: true }, baseUrl || 'Loading...')
          ),
          React.createElement(Box, { marginTop: 2 },
            React.createElement(Text, { dimColor: true }, 
              'The web interface allows you to edit:'
            )
          ),
          React.createElement(Box, { marginLeft: 2, flexDirection: 'column' },
            React.createElement(Text, { dimColor: true }, '• Environment configuration'),
            React.createElement(Text, { dimColor: true }, '• Tasks'),
            React.createElement(Text, { dimColor: true }, '• Errors'),
            React.createElement(Text, { dimColor: true }, '• Persona')
          ),
          React.createElement(Box, { marginTop: 2 },
            React.createElement(Text, { color: 'yellow' }, 
              'Note: Configuration editing has been moved to the web interface for a better experience.'
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
          : 'Tab: Switch tabs | q: Back to provider tab'
      )
    )
  );
};