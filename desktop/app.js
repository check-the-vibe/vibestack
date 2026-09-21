import RFB from '/novnc/core/rfb.js';
import {workspaceFetch as fetch} from '/auth.js';

const PREFERENCES_KEY = 'vibestack.desktop.preferences.v1';
const API_ROOT = '/api/v1';
const SERVICES = ['desktop', 'vnc', 'terminal', 'setup', 'ssh', 'native-vnc', 'editor'];
const RETRY_DELAYS = [1_000, 2_000, 4_000, 8_000, 10_000];
const VIEWPORT_RESIZE_DELAY = 650;
const RENDER_PROFILES = Object.freeze({
  balanced: Object.freeze({ qualityLevel: 7, compressionLevel: 2 }),
  clarity: Object.freeze({ qualityLevel: 9, compressionLevel: 2 }),
  constrained: Object.freeze({ qualityLevel: 5, compressionLevel: 6 }),
});
const DEFAULT_DISPLAY_BOUNDS = Object.freeze({
  minWidth: 640,
  minHeight: 480,
  maxWidth: 1920,
  maxHeight: 1200,
  widthStep: 8,
  heightStep: 2,
});
// Mobile browsers need editable content in the hidden input for Backspace to
// produce an input event. These characters are only a local buffer and are
// never sent to the remote desktop.
const VIRTUAL_KEYBOARD_SENTINEL = '_'.repeat(99);
const SERVICE_LABELS = {
  desktop: 'Desktop',
  vnc: 'VNC',
  terminal: 'Terminal',
  setup: 'Setup',
  ssh: 'SSH',
  'native-vnc': 'Native VNC',
  editor: 'Browser editor',
};
const MODIFIERS = {
  control: { keysym: 0xffe3, code: 'ControlLeft' },
  alt: { keysym: 0xffe9, code: 'AltLeft' },
  super: { keysym: 0xffeb, code: 'MetaLeft' },
};
const SPECIAL_KEYS = {
  Backspace: 0xff08,
  Tab: 0xff09,
  Enter: 0xff0d,
  Escape: 0xff1b,
  Delete: 0xffff,
  Home: 0xff50,
  ArrowLeft: 0xff51,
  ArrowUp: 0xff52,
  ArrowRight: 0xff53,
  ArrowDown: 0xff54,
  PageUp: 0xff55,
  PageDown: 0xff56,
  End: 0xff57,
};

const $ = (id) => document.getElementById(id);
const elements = {
  skipLink: $('skip-link'),
  appShell: $('app-shell'),
  stage: $('desktop-stage'),
  terminalStage: $('terminal-stage'),
  terminalFrame: $('terminal-frame'),
  editorStage: $('editor-stage'),
  editorFrame: $('editor-frame'),
  editorViewTab: $('editor-view-tab'),
  appsDialog: $('apps-dialog'),
  workspaceBack: $('workspace-back'),
  desktopViewTab: $('desktop-view-tab'),
  terminalViewTab: $('terminal-view-tab'),
  screen: $('screen'),
  connectionPill: $('connection-pill'),
  connectionLabel: $('connection-label'),
  connectionPanel: $('connection-panel'),
  connectionTitle: $('connection-title'),
  connectionMessage: $('connection-message'),
  connectionAction: $('connection-action'),
  desktopName: $('desktop-name'),
  focusButton: $('focus-button'),
  fullscreenButton: $('fullscreen-button'),
  inputControlsButton: $('input-controls-button'),
  inputControlsPanel: $('input-controls-panel'),
  matchScreenButton: $('match-screen-button'),
  settingsButton: $('settings-button'),
  toolsButton: $('tools-button'),
  keyboardButton: $('keyboard-button'),
  virtualKeyboard: $('virtual-keyboard'),
  clipboardButton: $('clipboard-button'),
  clipboardDialog: $('clipboard-dialog'),
  clipboardText: $('clipboard-text'),
  clipboardSend: $('clipboard-send'),
  clipboardCopy: $('clipboard-copy'),
  clipboardClear: $('clipboard-clear'),
  settingsDialog: $('settings-dialog'),
  toolsDialog: $('tools-dialog'),
  disconnectButton: $('disconnect-button'),
  settingsConnectionNote: $('settings-connection-note'),
  renderProfile: $('render-profile'),
  qualityRange: $('quality-range'),
  qualityOutput: $('quality-output'),
  compressionRange: $('compression-range'),
  compressionOutput: $('compression-output'),
  viewOnlyToggle: $('view-only-toggle'),
  reconnectToggle: $('reconnect-toggle'),
  autoResizeToggle: $('auto-resize-toggle'),
  displaySelect: $('display-select'),
  displayApply: $('display-apply'),
  displayNote: $('display-note'),
  statusUptime: $('status-uptime'),
  statusDisk: $('status-disk'),
  statusResolution: $('status-resolution'),
  serviceList: $('service-list'),
  statusRefresh: $('status-refresh'),
  logService: $('log-service'),
  logRefresh: $('log-refresh'),
  logOutput: $('log-output'),
  logStatus: $('log-status'),
  logMore: $('log-more'),
  cadButton: $('cad-button'),
  toastRegion: $('toast-region'),
};

const defaults = Object.freeze({
  scaleMode: 'fit',
  qualityLevel: RENDER_PROFILES.balanced.qualityLevel,
  compressionLevel: 2,
  viewOnly: false,
  reconnect: true,
  autoResize: false,
});

const state = {
  workspaceView: null,
  rfb: null,
  connected: false,
  hasConnected: false,
  manuallyDisconnected: false,
  retryAttempt: 0,
  retryTimer: null,
  retryCountdown: null,
  retryBlocked: false,
  expectingVncRestart: false,
  recoveringVncRestart: false,
  preferences: loadPreferences(),
  pressedModifiers: new Set(),
  keyboardModifiers: new Set(),
  keyboardComposing: false,
  virtualKeyboardValue: VIRTUAL_KEYBOARD_SENTINEL,
  remoteClipboard: '',
  logCursor: null,
  toastTimer: null,
  display: {
    current: '',
    modes: [],
    dynamicResize: true,
    bounds: { ...DEFAULT_DISPLAY_BOUNDS },
  },
  viewportResizeTimer: null,
  viewportResizeInFlight: false,
  viewportResizePending: false,
  viewportResizeAnnounce: false,
  lastRequestedResolution: '',
  displayIntentRevision: 0,
  pendingFixedResolution: null,
  expectingDisplayResize: false,
  displayResizeTimer: null,
  stageResizeObserver: null,
};
const dialogInvokers = new WeakMap();

function clampInteger(value, minimum, maximum, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? Math.min(maximum, Math.max(minimum, parsed)) : fallback;
}

function storedInteger(value, minimum, maximum, fallback) {
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : fallback;
}

function loadPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFERENCES_KEY));
    if (!saved || typeof saved !== 'object') return { ...defaults };
    // Read the short-lived development shape as a migration path, but always
    // write the documented v1 object directly under the versioned key.
    const candidate = saved.version === 1 && saved.preferences && typeof saved.preferences === 'object'
      ? saved.preferences
      : saved;
    return {
      scaleMode: candidate.scaleMode === 'actual' || candidate.scale === 'actual' ? 'actual' : 'fit',
      qualityLevel: storedInteger(candidate.qualityLevel ?? candidate.quality, 0, 9, defaults.qualityLevel),
      compressionLevel: storedInteger(candidate.compressionLevel ?? candidate.compression, 0, 9, defaults.compressionLevel),
      viewOnly: candidate.viewOnly === true,
      reconnect: (candidate.reconnect ?? candidate.autoReconnect) !== false,
      autoResize: candidate.autoResize === true,
    };
  } catch (_error) {
    return { ...defaults };
  }
}

function savePreferences() {
  try {
    localStorage.setItem(PREFERENCES_KEY, JSON.stringify(state.preferences));
  } catch (_error) {
    // Preferences are an enhancement; a blocked storage API must not block VNC.
  }
}

function websocketUrl() {
  const url = new URL('/vnc/websockify', window.location.href);
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.href;
}

