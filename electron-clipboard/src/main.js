const { app, BrowserWindow, ipcMain, clipboard, dialog } = require('electron');
const path = require('node:path');
const fs = require('node:fs').promises;
const Store = require('electron-store');

// Disable sandbox for development (fixes Linux sandbox error)
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-setuid-sandbox');
app.commandLine.appendSwitch('disable-gpu-sandbox');

// Force disable sandbox through environment
process.env['ELECTRON_DISABLE_SANDBOX'] = '1';

// Initialize store for user preferences
let store;
try {
  store = new Store({
    defaults: {
      outputFolder: null,
      autoSaveEnabled: false
    }
  });
} catch (error) {
  console.error('Failed to initialize electron-store:', error);
  // Fallback to in-memory storage
  const memoryStore = {
    data: { outputFolder: null, autoSaveEnabled: false },
    get: (key) => memoryStore.data[key],
    set: (key, value) => { memoryStore.data[key] = value; }
  };
  store = memoryStore;
}

// Handle creating/removing shortcuts on Windows when installing/uninstalling.
if (require('electron-squirrel-startup')) {
  app.quit();
}

const createWindow = () => {
  // Create the browser window.
  mainWindow = new BrowserWindow({
    width: 900,
    height: 700,
    webPreferences: {
      preload: MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY,
      contextIsolation: true,
      nodeIntegration: false
    },
  });

  // and load the index.html of the app.
  mainWindow.loadURL(MAIN_WINDOW_WEBPACK_ENTRY);

  // Open the DevTools.
  // mainWindow.webContents.openDevTools();
  
  return mainWindow;
};

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(() => {
  createWindow();

  // On OS X it's common to re-create a window in the app when the
  // dock icon is clicked and there are no other windows open.
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Clipboard monitoring functionality
let clipboardMonitor = null;
let lastClipboardContent = '';
let mainWindow = null;

const startClipboardMonitoring = () => {
  if (clipboardMonitor) return;
  
  clipboardMonitor = setInterval(() => {
    const currentContent = clipboard.readText();
    if (currentContent !== lastClipboardContent) {
      lastClipboardContent = currentContent;
      if (mainWindow) {
        mainWindow.webContents.send('clipboard-changed', currentContent);
        // Execute demo function when clipboard changes
        console.log('Clipboard changed:', currentContent);
        executeDemoFunction(currentContent);
      }
    }
  }, 500); // Check every 500ms
};

const stopClipboardMonitoring = () => {
  if (clipboardMonitor) {
    clearInterval(clipboardMonitor);
    clipboardMonitor = null;
  }
};

const executeDemoFunction = async (content) => {
  // Demo function that runs when clipboard changes
  console.log(`[DEMO] Processing clipboard content: "${content}"`);
  console.log(`[DEMO] Content length: ${content.length} characters`);
  console.log(`[DEMO] Content preview: ${content.substring(0, 50)}...`);
  
  // Save to file if enabled
  await saveClipboardToFile(content);
};

const saveClipboardToFile = async (content) => {
  const outputFolder = store.get('outputFolder');
  const autoSaveEnabled = store.get('autoSaveEnabled');
  
  if (!autoSaveEnabled || !outputFolder) {
    return;
  }
  
  try {
    // Get current date in YYYY-MM-DD format
    const date = new Date();
    const dateStr = date.toISOString().split('T')[0];
    const filename = `${dateStr}.md`;
    const filepath = path.join(outputFolder, filename);
    
    // Format the content with timestamp
    const timestamp = date.toLocaleTimeString();
    const entry = `- [${timestamp}] ${content}\n`;
    
    // Append to file (create if doesn't exist)
    await fs.appendFile(filepath, entry, 'utf8');
    console.log(`[SAVE] Clipboard content saved to ${filepath}`);
  } catch (error) {
    console.error('[SAVE] Error saving clipboard content:', error);
  }
};

// IPC handlers - Register all handlers before app is ready
console.log('[MAIN] Registering IPC handlers...');

ipcMain.handle('get-clipboard', () => {
  return clipboard.readText();
});

ipcMain.on('start-monitoring', () => {
  startClipboardMonitoring();
});

ipcMain.on('stop-monitoring', () => {
  stopClipboardMonitoring();
});

// IPC handlers for folder selection and settings
ipcMain.handle('select-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select Output Folder',
    buttonLabel: 'Select Folder'
  });
  
  if (!result.canceled && result.filePaths.length > 0) {
    const folderPath = result.filePaths[0];
    store.set('outputFolder', folderPath);
    return folderPath;
  }
  return null;
});

ipcMain.handle('get-settings', async () => {
  console.log('[MAIN] get-settings handler called');
  try {
    const settings = {
      outputFolder: store.get('outputFolder') || null,
      autoSaveEnabled: store.get('autoSaveEnabled') || false
    };
    console.log('[MAIN] Returning settings:', settings);
    return settings;
  } catch (error) {
    console.error('[SETTINGS] Error getting settings:', error);
    return {
      outputFolder: null,
      autoSaveEnabled: false
    };
  }
});

ipcMain.on('set-auto-save', (event, enabled) => {
  store.set('autoSaveEnabled', enabled);
});

console.log('[MAIN] All IPC handlers registered successfully');

// Cleanup on app quit
app.on('before-quit', () => {
  stopClipboardMonitoring();
});
