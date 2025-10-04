const DEBUG_LOGGING = true; // Global flag to enable/disable logging

function log(...args) {
  if (DEBUG_LOGGING) {
    console.log("VIBESTACK:", ...args);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.target !== 'background') return;
  if (message.type === 'chat') {
    log("Received chat message:", message.prompt);
    handleChat(message.prompt).then(response => {
      const responseText = response || "No response received";
      log("Sending response back to UI:", responseText.substring(0, 100) + (responseText.length > 100 ? "..." : ""));
      sendResponse({
        success: true,
        data: responseText,
        timestamp: new Date().toISOString()
      });
    }).catch(error => {
      log("Error in handleChat:", error.message, error.stack);
      const errorResponse = {
        success: false,
        error: error.message,
        errorType: error.name || 'UnknownError',
        timestamp: new Date().toISOString()
      };
      
      // Provide more specific error guidance
      if (error.message.includes('API key')) {
        errorResponse.suggestion = 'Please check your OpenAI API key is valid and has sufficient credits.';
      } else if (error.message.includes('Content script')) {
        errorResponse.suggestion = 'Try refreshing the page and ensuring the extension has permission to access this site.';
      } else if (error.message.includes('No active tab')) {
        errorResponse.suggestion = 'Please ensure you have an active browser tab open.';
      }
      
      sendResponse(errorResponse);
    });
    return true; // keep channel open for async response
  }
});

// Add DSL command handler to the existing message listener
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.target !== 'background') return;
  
  if (message.type === 'dsl') {
    log("Received DSL command:", message.code);
    handleDSLCommand(message.code).then(response => {
      log("DSL command result:", response);
      sendResponse({
        success: true,
        data: response,
        timestamp: new Date().toISOString()
      });
    }).catch(error => {
      log("Error in DSL command:", error.message);
      sendResponse({
        success: false,
        error: error.message,
        timestamp: new Date().toISOString()
      });
    });
    return true; // keep channel open for async response
  }
});

async function handleDSLCommand(code) {
  log("Executing DSL command:", code);
  try {
    const result = await runScriptOnActiveTab('executeCode', code);
    return result || 'DSL command executed successfully';
  } catch (error) {
    log("DSL execution error:", error.message);
    throw error;
  }
}

async function fetchCompletion(apiKey, messages, tools) {
  log(
    "Sending request to OpenAI with messages:",
    messages.map((m) => ({
      role: m.role,
      // log only the first 50 chars to avoid noise
      content: m.content?.substring(0, 50) + "...",
    }))
  );
  
  log("Using model: gpt-4.1-mini, tools enabled:", !!tools);

  try {
    const res = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: "gpt-4.1-mini",
        messages,
        ...(tools ? { tools, tool_choice: "auto" } : {}),
      }),
    });
    
    if (!res.ok) {
      const errorText = await res.text();
      log("OpenAI API error:", res.status, errorText);
      throw new Error(`OpenAI API error (${res.status}): ${errorText}`);
    }
    
    const data = await res.json();
    
    if (!data.choices || !data.choices[0]) {
      log("Invalid response from OpenAI:", data);
      throw new Error("Invalid response from OpenAI API");
    }
    
    const msg = data.choices[0].message;
    log(
      "Received response from OpenAI:",
      msg.content?.substring(0, 100) + "...",
      "Tool calls:", msg.tool_calls?.length || 0
    );
    return msg;
  } catch (error) {
    log("Error in fetchCompletion:", error.message);
    throw error;
  }
}

