import { expect, test } from './fixtures.mjs';

const FAKE_RFB_MODULE = `
export default class FakeRFB extends EventTarget {
  constructor(target, url, options) {
    super();
    this.target = target;
    this.url = url;
    this.options = options;
    this.calls = [];
    this.clipboard = [];
    this.disconnected = false;
    window.__rfbInstances ||= [];
    this.index = window.__rfbInstances.length;
    window.__rfbInstances.push(this);
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 400;
    target.append(canvas);
    queueMicrotask(() => {
      const mode = window.__rfbMode || 'connect';
      if (mode === 'initial-failure') {
        this.dispatchEvent(new CustomEvent('disconnect', { detail: { clean: false } }));
      } else if (mode === 'security-failure') {
        this.dispatchEvent(new CustomEvent('securityfailure', { detail: { reason: 'test rejection' } }));
      } else if (mode === 'drop-then-fail' && this.index > 0) {
        this.dispatchEvent(new CustomEvent('disconnect', { detail: { clean: false } }));
      } else {
        this.dispatchEvent(new CustomEvent('connect'));
      }
    });
  }
  disconnect() {
    this.disconnected = true;
    queueMicrotask(() => this.dispatchEvent(new CustomEvent('disconnect', { detail: { clean: true } })));
  }
  focus() { this.calls.push(['focus']); }
  blur() { this.calls.push(['blur']); }
  sendKey(...args) { this.calls.push(['sendKey', ...args]); }
  sendCtrlAltDel() { this.calls.push(['sendCtrlAltDel']); }
  clipboardPasteFrom(text) { this.clipboard.push(text); }
}
`;

async function useFakeRfb(page, mode = 'connect') {
  await page.addInitScript((selectedMode) => { window.__rfbMode = selectedMode; }, mode);
  await page.route('**/novnc/core/rfb.js', (route) => route.fulfill({
    status: 200,
    contentType: 'application/javascript',
    body: FAKE_RFB_MODULE,
  }));
}

async function openConnectedDesktop(page) {
  await page.goto('/vnc/', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveTitle(/VibeStack/);
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected', { timeout: 25_000 });
  await expect(page.locator('#screen canvas')).toBeVisible();
}

async function openInputControls(page) {
  const trigger = page.getByTestId('input-controls-toggle');
  const controls = page.getByTestId('input-controls-panel');
  if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect(controls).toBeVisible();
  return controls;
}

async function openSettings(page) {
  const controls = await openInputControls(page);
  await controls.getByTestId('open-settings').click();
  await expect(page.getByTestId('settings-drawer')).toHaveAttribute('open', '');
}

async function openTools(page) {
  const controls = await openInputControls(page);
  await controls.getByTestId('open-tools').click();
  await expect(page.getByTestId('tools-drawer')).toHaveAttribute('open', '');
}

async function waitForWorker(page) {
  await page.waitForFunction(() => Boolean(navigator.serviceWorker?.controller), null, { timeout: 20_000 });
  return page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
}

test('custom shell connects and its unified menu settings/tools contracts work', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await openConnectedDesktop(page);
  await expect(page.locator('#noVNC_control_bar')).toHaveCount(0);
  await expect(page.getByTestId('connection-panel')).toBeHidden();

  const manifest = await page.evaluate(async () => (await fetch('/manifest.webmanifest')).json());
  expect(manifest).toMatchObject({ start_url: '/', scope: '/', display: 'standalone' });
  expect(await waitForWorker(page)).toMatch(/\/$/);

  await openSettings(page);
  await page.getByRole('button', { name: 'Close settings' }).press('Escape');
  await expect(page.getByTestId('settings-drawer')).not.toHaveAttribute('open', '');
  await expect(page.getByTestId('input-controls-toggle')).toBeFocused();
  await openSettings(page);
  for (const resolution of ['1280x800', '1368x768', '1440x900', '1600x900', '1600x1200', '1920x1200']) {
    await expect(page.locator(`#display-select option[value="${resolution}"]`)).toHaveCount(1);
  }
  await expect(page.locator('#display-note')).toContainText('Current desktop:');

  await page.locator('#render-profile').selectOption('clarity');
  await expect(page.locator('#quality-range')).toHaveValue('9');
  await expect(page.locator('#compression-range')).toHaveValue('2');

  await page.locator('input[name="scale"][value="actual"]').check();
  await page.locator('#quality-range').evaluate((input) => {
    input.value = '8';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('vibestack.desktop.preferences.v1')))).toMatchObject({
    scaleMode: 'actual',
    qualityLevel: 8,
    compressionLevel: 2,
    viewOnly: false,
    reconnect: true,
  });
  await page.getByRole('button', { name: 'Close settings' }).click();

  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected', { timeout: 25_000 });
  await openSettings(page);
  await expect(page.locator('input[name="scale"][value="actual"]')).toBeChecked();
  await expect(page.locator('#quality-range')).toHaveValue('8');
  await page.getByRole('button', { name: 'Close settings' }).click();

  await openTools(page);
  await expect(page.locator('.service-row')).toHaveCount(7);
  await expect(page.locator('#status-uptime')).not.toHaveText('—');
  await expect(page.locator('#status-disk')).not.toHaveText('—');
  await expect(page.locator('#status-resolution')).toHaveText(/^\d+x\d+$/);

  await page.locator('#log-refresh').click();
  await expect(page.locator('#log-status')).toContainText(/Log is up to date|Showing the newest bounded log page/);

  let mutationRequests = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/api/v1/services/')) mutationRequests += 1;
  });
  page.once('dialog', async (dialog) => {
    expect(dialog.type()).toBe('confirm');
    expect(dialog.message()).toContain('Restart VNC');
    await dialog.dismiss();
  });
  await page.getByRole('button', { name: 'Restart VNC' }).click();
  expect(mutationRequests).toBe(0);

  expect(pageErrors).toEqual([]);
});