function workspaceViewFromLocation() {
  const view = new URL(window.location.href).searchParams.get('view');
  return ['terminal', 'editor'].includes(view) ? view : 'desktop';
}

function workspaceHref(view) {
  const url = new URL(window.location.href);
  url.pathname = '/vnc/';
  url.searchParams.set('view', view);
  url.searchParams.delete('panel');
  return `${url.pathname}${url.search}${url.hash}`;
}

function ensureTerminalFrame() {
  if (elements.terminalFrame.hasAttribute('src')) return;
  elements.terminalFrame.src = elements.terminalFrame.dataset.src || '/terminal/';
}

async function ensureEditorFrame() {
  if (elements.editorFrame.hasAttribute('src')) return;
  const message = $('editor-status');
  try {
    const status = await api('/status');
    const ready = String(status.services?.editor?.state || '').toUpperCase() === 'RUNNING';
    $('editor-unavailable').hidden = ready;
    elements.editorFrame.hidden = !ready;
    if (ready) elements.editorFrame.src = '/editor/';
    else message.textContent = 'Editor is starting or needs a restart. Retry, or restart Editor in Menu → Tools → Services.';
  } catch (_) {
    message.textContent = 'Editor status is unavailable. Retry, or check the Editor service in Tools.';
  }
}

async function loadApps() {
  const summary = $('apps-summary');
  const packs = $('apps-packs');
  try {
    const response = await fetch('/setup/api/state', {cache:'no-store', credentials:'same-origin'});
    if (!response.ok) throw new Error('Unavailable');
    const setup = await response.json();
    const count = setup.installed?.length || 0;
    summary.textContent = setup.job?.running ? 'An installation is running. Open Apps to follow its progress.' : `${count} installed app${count === 1 ? '' : 's'} and dependencies`;
    packs.replaceChildren();
    for (const pack of setup.catalog?.presets || []) {
      if (!pack.components?.length) continue;
      const link = document.createElement('a');
      link.className = 'apps-pack';
      const url = new URL('/setup/', window.location.href);
      url.search = new URLSearchParams({force:'1',screen:'apps',pack:pack.id});
      link.href = url.pathname + url.search;
      const title = document.createElement('strong');
      title.textContent = pack.name;
      const detail = document.createElement('small');
      detail.textContent = pack.description;
      link.append(title, detail);
      packs.append(link);
    }
  } catch (_) {
    summary.textContent = 'App status is unavailable. Open Apps to retry.';
  }
}

function applyPanelFromLocation() {
  const panel = new URL(window.location.href).searchParams.get('panel');
  if (panel === 'apps') {
    openDialog(elements.appsDialog);
    loadApps();
  } else if (panel === 'settings') {
    openDialog(elements.settingsDialog);
    loadDisplaySettings();
  }
}

function focusWorkspace() {
  if (state.workspaceView !== 'desktop') {
    if (state.workspaceView === 'terminal') ensureTerminalFrame();
    (state.workspaceView === 'editor' ? elements.editorFrame : elements.terminalFrame).focus();
    return;
  }
  if (state.connected) state.rfb?.focus();
  else if (!state.rfb) manualConnect();
  else toast('The desktop is still connecting');
}

function setWorkspaceView(view, { historyMode = null, focus = false, initial = false } = {}) {
  const nextView = ['terminal', 'editor'].includes(view) ? view : 'desktop';
  const previousView = state.workspaceView;
  const href = workspaceHref(nextView);
  if (historyMode === 'push' && previousView !== 'desktop' && nextView !== 'desktop') historyMode = 'replace';
  if (historyMode === 'push' && `${window.location.pathname}${window.location.search}${window.location.hash}` !== href) {
    window.history.pushState({ vibestackView: nextView }, '', href);
  } else if (historyMode === 'replace') {
    window.history.replaceState({ vibestackView: nextView }, '', href);
  }

  state.workspaceView = nextView;
  elements.appShell.dataset.view = nextView;
  elements.stage.hidden = nextView !== 'desktop';
  elements.terminalStage.hidden = nextView !== 'terminal';
  elements.editorStage.hidden = nextView !== 'editor';
  elements.workspaceBack.hidden = nextView === 'desktop';
  elements.skipLink.href = `#${nextView}-stage`;
  for (const tab of [elements.desktopViewTab, elements.terminalViewTab, elements.editorViewTab]) {
    const selected = tab.dataset.workspaceView === nextView;
    tab.href = workspaceHref(tab.dataset.workspaceView);
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }

  if (nextView === 'terminal') {
    ensureTerminalFrame();
    elements.desktopName.textContent = 'Browser terminal';
    document.title = 'Terminal — VibeStack';
    elements.focusButton.setAttribute('aria-label', 'Focus browser terminal');
    elements.focusButton.title = 'Focus browser terminal';
    cancelScheduledViewportMatch();
    if (!initial && previousView === 'desktop') disconnect();
  } else if (nextView === 'editor') {
    elements.desktopName.textContent = 'Editor';
    document.title = 'Editor — VibeStack';
    elements.focusButton.setAttribute('aria-label', 'Focus Editor');
    elements.focusButton.title = 'Focus Editor';
    cancelScheduledViewportMatch();
    if (!initial && previousView === 'desktop') disconnect();
    ensureEditorFrame();
  } else {
    elements.desktopName.textContent = 'Private desktop';
    document.title = 'VibeStack Desktop';
    elements.focusButton.setAttribute('aria-label', 'Focus remote desktop');
    elements.focusButton.title = 'Focus remote desktop';
    if (!initial && previousView !== 'desktop') manualConnect();
  }

  setInputControlsExpanded(false);
  if (focus) window.setTimeout(focusWorkspace, 0);
}

function setConnectionUi(kind, title, message, { action = false, overlay = true } = {}) {
  elements.connectionPill.dataset.state = kind;
  const labels = {
    connecting: 'Connecting',
    reconnecting: 'Reconnecting',
    connected: 'Connected',
    disconnected: 'Disconnected',
    failed: 'Connection lost',
    offline: 'Offline',
  };
  elements.connectionLabel.textContent = labels[kind] || 'Unavailable';
  elements.connectionTitle.textContent = title;
  elements.connectionMessage.textContent = message;
  elements.connectionAction.hidden = !action;
  elements.connectionPanel.hidden = !overlay;
  elements.settingsConnectionNote.textContent = kind === 'connected'
    ? 'The remote desktop is connected.'
    : kind === 'connecting' || kind === 'reconnecting'
      ? 'The remote desktop is connecting.'
      : 'The remote desktop is disconnected.';
  elements.disconnectButton.textContent = ['connecting', 'reconnecting', 'connected'].includes(kind)
    ? 'Disconnect desktop'
    : 'Connect desktop';
}

function applyRfbPreferences() {
  elements.stage.dataset.scale = state.preferences.scaleMode;
  if (!state.rfb) return;
  const fits = state.preferences.scaleMode === 'fit';
  state.rfb.scaleViewport = fits;
  state.rfb.clipViewport = !fits;
  state.rfb.dragViewport = !fits;
  state.rfb.resizeSession = false;
  state.rfb.qualityLevel = state.preferences.qualityLevel;
  state.rfb.compressionLevel = state.preferences.compressionLevel;
  state.rfb.viewOnly = state.preferences.viewOnly;
  state.rfb.focusOnClick = true;
  state.rfb.showDotCursor = true;
}

function clearRetry() {
  window.clearTimeout(state.retryTimer);
  window.clearInterval(state.retryCountdown);
  state.retryTimer = null;
  state.retryCountdown = null;
}

function clearExpectedDisplayResize() {
  window.clearTimeout(state.displayResizeTimer);
  state.displayResizeTimer = null;
  state.expectingDisplayResize = false;
}

function expectDisplayResize() {
  clearExpectedDisplayResize();
  state.expectingDisplayResize = true;
  state.displayResizeTimer = window.setTimeout(clearExpectedDisplayResize, 5_000);
}

