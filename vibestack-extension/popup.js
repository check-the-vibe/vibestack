// Popup Controller for Vibestack Terminal
document.addEventListener('DOMContentLoaded', () => {
  const toggleButton = document.getElementById('toggleButton');
  const statusDiv = document.getElementById('status');
  
  // Handle toggle button click
  toggleButton.addEventListener('click', async () => {
    try {
      // Get the active tab
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      
      if (!tab) {
        showStatus('No active tab found', 'error');
        return;
      }
      
      // Send message to content script to toggle terminal
      const response = await chrome.tabs.sendMessage(tab.id, {
        action: 'toggleTerminal'
      });
      
      if (response && response.success) {
        const status = response.visible ? 'Terminal shown' : 'Terminal hidden';
        showStatus(status, 'success');
        updateButtonText(response.visible);
      } else {
        // If content script not loaded, inject it first
        try {
          await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files: ['terminal-overlay.js']
          });
          
          // Wait a moment for injection to complete
          setTimeout(async () => {
            try {
              const retryResponse = await chrome.tabs.sendMessage(tab.id, {
                action: 'toggleTerminal'
              });
              
              if (retryResponse && retryResponse.success) {
                const status = retryResponse.visible ? 'Terminal shown' : 'Terminal hidden';
                showStatus(status, 'success');
                updateButtonText(retryResponse.visible);
              } else {
                showStatus('Failed to toggle terminal', 'error');
              }
            } catch (retryError) {
              showStatus('Terminal injection failed', 'error');
            }
          }, 500);
          
        } catch (injectionError) {
          showStatus('Cannot inject on this page', 'error');
        }
      }
    } catch (error) {
      showStatus('Communication error', 'error');
      console.error('Toggle error:', error);
    }
  });
  
  function showStatus(message, type) {
    statusDiv.textContent = message;
    statusDiv.className = `status ${type}`;
    statusDiv.style.display = 'block';
    
    // Hide status after 3 seconds
    setTimeout(() => {
      statusDiv.style.display = 'none';
    }, 3000);
  }
  
  function updateButtonText(visible) {
    toggleButton.textContent = visible ? 'Hide Terminal' : 'Show Terminal';
  }
  
  // Check terminal status on popup open
  checkTerminalStatus();
  
  async function checkTerminalStatus() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      
      if (!tab) {
        return;
      }
      
      // Try to get terminal status
      const response = await chrome.tabs.sendMessage(tab.id, {
        action: 'getTerminalStatus'
      });
      
      if (response && response.success) {
        updateButtonText(response.visible);
      }
    } catch (error) {
      // Content script not loaded or no response - keep default text
    }
  }
});