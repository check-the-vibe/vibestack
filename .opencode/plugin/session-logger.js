import { appendFileSync, existsSync, mkdirSync } from 'fs';
import { dirname, join } from 'path';

export const SessionLogger = async ({ project, client, $, directory, worktree }) => {
  const logPath = join(directory, 'log.txt');
  
  const ensureLogFile = () => {
    try {
      const dir = dirname(logPath);
      if (!existsSync(dir)) {
        mkdirSync(dir, { recursive: true });
      }
    } catch (error) {
      console.error('SessionLogger: Failed to ensure log directory:', error.message);
    }
  };

  const writeLog = (message) => {
    try {
      ensureLogFile();
      const timestamp = new Date().toISOString();
      const logEntry = `[${timestamp}] ${message}\n`;
      appendFileSync(logPath, logEntry, 'utf8');
    } catch (error) {
      console.error('SessionLogger: Failed to write log:', error.message);
    }
  };

  const formatArgs = (args) => {
    try {
      if (!args || typeof args !== 'object') {
        return '';
      }
      
      const parts = [];
      for (const [key, value] of Object.entries(args)) {
        if (value === null || value === undefined) continue;
        
        let displayValue = value;
        if (typeof value === 'string' && value.length > 100) {
          displayValue = value.substring(0, 100) + '...';
        } else if (typeof value === 'object') {
          displayValue = JSON.stringify(value).substring(0, 100);
          if (displayValue.length >= 100) displayValue += '...';
        }
        
        parts.push(`${key}=${displayValue}`);
      }
      
      return parts.length > 0 ? ` | ${parts.join(', ')}` : '';
    } catch (error) {
      return '';
    }
  };

  writeLog('SESSION_START | OpenCode session initialized');

  return {
    event: async ({ event }) => {
      try {
        if (event.type === 'session.idle') {
          writeLog('SESSION_IDLE | Session became idle');
        } else if (event.type === 'session.active') {
          writeLog('SESSION_ACTIVE | Session became active');
        } else {
          writeLog(`EVENT | ${event.type}`);
        }
      } catch (error) {
        console.error('SessionLogger event hook error:', error.message);
      }
    },

    'tool.execute.before': async (input, output) => {
      try {
        const toolName = input?.tool || 'unknown';
        const args = output?.args || {};
        const formattedArgs = formatArgs(args);
        
        writeLog(`TOOL_CALL | ${toolName}${formattedArgs}`);
      } catch (error) {
        console.error('SessionLogger tool.execute.before hook error:', error.message);
      }
    },
  };
};