test('Desktop landing switches to full-screen Terminal and returns', async ({ page }) => {
  await useFakeRfb(page);
  await page.route('**/setup/api/state', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({authentication:{password_configured:true}})}));
  await page.route('**/terminal/', route => route.fulfill({status:200,contentType:'text/html',body:'<main>Persistent test terminal</main>'}));
  await page.goto('/');
  await expect(page).toHaveURL(/\/vnc\/$/);
  await expect(page.getByTestId('desktop-stage')).toBeVisible();
  await page.getByTestId('terminal-view-tab').click();
  await expect(page.getByTestId('terminal-stage')).toBeVisible();
  await expect(page.getByTestId('desktop-stage')).toBeHidden();
  await expect(page.getByTestId('terminal-frame').contentFrame().getByText('Persistent test terminal')).toBeVisible();
  await page.locator('#workspace-back').click();
  await expect(page.getByTestId('desktop-stage')).toBeVisible();
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','connected');
});

test('fresh launcher requires password onboarding and the form clears submitted secrets', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const emptyState = {
    catalog: { version: 1, groups: [], presets: [], components: [] },
    architecture: 'amd64',
    installed: [],
    state: { completed: false, selected: [] },
    state_valid: true,
    state_error: null,
    job: { running: false, phase: 'idle', length: 0, available_from: 0 },
    missing: [],
    unknown_selected: [],
    unsupported_selected: [],
    authentication: { password_configured: false, sudo_password_required: true },
  };
  await page.route('**/setup/api/state', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(emptyState),
  }));
  let submitted = null;
  await page.route('**/setup/api/password', async (route) => {
    submitted = route.request().postDataJSON();
    emptyState.authentication.password_configured = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        authentication: { password_configured: true, sudo_password_required: true },
      }),
    });
  });

  await page.goto('/');
  await expect(page).toHaveURL(/\/setup\/\?force=1$/);
  await expect(page.getByRole('heading', { name: 'Create your Linux password' })).toBeVisible();
  const password = page.locator('#linux-password');
  const confirmation = page.locator('#linux-password-confirmation');
  await expect(password).toHaveAttribute('autocomplete', 'new-password');
  await password.fill('too short');
  await confirmation.fill('different');
  await page.getByRole('button', { name: 'Save password' }).click();
  await expect(page.locator('#password-error')).toContainText('do not match');
  expect(submitted).toBeNull();

  const browserOnlyPassword = `Browser acceptance ${Date.now()}!`;
  await password.fill(browserOnlyPassword);
  await confirmation.fill(browserOnlyPassword);
  await page.getByRole('button', { name: 'Save password' }).click();
  await expect(page).toHaveURL(/\/vnc\/\?panel=apps$/);
  await expect(page.locator('#apps-dialog')).toBeVisible();
  expect(submitted).toEqual({ password: browserOnlyPassword, confirmation: browserOnlyPassword });
  await expect(password).toHaveCount(0);
  await expect(confirmation).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('Editor opens full-screen within the Desktop workspace', async ({ page }) => {
  await page.route('**/setup/api/state', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      state_valid: true,
      state: { completed: true },
      authentication: { password_configured: true, sudo_password_required: true },
    }),
  }));
  await page.route('**/api/v1/status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      services: Object.fromEntries(
        ['desktop', 'vnc', 'terminal', 'setup', 'ssh', 'native-vnc', 'editor'].map((name) => [name, { state: 'RUNNING' }]),
      ),
    }),
  }));

  await page.goto('/');
  await page.getByRole('tab',{name:'Editor',exact:true}).click();
  await expect(page.locator('#editor-frame')).toHaveAttribute('src','/editor/');
  await expect(page.locator('#editor-stage')).toBeVisible();
  await page.locator('#workspace-back').click();
  await expect(page.getByTestId('desktop-stage')).toBeVisible();
});