function connect() {
  clearRetry();
  state.manuallyDisconnected = false;

  if (state.retryBlocked || state.workspaceView !== 'desktop') return;

  if (!navigator.onLine) {
    setConnectionUi('offline', 'You’re offline', 'Reconnect to the network and VibeStack will try again.', { action: true });
    return;
  }

  const previous = state.rfb;
  state.rfb = null;
  state.connected = false;
  if (previous) {
    releaseAllInput(previous);
    try { previous.disconnect(); } catch (_error) { /* already closed */ }
  }
  elements.screen.replaceChildren();
  setConnectionUi(
    state.retryAttempt ? 'reconnecting' : 'connecting',
    state.retryAttempt ? 'Reconnecting to your workspace' : 'Starting your workspace',
    'Connecting to the Linux desktop. This normally takes a few seconds.',
  );

  let rfb;
  try {
    rfb = new RFB(elements.screen, websocketUrl(), { shared: true });
  } catch (error) {
    handleConnectionFailure(error instanceof Error ? error.message : 'The noVNC client could not start.');
    return;
  }
  state.rfb = rfb;
  applyRfbPreferences();

  rfb.addEventListener('connect', () => {
    if (state.rfb !== rfb) return;
    state.connected = true;
    state.hasConnected = true;
    state.retryAttempt = 0;
    state.retryBlocked = false;
    state.expectingVncRestart = false;
    state.recoveringVncRestart = false;
    clearExpectedDisplayResize();
    clearRetry();
    setConnectionUi('connected', 'Desktop connected', 'Your remote desktop is ready.', { overlay: false });
    releaseModifiers();
    window.setTimeout(() => rfb.focus(), 80);
    scheduleViewportMatch();
  });

  rfb.addEventListener('disconnect', (event) => {
    if (state.rfb !== rfb) return;
    state.connected = false;
    state.rfb = null;
    releaseAllInput(rfb);
    if (state.manuallyDisconnected) {
      setConnectionUi('disconnected', 'Desktop disconnected', 'Reconnect whenever you’re ready.', { action: true });
      return;
    }
    if (state.expectingVncRestart) {
      state.expectingVncRestart = false;
      state.recoveringVncRestart = true;
      scheduleReconnect('VNC is restarting.', { force: true });
      return;
    }
    if (state.expectingDisplayResize) {
      clearExpectedDisplayResize();
      scheduleReconnect('The desktop display is resizing.', { force: true });
      return;
    }
    const clean = event.detail?.clean === true;
    if (clean) {
      stopConnection('disconnected', 'Desktop disconnected', 'The desktop ended the session. Reconnect whenever you’re ready.');
    } else {
      handleConnectionFailure('The connection to the desktop was interrupted.');
    }
  });

  rfb.addEventListener('securityfailure', (event) => {
    if (state.rfb !== rfb) return;
    stopConnection('failed', 'Security check failed', event.detail?.reason || 'The desktop rejected this connection. Check the deployment before retrying.');
  });

  rfb.addEventListener('credentialsrequired', () => {
    if (state.rfb !== rfb) return;
    stopConnection('failed', 'Credentials required', 'This VibeStack expects a passwordless local VNC connection. Check the server configuration.');
  });

  rfb.addEventListener('serververification', () => {
    if (state.rfb !== rfb) return;
    stopConnection('failed', 'Server verification required', 'VibeStack will not approve an unverified desktop identity automatically. Check the deployment before retrying.');
  });

  rfb.addEventListener('clipboard', (event) => {
    if (state.rfb !== rfb) return;
    state.remoteClipboard = typeof event.detail?.text === 'string' ? event.detail.text : '';
    elements.clipboardText.value = state.remoteClipboard;
    toast('Text copied from the desktop');
  });

  rfb.addEventListener('desktopname', (event) => {
    if (state.rfb !== rfb) return;
    const name = String(event.detail?.name || '').trim();
    elements.desktopName.textContent = name || 'Private desktop';
    if (name) document.title = `${name} — VibeStack`;
  });
}

function handleConnectionFailure(reason) {
  state.connected = false;
  if (state.manuallyDisconnected || state.retryBlocked) return;
  if (!state.hasConnected) {
    stopConnection(
      'failed',
      'Couldn’t reach the desktop',
      `${reason || 'The connection could not be established.'} Check the workspace, then try again.`,
    );
    return;
  }
  scheduleReconnect(reason || 'The connection could not be established.', { force: state.recoveringVncRestart });
}

function stopConnection(kind, title, message) {
  clearRetry();
  state.connected = false;
  state.hasConnected = false;
  state.manuallyDisconnected = true;
  state.retryBlocked = true;
  state.expectingVncRestart = false;
  state.recoveringVncRestart = false;
  clearExpectedDisplayResize();
  const rfb = state.rfb;
  state.rfb = null;
  releaseAllInput(rfb);
  if (rfb) {
    try { rfb.disconnect(); } catch (_error) { /* already closed */ }
  }
  setConnectionUi(kind, title, message, { action: true });
}

function manualConnect() {
  state.retryAttempt = 0;
  state.retryBlocked = false;
  state.manuallyDisconnected = false;
  state.expectingVncRestart = false;
  state.recoveringVncRestart = false;
  clearExpectedDisplayResize();
  // A user-started connection begins a fresh chain. It must establish one
  // session before unexpected disconnects are eligible for auto-recovery.
  state.hasConnected = false;
  connect();
}

function scheduleReconnect(reason, { force = false } = {}) {
  clearRetry();
  if (state.retryBlocked || state.workspaceView !== 'desktop') return;
  if ((!state.preferences.reconnect && !force) || !navigator.onLine) {
    const offline = !navigator.onLine;
    setConnectionUi(
      offline ? 'offline' : 'failed',
      offline ? 'You’re offline' : 'Couldn’t reach the desktop',
      offline ? 'Reconnect to the network and try again.' : reason,
      { action: true },
    );
    return;
  }

  if (state.retryAttempt >= RETRY_DELAYS.length) {
    state.retryBlocked = true;
    state.recoveringVncRestart = false;
    setConnectionUi(
      'failed',
      'Couldn’t reach the desktop',
      `${reason} Automatic reconnect stopped after five attempts.`,
      { action: true },
    );
    return;
  }

  const delay = RETRY_DELAYS[state.retryAttempt++];
  const deadline = Date.now() + delay;
  const updateCountdown = () => {
    const seconds = Math.max(1, Math.ceil((deadline - Date.now()) / 1000));
    setConnectionUi('reconnecting', 'Reconnecting to your workspace', `${reason} Trying again in ${seconds}s.`, { action: true });
  };
  updateCountdown();
  state.retryCountdown = window.setInterval(updateCountdown, 500);
  state.retryTimer = window.setTimeout(connect, delay);
}

function disconnect() {
  clearRetry();
  state.manuallyDisconnected = true;
  state.retryBlocked = true;
  state.retryAttempt = 0;
  state.connected = false;
  state.hasConnected = false;
  state.expectingVncRestart = false;
  state.recoveringVncRestart = false;
  clearExpectedDisplayResize();
  const rfb = state.rfb;
  state.rfb = null;
  releaseAllInput(rfb);
  if (rfb) {
    try { rfb.disconnect(); } catch (_error) { /* already closed */ }
  }
  setConnectionUi('disconnected', 'Desktop disconnected', 'Reconnect whenever you’re ready.', { action: true });
}

function toast(message, kind = 'info') {
  window.clearTimeout(state.toastTimer);
  elements.toastRegion.replaceChildren();
  const item = document.createElement('div');
  item.className = `toast ${kind}`;
  item.textContent = message;
  elements.toastRegion.append(item);
  state.toastTimer = window.setTimeout(() => item.remove(), 3200);
}

function showUpdateAvailable(worker) {
  window.clearTimeout(state.toastTimer);
  elements.toastRegion.replaceChildren();
  const item = document.createElement('div');
  item.className = 'toast update';
  const message = document.createElement('span');
  message.textContent = 'A VibeStack update is ready.';
  const reload = document.createElement('button');
  reload.type = 'button';
  reload.textContent = 'Reload now';
  reload.addEventListener('click', () => {
    reload.disabled = true;
    reload.textContent = 'Reloading…';
    navigator.serviceWorker.addEventListener('controllerchange', () => window.location.reload(), { once: true });
    worker.postMessage({ type: 'SKIP_WAITING' });
  });
  item.append(message, reload);
  elements.toastRegion.append(item);
}

