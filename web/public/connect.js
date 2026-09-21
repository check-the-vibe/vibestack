const form = document.getElementById('connect-form');
const input = document.getElementById('credential');
const status = document.getElementById('connection-status');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  let credential = input.value.trim();
  input.value = '';
  form.querySelector('button').disabled = true;
  status.textContent = 'Connecting…';
  try {
    const response = await fetch('/auth/session', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {Authorization: `Bearer ${credential}`},
    });
    credential = '';
    if (!response.ok) { status.textContent = 'Connection failed. Check your workspace credential and try again.'; return; }
    const value = new URLSearchParams(location.search).get('return') || '/vnc/';
    const next = new URL(value, location.origin);
    location.replace(next.origin === location.origin && next.pathname !== '/connect.html' ? next.pathname + next.search : '/vnc/');
  } catch {
    status.textContent = 'VibeStack is unavailable. Check that your workspace is running, then try again.';
  } finally {
    credential = '';
    form.querySelector('button').disabled = false;
  }
});