test('Connect your agent is secret-free and can approve and revoke individual clients', async ({ page }) => {
  const statePayload = {
    catalog: { version: 1, groups: [], presets: [], components: [] },
    architecture: 'amd64',
    installed: [],
    state: { completed: true, selected: [] },
    state_valid: true,
    state_error: null,
    job: { running: false, phase: 'idle', length: 0, available_from: 0 },
    missing: [],
    unknown_selected: [],
    unsupported_selected: [],
    authentication: { password_configured: true, sudo_password_required: true },
  };
  let approved = false;
  let revoked = false;
  await page.route('**/setup/api/state', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(statePayload),
  }));
  await page.route('**/setup/api/clients', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      pending: approved ? [] : [{
        pairing_id: '1'.repeat(32),
        verification_code: 'ABCD-2345',
        device_label: 'Claude on laptop',
        permissions: ['workspace'],
        expires_at: '2099-01-01T00:00:00Z',
      }],
      clients: approved && !revoked ? [{
        client_id: '2'.repeat(32),
        device_label: 'Claude on laptop',
        permissions: ['workspace'],
        created_at: '2099-01-01T00:00:00Z',
        revoked_at: '',
      }] : [],
    }),
  }));
  await page.route('**/setup/api/pairings/ABCD-2345/approve', async (route) => {
    approved = true;
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"pairing":{"status":"approved"}}' });
  });
  await page.route(`**/setup/api/clients/${'2'.repeat(32)}/revoke`, async (route) => {
    revoked = true;
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"client":{"revoked":true}}' });
  });

  await page.goto('/setup/?force=1');
  await expect(page.getByRole('heading', { name: 'Connect your agent' })).toBeVisible();
  const commands = await page.locator('#agent-connect').locator('pre').allTextContents();
  expect(commands.join('\n')).toContain('/cli.sh');
  expect(commands.join('\n')).toContain('--version 0.2.0');
  expect(commands.join('\n')).not.toMatch(/credential|bearer|token/i);

  await expect(page.getByText(/ABCD-2345.*Claude on laptop/)).toBeVisible();
  await page.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText('Claude on laptop — workspace')).toBeVisible();
  await page.getByRole('button', { name: 'Revoke' }).click();
  await expect(page.getByText('No active clients.')).toBeVisible();
  expect({ approved, revoked }).toEqual({ approved: true, revoked: true });
});

test('cached shell gives a truthful offline launch', async ({ page, context }) => {
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await openConnectedDesktop(page);
  await waitForWorker(page);

  await context.setOffline(true);
  try {
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('desktop-toolbar')).toBeVisible();
    await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'offline');
    await expect(page.getByTestId('connection-panel')).toContainText(/offline|Reconnect to the network/i);
    expect(pageErrors).toEqual([]);
  } finally {
    await context.setOffline(false);
  }
});

