/* Editor keeps the workspace frame and a return path to Desktop. */
(() => {
  for (const link of document.querySelectorAll('[data-workspace-editor]')) {
    link.href = '/vnc/?view=editor';
    link.title = 'Open Editor';
  }
})();
