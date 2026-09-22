import {test,expect} from './fixtures.mjs';
import {providerFixture,origin} from './provider-fixture.mjs';
import {randomUUID} from 'node:crypto';
test.use({serviceWorkers:'block'});

async function openAgent(page){await page.goto(origin+'/vnc/');await page.getByRole('button',{name:'Open VibeStack agent',exact:true}).click();}
async function startTurn(page){await page.getByRole('button',{name:'Activate provider',exact:true}).click();await expect(page.locator('#model-select')).toHaveValue('fixture/model');await page.getByLabel('Message your agent').fill('Build a harmless fixture');await page.getByRole('button',{name:'Send',exact:true}).click();await expect(page.getByRole('button',{name:'Stop turn',exact:true})).toBeVisible();}

test('only the icon overlays the desktop and keyboard close restores focus',async({page},info)=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await providerFixture(page);await page.goto(origin+'/?view=editor&panel=apps');
  await expect(page).toHaveURL(origin+'/vnc/');
  await expect(page.locator('#agent-panel')).toBeHidden();
  await expect(page.locator('#screen canvas')).toBeVisible();
  for(const selector of ['.topbar','#apps-dialog','#settings-dialog','#terminal-stage','#editor-stage'])await expect(page.locator(selector)).toHaveCount(0);
  const toggle=page.getByRole('button',{name:'Open VibeStack agent',exact:true});await toggle.focus();await toggle.press('Enter');
  await expect(page.getByRole('dialog',{name:'VibeStack agent'})).toBeVisible();
  await expect(page.locator('#agent-close')).toBeFocused();
  const hit=await page.evaluate(()=>document.elementFromPoint(20,20)?.closest('#agent-panel')!==null);expect(hit).toBe(false);
  await page.screenshot({path:info.outputPath('agent-setup.png')});
  await page.locator('#agent-close').press('Escape');await expect(page.locator('#agent-panel')).toBeHidden();await expect(toggle).toBeFocused();
  expect(errors).toEqual([]);
});

