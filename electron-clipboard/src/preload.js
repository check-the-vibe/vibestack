const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  getClipboard: () => ipcRenderer.invoke('get-clipboard'),
  startMonitoring: () => ipcRenderer.send('start-monitoring'),
  stopMonitoring: () => ipcRenderer.send('stop-monitoring'),
  onClipboardChange: (callback) => {
    ipcRenderer.on('clipboard-changed', (event, content) => callback(content));
  },
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  getSettings: () => ipcRenderer.invoke('get-settings'),
  setAutoSave: (enabled) => ipcRenderer.send('set-auto-save', enabled)
});