'use strict';
import {workspaceFetch as fetch} from '/auth.js';

const $ = (id) => document.getElementById(id);
const state = {
  catalog: null,
  installed: [],
  selected: new Set(),
  authentication: null,
  passwordRequired: false,
  logOffset: 0,
  poll: null,
  installFailed: false,
  search: "",
};

const fmtSize = (mb) => (!mb ? '' : mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB');

function show(step) {
  ['password', 'choose', 'install', 'done', 'error'].forEach((s) => {
    $('step-' + s).hidden = s !== step;
  });
  $('agent-connect').hidden = step === 'password' || step === 'install' || step === 'error' || new URL(window.location.href).searchParams.get('screen') === 'apps';
  if (!$('agent-connect').hidden) refreshClients();
}

function agentCommands() {
  const origin = window.location.origin;
  const install = `# Build the current client as described at ${origin}/SERVICE.md`;
  const connect = `vibestack connect --name my-workspace --url '${origin}' --token-stdin < /path/to/protected/credential-file`;
  $('agent-install-command').textContent = install;
  $('agent-connect-command').textContent = connect;
  return `${install}\n${connect}`;
}

function clientAction(label, handler) {
  const button = document.createElement('button');
  button.className = 'ghost compact';
  button.type = 'button';
  button.textContent = label;
  button.onclick = handler;
  return button;
}

async function refreshClients() {
  try {
    const data = await api('api/clients');
    $('agent-client-error').hidden = true;
    const pairingsHost = $('agent-pairings');
    const clientsHost = $('agent-clients');
    pairingsHost.replaceChildren();
    clientsHost.replaceChildren();
    const pairingTitle = document.createElement('h3');
    pairingTitle.textContent = 'Pending approvals';
    pairingsHost.appendChild(pairingTitle);
    if (!data.pending.length) {
      const empty = document.createElement('p');
      empty.className = 'dim';
      empty.textContent = 'No agent is waiting for approval.';
      pairingsHost.appendChild(empty);
    }
    data.pending.forEach((pairing) => {
      const row = document.createElement('div');
      row.className = 'client-row';
      const copy = document.createElement('span');
      copy.textContent = `${pairing.verification_code} — ${pairing.device_label} (${pairing.permissions.join(', ')})`;
      const actions = document.createElement('span');
      actions.append(
        clientAction('Approve', async () => {
          await api(`api/pairings/${encodeURIComponent(pairing.verification_code)}/approve`, { method: 'POST' });
          await refreshClients();
        }),
        clientAction('Deny', async () => {
          await api(`api/pairings/${encodeURIComponent(pairing.verification_code)}/deny`, { method: 'POST' });
          await refreshClients();
        }),
      );
      row.append(copy, actions);
      pairingsHost.appendChild(row);
    });
    const clientTitle = document.createElement('h3');
    clientTitle.textContent = 'Paired clients';
    clientsHost.appendChild(clientTitle);
    const active = data.clients.filter((client) => !client.revoked_at);
    if (!active.length) {
      const empty = document.createElement('p');
      empty.className = 'dim';
      empty.textContent = 'No active clients.';
      clientsHost.appendChild(empty);
    }
    active.forEach((client) => {
      const row = document.createElement('div');
      row.className = 'client-row';
      const copy = document.createElement('span');
      copy.textContent = `${client.device_label} — ${client.permissions.join(', ')}`;
      row.append(copy, clientAction('Revoke', async () => {
        await api(`api/clients/${encodeURIComponent(client.client_id)}/revoke`, { method: 'POST' });
        await refreshClients();
      }));
      clientsHost.appendChild(row);
    });
  } catch (err) {
    $('agent-client-error').textContent = err.message;
    $('agent-client-error').hidden = false;
  }
}

function fail(message) {
  $('error-text').textContent = message;
  show('error');
}

/* ---------- selection ---------- */

function componentById(id) {
  return state.catalog.components.find((c) => c.id === id);
}

function isSupported(id) {
  return componentById(id)?.supported !== false;
}

// Components pulled in only because something else requires them.
function impliedDeps() {
  const implied = new Set();
  state.selected.forEach((id) => {
    (componentById(id)?.requires || []).forEach((dep) => {
      if (!state.selected.has(dep)) implied.add(dep);
    });
  });
  return implied;
}

function toggle(id) {
  if (!isSupported(id)) return;
  if (state.selected.has(id)) {
    state.selected.delete(id);
    // Drop dependants that can no longer be installed.
    state.catalog.components.forEach((c) => {
      if ((c.requires || []).includes(id)) state.selected.delete(c.id);
    });
  } else {
    state.selected.add(id);
    (componentById(id)?.requires || []).forEach((dep) => state.selected.add(dep));
  }
  render();
}

function applyPreset(preset) {
  state.selected = new Set(
    preset.components.filter((id) => isSupported(id) && !state.installed.includes(id)),
  );
  render();
}

/* ---------- rendering ---------- */

function renderPresets() {
  const host = $('presets');
  host.innerHTML = '';
  state.catalog.presets.filter(preset => preset.components.length && matchesSearch(preset.name, preset.description, ...preset.components.map(id => componentById(id)?.name || ''))).forEach((preset) => {
    const btn = document.createElement('button');
    btn.className = 'preset';
    btn.type = 'button';
    btn.innerHTML = `<strong></strong><span></span>`;
    btn.querySelector('strong').textContent = preset.name;
    const unavailable = preset.unsupported_components || [];
    btn.querySelector('span').textContent =
      preset.description + ` (${preset.components.length} apps and dependencies)` +
      (unavailable.length ? ' Unavailable here: ' + unavailable.join(', ') + '.' : '');
    const wanted = preset.components.filter((id) => isSupported(id) && !state.installed.includes(id));
    const matches = wanted.length === state.selected.size && wanted.every((id) => state.selected.has(id));
    btn.setAttribute('aria-pressed', String(matches));
    btn.onclick = () => applyPreset(preset);
    host.appendChild(btn);
  });
}

function renderGroups() {
  const host = $('groups');
  const implied = impliedDeps();
  host.innerHTML = '';
  state.catalog.groups.forEach((group) => {
    const items = state.catalog.components.filter((c) => c.group === group.id && matchesSearch(c.name, c.description, group.name));
    if (!items.length) return;
    const section = document.createElement('div');
    section.className = 'group';
    const title = document.createElement('h3');
    title.textContent = group.name;
    section.appendChild(title);

    items.forEach((component) => {
      const isInstalled = state.installed.includes(component.id);
      const supported = component.supported !== false;
      const isImplied = implied.has(component.id);
      const checked = state.selected.has(component.id) || isImplied || isInstalled;

      const label = document.createElement('label');
      label.id = `component-${component.id}`;
      label.className = 'item' + (checked && !isInstalled ? ' on' : '');

      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = checked;
      box.disabled = isInstalled || !supported;
      box.onchange = (event) => {
        event.preventDefault();
        toggle(component.id);
      };

      const body = document.createElement('div');
      body.className = 'body';
      const name = document.createElement('div');
      name.className = 'name';
      name.textContent = component.name;
      const size = fmtSize(component.size_mb);
      if (size) name.appendChild(tag(size));
      if (isInstalled) name.appendChild(tag('installed', 'installed'));
      else if (isImplied) name.appendChild(tag('required', 'dep'));
      if (!supported) name.appendChild(tag('unavailable', 'dep'));
      const desc = document.createElement('div');
      desc.className = 'desc';
      desc.textContent =
        component.description + (!supported ? ' ' + component.support_reason : '');
      body.append(name, desc);

      label.append(box, body);
      section.appendChild(label);
    });
    host.appendChild(section);
  });
}

function tag(text, kind) {
  const el = document.createElement('span');
  el.className = 'tag' + (kind ? ' ' + kind : '');
  el.textContent = text;
  return el;
}

function matchesSearch(...values) {
  const words = state.search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const text = values.join(' ').toLocaleLowerCase();
  return words.every(word => text.includes(word));
}

function render() {
  renderPresets();
  renderGroups();
  $('search-empty').hidden = Boolean($('groups').children.length || $('presets').children.length);
  const chosen = pendingSelection();
  $('count').textContent = chosen.length === 1 ? '1 component selected' : chosen.length + ' components selected';
  const total = chosen.reduce((sum, id) => sum + (componentById(id)?.size_mb || 0), 0);
  $('size').textContent = total ? '~' + fmtSize(total) + ' to download and install' : '';
  $('btn-install').textContent = chosen.length ? 'Install' : 'Continue';
}

function pendingSelection() {
  const all = new Set([...state.selected, ...impliedDeps()]);
  return [...all].filter((id) => isSupported(id) && !state.installed.includes(id));
}

/* ---------- api ---------- */

async function api(path, options) {
  if (options?.method === 'POST' && options.body === undefined) {
    options = {
      ...options,
      headers: { ...options.headers, 'Content-Type': 'application/json' },
      body: '{}',
    };
  }
  const response = await fetch(path, options);
  if (!response.ok && response.status !== 202) {
    let detail = null;
    try {
      detail = await response.json();
    } catch (_error) {
      // The status-only fallback is safe even if a proxy returned HTML.
    }
    throw new Error(detail?.error?.message || detail?.error || path + ' returned ' + response.status);
  }
  return response.json();
}

async function refresh() {
  const data = await api('api/state');
  state.catalog = data.catalog;
  state.installed = data.installed;
  state.authentication = data.authentication;
  return data;
}

function pollLog(onFinish) {
  clearInterval(state.poll);
  state.poll = setInterval(async () => {
    let data;
    try {
      data = await api('api/log?offset=' + state.logOffset);
    } catch (err) {
      return; // transient; keep polling
    }
    if (data.text) {
      state.logOffset = data.offset;
      const box = $('log');
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
      box.textContent += data.text;
      if (atBottom) box.scrollTop = box.scrollHeight;
    }
    if (!data.running) {
      clearInterval(state.poll);
      onFinish(data.ok !== false);
    }
  }, 700);
}

/* ---------- steps ---------- */

function passwordPolicyError(password, confirmation) {
  if (password !== confirmation) return 'Passwords do not match.';
  const byteLength = new TextEncoder().encode(password).length;
  if (byteLength < 12 || byteLength > 256) return 'Use a password containing 12 to 256 UTF-8 bytes.';
  if (/^[\s]*$/u.test(password) || /[\u0000-\u001f\u007f]/u.test(password)) {
    return 'Control characters and whitespace-only passwords are not accepted.';
  }
  return '';
}

function openPasswordStep(required) {
  state.passwordRequired = required;
  $('password-eyebrow').textContent = required ? 'Required first step' : 'Account security';
  $('password-title').textContent = required ? 'Create your Linux password' : 'Change your Linux password';
  $('password-description').innerHTML = required
    ? 'Use this password when <code>sudo</code> prompts in either the desktop terminal or browser terminal. VibeStack stores only a salted password hash in its private persistent state.'
    : 'The new password takes effect immediately for <code>sudo</code> in both terminals. Only its salted hash is persisted.';
  $('btn-password-cancel').hidden = required;
  $('btn-password-save').textContent = required ? 'Save password' : 'Update password';
  $('password-error').hidden = true;
  $('password-error').textContent = '';
  $('linux-password').value = '';
  $('linux-password-confirmation').value = '';
  show('password');
  $('linux-password').focus();
}

async function savePassword(event) {
  event.preventDefault();
  const passwordInput = $('linux-password');
  const confirmationInput = $('linux-password-confirmation');
  const error = passwordPolicyError(passwordInput.value, confirmationInput.value);
  if (error) {
    $('password-error').textContent = error;
    $('password-error').hidden = false;
    return;
  }

  const button = $('btn-password-save');
  let password = passwordInput.value;
  let confirmation = confirmationInput.value;
  button.disabled = true;
  $('password-error').hidden = true;
  try {
    const result = await api('api/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, confirmation }),
    });
    state.authentication = result.authentication;
    window.location.replace('/vnc/?panel=apps');
  } catch (err) {
    $('password-error').textContent = err.message;
    $('password-error').hidden = false;
  } finally {
    // Keep plaintext out of browser persistence and out of the live form after
    // every network submission, including an error response.
    passwordInput.value = '';
    confirmationInput.value = '';
    button.disabled = false;
    password = null;
    confirmation = null;
  }
}