test('workspace credential and Linux password use separate deterministic forms without browser storage',async({page})=>{
  const state=await providerFixture(page,{authenticated:false,password:false});await openAgent(page);
  await expect(page.getByRole('heading',{name:'Connect your workspace'})).toBeVisible();
  await page.getByLabel('Workspace credential',{exact:true}).fill('disposable-browser-fixture');await page.getByRole('button',{name:'Connect',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Set your Linux password'})).toBeVisible();
  await expect(page.getByLabel('Workspace credential',{exact:true})).toHaveValue('');
  const secret=randomUUID();await page.getByLabel('Linux password',{exact:true}).fill(secret);await page.getByLabel('Confirm Linux password',{exact:true}).fill(secret);
  await page.getByRole('button',{name:'Save password',exact:true}).click();
  await expect(page.locator('#agent-workspace')).toBeVisible();expect(state.passwordSubmissions).toBe(1);expect(state.submissions).toEqual([]);
  expect(await page.evaluate(()=>localStorage.length+sessionStorage.length)).toBe(0);await expect(page).toHaveURL(origin+'/vnc/');
  await expect(page.locator('#linux-password')).toHaveValue('');
});

test('provider catalog drives setup, streamed text stays inert, and close/reopen keeps the same turn',async({page},info)=>{
  const state=await providerFixture(page);await openAgent(page);await startTurn(page);
  expect(state.activations).toBe(1);expect(state.submissions).toHaveLength(1);
  state.emit('text_delta','<img src=x onerror="window.untrusted=true">',{item_id:'reply'});
  await expect(page.getByRole('log')).toContainText('<img src=x');await expect(page.getByRole('log').locator('img')).toHaveCount(0);
  await page.getByRole('button',{name:'Close agent',exact:true}).click();state.emit('text_delta',' still here',{item_id:'reply'});
  await page.getByRole('button',{name:'Open VibeStack agent',exact:true}).click();await expect(page.getByRole('log')).toContainText('still here');
  expect(state.submissions).toHaveLength(1);expect(state.conversations).toHaveLength(1);
  await page.screenshot({path:info.outputPath('agent-conversation.png')});
  await page.getByRole('button',{name:'Stop turn',exact:true}).click();await expect(page.getByRole('button',{name:'Stop turn',exact:true})).toBeHidden();
  await page.locator('#provider-setup').evaluate(node=>{node.open=true;});await page.getByLabel('Provider',{exact:true}).selectOption('alternative');
  await expect(page.getByRole('log')).not.toContainText('still here');expect(state.submissions).toHaveLength(1);
});

test('native approvals require a human click and truncated scope cannot be allowed',async({page})=>{
  const state=await providerFixture(page);await openAgent(page);await startTurn(page);
  state.emit('approval','Run one harmless command',{approval_id:'b'.repeat(32),can_allow:true});
  await expect(page.getByRole('button',{name:'Allow once',exact:true})).toBeVisible();expect(state.approvalAnswers).toHaveLength(0);
  await page.getByRole('button',{name:'Allow once',exact:true}).click();await expect.poll(()=>state.approvalAnswers.length).toBe(1);
  expect(state.approvalAnswers[0]).toMatchObject({conversation:state.conversations[0].id,operation_id:state.submissions[0].operation_id,approval_id:'b'.repeat(32),allow:true});
  await expect(page.locator('#approvals .approval')).toHaveCount(0);
  state.emit('approval','Truncated scope',{approval_id:'c'.repeat(32),can_allow:false});
  await expect(page.getByRole('button',{name:'Allow once',exact:true})).toBeDisabled();await page.getByRole('button',{name:'Decline',exact:true}).click();
  await expect.poll(()=>state.approvalAnswers.length).toBe(2);expect(state.approvalAnswers[1].allow).toBe(false);
});

test('a dropped submission reply is inspected without replay and missing history stays visible',async({page})=>{
  const state=await providerFixture(page,{dropSubmit:true});await openAgent(page);await startTurn(page);
  await expect(page.locator('#panel-notice')).toContainText('No message was automatically resent');
  state.gap=true;state.emit('text_delta','Work already started',{item_id:'reply'});
  await expect(page.getByRole('log')).toContainText('Work already started');await expect(page.locator('#history-gap')).toBeVisible();
  await expect(page.getByLabel('Message your agent')).toHaveValue('');expect(state.submissions).toHaveLength(1);
});

test('small screens retain reachable controls without page overflow',async({page})=>{
  await page.setViewportSize({width:390,height:844});await providerFixture(page);await openAgent(page);
  const box=await page.locator('#agent-panel').boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(390);expect(box.y).toBeGreaterThanOrEqual(0);
  await page.locator('#provider-activate').scrollIntoViewIfNeeded();await expect(page.locator('#provider-activate')).toBeInViewport();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
});

test('desktop transport recovers once after a drop and security failures require explicit reconnect',async({page})=>{
  await providerFixture(page);await openAgent(page);
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','connected');
  await page.evaluate(()=>window.__rfb.dispatchEvent(new CustomEvent('disconnect',{detail:{clean:false}})));
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','reconnecting');
  await expect.poll(()=>page.evaluate(()=>window.__rfbConnections)).toBe(2);
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','connected');
  await page.evaluate(()=>window.__rfb.dispatchEvent(new Event('securityfailure')));
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','failed');
  await page.evaluate(()=>window.dispatchEvent(new Event('online')));
  expect(await page.evaluate(()=>window.__rfbConnections)).toBe(2);
  await page.locator('#desktop-recovery').evaluate(node=>{node.open=true;});
  await page.getByRole('button',{name:'Reconnect desktop',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.__rfbConnections)).toBe(3);
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','connected');
});

test('expired workspace authentication hides prior conversation content and disconnects the desktop',async({page})=>{
  const state=await providerFixture(page);await openAgent(page);await startTurn(page);
  state.emit('text_delta','Previous private response',{item_id:'reply'});
  await expect(page.getByRole('log')).toContainText('Previous private response');
  state.authenticated=false;
  await expect(page.getByRole('heading',{name:'Connect your workspace'})).toBeVisible({timeout:10000});
  await expect(page.locator('#messages')).toBeEmpty();
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','disconnected');
  expect(state.submissions).toHaveLength(1);
});
