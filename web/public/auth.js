let csrf = '';

function signIn() {
  const next = location.pathname + location.search;
  location.replace('/connect.html?return=' + encodeURIComponent(next));
}

export async function workspaceFetch(input, options = {}) {
  const target = new URL(input, location.href);
  if (target.origin !== location.origin) throw new Error('Workspace requests must stay on this service.');
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers);
  if (method !== 'GET' && method !== 'HEAD') {
    if (!csrf) {
      const session = await fetch('/auth/session', {credentials: 'same-origin', cache: 'no-store'});
      if (!session.ok) { signIn(); return session; }
      csrf = (await session.json()).csrf;
    }
    headers.set('X-VibeStack-CSRF', csrf);
  }
  const response = await fetch(target, {...options, headers, credentials: 'same-origin'});
  if (response.status === 401) { csrf = ''; signIn(); }
  return response;
}
