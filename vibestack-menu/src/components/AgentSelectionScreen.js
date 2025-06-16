import React, { useState } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { Tab, Tabs } from 'ink-tab';
import { Form } from 'ink-form';
import { spawn } from 'child_process';
import fs from 'fs/promises';
import path from 'path';

const TabContent = ({ activeTab, formData, onUpdate }) => {
  switch (activeTab) {
    case 'provider':
      return (
        <Form
          onSubmit={(values) => onUpdate('provider', values.providers)}
          customSubmit
          form={{
            sections: [{
              title: 'Select LLM Providers',
              fields: [{
                name: 'providers',
                label: 'Available Providers',
                type: 'multiSelect',
                options: [
                  { label: 'Claude', value: 'claude' },
                  { label: 'LLM', value: 'llm' }
                ],
                initialValue: formData.provider || []
              }]
            }]
          }}
        />
      );
    
    case 'environment':
      return (
        <Form
          onSubmit={async (values) => {
            // Save to ENVIRONMENT.md
            const envPath = path.join(process.cwd(), '.vibe', 'ENVIRONMENT.md');
            const content = `# Environment Configuration\n\nEnvironments: ${values.environments.join(', ')}\n`;
            
            try {
              await fs.mkdir(path.dirname(envPath), { recursive: true });
              await fs.writeFile(envPath, content);
              onUpdate('environment', values.environments);
            } catch (error) {
              console.error('Failed to save environment:', error);
            }
          }}
          customSubmit
          form={{
            sections: [{
              title: 'Select Environment',
              fields: [{
                name: 'environments',
                label: 'Target Environments',
                type: 'multiSelect',
                options: [
                  { label: 'GitHub Codespaces', value: 'codespaces' },
                  { label: 'Docker', value: 'docker' }
                ],
                initialValue: formData.environment || []
              }]
            }],
            buttons: [{
              label: 'Save',
              value: 'submit'
            }]
          }}
        />
      );
    
    case 'tools':
      return (
        <Box paddingY={2}>
          <Text color="yellow">Coming Soon!</Text>
        </Box>
      );
    
    case 'tasks':
      return (
        <Form
          onSubmit={async (values) => {
            // Save to TASKS.md
            const tasksPath = path.join(process.cwd(), '.vibe', 'TASKS.md');
            const content = `# Tasks\n\n${values.taskDescription}\n`;
            
            try {
              await fs.mkdir(path.dirname(tasksPath), { recursive: true });
              await fs.writeFile(tasksPath, content);
              onUpdate('tasks', values.taskDescription);
            } catch (error) {
              console.error('Failed to save tasks:', error);
            }
          }}
          customSubmit
          form={{
            sections: [{
              title: 'Define Tasks',
              fields: [{
                name: 'taskDescription',
                label: 'Task Description',
                type: 'string',
                multiline: true,
                initialValue: formData.tasks || ''
              }]
            }],
            buttons: [{
              label: 'Save',
              value: 'submit'
            }]
          }}
        />
      );
    
    default:
      return null;
  }
};

export const AgentSelectionScreen = () => {
  const { exit } = useApp();
  const [activeTab, setActiveTab] = useState('provider');
  const [formData, setFormData] = useState({
    provider: [],
    environment: [],
    tasks: ''
  });
  const [showStartButton, setShowStartButton] = useState(false);

  const handleTabChange = (name) => {
    setActiveTab(name);
  };

  const handleFormUpdate = (field, value) => {
    setFormData({
      ...formData,
      [field]: value
    });
    
    // Show start button if we have a provider selected
    if (field === 'provider' && value.length > 0) {
      setShowStartButton(true);
    }
  };

  const handleStart = () => {
    if (formData.provider.length === 0) {
      return;
    }

    const selectedProvider = formData.provider[0];
    
    // Exit Ink app first
    exit();
    
    // Launch the selected provider
    spawn(selectedProvider, [], {
      stdio: 'inherit',
      shell: true
    });
  };

  useInput((input, key) => {
    if (key.ctrl && input === 's' && showStartButton) {
      handleStart();
    }
    if (input === 'q') {
      exit();
    }
  });

  return (
    <Box flexDirection="column" paddingX={2} paddingY={1}>
      {/* Logo */}
      <Box marginBottom={2}>
        <Text bold color="cyan" fontSize={2}>VS</Text>
      </Box>

      {/* Tabs */}
      <Box marginBottom={2}>
        <Tabs onChange={handleTabChange}>
          <Tab name="provider">Provider</Tab>
          <Tab name="environment">Environment</Tab>
          <Tab name="tools">Tools</Tab>
          <Tab name="tasks">Tasks</Tab>
        </Tabs>
      </Box>

      {/* Tab Content */}
      <Box minHeight={10}>
        <TabContent 
          activeTab={activeTab}
          formData={formData}
          onUpdate={handleFormUpdate}
        />
      </Box>

      {/* Start Button */}
      {showStartButton && (
        <Box marginTop={2} flexDirection="column">
          <Box 
            borderStyle="round"
            borderColor={formData.provider.length > 0 ? 'green' : 'gray'}
            paddingX={3}
            paddingY={1}
            alignSelf="center"
          >
            <Text color={formData.provider.length > 0 ? 'green' : 'gray'} bold>
              Start
            </Text>
          </Box>
          <Box marginTop={1} alignSelf="center">
            <Text dimColor>Press Ctrl+S to start with selected provider</Text>
          </Box>
        </Box>
      )}

      {/* Help text */}
      <Box marginTop={2}>
        <Text dimColor>
          Tab: Switch tabs | Enter: Select | Space: Toggle option | q: Quit
        </Text>
      </Box>
    </Box>
  );
};