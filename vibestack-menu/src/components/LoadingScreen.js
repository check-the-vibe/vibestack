import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import BigText from 'ink-big-text';
import Gradient from 'ink-gradient';

export const LoadingScreen = ({ onComplete }) => {
  const [showButton, setShowButton] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    // Show button after animation
    const timer = setTimeout(() => setShowButton(true), 2000);
    return () => clearTimeout(timer);
  }, []);

  useInput((input, key) => {
    if (key.return && showButton) {
      onComplete();
    }
  });

  return React.createElement(Box, {
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    paddingY: 4
  },
    React.createElement(Box, { marginBottom: 4 },
      React.createElement(Gradient, { name: 'rainbow' },
        React.createElement(BigText, { text: 'Vibe Stack', font: 'block' })
      )
    ),
    
    showButton && React.createElement(Box, {
      borderStyle: 'round',
      borderColor: isHovered ? 'cyan' : 'gray',
      paddingX: 3,
      paddingY: 1
    },
      React.createElement(Text, { color: isHovered ? 'cyan' : 'white', bold: true },
        'Get Started'
      )
    ),
    
    showButton && React.createElement(Box, { marginTop: 2 },
      React.createElement(Text, { dimColor: true }, 'Press Enter to continue')
    )
  );
};