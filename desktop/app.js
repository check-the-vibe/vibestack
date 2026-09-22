import RFB from '/novnc/core/rfb.js';

const $ = id => document.getElementById(id);
const RETRY_DELAYS = [1000, 2000, 4000, 8000, 10000];
const state = {
  csrf: '', identity: '', owner: false, connected: false, open: false,
  rfb: null, hasConnected: false, retry: 0, retryTimer: null, blocked: false,
  providers: [], provider: '', conversations: [], conversation: null, cursor: 0,
  conversationGeneration: 0, refreshing: false, submitting: false, creating: false,
  messageNodes: new Map(), approvalNodes: new Map(), consumedApprovals: new Set(),
  transcriptBytes: 0, passwordReady: false,
};
const busyStates = new Set(['submitting', 'running', 'stopping']);
const uuid = () => [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, '0')).join('');
const note = value => { $('panel-notice').textContent = value; };
const friendlyErrors = {
  forbidden: 'This workspace credential does not allow that action. Ask the owner for the required access.',
  invalid_input: 'The request could not be accepted. Check the project, model and current action details.',
  conflict: 'The operation changed or was already answered. Refresh its state before doing anything else.',
  busy: 'The service or conversation has reached its capacity. Inspect the existing operation before continuing.',
  unavailable: 'The provider is unavailable. Refresh its status or stop and activate it again.',
  timeout: 'The response was not confirmed. Inspect the existing operation; it has not been resent.',
};
function failure(code = 'unavailable') { const error = new Error(friendlyErrors[code] || friendlyErrors.unavailable); error.code = code; return error; }