test('initial and security failures require a manual retry without a loop', async ({ page }) => {
  await useFakeRfb(page, 'initial-failure');
  await page.goto('/vnc/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'failed');
  await expect(page.getByTestId('connection-panel')).toContainText('try again');
  await page.waitForTimeout(1_250);
  expect(await page.evaluate(() => window.__rfbInstances.length)).toBe(1);
});

test('security failure never retries', async ({ page }) => {
  await useFakeRfb(page, 'security-failure');
  await page.goto('/vnc/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'failed');
  await expect(page.getByTestId('connection-panel')).toContainText('test rejection');
  await page.waitForTimeout(1_250);
  expect(await page.evaluate(() => window.__rfbInstances.length)).toBe(1);
});

test('an established session uses five bounded reconnect attempts', async ({ page }) => {
  await useFakeRfb(page, 'drop-then-fail');
  await page.clock.install();
  await page.goto('/vnc/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected');
  await page.evaluate(() => window.__rfbInstances[0].dispatchEvent(new CustomEvent('disconnect', { detail: { clean: false } })));
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'reconnecting');
  await page.clock.runFor(26_000);
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'failed');
  await expect(page.getByTestId('connection-panel')).toContainText('stopped after five attempts');
  expect(await page.evaluate(() => window.__rfbInstances.length)).toBe(6);
});

test('keyboard, modifiers, clipboard and view-only use the RFB adapter', async ({ page }) => {
  await useFakeRfb(page);
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText(text) {
          window.__browserClipboard = text;
          return Promise.resolve();
        },
      },
    });
  });
  await page.goto('/vnc/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected');

  await openInputControls(page);

  await page.getByRole('button', { name: 'Keyboard', exact: true }).click();
  await page.locator('#virtual-keyboard').pressSequentially('A');
  await page.locator('#virtual-keyboard').press('Backspace');
  await openInputControls(page);
  await page.getByRole('button', { name: 'Ctrl', exact: true }).click();
  await page.getByRole('button', { name: 'Ctrl', exact: true }).click();
  await openInputControls(page);
  await page.getByRole('button', { name: 'Ctrl Alt Del', exact: true }).click();

  await page.evaluate(() => {
    const input = document.querySelector('#virtual-keyboard');
    input.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
    input.value += '漢';
    input.dispatchEvent(new InputEvent('input', { bubbles: true, data: '漢', inputType: 'insertCompositionText', isComposing: true }));
    input.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '漢' }));
  });

  await page.evaluate(() => window.__rfbInstances[0].dispatchEvent(new CustomEvent('clipboard', { detail: { text: 'hello from Linux' } })));
  await openInputControls(page);
  await page.getByRole('button', { name: 'Clipboard', exact: true }).click();
  await expect(page.locator('#clipboard-text')).toHaveValue('hello from Linux');
  await page.getByRole('button', { name: 'Copy to this device' }).click();
  expect(await page.evaluate(() => window.__browserClipboard)).toBe('hello from Linux');
  await page.locator('#clipboard-text').fill('hello from the shell');
  await page.getByRole('button', { name: 'Send to desktop' }).click();

  const adapter = await page.evaluate(() => ({
    calls: window.__rfbInstances[0].calls,
    clipboard: window.__rfbInstances[0].clipboard,
  }));
  expect(adapter.calls.some((call) => call[0] === 'sendKey' && call[1] === 65)).toBe(true);
  expect(adapter.calls).toContainEqual(['sendKey', 0xff08, 'Backspace', true]);
  expect(adapter.calls).toContainEqual(['sendKey', 0xff08, 'Backspace', false]);
  expect(adapter.calls).toContainEqual(['sendKey', 0xffe3, 'ControlLeft', true]);
  expect(adapter.calls).toContainEqual(['sendKey', 0xffe3, 'ControlLeft', false]);
  expect(adapter.calls.some((call) => call[0] === 'sendKey' && call[1] === (0x01000000 | '漢'.codePointAt(0)))).toBe(true);
  expect(adapter.calls).toContainEqual(['sendCtrlAltDel']);
  expect(adapter.clipboard).toEqual(['hello from the shell']);

  await openSettings(page);
  await page.locator('#view-only-toggle').check();
  await page.getByRole('button', { name: 'Close settings' }).click();
  const before = await page.evaluate(() => window.__rfbInstances[0].calls.length);
  await openInputControls(page);
  await page.getByRole('button', { name: 'Keyboard', exact: true }).click();
  await page.locator('#virtual-keyboard').pressSequentially('B');
  expect(await page.evaluate(() => window.__rfbInstances[0].calls.length)).toBe(before);
});

