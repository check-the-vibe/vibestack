/* Old navigation links land on the desktop and the agent overlay. */
(() => {
  const source = new URL(window.location.href);
  const target = new URL('/vnc/', source);
  for (const [key, values] of Object.entries({walkthrough:['0','1']})) {
    const value = source.searchParams.get(key);
    if (values.includes(value)) target.searchParams.set(key, value);
  }
  window.location.replace(target.pathname + target.search);
})();