async function request(path, {method = 'GET', input, headers = {}} = {}) {
  const options = {method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(35000), headers: {...headers}};
  if (method !== 'GET' && method !== 'HEAD' && state.csrf) options.headers['X-VibeStack-CSRF'] = state.csrf;
  if (input !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(input); }
  let response;
  try { response = await fetch(path, options); } catch { throw failure('timeout'); }
  if (response.status === 401) {
    state.csrf = ''; state.connected = false; state.owner = false;
    clearTimeout(state.retryTimer);
    const rfb = state.rfb; state.rfb = null; rfb?.disconnect();
    chooseConversation(null); $('message-input').value = '';
    renderConnection();
    throw new Error('Connect your workspace to continue.');
  }
  const reader = response.body?.getReader();
  let size = 0, text = ''; const decoder = new TextDecoder();
  if (reader) {
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.length;
      if (size > 2 * 1024 * 1024) { await reader.cancel(); throw failure(); }
      text += decoder.decode(part.value, {stream: true});
    }
    text += decoder.decode();
  }
  let value;
  try { value = text ? JSON.parse(text) : {}; } catch { throw failure(); }
  if (!response.ok || value.error) throw failure(value.error?.code || (response.status === 403 ? 'forbidden' : 'unavailable'));
  return value;
}
async function call(id, input = {}) {
  const value = await request(`/api/v1/capabilities/${id}/invoke`, {method: 'POST', input, headers:{'X-VibeStack-Expected-Instance':state.identity}});
  if (value.instance_id !== state.identity || value.capability !== id || !value.result) throw failure();
  return value.result;
}
function currentProvider() { return state.providers.find(p => p.id === state.provider); }
function activeOperation() { return state.conversation?.operations.find(op => busyStates.has(op.status)); }
function renderConnection() {
  $('connection-step').hidden = state.connected;
  $('password-step').hidden = !state.connected || state.passwordReady || !state.owner;
  $('agent-workspace').hidden = !state.connected || !state.passwordReady;
  $('disconnect-workspace').hidden = !state.connected;
  if (!state.connected) {
    desktopStatus('disconnected', 'Open the agent to connect your workspace.');
    $('agent-indicator').dataset.state = 'attention';
  }
}
function setOpen(open) {
  state.open = open;
  $('agent-panel').hidden = !open;
  $('agent-toggle').setAttribute('aria-expanded', String(open));
  $('agent-toggle').setAttribute('aria-label', open ? 'Close VibeStack agent' : 'Open VibeStack agent');
  if (open) {
    state.rfb?.blur();
    $('agent-close').focus();
    refresh().catch(error => note(error.message));
  } else {
    $('workspace-credential').value = '';
    $('linux-password').value = '';
    $('linux-confirmation').value = '';
    $('agent-toggle').focus();
  }
}
function options(select, values, chosen, placeholder) {
  const fingerprint = JSON.stringify(values.map(({id,name})=>({id,name})));
  if (select.dataset.fingerprint !== fingerprint) {
    select.replaceChildren();
    if (placeholder !== undefined) select.add(new Option(placeholder, ''));
    for (const item of values) select.add(new Option(item.name, item.id));
    select.dataset.fingerprint = fingerprint;
  }
  if (values.some(item => item.id === chosen)) select.value = chosen;
}
function renderProvider() {
  options($('provider-select'), state.providers, state.provider);
  const provider = currentProvider();
  if (!provider) return;
  const installed = provider.installed === null ? 'Not checked' : provider.installed ? `Installed ${provider.version}` : 'Not installed';
  const phases = {probing:'Checking installation', installing:'Installing inside VibeStack…', starting:'Starting the native runtime…', stopping:'Stopping the runtime…', active:'Runtime running', stopped:'Runtime stopped', failed:'Activation failed', idle:'Ready to activate'};
  let detail = `${installed} · ${phases[provider.phase] || 'Status unavailable'}`;
  if (provider.authentication === 'needs_sign_in') detail += '\nSign in using the provider application, then refresh status.';
  else if (provider.readiness === 'verified') detail += '\nA model turn completed successfully.';
  else if (provider.process === 'running') detail += '\nModel access and account quota will be checked by your first task.';
  if (provider.failure) detail += '\n' + ({storage_unavailable:'Saved state is unavailable. Stop the provider and ask the operator to repair storage.', incompatible_protocol:'The runtime does not match the supported protocol. Ask the operator to repair its installation.', connection_lost:'The native connection was lost. Inspect saved work before reactivating.', provider_rejected:'The native request was rejected. Check sign-in and model configuration in the provider app.'}[provider.failure] || 'The operation could not finish. Refresh status and inspect the provider app.');
  $('provider-status').textContent = detail;
  const activating = ['probing','installing','starting','stopping'].includes(provider.phase);
  $('provider-activate').disabled = activating || provider.process === 'running';
  $('provider-activate').textContent = activating ? 'Activation in progress…' : 'Activate provider';
  $('provider-stop').hidden = provider.process !== 'running' && !activating;
  $('provider-open').hidden = !provider.installed;
  $('provider-open').disabled = !state.owner;
  $('provider-open').textContent = provider.authentication === 'needs_sign_in' ? 'Open sign-in app' : 'Open provider app';
  const models = provider.models || [];
  const chosen = state.conversation?.provider === state.provider ? state.conversation.model : $('model-select').value;
  options($('model-select'), models, chosen, models.length ? undefined : 'No configured models');
  if (!models.some(model => model.id === $('model-select').value) && models.length) $('model-select').value = (models.find(model => model.default) || models[0]).id;
  $('model-select').disabled = !models.length || Boolean(state.conversation);
  $('project-select').disabled = Boolean(state.conversation);
  $('agent-indicator').dataset.state = activating || activeOperation() ? 'working' : provider.readiness === 'verified' ? 'active' : 'attention';
  renderTurnControls();
}
function renderTurnControls() {
  const op = activeOperation();
  const p = currentProvider();
  $('send-message').disabled = state.submitting || state.creating || Boolean(op) || !state.passwordReady || p?.process !== 'running' || !$('model-select').value || (state.conversation && state.conversation.status !== 'idle');
  $('stop-turn').hidden = !op;
  $('stop-turn').disabled = op?.status === 'submitting' || op?.status === 'stopping';
  $('stop-turn').textContent = op?.status === 'stopping' ? 'Stopping…' : 'Stop turn';
  $('new-conversation').disabled = state.creating || state.submitting;
}
function renderConversationChoices() {
  const values = state.conversations.filter(c => c.provider === state.provider).map(c => ({id:c.id, name:`${c.project} · ${new Date(c.created_at).toLocaleString()}`}));
  options($('conversation-select'), values, state.conversation?.id, 'New conversation');
  if (!state.conversation) $('conversation-select').value = '';
}
function chooseConversation(conversation) {
  state.conversationGeneration++;
  state.conversation = conversation;
  state.cursor = 0; state.messageNodes.clear(); state.approvalNodes.clear(); state.consumedApprovals.clear(); state.transcriptBytes = 0;
  $('messages').replaceChildren(); $('approvals').replaceChildren(); $('history-gap').hidden = true;
  if (conversation) { state.provider = conversation.provider; $('project-select').value = conversation.project; }
  $('conversation-status').textContent = conversation ? 'Loading the native conversation…' : 'Choose a provider and model to begin.';
  renderConversationChoices(); renderProvider();
}
function appendMessage(kind, text, key = '') {
  if (!text) return;
  let node = key ? state.messageNodes.get(key) : null;
  if (!node) {
    node = document.createElement('div'); node.className = 'message'; node.dataset.kind = kind;
    if (key) { node.dataset.key = key; state.messageNodes.set(key, node); }
    $('messages').append(node);
  }
  const room = Math.max(0, 64 * 1024 - node.textContent.length);
  const added = String(text).slice(0, room);
  node.textContent += added; state.transcriptBytes += added.length;
  if (added.length < text.length) $('history-gap').hidden = false;
  while ($('messages').children.length > 160 || state.transcriptBytes > 512 * 1024) {
    const first = $('messages').firstElementChild;
    state.transcriptBytes -= first.textContent.length;
    state.messageNodes.delete(first.dataset.key); first.remove(); $('history-gap').hidden = false;
  }
}
function renderApprovals(approvals, conversation) {
  const ids = new Set(approvals.map(a => a.approval_id));
  for (const [id, node] of state.approvalNodes) if (!ids.has(id)) { node.remove(); state.approvalNodes.delete(id); }
  for (const approval of approvals) {
    if (state.approvalNodes.has(approval.approval_id)) continue;
    const node = document.createElement('section'); node.className = 'approval';
    const title = document.createElement('h3'); title.textContent = 'Your approval is required';
    const preview = document.createElement('pre'); preview.textContent = approval.text;
    const explanation = document.createElement('p'); explanation.textContent = approval.can_allow ? 'Review the action before allowing it once.' : 'The full action could not be shown. You can decline it and inspect the native application.';
    const row = document.createElement('div'); row.className = 'button-row';
    for (const [label, allow] of [['Decline',false],['Allow once',true]]) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
      button.disabled = !state.owner || (allow && !approval.can_allow) || state.consumedApprovals.has(approval.approval_id);
      button.addEventListener('click', async () => {
        if (state.consumedApprovals.has(approval.approval_id)) return;
        state.consumedApprovals.add(approval.approval_id);
        row.querySelectorAll('button').forEach(b => { b.disabled = true; });
        explanation.textContent = 'Sending your decision…';
        try {
          await call('answerProviderApproval', {conversation:conversation.id, operation_id:approval.operation_id, approval_id:approval.approval_id, allow});
          explanation.textContent = 'Decision delivered.';
        } catch { explanation.textContent = 'Delivery could not be confirmed. This answer was not resent. Inspect or stop the native turn.'; }
      });
      row.append(button);
    }
    node.append(title, preview, explanation, row); $('approvals').append(node); state.approvalNodes.set(approval.approval_id,node);
  }
}
async function readConversation() {
  const conversation = state.conversation; const generation = state.conversationGeneration;
  if (!conversation) return;
  const page = await call('readProviderEvents', {conversation:conversation.id, cursor:state.cursor});
  if (generation !== state.conversationGeneration) return;
  if (page.cursor < state.cursor) { state.cursor = 0; state.messageNodes.clear(); }
  state.conversation = page.conversation;
  if (page.gap) $('history-gap').hidden = false;
  for (const event of page.events) {
    if (event.sequence <= state.cursor) continue;
    if (event.kind === 'text_delta') appendMessage('assistant', event.text, `${event.operation_id}/${event.item_id || 'message'}`);
    else if (event.kind === 'action') appendMessage('action', event.text);
    else if (event.kind === 'error') appendMessage('error', event.text);
    else if (event.kind === 'completed') appendMessage('action', ({completed:'Turn completed.', interrupted:'Turn interrupted. Existing edits remain.', failed:'The provider could not complete this turn. Check sign-in, model access and quota in its application.'})[event.outcome] || 'Turn outcome unknown. Inspect native history.');
  }
  state.cursor = page.cursor;
  const op = activeOperation();
  const previous = page.conversation.operations.at(-1);
  $('conversation-status').textContent = page.conversation.status === 'creating' ? 'Creating the native conversation…' : page.conversation.status === 'unknown' ? 'Creation could not be confirmed. Inspect the provider app before starting another conversation.' : op ? `Agent ${op.status}…` : previous?.status === 'unknown' ? 'The previous turn has an unknown outcome. Inspect native history before requesting more work.' : `${page.conversation.project} · ${page.conversation.model}`;
  renderApprovals(page.approvals, page.conversation); renderTurnControls();
}
async function refresh() {
  if (!state.connected || state.refreshing) return;
  state.refreshing = true;
  try {
    const catalog = await call('listProviders');
    state.providers = catalog.providers;
    if (!state.providers.some(p => p.id === state.provider)) state.provider = state.providers[0]?.id || '';
    const selected = state.provider;
    if (selected) {
      const result = await call('getProviderStatus', {provider:selected});
      const index = state.providers.findIndex(p => p.id === selected);
      if (index >= 0) state.providers[index] = result.provider;
    }
    const list = await call('listProviderConversations'); state.conversations = list.conversations;
    renderProvider(); renderConversationChoices();
    await readConversation();
  } finally { state.refreshing = false; }
}
async function setupSession() {
  const session = await request('/auth/session');
  if (state.identity && state.identity !== session.instance_id) {
    chooseConversation(null); state.providers = []; state.conversations = [];
  }
  state.csrf = session.csrf; state.identity = session.instance_id; state.owner = session.owner === true; state.connected = true;
  state.passwordReady = false;
  const setup = await request('/setup/api/state');
  state.passwordReady = setup.authentication?.password_configured === true;
  renderConnection();
  if (!state.passwordReady && !state.owner) note('Ask the workspace owner to set the Linux password before activating an agent.');
  if (state.passwordReady) await refresh();
  if (!state.rfb) connectDesktop();
}
async function ensureConversation() {
  if (state.conversation) return state.conversation;
  if (!$('project-select').checkValidity()) { $('project-select').reportValidity(); throw new Error('Select an existing project folder.'); }
  const provider = state.provider, model = $('model-select').value, project = $('project-select').value;
  const id = uuid(); const generation = state.conversationGeneration;
  state.creating = true; renderTurnControls();
  try {
    // Retain the ID even if the creation reply is lost. Never create a replacement
    // conversation or submit a message automatically after uncertain delivery.
    const placeholder = {id, provider, model, project, status:'creating', operations:[], created_at:Date.now()};
    state.conversation = placeholder;
    const result = await call('createProviderConversation', {id, provider, project, model});
    if (generation !== state.conversationGeneration) throw new Error('Conversation changed; no message was submitted.');
    state.conversation = result.conversation;
    for (let attempt=0; attempt<30 && state.conversation.status === 'creating'; attempt++) {
      await new Promise(resolve => setTimeout(resolve,500)); await readConversation();
      if (generation !== state.conversationGeneration) throw new Error('Conversation changed; no message was submitted.');
    }
    if (state.conversation.status !== 'idle') throw new Error('Conversation creation is not confirmed. Inspect it before continuing.');
    return state.conversation;
  } finally { state.creating = false; renderProvider(); }
}