test('one accessible topbar menu contains input, display, settings and tools controls', async ({ page }) => {
  await useFakeRfb(page);
  await page.goto('/vnc/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected');

  const toolbar = page.getByTestId('desktop-toolbar');
  const trigger = page.getByTestId('input-controls-toggle');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');

  const controlledId = await trigger.getAttribute('aria-controls');
  expect(controlledId).toBeTruthy();
  const controls = page.getByTestId('input-controls-panel');
  await expect(controls).toHaveCount(1);
  await expect(controls).toBeHidden();
  await expect(toolbar.locator('#input-controls-button')).toHaveCount(1);

  // The desktop stage must no longer contain a persistent bottom control dock.
  await expect(page.locator('.touch-dock')).toHaveCount(0);
  await expect(page.getByTestId('desktop-stage').locator(`#${controlledId}`)).toHaveCount(0);

  await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect(controls).toBeVisible();
  await expect(toolbar.locator('.top-actions #settings-button')).toHaveCount(0);
  await expect(toolbar.locator('.top-actions #tools-button')).toHaveCount(0);
  for (const name of ['Keyboard', 'Clipboard', 'Ctrl', 'Alt', 'Super', 'Ctrl Alt Del', 'Match screen', 'Settings', 'Tools']) {
    await expect(controls.getByRole('button', { name, exact: true })).toBeVisible();
  }

  const keyboardControl = controls.locator('#keyboard-button');
  await keyboardControl.click();
  await expect(page.locator('#virtual-keyboard')).toBeFocused();
  await expect(keyboardControl).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Escape');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(controls).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(keyboardControl).toHaveAttribute('aria-pressed', 'false');

  await trigger.click();
  await expect(controls).toBeVisible();
  await trigger.click();
  await expect(controls).toBeHidden();
});

