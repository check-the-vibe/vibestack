// Terminal Overlay Content Script - Vibestack Integration
(function() {
  'use strict';
  
  let globalTerminal = null;

  if (window.vibestackTerminalInjected) {
    return;
  }
  window.vibestackTerminalInjected = true;

  class VibestackPageTerminal {
    constructor() {
      this.commandHistory = [];
      this.historyIndex = 0;
      this.isVisible = false;
      this.vibestackApiUrl = this.detectVibestackUrl();
      this.currentSession = null;
      this.sessions = [];
      this.logPollInterval = null;
      this.lastLogLength = 0;
      this.createTerminal();
      this.initializeEventListeners();
      this.initializeSettings();
    }

    detectVibestackUrl() {
      if (typeof window.VIBESTACK_CONFIG !== 'undefined' && window.VIBESTACK_CONFIG.configured) {
        return window.VIBESTACK_CONFIG.baseUrl;
      }
      
      const currentOrigin = window.location.origin;
      
      if (currentOrigin.includes('ngrok') || 
          currentOrigin.includes('vibestack') || 
          document.querySelector('meta[name="vibestack"]')) {
        return currentOrigin;
      }
      
      const savedUrl = localStorage.getItem('vibestackApiUrl');
      if (savedUrl) {
        return savedUrl;
      }
      
      return 'https://afeeb1ba4000.ngrok.app';
    }

    createTerminal() {
      this.container = document.createElement('div');
      this.container.id = 'vibestack-terminal';
      this.container.innerHTML = `
        <style>
          #vibestack-terminal {
            position: fixed !important;
            bottom: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 300px !important;
            background: #0c0c0c !important;
            color: #00ff00 !important;
            font-family: 'Courier New', monospace !important;
            font-size: 10px !important;
            z-index: 999999 !important;
            border-top: 2px solid #333 !important;
            box-sizing: border-box !important;
            transform: translateY(100%) !important;
            transition: transform 0.3s ease !important;
            display: flex !important;
            flex-direction: column !important;
            padding: 5px 10px !important;
          }
          
          #vibestack-terminal.visible {
            transform: translateY(0) !important;
          }
          
          #vibestack-terminal-header {
            border-bottom: 1px solid #333 !important;
            padding-bottom: 2px !important;
            margin-bottom: 3px !important;
            font-size: 9px !important;
            color: #888 !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
          }
          
          #vibestack-session-section {
            margin-bottom: 3px !important;
            font-size: 8px !important;
            display: flex !important;
            align-items: center !important;
            gap: 5px !important;
            flex-wrap: wrap !important;
          }
          
          #vibestack-api-url-input {
            background: #1a1a1a !important;
            border: 1px solid #333 !important;
            color: #00ff00 !important;
            padding: 1px 3px !important;
            font-family: 'Courier New', monospace !important;
            font-size: 8px !important;
            width: 200px !important;
          }
          
          #vibestack-session-select {
            background: #1a1a1a !important;
            border: 1px solid #333 !important;
            color: #00ff00 !important;
            padding: 1px 3px !important;
            font-family: 'Courier New', monospace !important;
            font-size: 8px !important;
            min-width: 120px !important;
          }
          
          .vibestack-btn {
            background: #333 !important;
            border: 1px solid #555 !important;
            color: #00ff00 !important;
            padding: 1px 6px !important;
            font-family: 'Courier New', monospace !important;
            font-size: 8px !important;
            cursor: pointer !important;
          }
          
          .vibestack-btn:hover {
            background: #555 !important;
          }
          
          .vibestack-btn:disabled {
            opacity: 0.5 !important;
            cursor: not-allowed !important;
          }
          
          #vibestack-close-btn {
            background: #555 !important;
            border: 1px solid #777 !important;
            color: #ff4444 !important;
            padding: 1px 6px !important;
            font-family: 'Courier New', monospace !important;
            font-size: 8px !important;
            cursor: pointer !important;
          }
          
          #vibestack-close-btn:hover {
            background: #777 !important;
          }
          
          #vibestack-output {
            flex: 1 !important;
            overflow-y: auto !important;
            padding: 2px 0 !important;
            font-size: 9px !important;
            line-height: 1.2 !important;
            white-space: pre-wrap !important;
            word-break: break-word !important;
          }
          
          #vibestack-input-line {
            display: flex !important;
            align-items: center !important;
            border-top: 1px solid #333 !important;
            padding-top: 2px !important;
          }
          
          #vibestack-prompt {
            color: #00ff00 !important;
            margin-right: 5px !important;
            user-select: none !important;
          }
          
          #vibestack-input {
            flex: 1 !important;
            background: transparent !important;
            border: none !important;
            outline: none !important;
            color: #00ff00 !important;
            font-family: 'Courier New', monospace !important;
            font-size: 9px !important;
          }
          
          .vibestack-output-line {
            margin: 1px 0 !important;
          }
          
          .vibestack-command-echo {
            color: #888 !important;
          }
          
          .vibestack-error-text {
            color: #ff4444 !important;
          }
          
          .vibestack-success-text {
            color: #44ff44 !important;
          }
          
          .vibestack-info-text {
            color: #4488ff !important;
          }
          
          #vibestack-terminal::-webkit-scrollbar {
            width: 6px !important;
          }
          
          #vibestack-terminal::-webkit-scrollbar-track {
            background: #1a1a1a !important;
          }
          
          #vibestack-terminal::-webkit-scrollbar-thumb {
            background: #333 !important;
            border-radius: 3px !important;
          }
          
          #vibestack-terminal::-webkit-scrollbar-thumb:hover {
            background: #555 !important;
          }
        </style>
        
        <div id="vibestack-terminal-header">
          <span>Vibestack Terminal - Press Ctrl+~ to toggle</span>
          <button id="vibestack-close-btn">Close</button>
        </div>
        
        <div id="vibestack-session-section">
          API: <input type="text" id="vibestack-api-url-input" placeholder="https://..." />
          <button id="vibestack-save-url-btn" class="vibestack-btn">Save URL</button>
          <select id="vibestack-session-select">
            <option value="">No session selected</option>
          </select>
          <button id="vibestack-refresh-btn" class="vibestack-btn">Refresh</button>
          <button id="vibestack-new-session-btn" class="vibestack-btn">New Session</button>
        </div>
        
        <div id="vibestack-output"></div>
        
        <div id="vibestack-input-line">
          <span id="vibestack-prompt">$</span>
          <input type="text" id="vibestack-input" placeholder="Enter command..." />
        </div>
      `;
      
      document.body.appendChild(this.container);
      
      this.outputElement = document.getElementById('vibestack-output');
      this.inputElement = document.getElementById('vibestack-input');
      this.apiUrlInput = document.getElementById('vibestack-api-url-input');
      this.sessionSelect = document.getElementById('vibestack-session-select');
    }

    initializeEventListeners() {
      document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === '`') {
          e.preventDefault();
          this.toggle();
        }
      });

      document.getElementById('vibestack-save-url-btn').addEventListener('click', async () => {
        const url = this.apiUrlInput.value.trim();
        if (url) {
          this.vibestackApiUrl = url;
          await this.saveSettings();
          this.printOutput('API URL saved: ' + url, 'vibestack-success-text');
          await this.refreshSessions();
        } else {
          this.printOutput('Please enter a valid API URL.', 'vibestack-error-text');
        }
      });

      document.getElementById('vibestack-close-btn').addEventListener('click', () => {
        this.hide();
      });

      document.getElementById('vibestack-refresh-btn').addEventListener('click', async () => {
        await this.refreshSessions();
      });

      document.getElementById('vibestack-new-session-btn').addEventListener('click', async () => {
        await this.createNewSession();
      });

      this.sessionSelect.addEventListener('change', (e) => {
        this.switchSession(e.target.value);
      });

      this.inputElement.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          const command = this.inputElement.value.trim();
          if (command) {
            this.executeCommand(command);
            this.commandHistory.push(command);
            this.historyIndex = this.commandHistory.length;
            this.inputElement.value = '';
          }
          e.preventDefault();
        } else if (e.key === 'ArrowUp') {
          if (this.historyIndex > 0) {
            this.historyIndex--;
            this.inputElement.value = this.commandHistory[this.historyIndex];
          }
          e.preventDefault();
        } else if (e.key === 'ArrowDown') {
          if (this.historyIndex < this.commandHistory.length - 1) {
            this.historyIndex++;
            this.inputElement.value = this.commandHistory[this.historyIndex];
          } else {
            this.historyIndex = this.commandHistory.length;
            this.inputElement.value = '';
          }
          e.preventDefault();
        } else if (e.key === 'Escape') {
          this.hide();
        }
      });

      this.container.addEventListener('click', (e) => {
        e.stopPropagation();
      });
    }

    async initializeSettings() {
      try {
        const result = await chrome.storage.local.get(['vibestackApiUrl', 'vibestackCurrentSession']);
        if (result.vibestackApiUrl) {
          this.vibestackApiUrl = result.vibestackApiUrl;
          this.apiUrlInput.value = this.vibestackApiUrl;
          localStorage.setItem('vibestackApiUrl', this.vibestackApiUrl);
        }
        if (!this.apiUrlInput.value) {
          this.apiUrlInput.value = this.vibestackApiUrl;
        }
        if (result.vibestackCurrentSession) {
          this.currentSession = result.vibestackCurrentSession;
        }
      } catch (error) {
        console.log('Could not load settings:', error);
      }
    }

    async saveSettings() {
      try {
        await chrome.storage.local.set({
          vibestackApiUrl: this.vibestackApiUrl,
          vibestackCurrentSession: this.currentSession
        });
        localStorage.setItem('vibestackApiUrl', this.vibestackApiUrl);
      } catch (error) {
        console.error('Could not save settings:', error);
      }
    }

    toggle() {
      if (this.isVisible) {
        this.hide();
      } else {
        this.show();
      }
    }

    show() {
      this.container.classList.add('visible');
      this.isVisible = true;
      setTimeout(() => {
        this.inputElement.focus();
      }, 300);
      
      if (this.outputElement.children.length === 0) {
        this.printWelcome();
      }
      
      this.refreshSessions();
    }

    hide() {
      this.container.classList.remove('visible');
      this.isVisible = false;
      this.inputElement.blur();
      this.stopLogPolling();
    }

    printWelcome() {
      this.printOutput('Vibestack Terminal Ready', 'vibestack-info-text');
      this.printOutput('Commands are sent to the active Vibestack session', 'vibestack-info-text');
      this.printOutput('Press Ctrl+~ to toggle, Escape to close', 'vibestack-info-text');
      this.printOutput('', '');
    }

    printOutput(text, className = '') {
      const line = document.createElement('div');
      line.className = `vibestack-output-line ${className}`;
      line.textContent = text;
      this.outputElement.appendChild(line);
      this.outputElement.scrollTop = this.outputElement.scrollHeight;
    }

    clearOutput() {
      this.outputElement.innerHTML = '';
    }

    async refreshSessions() {
      try {
        const response = await fetch(`${this.vibestackApiUrl}/admin/api/sessions`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        this.sessions = await response.json();
        this.updateSessionSelector();
        this.printOutput(`Found ${this.sessions.length} session(s)`, 'vibestack-info-text');
      } catch (error) {
        this.printOutput(`Error fetching sessions: ${error.message}`, 'vibestack-error-text');
      }
    }

    updateSessionSelector() {
      this.sessionSelect.innerHTML = '<option value="">No session selected</option>';
      this.sessions.forEach(session => {
        const option = document.createElement('option');
        option.value = session.name;
        option.textContent = `${session.name} (${session.status})`;
        if (this.currentSession === session.name) {
          option.selected = true;
        }
        this.sessionSelect.appendChild(option);
      });
    }

    async createNewSession() {
      const sessionName = prompt('Enter session name:', `session-${Date.now()}`);
      if (!sessionName) return;

      const template = prompt('Enter template name (default: bash):', 'bash') || 'bash';

      try {
        const response = await fetch(`${this.vibestackApiUrl}/admin/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: sessionName,
            template: template,
            description: 'Created from Chrome Extension'
          })
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const session = await response.json();
        this.printOutput(`Session created: ${session.name}`, 'vibestack-success-text');
        await this.refreshSessions();
        this.switchSession(session.name);
      } catch (error) {
        this.printOutput(`Error creating session: ${error.message}`, 'vibestack-error-text');
      }
    }

    switchSession(sessionName) {
      this.stopLogPolling();
      this.currentSession = sessionName;
      this.saveSettings();
      
      if (sessionName) {
        this.clearOutput();
        this.printOutput(`Switched to session: ${sessionName}`, 'vibestack-success-text');
        this.printOutput('Loading logs...', 'vibestack-info-text');
        this.startLogPolling();
      } else {
        this.clearOutput();
        this.printWelcome();
      }
    }

    async executeCommand(command) {
      if (!this.currentSession) {
        this.printOutput('No session selected. Create or select a session first.', 'vibestack-error-text');
        return;
      }

      try {
        const response = await fetch(`${this.vibestackApiUrl}/admin/api/sessions/${this.currentSession}/input`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: command,
            enter: true
          })
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        await this.fetchAndDisplayLogs();
      } catch (error) {
        this.printOutput(`Error sending command: ${error.message}`, 'vibestack-error-text');
      }
    }

    async fetchAndDisplayLogs() {
      if (!this.currentSession) return;

      try {
        const response = await fetch(`${this.vibestackApiUrl}/admin/api/sessions/${this.currentSession}/log?lines=500`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const logLines = data.log.split('\n');
        
        if (logLines.length !== this.lastLogLength) {
          this.clearOutput();
          logLines.forEach(line => {
            if (line.trim()) {
              this.printOutput(line, '');
            }
          });
          this.lastLogLength = logLines.length;
        }
      } catch (error) {
        console.error('Error fetching logs:', error);
      }
    }

    startLogPolling() {
      this.stopLogPolling();
      this.lastLogLength = 0;
      this.fetchAndDisplayLogs();
      this.logPollInterval = setInterval(() => {
        this.fetchAndDisplayLogs();
      }, 1000);
    }

    stopLogPolling() {
      if (this.logPollInterval) {
        clearInterval(this.logPollInterval);
        this.logPollInterval = null;
      }
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === 'toggleTerminal') {
      if (globalTerminal) {
        globalTerminal.toggle();
        sendResponse({ success: true, visible: globalTerminal.isVisible });
      } else {
        sendResponse({ success: false, error: 'Terminal not initialized' });
      }
      return true;
    }
    
    if (message.action === 'getTerminalStatus') {
      if (globalTerminal) {
        sendResponse({ success: true, visible: globalTerminal.isVisible });
      } else {
        sendResponse({ success: false, error: 'Terminal not initialized' });
      }
      return true;
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      globalTerminal = new VibestackPageTerminal();
    });
  } else {
    globalTerminal = new VibestackPageTerminal();
  }

})();