$('agent-toggle').addEventListener('click', () => setOpen(!state.open));
$('agent-close').addEventListener('click', () => setOpen(false));
$('agent-panel').addEventListener('focusin', () => state.rfb?.blur());
$('agent-panel').addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setOpen(false); } });
$('credential-form').addEventListener('submit', async event => {
  event.preventDefault(); let credential = $('workspace-credential').value.trim(); $('workspace-credential').value = '';
  const button = event.submitter; button.disabled = true;
  try { await request('/auth/session', {method:'POST', headers:{Authorization:`Bearer ${credential}`}}); credential = ''; note(''); await setupSession(); }
  catch (error) { note(error.message); } finally { credential = ''; button.disabled = false; }
});
$('password-form').addEventListener('submit', async event => {
  event.preventDefault(); let password = $('linux-password').value, confirmation = $('linux-confirmation').value;
  const length = new TextEncoder().encode(password).length;
  if (password !== confirmation || length < 12 || length > 256 || /[\u0000-\u001f\u007f]/u.test(password) || !password.trim()) { note('Use matching passwords containing 12 to 256 bytes, without control characters.'); return; }
  $('linux-password').value = ''; $('linux-confirmation').value = ''; event.submitter.disabled = true;
  try { await request('/setup/api/password', {method:'POST',input:{password,confirmation}}); password = ''; confirmation = ''; note(''); await setupSession(); }
  catch (error) { note(error.message); } finally { password = ''; confirmation = ''; event.submitter.disabled = false; }
});
$('provider-select').addEventListener('change', () => { state.provider = $('provider-select').value; chooseConversation(null); $('message-input').value = ''; refresh().catch(error => note(error.message)); });
$('model-select').addEventListener('change', renderTurnControls);
$('new-conversation').addEventListener('click', () => { chooseConversation(null); $('message-input').value = ''; $('provider-setup').open = true; });
$('conversation-select').addEventListener('change', () => { chooseConversation(state.conversations.find(c => c.id === $('conversation-select').value) || null); $('message-input').value = ''; refresh().catch(error => note(error.message)); });
for (const [buttonID, capability] of [['provider-activate','activateProvider'],['provider-stop','stopProvider'],['provider-open','openProviderApp']]) {
  $(buttonID).addEventListener('click', async () => {
    $(buttonID).disabled = true;
    try { await call(capability,{provider:state.provider}); note(capability === 'openProviderApp' ? 'Complete sign-in in the desktop application, then refresh status. No login details go into this chat.' : ''); await refresh(); }
    catch(error) { note(error.message); } finally { $(buttonID).disabled = false; renderProvider(); }
  });
}
$('provider-refresh').addEventListener('click', () => { note(''); refresh().catch(error => note(error.message)); });
$('message-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.submitting || state.creating || activeOperation()) return;
  const prompt = $('message-input').value;
  if (!prompt.trim() || new TextEncoder().encode(prompt).length > 64*1024) { note('Enter a message of at most 64 KiB.'); return; }
  state.submitting = true; renderTurnControls(); note('');
  try {
    const conversation = await ensureConversation(); const operation = uuid();
    $('message-input').value = ''; appendMessage('user',prompt,operation);
    // A network failure never resubmits or restores the prompt to a Send button.
    await call('submitProviderMessage',{conversation:conversation.id,operation_id:operation,prompt});
    $('provider-setup').open = false; await readConversation();
  } catch(error) { note(error.message + ' No message was automatically resent.'); }
  finally { state.submitting = false; renderTurnControls(); }
});
$('stop-turn').addEventListener('click', async () => {
  const conversation = state.conversation, op = activeOperation(); if (!op) return;
  $('stop-turn').disabled = true;
  try { await call('interruptProviderTurn',{conversation:conversation.id,operation_id:op.id}); await readConversation(); }
  catch(error) { note(error.message); } finally { renderTurnControls(); }
});
$('disconnect-workspace').addEventListener('click', async () => {
  try { await request('/auth/session',{method:'DELETE'}); } catch(error) { note(error.message); return; }
  state.csrf = ''; state.connected = false; state.owner = false; chooseConversation(null); $('message-input').value = '';
  const rfb = state.rfb; state.rfb = null; rfb?.disconnect(); renderConnection();
});
function desktopStatus(kind, message) {
  $('connection-status').dataset.state = kind; $('connection-status').textContent = message;
  $('connection-panel').hidden = kind === 'connected'; $('connection-message').textContent = message;
}
function stopDesktop(message) {
  state.blocked = true; clearTimeout(state.retryTimer);
  const rfb = state.rfb; state.rfb = null; rfb?.disconnect(); desktopStatus('failed',message);
}
function connectDesktop(manual=false) {
  clearTimeout(state.retryTimer);
  if (manual) { state.hasConnected=false; state.retry=0; state.blocked=false; }
  if (!state.connected || state.blocked || !navigator.onLine) return;
  const previous=state.rfb; state.rfb=null; previous?.disconnect(); $('screen').replaceChildren();
  const url=new URL('/vnc/websockify',location.href); url.protocol=location.protocol==='https:'?'wss:':'ws:';
  desktopStatus('connecting','Connecting to the desktop…');
  let rfb;
  try { rfb=new RFB($('screen'),url.href,{shared:true}); } catch { stopDesktop('Desktop connection failed. Open the agent for connection help.'); return; }
  state.rfb=rfb; rfb.scaleViewport=true; rfb.resizeSession=false; rfb.qualityLevel=7; rfb.compressionLevel=2; rfb.focusOnClick=true; rfb.showDotCursor=true;
  rfb.addEventListener('connect',()=>{ if(state.rfb!==rfb)return; state.hasConnected=true;state.retry=0;desktopStatus('connected','Desktop connected');if(!state.open)rfb.focus(); });
  rfb.addEventListener('disconnect',event=>{
    if(state.rfb!==rfb)return;state.rfb=null;
    if(!state.hasConnected || state.retry>=RETRY_DELAYS.length || event.detail?.clean){ desktopStatus('disconnected','Desktop disconnected. Open the agent for connection help.');return; }
    desktopStatus('reconnecting','Reconnecting to the desktop…');state.retryTimer=setTimeout(()=>connectDesktop(),RETRY_DELAYS[state.retry++]);
  });
  rfb.addEventListener('securityfailure',()=>stopDesktop('Desktop security check failed. Ask the operator to inspect the service.'));
  rfb.addEventListener('credentialsrequired',()=>stopDesktop('Unexpected native VNC authentication. Ask the operator to inspect the service.'));
  rfb.addEventListener('serververification',()=>stopDesktop('Desktop identity requires verification. Ask the operator to inspect the service.'));
}
$('desktop-reconnect').addEventListener('click',()=>connectDesktop(true));
window.addEventListener('online',()=>{if(state.hasConnected&&!state.rfb)connectDesktop();});
window.addEventListener('pagehide',()=>{clearTimeout(state.retryTimer);const rfb=state.rfb;state.rfb=null;rfb?.disconnect();});
async function poll() {
  try { if(state.connected && state.passwordReady && (state.open || activeOperation() || ['probing','installing','starting'].includes(currentProvider()?.phase)))await refresh(); } catch(error) { if(state.open)note(error.message); }
  setTimeout(poll,2000);
}
setupSession().catch(error=>{note(error.message);renderConnection();}).finally(()=>poll());
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js',{scope:'/'}).catch(()=>{});