test('match-screen sizing is opt-in and derives bounded, orientation-preserving dimensions', async ({ page }) => {
  const availableResolutions = ['1280x800', '1368x768', '1440x900', '1600x900', '1600x1200', '1920x1200'];
  let currentResolution = '1920x1200';
  const displayRequests = [];
  let heldResolution = '';
  let heldPutGate = null;
  let heldPutStarted = null;

  await useFakeRfb(page);
  // The 58px desktop toolbar leaves a 1280x900 stage at this viewport.
  await page.setViewportSize({ width: 1280, height: 958 });
  await page.route('**/api/v1/display', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          apiVersion: '1',
          resolution: currentResolution,
          availableResolutions,
          supportedResolutions: availableResolutions,
        }),
      });
      return;
    }

    const payload = route.request().postDataJSON();
    displayRequests.push(payload);
    if (payload.resolution === heldResolution && heldPutGate) {
      heldPutStarted?.();
      await heldPutGate;
    }
    currentResolution = payload.resolution;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        apiVersion: '1',
        resolution: currentResolution,
        availableResolutions,
        supportedResolutions: availableResolutions,
      }),
    });
  });

  await page.goto('/vnc/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected');
  await openSettings(page);

  const matchScreen = page.locator('#auto-resize-toggle');
  await expect(matchScreen).toHaveAccessibleName(/match screen automatically/i);
  await expect(matchScreen).not.toBeChecked();
  await expect.poll(() => displayRequests.length).toBe(0);

  await matchScreen.check();
  await expect.poll(() => displayRequests.length).toBeGreaterThan(0);
  expect(displayRequests[0]).toEqual({ resolution: '1280x900' });

  await page.getByRole('button', { name: 'Close settings' }).click();
  await openInputControls(page);
  await page.getByRole('button', { name: 'Keyboard', exact: true }).click();
  await expect(page.locator('#virtual-keyboard')).toBeFocused();
  const requestsBeforeKeyboardResize = displayRequests.length;
  await page.setViewportSize({ width: 1280, height: 700 });
  await page.waitForTimeout(1_000);
  expect(displayRequests).toHaveLength(requestsBeforeKeyboardResize);
  await page.setViewportSize({ width: 1280, height: 958 });
  await page.locator('#virtual-keyboard').evaluate((input) => input.blur());

  await openInputControls(page);
  await page.getByRole('button', { name: 'Clipboard', exact: true }).click();
  await expect(page.locator('#clipboard-dialog')).toHaveAttribute('open', '');
  await expect(page.locator('#clipboard-text')).toBeFocused();
  const requestsBeforeClipboardResize = displayRequests.length;
  await page.setViewportSize({ width: 1280, height: 700 });
  await page.waitForTimeout(1_000);
  expect(displayRequests).toHaveLength(requestsBeforeClipboardResize);
  await page.setViewportSize({ width: 1280, height: 958 });
  await page.getByRole('button', { name: 'Close clipboard' }).click();

  // ResizeObserver/orientation bursts are trailing-debounced to the final stage.
  await page.setViewportSize({ width: 1000, height: 858 });
  await page.setViewportSize({ width: 1200, height: 858 });
  await expect.poll(() => displayRequests.some(({ resolution }) => resolution === '1200x800')).toBe(true);
  expect(displayRequests.some(({ resolution }) => resolution === '1000x800')).toBe(false);

  // The two-row navigation is 110px tall below 900px. A 768x1024 stage
  // keeps portrait orientation instead of falling back to a landscape preset.
  await page.setViewportSize({ width: 768, height: 1134 });
  await expect.poll(async () => (await page.getByTestId('desktop-stage').boundingBox()).height).toBe(1024);
  await expect.poll(() => displayRequests.some(({ resolution }) => resolution === '768x1024')).toBe(true);

  // A stage narrower than the 640px safety floor scales both axes together,
  // then aligns the width to 8px and height to 2px for XRandR.
  await page.setViewportSize({ width: 608, height: 1134 });
  await expect.poll(() => displayRequests.some(({ resolution }) => resolution === '640x1078')).toBe(true);

  // If the user chooses a fixed preset while an automatic PUT is in flight,
  // their explicit choice must be queued and win after the stale match returns.
  await expect(page.locator('#display-note')).toContainText('640x1078');
  let releaseHeldPut;
  heldResolution = '1368x768';
  heldPutGate = new Promise((resolve) => { releaseHeldPut = resolve; });
  const autoPutStarted = new Promise((resolve) => { heldPutStarted = resolve; });
  await page.setViewportSize({ width: 1368, height: 826 });
  await autoPutStarted;

  await openSettings(page);
  await expect(page.locator('#display-select option[value="1440x900"]')).toHaveCount(1);
  await page.locator('#display-select').selectOption('1440x900');
  await page.locator('#display-apply').click();
  await expect(page.locator('#display-note')).toContainText('Waiting to apply 1440x900');
  releaseHeldPut();
  await expect.poll(() => displayRequests.at(-1)?.resolution).toBe('1440x900');
  await expect(page.locator('#display-note')).toContainText('Desktop set to 1440x900');
  await expect(matchScreen).not.toBeChecked();
  await page.waitForTimeout(800);
  expect(displayRequests.at(-1)).toEqual({ resolution: '1440x900' });

  for (const payload of displayRequests) {
    expect(Object.keys(payload)).toEqual(['resolution']);
    const match = /^(\d+)x(\d+)$/.exec(payload.resolution);
    expect(match).toBeTruthy();
    const [, width, height] = match.map(Number);
    expect(width).toBeGreaterThanOrEqual(640);
    expect(width).toBeLessThanOrEqual(1920);
    expect(height).toBeGreaterThanOrEqual(480);
    expect(height).toBeLessThanOrEqual(1200);
    expect(width % 8).toBe(0);
    expect(height % 2).toBe(0);
  }
  for (let index = 1; index < displayRequests.length; index += 1) {
    expect(displayRequests[index].resolution).not.toBe(displayRequests[index - 1].resolution);
  }
});

test('a confirmed VNC restart retries an expected clean disconnect', async ({ page }) => {
  await useFakeRfb(page);
  await page.route('**/api/v1/services/vnc/restart', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ apiVersion: '1', service: 'vnc', state: 'RUNNING', restarted: true }),
  }));
  await page.goto('/vnc/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected');
  await openTools(page);
  await expect(page.locator('.service-row')).toHaveCount(7);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Restart VNC' }).click();
  await page.evaluate(() => window.__rfbInstances[0].dispatchEvent(new CustomEvent('disconnect', { detail: { clean: true } })));
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'reconnecting');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected', { timeout: 5_000 });
  expect(await page.evaluate(() => window.__rfbInstances.length)).toBe(2);
});

