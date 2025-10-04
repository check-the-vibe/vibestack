// Prevent multiple injections
if (!window.vibestackInjected) {
  window.vibestackInjected = true;

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log("VIBESTACK Content Script: Received message:", message);
    
    if (message.action === 'getPageInfo') {
      const pageInfo = {
        url: window.location.href,
        title: document.title,
        html: document.documentElement.outerHTML,
        ...extractPageStructure()
      };
      console.log("VIBESTACK Content Script: Sending page info for URL:", pageInfo.url);
      sendResponse(pageInfo);
      return true;
    }
    
    console.log("VIBESTACK Content Script: Unknown action:", message.action);
    sendResponse({ error: "Unknown action" });
  });

  function extractPageStructure() {
    try {
      // Extract clickable elements
      const clickableElements = [];
      const buttons = document.querySelectorAll('button, input[type="button"], input[type="submit"], a[href]');
      buttons.forEach((element, index) => {
        clickableElements.push({
          type: element.tagName.toLowerCase(),
          text: element.textContent?.trim() || element.value || element.title || element.getAttribute('aria-label'),
          selector: generateSelector(element),
          href: element.href || null,
          id: element.id || null,
          classes: element.className || null
        });
      });

      // Extract form elements
      const formElements = [];
      const inputs = document.querySelectorAll('input, textarea, select');
      inputs.forEach((element, index) => {
        formElements.push({
          type: element.type || element.tagName.toLowerCase(),
          name: element.name || null,
          id: element.id || null,
          placeholder: element.placeholder || null,
          selector: generateSelector(element),
          value: element.value || null
        });
      });

      // Extract links
      const links = [];
      const anchorElements = document.querySelectorAll('a[href]');
      anchorElements.forEach((element, index) => {
        links.push({
          text: element.textContent?.trim(),
          href: element.href,
          selector: generateSelector(element)
        });
      });

      // Extract headings for page structure
      const headings = [];
      const headingElements = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
      headingElements.forEach((element, index) => {
        headings.push({
          level: element.tagName.toLowerCase(),
          text: element.textContent?.trim(),
          selector: generateSelector(element)
        });
      });

      // Extract visible text content (simplified)
      const visibleText = extractVisibleText();

      return {
        clickableElements: clickableElements.slice(0, 20), // Limit to prevent too much data
        formElements: formElements.slice(0, 15),
        links: links.slice(0, 15),
        headings: headings.slice(0, 10),
        visibleText: visibleText.substring(0, 2000) // Limit text length
      };
    } catch (error) {
      console.error("VIBESTACK Content Script: Error extracting page structure:", error);
      return {
        clickableElements: [],
        formElements: [],
        links: [],
        headings: [],
        visibleText: "",
        error: error.message
      };
    }
  }

  function generateSelector(element, depth = 0) {
    // Prevent infinite recursion and overly complex selectors
    if (depth > 10) {
      return element.tagName.toLowerCase();
    }
    
    // Use ID if available (most reliable)
    if (element.id) {
      return `#${element.id}`;
    }
    
    const tagName = element.tagName.toLowerCase();
    const parent = element.parentElement;
    
    // If we've reached the body or html, stop here
    if (!parent || tagName === 'body' || tagName === 'html') {
      return tagName;
    }
    
    // Find position among siblings of the same tag
    const siblings = Array.from(parent.children).filter(child => child.tagName === element.tagName);
    if (siblings.length === 1) {
      return `${generateSelector(parent, depth + 1)} > ${tagName}`;
    } else {
      const index = siblings.indexOf(element);
      return `${generateSelector(parent, depth + 1)} > ${tagName}:nth-of-type(${index + 1})`;
    }
  }

  function extractVisibleText() {
    // Extract visible text content from the page
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function(node) {
          // Skip script and style elements
          const parent = node.parentElement;
          if (parent && (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE')) {
            return NodeFilter.FILTER_REJECT;
          }
          
          // Skip elements that are not visible
          if (parent && (parent.style.display === 'none' || parent.style.visibility === 'hidden')) {
            return NodeFilter.FILTER_REJECT;
          }
          
          // Only include text nodes with meaningful content
          if (node.textContent && node.textContent.trim().length > 0) {
            return NodeFilter.FILTER_ACCEPT;
          }
          
          return NodeFilter.FILTER_REJECT;
        }
      }
    );
    
    let text = '';
    let node;
    
    while (node = walker.nextNode()) {
      text += node.textContent.trim() + ' ';
      if (text.length > 2000) break; // Limit total text
    }
    
    return text.trim();
  }

  console.log("VIBESTACK Content Script: Loaded and ready");
}