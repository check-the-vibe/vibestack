import React, { useState } from 'react';
import { Box } from 'ink';
import { LoadingScreen } from './components/LoadingScreen.js';
import { AgentSelectionScreen } from './components/AgentSelectionCombined.js';

export const VibeStackMenuNew = () => {
  const [screen, setScreen] = useState('loading');

  const handleLoadingComplete = () => {
    setScreen('agent-selection');
  };

  return React.createElement(Box, {
    flexDirection: 'column',
    height: '100%'
  },
    screen === 'loading' && React.createElement(LoadingScreen, {
      onComplete: handleLoadingComplete
    }),
    screen === 'agent-selection' && React.createElement(AgentSelectionScreen)
  );
};