test('confirmed VNC restart recovers the live desktop session', async ({ page }) => {
  test.skip(
    process.env.VIBESTACK_ALLOW_MUTATING_BROWSER_TESTS !== '1',
    'real service restarts run only against a disposable acceptance container',
  );
  test.setTimeout(75_000);
  await openConnectedDesktop(page);
  await openTools(page);
  await expect(page.locator('.service-row')).toHaveCount(7);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Restart VNC' }).click();
  const restartReported = expect(page.locator('#toast-region')).toContainText('VNC restarted', { timeout: 45_000 });
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'reconnecting', { timeout: 15_000 });
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'connected', { timeout: 45_000 });
  await restartReported;
  await expect(page.locator('#screen canvas')).toBeVisible();
});

test('embedded terminal loads the real ttyd client and executes keyboard input', async ({ page }) => {
  test.skip(
    process.env.VIBESTACK_ALLOW_MUTATING_BROWSER_TESTS !== '1',
    'real terminal input runs only against a disposable acceptance container',
  );
  test.setTimeout(60_000);

  const pageErrors = [];
  const cspErrors = [];
  const failedTerminalRequests = [];
  const terminalResponses = [];
  const terminalSockets = [];
  const receivedFrames = [];

  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    if (/Content Security Policy|Refused to (?:connect|frame|load|execute|apply)/i.test(message.text())) {
      cspErrors.push(message.text());
    }
  });
  page.on('requestfailed', (request) => {
    if (new URL(request.url()).pathname.startsWith('/terminal/')) {
      failedTerminalRequests.push(`${request.url()}: ${request.failure()?.errorText || 'unknown failure'}`);
    }
  });
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.pathname === '/terminal/') {
      terminalResponses.push({
        status: response.status(),
        contentType: response.headers()['content-type'] || '',
      });
    }
  });
  page.on('websocket', (socket) => {
    if (new URL(socket.url()).pathname !== '/terminal/ws') return;
    terminalSockets.push(socket.url());
    socket.on('framereceived', ({ payload }) => {
      receivedFrames.push(typeof payload === 'string' ? payload : Buffer.from(payload).toString('utf8'));
    });
  });

  const shellResponse = await page.goto('/vnc/?view=terminal', { waitUntil: 'domcontentloaded' });
  expect(shellResponse?.status()).toBe(200);
  const shellCsp = shellResponse?.headers()['content-security-policy'] || '';
  expect(shellCsp).toContain("default-src 'self'");
  expect(shellCsp).toContain("frame-ancestors 'self'");
  expect(shellCsp).not.toContain("frame-src 'none'");

  await expect(page.getByTestId('terminal-stage')).toBeVisible();
  await expect(page.getByTestId('desktop-stage')).toBeHidden();
  const iframe = page.getByTestId('terminal-frame');
  await expect(iframe).toHaveAttribute('src', '/terminal/');

  const terminal = iframe.contentFrame();
  await expect(terminal.locator('#terminal-container .xterm')).toBeVisible({ timeout: 30_000 });
  await expect(terminal.locator('.xterm-screen canvas').first()).toBeVisible();
  await expect.poll(() => terminalResponses).toContainEqual({
    status: 200,
    contentType: expect.stringContaining('text/html'),
  });
  await expect.poll(() => terminalSockets.length).toBe(1);

  const screen = terminal.locator('.xterm-screen');
  await screen.click({ position: { x: 20, y: 20 } });
  await expect.poll(() => page.evaluate(() => document.activeElement?.id)).toBe('terminal-frame');
  const terminalInput = terminal.locator('.xterm-helper-textarea');
  await expect.poll(() => terminalInput.evaluate((input) => input === document.activeElement)).toBe(true);

  const left = 410_000 + Math.floor(Math.random() * 10_000);
  const right = 270_000 + Math.floor(Math.random() * 10_000);
  const expectedOutput = `VIBESTACK_TTYD_RESULT_${left + right}`;
  const command = `printf 'VIBESTACK_TTYD_RESULT_%s\\n' \"$(( ${left} + ${right} ))\"`;
  expect(command).not.toContain(expectedOutput);
  await terminalInput.pressSequentially(command, { delay: 2 });
  await terminalInput.press('Enter');
  await expect.poll(() => receivedFrames.join('').includes(expectedOutput), { timeout: 20_000 }).toBe(true);

  expect(failedTerminalRequests).toEqual([]);
  expect(cspErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