function setInputControlsExpanded(expanded, { restoreFocus = false } = {}) {
  const open = Boolean(expanded);
  elements.inputControlsPanel.hidden = !open;
  elements.inputControlsButton.setAttribute('aria-expanded', String(open));
  elements.inputControlsButton.setAttribute('aria-label', open ? 'Hide workspace menu' : 'Show workspace menu');
  if (!open) {
    if (document.activeElement === elements.virtualKeyboard) elements.virtualKeyboard.blur();
    state.keyboardComposing = false;
    releaseModifiers();
    releaseKeyboardModifiers();
  }
  if (!open && restoreFocus) window.setTimeout(() => elements.inputControlsButton.focus(), 0);
}

function toggleInputControls() {
  setInputControlsExpanded(elements.inputControlsButton.getAttribute('aria-expanded') !== 'true');
}

function openDialog(dialog) {
  const activeElement = document.activeElement;
  const invoker = elements.inputControlsPanel.contains(activeElement)
    ? elements.inputControlsButton
    : activeElement;
  setInputControlsExpanded(false);
  document.querySelectorAll('dialog[open]').forEach((open) => {
    if (open !== dialog) open.close();
  });
  dialogInvokers.set(dialog, invoker);
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
}

function sendKey(keysym, code = '', down) {
  if (!state.connected || !state.rfb || state.preferences.viewOnly) return false;
  state.rfb.sendKey(keysym, code, down);
  return true;
}

function unicodeKeysym(character) {
  const codepoint = character.codePointAt(0);
  return codepoint <= 0xff ? codepoint : 0x01000000 | codepoint;
}

function sendText(text) {
  for (const character of text) sendKey(unicodeKeysym(character));
}

function toggleModifier(name) {
  const modifier = MODIFIERS[name];
  if (!modifier || !state.connected || !state.rfb || state.preferences.viewOnly) return;
  const active = state.pressedModifiers.has(name);
  sendKey(modifier.keysym, modifier.code, !active);
  if (active) state.pressedModifiers.delete(name);
  else state.pressedModifiers.add(name);
  document.querySelector(`[data-modifier="${name}"]`)?.setAttribute('aria-pressed', String(!active));
}

function releaseModifiers(target = state.rfb) {
  for (const name of state.pressedModifiers) {
    const modifier = MODIFIERS[name];
    try { target?.sendKey(modifier.keysym, modifier.code, false); } catch (_error) { /* connection may be gone */ }
  }
  state.pressedModifiers.clear();
  document.querySelectorAll('[data-modifier]').forEach((button) => button.setAttribute('aria-pressed', 'false'));
}

function releaseKeyboardModifiers(target = state.rfb) {
  for (const name of state.keyboardModifiers) {
    const modifier = MODIFIERS[name];
    try { target?.sendKey(modifier.keysym, modifier.code, false); } catch (_error) { /* connection may be gone */ }
  }
  state.keyboardModifiers.clear();
}

function releaseAllInput(target = state.rfb) {
  releaseModifiers(target);
  releaseKeyboardModifiers(target);
  try { target?.blur(); } catch (_error) { /* connection may be gone */ }
}

function toggleVirtualKeyboard() {
  if (document.activeElement === elements.virtualKeyboard) {
    elements.virtualKeyboard.blur();
    state.rfb?.focus();
    return;
  }
  resetVirtualKeyboardInput();
  elements.virtualKeyboard.focus({ preventScroll: true });
}

function resetVirtualKeyboardInput() {
  elements.virtualKeyboard.value = VIRTUAL_KEYBOARD_SENTINEL;
  state.virtualKeyboardValue = VIRTUAL_KEYBOARD_SENTINEL;
  try {
    const end = elements.virtualKeyboard.value.length;
    elements.virtualKeyboard.setSelectionRange(end, end);
  } catch (_error) {
    // Some mobile browsers expose no selection API for hidden inputs.
  }
}

function virtualKeyboardDelta(previousValue, nextValue) {
  const previous = [...previousValue];
  const next = [...nextValue];
  let unchanged = 0;
  while (unchanged < previous.length && unchanged < next.length && previous[unchanged] === next[unchanged]) {
    unchanged += 1;
  }
  return {
    backspaces: previous.length - unchanged,
    inserted: next.slice(unchanged).join(''),
  };
}

function applyVirtualKeyboardValue() {
  const nextValue = elements.virtualKeyboard.value;
  const { backspaces, inserted } = virtualKeyboardDelta(state.virtualKeyboardValue, nextValue);
  for (let index = 0; index < backspaces; index += 1) sendKey(SPECIAL_KEYS.Backspace);
  if (inserted) sendText(inserted);
  state.virtualKeyboardValue = nextValue;

  // Bound the local context. If all sentinel text is deleted, restore it so a
  // subsequent software-keyboard Backspace still changes the input value.
  if (nextValue.length > VIRTUAL_KEYBOARD_SENTINEL.length * 2 || nextValue.length < 1) {
    const refocus = document.activeElement === elements.virtualKeyboard;
    resetVirtualKeyboardInput();
    if (refocus && nextValue.length < 1) {
      elements.virtualKeyboard.blur();
      window.setTimeout(() => elements.virtualKeyboard.focus({ preventScroll: true }), 0);
    }
  }
}

function handleVirtualKeyboardInput(event) {
  if (state.preferences.viewOnly) {
    resetVirtualKeyboardInput();
    toast('Turn off View only to type', 'error');
    return;
  }
  if (event.isComposing || state.keyboardComposing) return;
  applyVirtualKeyboardValue();
}

function handleVirtualKeyboardKey(event, down) {
  if (event.isComposing || state.keyboardComposing || event.keyCode === 229) return;
  const modifierName = event.key === 'Control' ? 'control' : event.key === 'Alt' ? 'alt' : event.key === 'Meta' ? 'super' : null;
  if (modifierName) {
    const modifier = MODIFIERS[modifierName];
    if (sendKey(modifier.keysym, event.code || modifier.code, down)) {
      if (down) state.keyboardModifiers.add(modifierName);
      else state.keyboardModifiers.delete(modifierName);
    }
    event.preventDefault();
    return;
  }
  const keysym = SPECIAL_KEYS[event.key];
  if (keysym) {
    sendKey(keysym, event.code || '', down);
    event.preventDefault();
    return;
  }
  if ((event.ctrlKey || event.altKey || event.metaKey) && event.key.length === 1) {
    sendKey(unicodeKeysym(event.key), event.code || '', down);
    event.preventDefault();
  }
}

