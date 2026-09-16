/* Desktop is the landing page; preserve only supported navigation options. */
(() => {
  const source = new URL(window.location.href);
  const target = new URL('/vnc/', source);
  for (const [key, values] of Object.entries({view:['desktop','terminal','editor'],panel:['apps','settings'],walkthrough:['0','1']})) {
    const value = source.searchParams.get(key);
    if (values.includes(value)) target.searchParams.set(key, value);
  }
  window.location.replace(target.pathname + target.search);
})();