async function startInstall() {
  const chosen = pendingSelection();
  if (!chosen.length) {
    await api('api/complete', { method: 'POST' });
    return showDone(true);
  }
  $('log').textContent = '';
  state.logOffset = 0;
  $('install-title').textContent = 'Installing ' + chosen.length + ' component' + (chosen.length === 1 ? '' : 's');
  show('install');
  await api('api/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ components: chosen }),
  });
  pollLog((ok) => showDone(ok));
}

async function showDone(ok) {
  const data = await refresh();
  state.installFailed = !ok;
  if (!ok) {
    const saved = Array.isArray(data.state?.selected) ? data.state.selected : [];
    state.selected = new Set(saved.filter((id) => !state.installed.includes(id)));
  }
  $('done-title').textContent = ok ? 'Ready' : 'Finished with errors';
  $('btn-more').textContent = ok ? 'Add more' : 'Review and retry';
  const host = $('next-steps');
  host.innerHTML = '';
  if (!ok) {
    const li = document.createElement('li');
    li.textContent = 'Some components failed to install. The log above has the details. You can try again from this page.';
    host.appendChild(li);
  }
  state.installed.forEach((id) => {
    const component = componentById(id);
    (component?.next_steps || []).forEach((text) => {
      const li = document.createElement('li');
      const strong = document.createElement('strong');
      strong.textContent = component.name;
      li.append(strong, document.createTextNode(text));
      host.appendChild(li);
    });
  });
  if (!host.children.length) {
    const li = document.createElement('li');
    li.textContent = 'Nothing else to do. The desktop and terminal are ready.';
    host.appendChild(li);
  }
  show('done');
}