async function runScriptOnActiveTab(action, code) {
  log("Running script on active tab:", action);
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tabs || tabs.length === 0) {
    log("No active tab found");
    throw new Error("No active tab found. Please ensure a browser tab is open and active.");
  }
  const tab = tabs[0];
  log("Found active tab:", tab.url);

  if (action === 'getPageInfo') {
    // For page info, use the content script
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content-script.js']
      });
      log("Content script injected successfully");
    } catch (error) {
      log("Failed to inject content script:", error.message);
    }

    return new Promise((resolve, reject) => {
      chrome.tabs.sendMessage(
        tab.id,
        { action, code },
        (response) => {
          if (chrome.runtime.lastError) {
            log("Error sending message to content script:", chrome.runtime.lastError.message);
            reject(new Error(`Content script error: ${chrome.runtime.lastError.message}`));
          } else if (!response) {
            log("No response from content script. Is it loaded?");
            reject(new Error("No response from content script. Content script may not be injected on this page."));
          } else {
            log("Content script response:", response);
            resolve(response);
          }
        }
      );
    });
  }

  if (action === 'executeCode') {
    log("Executing code:", code);
    
    // Parse the action type from the code
    let actionType = 'unknown';
    let params = {};
    
    // Data extraction/query actions (prioritize over click detection)
    if (code.includes('querySelectorAll') || code.includes('forEach') || 
        code.includes('textContent') || code.includes('getAttribute') ||
        code.includes('data-hovercard-type') || code.includes('contributors') ||
        (code.includes('Array.from') && !code.includes('.click()'))) {
      actionType = 'generic';
      params.code = code;
    }
    // Click actions
    else if (code.includes('.click()') || code.toLowerCase().includes('click')) {
      actionType = 'click';
      const selectorMatch = code.match(/querySelector\(['"`]([^'"`]+)['"`]\)/) || 
                           code.match(/getElementById\(['"`]([^'"`]+)['"`]\)/) ||
                           code.match(/getElementsByClassName\(['"`]([^'"`]+)['"`]\)/) ||
                           code.match(/getElementsByTagName\(['"`]([^'"`]+)['"`]\)/);
      if (selectorMatch) {
        params.selector = selectorMatch[1];
        params.selectorType = code.includes('getElementById') ? 'id' :
                             code.includes('getElementsByClassName') ? 'class' :
                             code.includes('getElementsByTagName') ? 'tag' : 'query';
      }
    }
    
    // CSS modification actions
    else if (code.includes('.style.') || code.includes('insertRule') || code.includes('addRule')) {
      actionType = 'modifyCSS';
      params.cssCode = code;
    }
    
    // Navigation actions
    else if (code.includes('window.location') || code.includes('location.href') || code.includes('.href')) {
      actionType = 'navigate';
      // Look for explicit URL assignments
      const urlMatch = code.match(/(?:window\.location\.href|location\.href)\s*=\s*['"`]([^'"`]+)['"`]/) ||
                       code.match(/href\s*:\s*['"`]([^'"`]+)['"`]/) ||
                       code.match(/['"`](https?:\/\/[^'"`]+)['"`]/);
      if (urlMatch) {
        params.url = urlMatch[1];
      }
    }
    
    // Generic code execution for other cases
    else {
      actionType = 'generic';
      params.code = code;
    }
    
    log("Parsed action type:", actionType, "with params:", params);
    
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: executeAction,
        args: [actionType, params]
      });
      
      const result = results[0].result;
      log("Script execution result:", result);
      return result;
    } catch (error) {
      log("Script execution error:", error.message);
      return `Error executing action: ${error.message}`;
    }
  }

  throw new Error(`Unknown action: ${action}`);
}

// Function to be injected into page context for safe code execution
function executeAction(actionType, params) {
  console.log("VIBESTACK: Executing action:", actionType, "with params:", params);
  
  switch (actionType) {
    case 'click':
      return executeClickAction(params);
    case 'modifyCSS':
      return executeCSS(params);
    case 'navigate':
      return executeNavigation(params);
    case 'generic':
      return executeGeneric(params);
    default:
      return `Unknown action type: ${actionType}`;
  }
  
  function executeClickAction(params) {
    try {
      let element;
      
      if (params.selectorType === 'id') {
        element = document.getElementById(params.selector);
      } else if (params.selectorType === 'class') {
        const elements = document.getElementsByClassName(params.selector);
        element = elements.length > 0 ? elements[0] : null;
      } else if (params.selectorType === 'tag') {
        const elements = document.getElementsByTagName(params.selector);
        element = elements.length > 0 ? elements[0] : null;
      } else {
        // Default to querySelector
        element = document.querySelector(params.selector);
      }
      
      if (!element) {
        // Try alternative selectors if the main one fails
        const alternativeSelectors = [
          `[data-testid="${params.selector}"]`,
          `[aria-label="${params.selector}"]`,
          `[title="${params.selector}"]`,
          `button[value="${params.selector}"]`,
          `input[value="${params.selector}"]`,
          `a[href*="${params.selector}"]`
        ];
        
        for (const altSelector of alternativeSelectors) {
          try {
            element = document.querySelector(altSelector);
            if (element) break;
          } catch (e) {
            continue;
          }
        }
        
        // If still not found, try finding by text content
        if (!element) {
          const allButtons = document.querySelectorAll('button, a, input[type="button"], input[type="submit"]');
          for (const btn of allButtons) {
            if (btn.textContent.includes(params.selector) || btn.innerText.includes(params.selector)) {
              element = btn;
              break;
            }
          }
        }
      }
      
      if (element) {
        // Scroll element into view first
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        
        // Add highlight for visual feedback
        const originalStyle = element.style.cssText;
        element.style.cssText += 'border: 3px solid red !important; background: yellow !important;';
        
        setTimeout(() => {
          element.style.cssText = originalStyle;
        }, 1000);
        
        // Simulate a real click
        element.click();
        
        return `Successfully clicked element: ${params.selector} (${element.tagName})`;
      } else {
        return `Element not found: ${params.selector}`;
      }
    } catch (error) {
      return `Error clicking element: ${error.message}`;
    }
  }
  
  function executeCSS(params) {
    try {
      // Create or get a style element for our custom CSS
      let styleElement = document.getElementById('vibestack-custom-styles');
      if (!styleElement) {
        styleElement = document.createElement('style');
        styleElement.id = 'vibestack-custom-styles';
        document.head.appendChild(styleElement);
      }
      
      // Parse and apply CSS
      if (params.cssCode.includes('.style.')) {
        // Direct style modification
        eval(params.cssCode); // Safe in this isolated context
        return `Applied direct CSS modification`;
      } else if (params.cssCode.includes('insertRule') || params.cssCode.includes('addRule')) {
        // CSS rule insertion
        const cssMatch = params.cssCode.match(/['"`]([^'"`]+)['"`]/);
        if (cssMatch) {
          const cssRule = cssMatch[1];
          styleElement.textContent += cssRule + '\n';
          return `Added CSS rule: ${cssRule}`;
        }
      } else {
        // Assume it's a complete CSS rule
        styleElement.textContent += params.cssCode + '\n';
        return `Added CSS: ${params.cssCode}`;
      }
    } catch (error) {
      return `Error applying CSS: ${error.message}`;
    }
  }
  
  function executeNavigation(params) {
    try {
      if (params.url && params.url.startsWith('http')) {
        // Only navigate to valid HTTP/HTTPS URLs
        window.location.href = params.url;
        return `Navigating to: ${params.url}`;
      } else if (params.url) {
        // Handle relative URLs
        const base = new URL(window.location.href);
        let targetUrl;
        if (params.url.startsWith('/')) {
          targetUrl = base.origin + params.url;
        } else {
          targetUrl = new URL(params.url, base).href;
        }
        window.location.href = targetUrl;
        return `Navigating to: ${targetUrl}`;
      } else {
        return `Invalid or no URL specified for navigation`;
      }
    } catch (error) {
      return `Error navigating: ${error.message}`;
    }
  }
  
  function executeGeneric(params) {
    try {
      // Parse and execute safe operations without eval()
      const code = params.code;
      
      // Handle simple querySelector operations
      if (code.includes('querySelector') && code.includes('textContent')) {
        const selectorMatch = code.match(/querySelector\(['"`]([^'"`]+)['"`]\)/);
        if (selectorMatch) {
          const elements = document.querySelectorAll(selectorMatch[1]);
          const results = Array.from(elements).map(el => el.textContent?.trim()).filter(t => t);
          return `Found ${results.length} elements: ${JSON.stringify(results)}`;
        }
      }
      
      // Handle collecting user links specifically
      if (code.includes('data-hovercard-type="user"')) {
        const userLinks = document.querySelectorAll('a[data-hovercard-type="user"]');
        const users = [];
        userLinks.forEach(link => {
          const username = link.textContent?.trim() || link.getAttribute('href')?.replace('/', '');
          if (username) users.push(username);
        });
        const uniqueUsers = [...new Set(users)];
        return `Found contributors: ${JSON.stringify(uniqueUsers)}`;
      }
      
      // Handle avatar/contributor searches
      if (code.includes('contributors') || code.includes('avatars')) {
        const avatars = document.querySelectorAll('img[data-testid="avatar"], .avatar, a[data-hovercard-type="user"]');
        const contributors = [];
        avatars.forEach(el => {
          const username = el.getAttribute('alt') || el.textContent?.trim() || 
                          el.getAttribute('href')?.split('/').pop();
          if (username && username !== 'Avatar' && username.length > 0) {
            contributors.push(username);
          }
        });
        const uniqueContributors = [...new Set(contributors)];
        return `Found contributors: ${JSON.stringify(uniqueContributors)}`;
      }
      
      // Handle finding links by href patterns
      if (code.includes('href') && (code.includes('contributors') || code.includes('graphs'))) {
        const contributorLinks = document.querySelectorAll('a[href*="contributors"], a[href*="graphs/contributors"]');
        if (contributorLinks.length > 0) {
          const link = contributorLinks[0];
          return `Found contributors link: ${link.href}`;
        } else {
          return 'No contributors link found';
        }
      }
      
      // Fallback for other operations
      return `Cannot execute code safely due to CSP restrictions. Code attempted: ${code.substring(0, 100)}...`;
    } catch (error) {
      return `Error executing code: ${error.message}`;
    }
  }
}

async function handleChat(prompt) {
  log("Handling chat with prompt:", prompt);
  
  const {apiKey} = await chrome.storage.local.get('apiKey');
  if (!apiKey) {
    log("API key missing");
    return 'Missing API key';
  }
  log("API key found");

  try {
    // Get current page information
    log("Requesting page info");
    const pageInfo = await runScriptOnActiveTab('getPageInfo');
    
    // Check if pageInfo is valid before accessing properties
    if (!pageInfo || typeof pageInfo !== 'object') {
      log("Invalid page info received:", pageInfo);
      throw new Error("Unable to get page information. Content script may not be loaded.");
    }
    
    log("Page info received, URL:", pageInfo.url);

    // Create context-aware message with enhanced page structure
    const htmlPreview = pageInfo.html ? pageInfo.html.substring(0, 100) + "..." : "No HTML available";
    log("HTML preview:", htmlPreview);
    
    // Build enhanced context with structured data
    let pageContext = `Current page URL: ${pageInfo.url}\nPage Title: ${pageInfo.title || 'No title'}\n\n`;
    
    // Add clickable elements information
    if (pageInfo.clickableElements && pageInfo.clickableElements.length > 0) {
      pageContext += `CLICKABLE ELEMENTS:\n`;
      pageInfo.clickableElements.forEach((element, index) => {
        pageContext += `${index + 1}. ${element.type.toUpperCase()}: "${element.text}" (selector: ${element.selector})\n`;
      });
      pageContext += '\n';
    }
    
    // Add links information
    if (pageInfo.links && pageInfo.links.length > 0) {
      pageContext += `LINKS:\n`;
      pageInfo.links.forEach((link, index) => {
        pageContext += `${index + 1}. "${link.text}" -> ${link.href} (selector: ${link.selector})\n`;
      });
      pageContext += '\n';
    }
    
    // Add form elements information
    if (pageInfo.formElements && pageInfo.formElements.length > 0) {
      pageContext += `FORM ELEMENTS:\n`;
      pageInfo.formElements.forEach((element, index) => {
        pageContext += `${index + 1}. ${element.type.toUpperCase()}: ${element.placeholder || element.name || 'unnamed'} (selector: ${element.selector})\n`;
      });
      pageContext += '\n';
    }
    
    // Add headings for page structure
    if (pageInfo.headings && pageInfo.headings.length > 0) {
      pageContext += `PAGE STRUCTURE (HEADINGS):\n`;
      pageInfo.headings.forEach((heading, index) => {
        pageContext += `${index + 1}. ${heading.level.toUpperCase()}: "${heading.text}"\n`;
      });
      pageContext += '\n';
    }
    
    // Add visible text (truncated)
    if (pageInfo.visibleText) {
      pageContext += `VISIBLE TEXT (SAMPLE):\n${pageInfo.visibleText.substring(0, 500)}${pageInfo.visibleText.length > 500 ? '...' : ''}\n\n`;
    }
    
    // Add raw HTML as fallback (truncated)
    pageContext += `RAW HTML (TRUNCATED):\n${pageInfo.html ? pageInfo.html.substring(0, 2000) + '...' : 'No HTML available'}`;
    
    log("Enhanced page context prepared, length:", pageContext.length);

    log("Fetching completion from OpenAI");
    const tools = [
      {
        type: "function",
        function: {
          name: "executeCode",
          description: "Execute JavaScript code on the current page",
          parameters: {
            type: "object",
            properties: {
              code: {
                type: "string",
                description: "JavaScript code to execute"
              }
            },
            required: ["code"]
          }
        }
      }
    ];

    const messages = [
      {
        role: "system",
        content: `You are an advanced browsing agent that can parse web pages and execute JavaScript actions. You have access to structured page information including clickable elements, links, forms, and page content.

AVAILABLE ACTIONS:
1. DATA EXTRACTION: Use executeCode to extract information from the page:
   - Find elements: document.querySelectorAll('a[data-hovercard-type="user"]')
   - Get text content: element.textContent
   - Get attributes: element.getAttribute('href')
   - Extract contributor info from GitHub pages
   - IMPORTANT: Use simple DOM operations, avoid eval(), complex expressions

2. CLICKING: Use executeCode with selectors like: document.querySelector('selector').click()
   - You can use CSS selectors, IDs (#id), classes (.class), or the selectors provided in the page context
   - The system will automatically try alternative selectors if the first one fails

3. CSS MODIFICATION: Use executeCode to modify page styles:
   - Direct style changes: document.querySelector('selector').style.property = 'value'
   - CSS rule injection: Use insertRule or addRule to add custom CSS

4. NAVIGATION: Use executeCode to navigate:
   - Navigate to URLs: window.location.href = 'https://example.com'
   - Click links using selectors provided in the LINKS section

IMPORTANT:
- For data extraction, use simple DOM queries without complex JavaScript expressions
- Use the structured page information (CLICKABLE ELEMENTS, LINKS, FORM ELEMENTS) to understand what's available
- Prefer using the selectors provided in the page context for reliable element targeting
- When extracting GitHub contributors, look for 'a[data-hovercard-type="user"]' elements
- All actions will be logged and provide visual feedback on the page

Respond conversationally and execute the requested actions using the executeCode function.`
      },
      {
        role: "user",
        content: pageContext + "\n\nUser request: " + prompt
      }
    ];

    let reply = await fetchCompletion(apiKey, messages, tools);
    log("Reply received from OpenAI");

    // Handle tool calls
    while (reply.tool_calls && reply.tool_calls.length > 0) {
      for (const toolCall of reply.tool_calls) {
        if (toolCall.function.name === 'executeCode') {
          log("Tool call received:", toolCall);
          
          let args;
          try {
            // Check if arguments exist and are valid - fix the property access
            if (!toolCall.function.arguments || toolCall.function.arguments === 'undefined') {
              log("Tool call has invalid arguments:", toolCall.function.arguments);
              throw new Error("Tool call arguments are undefined or invalid");
            }
            args = JSON.parse(toolCall.function.arguments);
          } catch (parseError) {
            log("Failed to parse tool call arguments:", parseError.message, "Raw arguments:", toolCall.function.arguments);
            
            // Add error message to conversation and continue
            messages.push({
              role: "assistant",
              content: reply.content,
              tool_calls: reply.tool_calls
            });
            
            messages.push({
              role: "tool",
              tool_call_id: toolCall.id,
              content: `Error parsing tool arguments: ${parseError.message}`
            });
            continue;
          }
          
          log("Tool executeCode invoked with code:", args.code);
          
          try {
            const result = await runScriptOnActiveTab('executeCode', args.code);
            log("Tool execution result:", result);
            
            messages.push({
              role: "assistant",
              content: reply.content,
              tool_calls: reply.tool_calls
            });
            
            messages.push({
              role: "tool",
              tool_call_id: toolCall.id,
              content: result.toString()
            });
          } catch (error) {
            log("Tool execution error:", error.message);
            messages.push({
              role: "assistant",
              content: reply.content,
              tool_calls: reply.tool_calls
            });
            
            messages.push({
              role: "tool",
              tool_call_id: toolCall.id,
              content: `Error: ${error.message}`
            });
          }
        }
      }
      
      // Get next response from OpenAI
      reply = await fetchCompletion(apiKey, messages, tools);
      log("Reply received from OpenAI");
    }

    log("Final reply received");
    return reply.content || "Action completed successfully";

  } catch (error) {
    log("Error in handleChat:", error.message);
    throw error;
  }
}

// Also add the executeCodeTool function if it's missing
async function executeCodeTool(code) {
  log("Executing code tool:", code);
  return await runScriptOnActiveTab('executeCode', code);
}