function formatDuration(value) {
  if (typeof value === 'string' && value.trim()) return value;
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatBytes(value) {
  if (typeof value === 'string' && value.trim()) return value;
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = bytes;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

async function api(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: 'same-origin',
    cache: 'no-store',
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  let payload = null;
  try { payload = await response.json(); } catch (_error) { /* handled below */ }
  if (!response.ok) {
    const message = payload?.message || payload?.error?.message || payload?.error || `Request failed (${response.status})`;
    const error = new Error(message);
    error.code = payload?.code || payload?.error?.code || `http_${response.status}`;
    throw error;
  }
  return payload || {};
}

function normalizeService(raw) {
  if (typeof raw === 'string') return { state: raw, detail: '' };
  if (typeof raw === 'boolean') return { state: raw ? 'running' : 'stopped', detail: '' };
  if (!raw || typeof raw !== 'object') return { state: 'unknown', detail: '' };
  const serviceState = raw.state || raw.status || (raw.running === true ? 'running' : raw.running === false ? 'stopped' : 'unknown');
  return { state: String(serviceState).toLowerCase(), detail: raw.detail || raw.message || raw.error?.message || '' };
}

function serviceData(services, id) {
  if (Array.isArray(services)) {
    const match = services.find((item) => item?.id === id || item?.name === id);
    return normalizeService(match);
  }
  return normalizeService(services?.[id]);
}

function renderServices(services = {}) {
  elements.serviceList.replaceChildren();
  for (const id of SERVICES) {
    const info = serviceData(services, id);
    const row = document.createElement('div');
    row.className = 'service-row';
    const dot = document.createElement('span');
    dot.className = `service-state ${info.state.replace(/[^a-z-]/g, '')}`;
    dot.setAttribute('aria-label', info.state);
    const copy = document.createElement('span');
    copy.className = 'service-copy';
    const name = document.createElement('strong');
    name.textContent = SERVICE_LABELS[id];
    const status = document.createElement('small');
    status.textContent = info.detail || info.state;
    copy.append(name, status);
    const action = document.createElement('button');
    action.type = 'button';
    action.className = 'restart-button';
    const running = info.state === 'running';
    action.textContent = running ? 'Stop' : 'Start';
    action.setAttribute('aria-label', `${running ? 'Stop' : 'Start'} ${SERVICE_LABELS[id]}`);
    action.addEventListener('click', () => setServiceRunning(id, !running, action));
    const restart = document.createElement('button');
    restart.type = 'button';
    restart.className = 'restart-button';
    restart.textContent = 'Restart';
    restart.setAttribute('aria-label', `Restart ${SERVICE_LABELS[id]}`);
    restart.addEventListener('click', () => restartService(id, restart));
    const buttons = document.createElement('span');
    buttons.className = 'service-actions';
    buttons.append(action, restart);
    row.append(dot, copy, buttons);
    elements.serviceList.append(row);
  }
}

async function setServiceRunning(id, running, button) {
  if (!SERVICES.includes(id)) return;
  if (!window.confirm(`${running ? 'Start' : 'Stop'} ${SERVICE_LABELS[id]}?`)) return;
  button.disabled = true;
  button.textContent = running ? 'Starting…' : 'Stopping…';
  try {
    await api(`/services/${encodeURIComponent(id)}/${running ? 'start' : 'stop'}`, { method: 'POST', body: '{}' });
    toast(`${SERVICE_LABELS[id]} ${running ? 'started' : 'stopped'}`);
    window.setTimeout(refreshStatus, 600);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

async function refreshStatus() {
  elements.statusRefresh.disabled = true;
  try {
    const data = await api('/status');
    const uptime = data.uptimeSeconds ?? data.uptime_seconds ?? data.uptime ?? data.system?.uptime_seconds;
    const disk = data.disk?.availableBytes ?? data.disk?.available_bytes ?? data.disk?.free_bytes ?? data.disk_available_bytes ?? data.disk_free_bytes ?? data.disk?.available;
    const resolution = data.display?.resolution ?? data.display?.current ?? data.current_resolution ?? data.resolution;
    elements.statusUptime.textContent = formatDuration(uptime);
    elements.statusDisk.textContent = formatBytes(disk);
    elements.statusResolution.textContent = resolution || '—';
    renderServices(data.services);
  } catch (error) {
    elements.serviceList.replaceChildren();
    const unavailable = document.createElement('p');
    unavailable.className = 'empty-state';
    unavailable.textContent = 'System status is unavailable.';
    elements.serviceList.append(unavailable);
    toast(error.message, 'error');
  } finally {
    elements.statusRefresh.disabled = false;
  }
}

async function restartService(id, button) {
  if (!SERVICES.includes(id)) return;
  const confirmed = window.confirm(`Restart ${SERVICE_LABELS[id]}? Its current connections may be interrupted.`);
  if (!confirmed) return;
  button.disabled = true;
  button.textContent = 'Restarting…';
  if (id === 'vnc' && state.connected) state.expectingVncRestart = true;
  try {
    await api(`/services/${encodeURIComponent(id)}/restart`, { method: 'POST', body: '{}' });
    toast(`${SERVICE_LABELS[id]} restarted`);
    if (id === 'vnc') {
      // A supervisor response can race the WebSocket close. Keep the expected
      // restart window open briefly so a clean close still follows recovery.
      window.setTimeout(() => {
        if (state.connected) state.expectingVncRestart = false;
      }, 5_000);
    }
    window.setTimeout(refreshStatus, 1200);
  } catch (error) {
    if (id === 'vnc' && state.connected) state.expectingVncRestart = false;
    toast(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = 'Restart';
  }
}

function displayBound(value, fallback) {
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function normalizeDisplay(data) {
  const source = data.display && typeof data.display === 'object' ? data.display : data;
  const current = source.resolution ?? source.current ?? source.current_resolution ?? '';
  const availableModes = source.availableResolutions ?? source.modes ?? source.available_modes ?? source.resolutions ?? [];
  const supportedModes = source.supportedResolutions ?? source.supported ?? [];
  const dynamicResize = source.dynamicResize !== false;
  const rawBounds = source.bounds && typeof source.bounds === 'object' ? source.bounds : {};
  const bounds = {
    minWidth: displayBound(rawBounds.minWidth, DEFAULT_DISPLAY_BOUNDS.minWidth),
    minHeight: displayBound(rawBounds.minHeight, DEFAULT_DISPLAY_BOUNDS.minHeight),
    maxWidth: displayBound(rawBounds.maxWidth, DEFAULT_DISPLAY_BOUNDS.maxWidth),
    maxHeight: displayBound(rawBounds.maxHeight, DEFAULT_DISPLAY_BOUNDS.maxHeight),
    widthStep: displayBound(rawBounds.widthStep, DEFAULT_DISPLAY_BOUNDS.widthStep),
    heightStep: displayBound(rawBounds.heightStep, DEFAULT_DISPLAY_BOUNDS.heightStep),
  };
  if (bounds.minWidth > bounds.maxWidth || bounds.minHeight > bounds.maxHeight) {
    Object.assign(bounds, DEFAULT_DISPLAY_BOUNDS);
  }
  const rawModes = [
    ...(Array.isArray(availableModes) ? availableModes : []),
    ...(dynamicResize && Array.isArray(supportedModes) ? supportedModes : []),
  ];
  const modes = rawModes
    .map((mode) => typeof mode === 'string' ? mode : mode?.resolution || mode?.name)
    .filter((mode) => {
      const match = /^(\d+)x(\d+)$/.exec(mode || '');
      if (!match) return false;
      const width = Number(match[1]);
      const height = Number(match[2]);
      return width >= bounds.minWidth && width <= bounds.maxWidth
        && height >= bounds.minHeight && height <= bounds.maxHeight
        && width % bounds.widthStep === 0 && height % bounds.heightStep === 0;
    });
  const normalizedCurrent = String(current || '');
  if (normalizedCurrent && !modes.includes(normalizedCurrent)) modes.unshift(normalizedCurrent);
  return {
    current: normalizedCurrent,
    modes: [...new Set(modes)],
    dynamicResize,
    bounds,
  };
}

function renderDisplaySettings(display, note = '') {
  state.display = display;
  elements.displaySelect.replaceChildren();
  for (const mode of display.modes) {
    const option = document.createElement('option');
    option.value = mode;
    option.textContent = mode === display.current ? `${mode} (current)` : mode;
    option.selected = mode === display.current;
    elements.displaySelect.append(option);
  }
  if (!display.modes.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'No display modes reported';
    elements.displaySelect.append(option);
  }
  elements.displayApply.disabled = !display.modes.length;
  elements.displayNote.classList.remove('error');
  elements.displayNote.textContent = note || (display.current ? `Current desktop: ${display.current}` : 'Choose an available resolution.');
  if (display.current) elements.statusResolution.textContent = display.current;
}

async function loadDisplaySettings() {
  elements.displayApply.disabled = true;
  elements.displayNote.classList.remove('error');
  elements.displayNote.textContent = 'Loading display modes…';
  try {
    renderDisplaySettings(normalizeDisplay(await api('/display')));
  } catch (error) {
    elements.displaySelect.replaceChildren();
    const unavailable = document.createElement('option');
    unavailable.value = '';
    unavailable.textContent = 'Display service unavailable';
    elements.displaySelect.append(unavailable);
    elements.displayNote.textContent = error.message;
    elements.displayNote.classList.add('error');
  }
}

function alignDisplayDimension(value, minimum, maximum, step) {
  const alignedMinimum = Math.ceil(minimum / step) * step;
  const alignedMaximum = Math.floor(maximum / step) * step;
  const aligned = Math.round(value / step) * step;
  return Math.min(alignedMaximum, Math.max(alignedMinimum, aligned));
}

function viewportResolution(rect, bounds = DEFAULT_DISPLAY_BOUNDS) {
  const viewportWidth = Math.max(1, Number(rect.width) || 0);
  const viewportHeight = Math.max(1, Number(rect.height) || 0);
  const minimumScale = Math.max(bounds.minWidth / viewportWidth, bounds.minHeight / viewportHeight);
  const maximumScale = Math.min(bounds.maxWidth / viewportWidth, bounds.maxHeight / viewportHeight);
  const hasAspectPreservingSize = minimumScale <= maximumScale;
  const scale = hasAspectPreservingSize
    ? Math.min(maximumScale, Math.max(minimumScale, 1))
    : 1;
  const width = hasAspectPreservingSize
    ? viewportWidth * scale
    : Math.min(bounds.maxWidth, Math.max(bounds.minWidth, viewportWidth));
  const height = hasAspectPreservingSize
    ? viewportHeight * scale
    : Math.min(bounds.maxHeight, Math.max(bounds.minHeight, viewportHeight));
  const alignedWidth = alignDisplayDimension(width, bounds.minWidth, bounds.maxWidth, bounds.widthStep);
  const alignedHeight = alignDisplayDimension(height, bounds.minHeight, bounds.maxHeight, bounds.heightStep);
  return `${alignedWidth}x${alignedHeight}`;
}

function textEditingElement(element = document.activeElement) {
  if (!(element instanceof HTMLElement)) return false;
  if (element.isContentEditable || element.tagName === 'TEXTAREA') return true;
  if (element.tagName !== 'INPUT') return false;
  return !['button', 'checkbox', 'color', 'file', 'radio', 'range', 'reset', 'submit'].includes(element.type);
}

function softwareKeyboardOwnsViewport() {
  return state.keyboardComposing || textEditingElement();
}

function cancelScheduledViewportMatch() {
  window.clearTimeout(state.viewportResizeTimer);
  state.viewportResizeTimer = null;
  state.viewportResizePending = false;
  state.viewportResizeAnnounce = false;
}

function scheduleViewportMatch({ announce = false } = {}) {
  if (state.workspaceView !== 'desktop') return;
  if (!state.preferences.autoResize && !announce) return;
  if (document.visibilityState === 'hidden' || !state.connected || softwareKeyboardOwnsViewport()) return;
  window.clearTimeout(state.viewportResizeTimer);
  state.viewportResizeAnnounce = state.viewportResizeAnnounce || announce;
  state.viewportResizeTimer = window.setTimeout(() => {
    state.viewportResizeTimer = null;
    const shouldAnnounce = state.viewportResizeAnnounce;
    state.viewportResizeAnnounce = false;
    matchDesktopToViewport({ announce: shouldAnnounce });
  }, VIEWPORT_RESIZE_DELAY);
}

async function matchDesktopToViewport({ announce = false } = {}) {
  if (state.workspaceView !== 'desktop' || !state.connected) {
    if (announce) toast('Connect the desktop before matching its size', 'error');
    return;
  }
  if (document.visibilityState === 'hidden' || softwareKeyboardOwnsViewport()) return;
  if (state.viewportResizeInFlight) {
    state.viewportResizePending = true;
    state.viewportResizeAnnounce = state.viewportResizeAnnounce || announce;
    return;
  }

  const intentRevision = state.displayIntentRevision;
  state.viewportResizeInFlight = true;
  elements.matchScreenButton.disabled = true;
  try {
    // Refresh the shared server state before comparing. A second browser may
    // have resized this desktop since our settings panel was last opened.
    state.display = normalizeDisplay(await api('/display'));
    if (intentRevision !== state.displayIntentRevision || (!announce && !state.preferences.autoResize)) return;
    if (!state.display.dynamicResize) throw new Error('This desktop does not support screen matching');
    const resolution = viewportResolution(elements.stage.getBoundingClientRect(), state.display.bounds);
    if (resolution === state.display.current || resolution === state.lastRequestedResolution) {
      if (announce) toast(`Desktop already matches this screen at ${resolution}`);
      return;
    }
    state.lastRequestedResolution = resolution;
    expectDisplayResize();
    const display = normalizeDisplay(await api('/display', {
      method: 'PUT',
      body: JSON.stringify({ resolution }),
    }));
    renderDisplaySettings(display, `Desktop matched to this screen at ${display.current || resolution}.`);
    if (announce) toast(`Desktop matched to ${display.current || resolution}`);
  } catch (error) {
    clearExpectedDisplayResize();
    elements.displayNote.textContent = error.message;
    elements.displayNote.classList.add('error');
    if (announce) toast(error.message, 'error');
  } finally {
    state.lastRequestedResolution = '';
    state.viewportResizeInFlight = false;
    elements.matchScreenButton.disabled = false;
    const pendingFixed = state.pendingFixedResolution;
    state.pendingFixedResolution = null;
    if (pendingFixed && pendingFixed.revision === state.displayIntentRevision) {
      applyFixedDisplaySetting(pendingFixed.resolution, pendingFixed.revision);
    } else if (state.viewportResizePending) {
      state.viewportResizePending = false;
      scheduleViewportMatch({ announce: state.viewportResizeAnnounce });
    }
  }
}

async function applyFixedDisplaySetting(resolution, intentRevision) {
  elements.displayApply.disabled = true;
  elements.displayNote.classList.remove('error');
  elements.displayNote.textContent = `Applying ${resolution}…`;
  try {
    if (intentRevision !== state.displayIntentRevision) return;
    state.lastRequestedResolution = resolution;
    expectDisplayResize();
    const display = normalizeDisplay(await api('/display', { method: 'PUT', body: JSON.stringify({ resolution }) }));
    renderDisplaySettings(display, `Desktop set to ${display.current || resolution}. Automatic matching is off.`);
    toast(`Desktop resolution changed to ${display.current || resolution}`);
  } catch (error) {
    clearExpectedDisplayResize();
    elements.displayNote.textContent = error.message;
    elements.displayNote.classList.add('error');
  } finally {
    state.lastRequestedResolution = '';
    elements.displayApply.disabled = false;
  }
}

function applyDisplaySetting() {
  const resolution = elements.displaySelect.value;
  if (!resolution) return;
  state.preferences.autoResize = false;
  elements.autoResizeToggle.checked = false;
  savePreferences();
  cancelScheduledViewportMatch();
  const revision = ++state.displayIntentRevision;
  if (state.viewportResizeInFlight) {
    state.pendingFixedResolution = { resolution, revision };
    elements.displayApply.disabled = true;
    elements.displayNote.classList.remove('error');
    elements.displayNote.textContent = `Waiting to apply ${resolution}…`;
    return;
  }
  applyFixedDisplaySetting(resolution, revision);
}

function logText(data) {
  if (typeof data.text === 'string') return data.text;
  if (Array.isArray(data.lines)) return data.lines.join('\n');
  return '';
}

async function loadLogs({ append = false } = {}) {
  const id = elements.logService.value;
  if (!SERVICES.includes(id)) return;
  const requestedCursor = append ? state.logCursor : null;
  const query = new URLSearchParams({ limit: '200' });
  if (requestedCursor !== null && requestedCursor !== '') query.set('cursor', requestedCursor);
  elements.logRefresh.disabled = true;
  elements.logMore.disabled = true;
  elements.logStatus.textContent = append ? 'Checking for new entries…' : 'Loading recent log…';
  try {
    const data = await api(`/logs/${encodeURIComponent(id)}?${query}`);
    const text = logText(data);
    if (!append || data.reset === true) {
      elements.logOutput.textContent = text || '(No log entries returned.)';
    } else if (text) {
      elements.logOutput.textContent = `${elements.logOutput.textContent}\n${text}`;
    }
    const next = data.next_cursor ?? data.nextCursor ?? null;
    state.logCursor = next;
    elements.logMore.hidden = next === null || next === '';
    elements.logStatus.textContent = data.reset === true
      ? 'The log rotated; the view was refreshed.'
      : append && !text
        ? 'No new log entries.'
        : data.truncated === true
          ? 'Showing the newest bounded log page.'
          : 'Log is up to date.';
    elements.logOutput.scrollTop = append && data.reset !== true ? elements.logOutput.scrollHeight : 0;
  } catch (error) {
    elements.logOutput.textContent = append ? `${elements.logOutput.textContent}\n[Error] ${error.message}` : `Could not load logs: ${error.message}`;
    elements.logMore.hidden = true;
    elements.logStatus.textContent = 'Log request failed.';
  } finally {
    elements.logRefresh.disabled = false;
    elements.logMore.disabled = false;
  }
}

function syncSettingsControls() {
  const selectedScale = document.querySelector(`input[name="scale"][value="${state.preferences.scaleMode}"]`);
  if (selectedScale) selectedScale.checked = true;
  elements.qualityRange.value = String(state.preferences.qualityLevel);
  elements.qualityOutput.value = String(state.preferences.qualityLevel);
  elements.compressionRange.value = String(state.preferences.compressionLevel);
  elements.compressionOutput.value = String(state.preferences.compressionLevel);
  syncRenderProfile();
  elements.viewOnlyToggle.checked = state.preferences.viewOnly;
  elements.reconnectToggle.checked = state.preferences.reconnect;
  elements.autoResizeToggle.checked = state.preferences.autoResize;
  applyRfbPreferences();
}

function syncRenderProfile() {
  const match = Object.entries(RENDER_PROFILES).find(([, values]) => (
    values.qualityLevel === state.preferences.qualityLevel
    && values.compressionLevel === state.preferences.compressionLevel
  ));
  elements.renderProfile.value = match?.[0] || 'custom';
}

function bindEvents() {
  for (const tab of [elements.desktopViewTab, elements.terminalViewTab, elements.editorViewTab]) {
    tab.addEventListener('click', (event) => {
      event.preventDefault();
      setWorkspaceView(tab.dataset.workspaceView, { historyMode: 'push', focus: true });
    });
    tab.addEventListener('keydown', (event) => {
      const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'];
      if (!keys.includes(event.key)) return;
      event.preventDefault();
      const tabs = [elements.desktopViewTab, elements.terminalViewTab, elements.editorViewTab];
      const index = tabs.indexOf(tab);
      const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (['ArrowRight','ArrowDown'].includes(event.key) ? 1 : 2)) % 3;
      setWorkspaceView(tabs[nextIndex].dataset.workspaceView, { historyMode: 'push' });
      tabs[nextIndex].focus();
    });
  }
  window.addEventListener('popstate', () => {
    document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
    setWorkspaceView(workspaceViewFromLocation());
    applyPanelFromLocation();
  });
  $('editor-retry').addEventListener('click', ensureEditorFrame);
  elements.workspaceBack.addEventListener('click', event => {
    event.preventDefault();
    if (window.history.state?.vibestackView && state.workspaceView !== 'desktop') window.history.back();
    else setWorkspaceView('desktop', {historyMode:'replace', focus:true});
  });
  document.querySelectorAll('[data-open-apps]').forEach(button => button.addEventListener('click', (event) => {
    event.preventDefault();
    openDialog(elements.appsDialog);
    loadApps();
  }));
  elements.connectionAction.addEventListener('click', manualConnect);
  elements.inputControlsButton.addEventListener('click', toggleInputControls);
  elements.matchScreenButton.addEventListener('click', () => matchDesktopToViewport({ announce: true }));
  document.addEventListener('pointerdown', (event) => {
    if (elements.inputControlsButton.getAttribute('aria-expanded') !== 'true') return;
    if (elements.inputControlsButton.contains(event.target) || elements.inputControlsPanel.contains(event.target)) return;
    if (state.pressedModifiers.size || softwareKeyboardOwnsViewport()) return;
    setInputControlsExpanded(false);
  });
  elements.focusButton.addEventListener('click', focusWorkspace);
  elements.fullscreenButton.addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
      else toast('Full screen is available when VibeStack is installed to the Home Screen', 'error');
    } catch (_error) {
      toast('The browser did not allow full screen', 'error');
    }
  });
  document.addEventListener('fullscreenchange', () => {
    const active = Boolean(document.fullscreenElement);
    elements.fullscreenButton.setAttribute('aria-pressed', String(active));
    elements.fullscreenButton.setAttribute('aria-label', active ? 'Exit full screen' : 'Enter full screen');
  });

  document.querySelectorAll('[data-open-settings]').forEach((button) => button.addEventListener('click', (event) => {
    event.preventDefault();
    if (elements.toolsDialog.open) elements.toolsDialog.close();
    openDialog(elements.settingsDialog);
    loadDisplaySettings();
  }));
  document.querySelectorAll('[data-menu-view]').forEach((link) => link.addEventListener('click', (event) => {
    event.preventDefault();
    setWorkspaceView(link.dataset.menuView, { historyMode: 'push', focus: true });
  }));
  elements.disconnectButton.addEventListener('click', () => {
    if (state.workspaceView === 'terminal') {
      setWorkspaceView('desktop', { historyMode: 'push', focus: true });
      return;
    }
    if (state.connected || state.rfb) disconnect();
    else manualConnect();
  });
  elements.toolsButton.addEventListener('click', () => {
    openDialog(elements.toolsDialog);
    refreshStatus();
  });
  document.querySelectorAll('[data-close-dialog]').forEach((button) => {
    button.addEventListener('click', () => button.closest('dialog')?.close());
  });
  document.querySelectorAll('dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener('close', () => {
      const invoker = dialogInvokers.get(dialog);
      if (invoker?.isConnected) window.setTimeout(() => invoker.focus(), 0);
      window.setTimeout(() => scheduleViewportMatch(), 0);
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const dialog = document.querySelector('dialog[open]');
    if (dialog) {
      event.preventDefault();
      dialog.close();
      return;
    }
    if (elements.inputControlsButton.getAttribute('aria-expanded') === 'true') {
      event.preventDefault();
      setInputControlsExpanded(false, { restoreFocus: true });
    }
  });

  elements.keyboardButton.addEventListener('click', toggleVirtualKeyboard);
  elements.virtualKeyboard.addEventListener('focus', () => elements.keyboardButton.setAttribute('aria-pressed', 'true'));
  elements.virtualKeyboard.addEventListener('blur', () => {
    state.keyboardComposing = false;
    releaseKeyboardModifiers();
    elements.keyboardButton.setAttribute('aria-pressed', 'false');
    scheduleViewportMatch();
  });
  elements.virtualKeyboard.addEventListener('compositionstart', () => {
    state.keyboardComposing = true;
  });
  elements.virtualKeyboard.addEventListener('compositionend', () => {
    state.keyboardComposing = false;
    if (!state.preferences.viewOnly) applyVirtualKeyboardValue();
    else resetVirtualKeyboardInput();
  });
  elements.virtualKeyboard.addEventListener('input', handleVirtualKeyboardInput);
  elements.virtualKeyboard.addEventListener('keydown', (event) => handleVirtualKeyboardKey(event, true));
  elements.virtualKeyboard.addEventListener('keyup', (event) => handleVirtualKeyboardKey(event, false));
  document.addEventListener('focusout', (event) => {
    if (!textEditingElement(event.target)) return;
    window.setTimeout(() => scheduleViewportMatch(), 0);
  });
  document.querySelectorAll('[data-modifier]').forEach((button) => button.addEventListener('click', () => toggleModifier(button.dataset.modifier)));
  elements.cadButton.addEventListener('click', () => {
    if (!state.connected || !state.rfb || state.preferences.viewOnly) return;
    releaseAllInput();
    state.rfb.sendCtrlAltDel();
    toast('Sent Ctrl+Alt+Delete');
  });

  elements.clipboardButton.addEventListener('click', () => {
    elements.clipboardText.value = state.remoteClipboard;
    openDialog(elements.clipboardDialog);
    window.setTimeout(() => elements.clipboardText.focus(), 0);
  });
  elements.clipboardClear.addEventListener('click', () => {
    state.remoteClipboard = '';
    elements.clipboardText.value = '';
    elements.clipboardText.focus();
  });
  elements.clipboardCopy.addEventListener('click', async () => {
    const text = elements.clipboardText.value;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
      await navigator.clipboard.writeText(text);
      toast('Clipboard copied to this device');
    } catch (_error) {
      elements.clipboardText.focus();
      elements.clipboardText.select();
      toast('Clipboard access was denied. The text is selected so you can copy it manually.', 'error');
    }
  });
  elements.clipboardSend.addEventListener('click', () => {
    if (!state.connected || !state.rfb) {
      toast('Connect the desktop before sending clipboard text', 'error');
      return;
    }
    if (state.preferences.viewOnly) {
      toast('Turn off View only to send clipboard text', 'error');
      return;
    }
    state.remoteClipboard = elements.clipboardText.value;
    state.rfb.clipboardPasteFrom(state.remoteClipboard);
    elements.clipboardDialog.close();
    toast('Clipboard sent to the desktop');
  });

  document.querySelectorAll('input[name="scale"]').forEach((radio) => radio.addEventListener('change', () => {
    if (!radio.checked) return;
    state.preferences.scaleMode = radio.value === 'actual' ? 'actual' : 'fit';
    savePreferences();
    applyRfbPreferences();
  }));
  elements.renderProfile.addEventListener('change', () => {
    const profile = RENDER_PROFILES[elements.renderProfile.value];
    if (!profile) return;
    state.preferences.qualityLevel = profile.qualityLevel;
    state.preferences.compressionLevel = profile.compressionLevel;
    elements.qualityRange.value = String(profile.qualityLevel);
    elements.qualityOutput.value = String(profile.qualityLevel);
    elements.compressionRange.value = String(profile.compressionLevel);
    elements.compressionOutput.value = String(profile.compressionLevel);
    savePreferences();
    applyRfbPreferences();
  });
  elements.qualityRange.addEventListener('input', () => {
    state.preferences.qualityLevel = clampInteger(elements.qualityRange.value, 0, 9, defaults.qualityLevel);
    elements.qualityOutput.value = String(state.preferences.qualityLevel);
    syncRenderProfile();
    savePreferences();
    applyRfbPreferences();
  });
  elements.compressionRange.addEventListener('input', () => {
    state.preferences.compressionLevel = clampInteger(elements.compressionRange.value, 0, 9, defaults.compressionLevel);
    elements.compressionOutput.value = String(state.preferences.compressionLevel);
    syncRenderProfile();
    savePreferences();
    applyRfbPreferences();
  });
  elements.viewOnlyToggle.addEventListener('change', () => {
    state.preferences.viewOnly = elements.viewOnlyToggle.checked;
    if (state.preferences.viewOnly) releaseAllInput();
    savePreferences();
    applyRfbPreferences();
  });
  elements.reconnectToggle.addEventListener('change', () => {
    state.preferences.reconnect = elements.reconnectToggle.checked;
    savePreferences();
    if (state.preferences.reconnect && !state.connected && !state.retryTimer && !state.retryBlocked) scheduleReconnect('Automatic reconnect was enabled.');
    else if (!state.preferences.reconnect) clearRetry();
  });
  elements.autoResizeToggle.addEventListener('change', () => {
    state.displayIntentRevision += 1;
    state.pendingFixedResolution = null;
    state.preferences.autoResize = elements.autoResizeToggle.checked;
    savePreferences();
    cancelScheduledViewportMatch();
    elements.displayApply.disabled = !state.display.modes.length;
    if (state.preferences.autoResize) {
      elements.displayNote.textContent = 'Matching the desktop after this viewport settles…';
      scheduleViewportMatch({ announce: true });
    } else {
      elements.displayNote.textContent = state.display.current
        ? `Current desktop: ${state.display.current}. Automatic matching is off.`
        : 'Automatic matching is off.';
    }
  });

  elements.displayApply.addEventListener('click', applyDisplaySetting);
  elements.statusRefresh.addEventListener('click', refreshStatus);
  elements.logRefresh.addEventListener('click', () => loadLogs());
  elements.logMore.addEventListener('click', () => loadLogs({ append: true }));
  elements.logService.addEventListener('change', () => {
    state.logCursor = null;
    elements.logMore.hidden = true;
    elements.logOutput.textContent = 'Choose Load to view this service’s recent log.';
    elements.logStatus.textContent = '';
  });

  if ('ResizeObserver' in window) {
    state.stageResizeObserver = new ResizeObserver(() => scheduleViewportMatch());
    state.stageResizeObserver.observe(elements.stage);
  } else {
    window.addEventListener('resize', () => scheduleViewportMatch());
  }
  window.addEventListener('orientationchange', () => scheduleViewportMatch());
  window.visualViewport?.addEventListener('resize', () => scheduleViewportMatch());

  window.addEventListener('online', () => {
    toast('Network connection restored');
    if (state.workspaceView === 'desktop' && !state.connected && !state.retryBlocked && (state.preferences.reconnect || state.recoveringVncRestart)) connect();
  });
  window.addEventListener('offline', () => {
    clearRetry();
    const rfb = state.rfb;
    state.rfb = null;
    state.connected = false;
    state.expectingVncRestart = false;
    clearExpectedDisplayResize();
    cancelScheduledViewportMatch();
    releaseAllInput(rfb);
    if (rfb) {
      try { rfb.disconnect(); } catch (_error) { /* already closed */ }
    }
    setConnectionUi('offline', 'You’re offline', 'Reconnect to the network and VibeStack will try again.', { action: true });
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted && state.workspaceView === 'desktop' && !state.connected && !state.retryBlocked && (state.preferences.reconnect || state.recoveringVncRestart)) connect();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      cancelScheduledViewportMatch();
      releaseAllInput();
    } else {
      if (state.workspaceView === 'desktop' && !state.connected && !state.retryTimer && !state.retryBlocked && (state.preferences.reconnect || state.recoveringVncRestart)) {
        connect();
      } else {
        scheduleViewportMatch();
      }
    }
  });
  window.addEventListener('pagehide', () => {
    cancelScheduledViewportMatch();
    releaseAllInput();
  });
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  try {
    const registration = await navigator.serviceWorker.register('/service-worker.js', { scope: '/' });
    if (registration.waiting && navigator.serviceWorker.controller) showUpdateAvailable(registration.waiting);
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing;
      worker?.addEventListener('statechange', () => {
        if (worker.state === 'installed' && navigator.serviceWorker.controller) showUpdateAvailable(worker);
      });
    });
  } catch (error) {
    console.warn('VibeStack service worker registration failed:', error);
  }
}

async function initialize() {
  try {
    const response = await fetch('/setup/api/state', {cache:'no-store', credentials:'same-origin'});
    const setup = response.ok ? await response.json() : null;
    if (setup?.authentication?.password_configured === false) {
      window.location.replace('/setup/?force=1');
      return;
    }
  } catch (_) { /* Keep the desktop usable during setup-service recovery. */ }
  resetVirtualKeyboardInput();
  syncSettingsControls();
  bindEvents();
  const initialView = workspaceViewFromLocation();
  if (initialView !== 'desktop') {
    const requested = window.location.pathname + window.location.search;
    window.history.replaceState({vibestackView:'desktop'}, '', workspaceHref('desktop'));
    window.history.pushState({vibestackView:initialView}, '', requested);
  }
  setWorkspaceView(initialView, { initial: true });
  registerServiceWorker();
  applyPanelFromLocation();
  if (initialView === 'desktop') connect();
  else setConnectionUi('disconnected', 'Desktop paused', 'Switch to Desktop when you want to open the graphical workspace.', { action: true });
}

initialize();