/* ---------- boot ---------- */

async function main() {
  let data;
  try {
    data = await refresh();
  } catch (err) {
    return fail('Could not reach the setup service: ' + err.message);
  }
  if (data.state_valid !== true) {
    return fail(
      'Saved setup state is invalid (' +
        (data.state_error?.code || 'unknown error') +
        '). Run vibestack-setup reset, then reload this page.'
    );
  }
  if (data.unknown_selected?.length) {
    return fail(
      'Saved components are not available in this image: ' +
        data.unknown_selected.join(', ') +
        '. Restore the prior image or run vibestack-setup reset.'
    );
  }
  if (data.unsupported_selected?.length) {
    return fail(
      'Saved components are unavailable in this VibeStack runtime (' +
        data.architecture +
        '): ' +
        data.unsupported_selected.join(', ') +
        '. Restore the prior image or reset the saved selection.'
    );
  }

  if (
    !data.authentication ||
    typeof data.authentication.password_configured !== 'boolean' ||
    data.authentication.sudo_password_required !== true
  ) {
    return fail('The Linux password service returned an invalid status.');
  }

  $('password-form').onsubmit = (event) => savePassword(event);
  $('btn-password-cancel').onclick = () => show('choose');
  $('btn-change-password').onclick = () => openPasswordStep(false);
  $('btn-install').onclick = () => startInstall().catch((err) => fail(err.message));
  $('btn-skip').onclick = () => { window.location.href = '/vnc/?view=desktop'; };
  $('app-search').addEventListener('input', event => { state.search = event.target.value; render(); });
  $('btn-more').onclick = () => {
    if (!state.installFailed) state.selected = new Set();
    state.installFailed = false;
    render();
    show('choose');
  };
  $('btn-refresh-clients').onclick = refreshClients;
  $('btn-copy-agent').onclick = async () => {
    try {
      await navigator.clipboard.writeText(agentCommands());
      $('btn-copy-agent').textContent = 'Copied';
      window.setTimeout(() => { $('btn-copy-agent').textContent = 'Copy starter commands'; }, 1500);
    } catch (_error) {
      $('agent-client-error').textContent = 'Clipboard access is unavailable; select and copy the commands above.';
      $('agent-client-error').hidden = false;
    }
  };
  agentCommands();

  const saved = Array.isArray(data.state?.selected) ? data.state.selected : [];
  const pending = saved.filter((id) => !state.installed.includes(id));
  const pack = new URL(window.location.href).searchParams.get('pack');
  const preset = state.catalog.presets.find(item => item.id === pack);
  if (preset) applyPreset(preset);
  else {
    state.selected = new Set(pending);
    render();
  }

  // A restore or install started before this page loaded: follow it. Password
  // setup resumes when that pre-existing job completes.
  if (data.job.running) {
    $('install-title').textContent = data.job.phase === 'restore' ? 'Restoring components' : 'Installing';
    $('install-note').textContent =
      data.job.phase === 'restore'
        ? 'This container was recreated, so the components you chose are being reinstalled.'
        : 'This runs apt and npm inside the container. It can take several minutes.';
    show('install');
    pollLog((ok) => {
      if (state.authentication.password_configured) showDone(ok);
      else openPasswordStep(true);
    });
    return;
  }

  if (data.state.completed) {
    $('subtitle').textContent = 'Apps and packs for your workspace.';
  }
  if (!data.authentication.password_configured) openPasswordStep(true);
  else if (new URL(window.location.href).searchParams.get('screen') === 'password') openPasswordStep(false);
  else {
    show('choose');
    if (window.location.hash === '#component-browser-editor') {
      document.getElementById('component-browser-editor')?.scrollIntoView({block:'center'});
    }
  }
}

main();
