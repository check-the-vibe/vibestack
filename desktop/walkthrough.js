/* Opt-in diagnostics: no form values, body contents, query strings or raw errors. */
(() => {
  'use strict';
  try {
    const toggle = new URL(location.href).searchParams.get('walkthrough');
    if (toggle === '1') sessionStorage.setItem('vibestack-walkthrough', '1');
    if (toggle === '0') sessionStorage.removeItem('vibestack-walkthrough');
    if (sessionStorage.getItem('vibestack-walkthrough') !== '1') return;
    const session = sessionStorage.getItem('vibestack-walkthrough-session') || crypto.randomUUID().replaceAll('-', '');
    sessionStorage.setItem('vibestack-walkthrough-session', session);
    let seq = Number(sessionStorage.getItem('vibestack-walkthrough-seq') || 0);
    const nativeFetch = window.fetch.bind(window);
    const csrfReady = nativeFetch('/auth/session', {credentials:'same-origin',cache:'no-store'})
      .then(response => response.ok ? response.json() : null)
      .then(value => typeof value?.csrf === 'string' ? value.csrf : '')
      .catch(() => '');
    const targets = new Set(["agent-client-error", "agent-clients", "agent-connect", "agent-connect-command", "agent-connect-title", "agent-install-command", "agent-pairings", "app-shell", "auto-resize-toggle", "btn-change-password", "btn-copy-agent", "btn-install", "btn-more", "btn-password-cancel", "btn-password-save", "btn-refresh-clients", "btn-skip", "cad-button", "clipboard-button", "clipboard-clear", "clipboard-copy", "clipboard-dialog", "clipboard-send", "clipboard-text", "clipboard-title", "compression-heading", "compression-output", "compression-range", "connection-action", "connection-heading", "connection-label", "connection-message", "connection-panel", "connection-pill", "connection-title", "count", "desktop-name", "desktop-stage", "desktop-view-tab", "disconnect-button", "display-apply", "display-heading", "display-note", "display-select", "done-title", "editor-description", "error-text", "focus-button", "fullscreen-button", "groups", "i-chevron", "i-clipboard", "i-close", "i-desktop", "i-external", "i-focus", "i-fullscreen", "i-keyboard", "i-refresh", "i-settings", "i-terminal", "i-tools", "input-controls-button", "input-controls-panel", "install-note", "install-title", "keyboard-button", "launch-editor", "linux-password", "linux-password-confirmation", "log", "log-more", "log-output", "log-refresh", "log-service", "log-status", "logs-heading", "match-screen-button", "next-steps", "password-description", "password-error", "password-eyebrow", "password-form", "password-title", "password-trust-note", "presets", "quality-heading", "quality-output", "quality-range", "readiness-label", "reconnect-toggle", "render-profile", "render-profile-heading", "scale-heading", "screen", "service-list", "services-heading", "settings-button", "settings-connection-note", "settings-dialog", "settings-title", "size", "skip-link", "status-disk", "status-refresh", "status-resolution", "status-uptime", "step-choose", "step-done", "step-error", "step-install", "step-password", "subtitle", "terminal-frame", "terminal-stage", "terminal-view-tab", "toast-region", "tools-button", "tools-dialog", "tools-title", "view-only-toggle", "virtual-keyboard"]);
    const routes = new Set(['/', '/setup/', '/vnc/', '/setup/api/state', '/setup/api/catalog', '/setup/api/install', '/setup/api/password', '/setup/api/log', '/setup/api/skip', '/api/v1/status', '/api/v1/display', '/api/v1/automation', '/vnc/websockify', '/terminal/ws', '/terminal/', '/editor/']);
    const page = ['/','/setup/','/vnc/'].includes(location.pathname) ? location.pathname : 'other';
    const view = ['desktop','terminal','editor'].includes(new URL(location.href).searchParams.get('view')) ? new URL(location.href).searchParams.get('view') : 'other';
    const route = (value) => {
      try {
        const u = new URL(value, location.href);
        if (u.host !== location.host) return 'external';
        if (routes.has(u.pathname)) return u.pathname;
        if (/^\/api\/v1\/services\//.test(u.pathname)) return 'service-operation';
        if (/^\/api\/v1\/logs\//.test(u.pathname)) return 'service-log';
        if (u.pathname.includes('/pairing/')) return 'pairing';
        if (u.pathname.includes('/jobs/')) return 'job';
      } catch (_) { /* Ignore malformed/unavailable destinations. */ }
      return 'other';
    };
    let windowStart = Date.now(), count = 0;
    const emit = (kind, details = {}) => {
      if (Date.now() - windowStart > 10000) { windowStart = Date.now(); count = 0; }
      if (++count > 100) return;
      seq += 1;
      try { sessionStorage.setItem('vibestack-walkthrough-seq', String(seq)); } catch (_) { /* Logging must never break UI. */ }
      const data = {session, seq, kind, page, view, time_ms:Date.now(), ...details};
      csrfReady.then(csrf => {
        if (!csrf) return;
        return nativeFetch('/api/v1/diagnostics/events', {method:'POST',headers:{'Content-Type':'application/json','X-VibeStack-CSRF':csrf},body:JSON.stringify(data),keepalive:true,cache:'no-store'});
      }).catch(() => {});
    };
    const action = (element) => targets.has(element?.id) ? element.id : ({BUTTON:'button', A:'link', FORM:'form', INPUT:'input', SELECT:'select'}[element?.tagName] || 'other');
    emit('page');
    document.addEventListener('DOMContentLoaded', () => {
      let previous = '';
      const steps = ['password','choose','install','done','error'];
      const observe = () => {
        const step = steps.find(id => { const el=document.getElementById('step-'+id); return el && !el.hidden; });
        if (step && step !== previous) { previous=step; emit('step',{step}); }
      };
      const observer = new MutationObserver(observe);
      for (const step of steps) { const el=document.getElementById('step-'+step); if (el) observer.observe(el,{attributes:true,attributeFilter:['hidden']}); }
      observe();
      for (const panel of ['apps','settings','tools','clipboard']) {
        const dialog = document.getElementById(panel+'-dialog');
        if (dialog) new MutationObserver(() => emit('panel',{panel,visible:dialog.open?'visible':'hidden'})).observe(dialog,{attributes:true,attributeFilter:['open']});
      }
    });
    document.addEventListener('click', e => { const target=e.target.closest?.('button,a,input[type=checkbox],input[type=radio]'); if(target) emit('click',{action:action(target)}); }, true);
    document.addEventListener('submit', e => emit('submit',{action:action(e.target)}), true);
    document.addEventListener('visibilitychange', () => emit('visibility',{visible:document.visibilityState}));
    for (const kind of ['online','offline']) window.addEventListener(kind, () => emit(kind));
    window.addEventListener('error', e => {
      if (e.target !== window) { emit('resource_error'); return; }
      const name = e.error?.name;
      emit('script_error',{error:['Error','TypeError','SyntaxError','ReferenceError','RangeError','URIError','EvalError'].includes(name)?name:'other',line:Math.max(0,e.lineno||0),column:Math.max(0,e.colno||0)});
    }, true);
    window.addEventListener('unhandledrejection', () => emit('promise_error',{error:'other'}));
    window.fetch = async (...args) => {
      const start=performance.now();
      const endpoint=route(typeof args[0]==='string' || args[0] instanceof URL ? args[0] : args[0]?.url);
      const rawMethod=String(args[1]?.method || args[0]?.method || 'GET').toUpperCase();
      const method=['GET','POST','PUT','DELETE','HEAD','PATCH'].includes(rawMethod)?rawMethod:'other';
      try {
        const response=await nativeFetch(...args);
        emit('request',{endpoint,method,status:response.status,duration_ms:Math.round(performance.now()-start)});
        return response;
      } catch(error) {
        emit('request_error',{endpoint,method,duration_ms:Math.round(performance.now()-start)});
        throw error;
      }
    };
    const NativeSocket=window.WebSocket;
    // Keep the native instance/prototype: noVNC checks own prototype methods.
    window.WebSocket=new Proxy(NativeSocket, {
      construct(target,args,newTarget) {
        const socket=Reflect.construct(target,args,newTarget);
        try {
          const endpoint=route(args[0]);
          socket.addEventListener('open',()=>emit('socket_open',{endpoint}));
          socket.addEventListener('error',()=>emit('socket_error',{endpoint}));
          socket.addEventListener('close',e=>emit('socket_close',{endpoint,socket_code:e.code}));
        } catch (_) { /* A logging failure must not prevent the connection. */ }
        return socket;
      }
    });
  } catch (_) { /* Diagnostics are best-effort and must not block onboarding. */ }
})();
