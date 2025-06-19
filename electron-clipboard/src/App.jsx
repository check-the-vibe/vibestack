import React, { useState, useEffect } from 'react';

const App = () => {
  const [clipboardContent, setClipboardContent] = useState('');
  const [isMonitoring, setIsMonitoring] = useState(false);
  const [history, setHistory] = useState([]);
  const [outputFolder, setOutputFolder] = useState('');
  const [autoSaveEnabled, setAutoSaveEnabled] = useState(false);

  useEffect(() => {
    // Listen for clipboard updates from main process
    window.electronAPI.onClipboardChange((content) => {
      setClipboardContent(content);
      setHistory(prev => [...prev, { content, timestamp: new Date().toLocaleTimeString() }].slice(-10));
    });

    // Get initial clipboard content
    window.electronAPI.getClipboard().then(content => {
      setClipboardContent(content);
    });
    
    // Load settings
    window.electronAPI.getSettings().then(settings => {
      setOutputFolder(settings.outputFolder || '');
      setAutoSaveEnabled(settings.autoSaveEnabled || false);
    });
  }, []);

  const toggleMonitoring = () => {
    if (isMonitoring) {
      window.electronAPI.stopMonitoring();
    } else {
      window.electronAPI.startMonitoring();
    }
    setIsMonitoring(!isMonitoring);
  };
  
  const selectOutputFolder = async () => {
    const folder = await window.electronAPI.selectFolder();
    if (folder) {
      setOutputFolder(folder);
    }
  };
  
  const toggleAutoSave = () => {
    const newValue = !autoSaveEnabled;
    setAutoSaveEnabled(newValue);
    window.electronAPI.setAutoSave(newValue);
  };

  return (
    <div className="app">
      <h1>Electron Clipboard Monitor</h1>
      
      <div className="status">
        <h2>Status: {isMonitoring ? 'Monitoring' : 'Stopped'}</h2>
        <button onClick={toggleMonitoring}>
          {isMonitoring ? 'Stop Monitoring' : 'Start Monitoring'}
        </button>
      </div>

      <div className="settings">
        <h3>Save Settings:</h3>
        <div className="settings-group">
          <div className="folder-selection">
            <label>Output Folder:</label>
            <div className="folder-input">
              <input 
                type="text" 
                value={outputFolder || '(no folder selected)'} 
                readOnly 
                placeholder="Click to select folder"
              />
              <button onClick={selectOutputFolder}>Browse...</button>
            </div>
          </div>
          <div className="auto-save-toggle">
            <label>
              <input 
                type="checkbox" 
                checked={autoSaveEnabled} 
                onChange={toggleAutoSave}
              />
              Auto-save clipboard content to file
            </label>
          </div>
        </div>
      </div>

      <div className="current-content">
        <h3>Current Clipboard:</h3>
        <div className="content-box">
          {clipboardContent || '(empty)'}
        </div>
      </div>

      <div className="history">
        <h3>Recent History:</h3>
        <ul>
          {history.map((item, index) => (
            <li key={index}>
              <span className="timestamp">{item.timestamp}</span>: {item.content.substring(0, 50)}...
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default App;