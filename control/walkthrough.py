"""Bounded, metadata-only browser diagnostics for opt-in manual walkthroughs."""
import datetime
import json
import re
import threading
import time

EVENTS = {'page', 'panel', 'step', 'click', 'submit', 'request', 'request_error', 'script_error', 'resource_error', 'promise_error', 'visibility', 'online', 'offline', 'socket_open', 'socket_close', 'socket_error'}
PAGES = {'/', '/setup/', '/vnc/', 'other'}
ROUTES = {'/', '/setup/', '/vnc/', '/setup/api/state', '/setup/api/catalog', '/setup/api/install', '/setup/api/password', '/setup/api/log', '/setup/api/skip', '/api/v1/status', '/api/v1/display', '/api/v1/automation', '/vnc/websockify', '/terminal/ws', '/terminal/', '/editor/', 'other', 'external', 'service-operation', 'service-log', 'pairing', 'job'}
ERRORS = {'Error', 'TypeError', 'SyntaxError', 'ReferenceError', 'RangeError', 'URIError', 'EvalError', 'other'}
TARGETS = {'button', 'link', 'form', 'input', 'select', 'other'}
# Fixed product IDs only; caller text and input values are never accepted.
TARGETS.update(['agent-client-error', 'agent-clients', 'agent-connect', 'agent-connect-command', 'agent-connect-title', 'agent-install-command', 'agent-pairings', 'app-shell', 'auto-resize-toggle', 'btn-change-password', 'btn-copy-agent', 'btn-install', 'btn-more', 'btn-password-cancel', 'btn-password-save', 'btn-refresh-clients', 'btn-skip', 'cad-button', 'clipboard-button', 'clipboard-clear', 'clipboard-copy', 'clipboard-dialog', 'clipboard-send', 'clipboard-text', 'clipboard-title', 'compression-heading', 'compression-output', 'compression-range', 'connection-action', 'connection-heading', 'connection-label', 'connection-message', 'connection-panel', 'connection-pill', 'connection-title', 'count', 'desktop-name', 'desktop-stage', 'desktop-view-tab', 'disconnect-button', 'display-apply', 'display-heading', 'display-note', 'display-select', 'done-title', 'editor-description', 'error-text', 'focus-button', 'fullscreen-button', 'groups', 'i-chevron', 'i-clipboard', 'i-close', 'i-desktop', 'i-external', 'i-focus', 'i-fullscreen', 'i-keyboard', 'i-refresh', 'i-settings', 'i-terminal', 'i-tools', 'input-controls-button', 'input-controls-panel', 'install-note', 'install-title', 'keyboard-button', 'launch-editor', 'linux-password', 'linux-password-confirmation', 'log', 'log-more', 'log-output', 'log-refresh', 'log-service', 'log-status', 'logs-heading', 'match-screen-button', 'next-steps', 'password-description', 'password-error', 'password-eyebrow', 'password-form', 'password-title', 'password-trust-note', 'presets', 'quality-heading', 'quality-output', 'quality-range', 'readiness-label', 'reconnect-toggle', 'render-profile', 'render-profile-heading', 'scale-heading', 'screen', 'service-list', 'services-heading', 'settings-button', 'settings-connection-note', 'settings-dialog', 'settings-title', 'size', 'skip-link', 'status-disk', 'status-refresh', 'status-resolution', 'status-uptime', 'step-choose', 'step-done', 'step-error', 'step-install', 'step-password', 'subtitle', 'terminal-frame', 'terminal-stage', 'terminal-view-tab', 'toast-region', 'tools-button', 'tools-dialog', 'tools-title', 'view-only-toggle', 'virtual-keyboard'])
_lock = threading.Lock()
_window = 0.0
_count = 0


def validate(body):
    if not isinstance(body, dict) or set(body) - {'session', 'seq', 'kind', 'page', 'view', 'action', 'endpoint', 'method', 'status', 'duration_ms', 'error', 'line', 'column', 'visible', 'time_ms', 'socket_code', 'step', 'panel'}:
        raise ValueError('invalid diagnostic fields')
    if not {'session', 'seq', 'kind', 'page'} <= set(body):
        raise ValueError('missing diagnostic fields')
    if not isinstance(body['session'], str) or not re.fullmatch(r'[a-f0-9]{32}', body['session']):
        raise ValueError('invalid session')
    enums = {'panel':{'apps','settings','tools','clipboard'}, 'step':{'password','choose','install','done','error'}, 'kind':EVENTS, 'page':PAGES, 'view':{'desktop','terminal','editor','other'}, 'action':TARGETS, 'endpoint':ROUTES, 'method':{'GET','POST','PUT','DELETE','HEAD','PATCH','other'}, 'error':ERRORS, 'visible':{'visible','hidden'}}
    for key, allowed in enums.items():
        if key in body and (not isinstance(body[key], str) or body[key] not in allowed):
            raise ValueError('invalid diagnostic value')
    for key, maximum in {'seq':10**9, 'status':599, 'duration_ms':86400000, 'line':10**7, 'column':10**7, 'time_ms':10**14, 'socket_code':4999}.items():
        if key in body and (type(body[key]) is not int or not 0 <= body[key] <= maximum):
            raise ValueError('invalid diagnostic number')
    return dict(body)


def record(body):
    value = validate(body)
    global _window, _count
    with _lock:
        now = time.monotonic()
        if now - _window >= 10:
            _window, _count = now, 0
        if _count >= 200:
            return False
        _count += 1
        value.update(source='walkthrough', timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat())
        # Supervisor owns/rotates the canonical control service log (10 MiB x 4).
        print(json.dumps(value, separators=(',', ':')), flush=True)
    return True
