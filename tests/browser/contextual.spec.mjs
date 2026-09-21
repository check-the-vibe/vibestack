import {test, expect} from './fixtures.mjs';
import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';

// Entirely isolated API and desktop transports; never change a live password or install apps.
const origin = 'http://vibestack.test';
const root = new URL('../../', import.meta.url);
const fakeRfb = `export default class extends EventTarget { constructor(target) { super(); target.append(document.createElement('canvas')); queueMicrotask(()=>this.dispatchEvent(new Event('connect'))); } disconnect(){this.dispatchEvent(new CustomEvent('disconnect',{detail:{clean:true}}));} focus(){} blur(){} }`;
async function fixture(page, {password=true,editor=true}={}) {
  const catalog=JSON.parse(await readFile(new URL('setup/catalog.json',root),'utf8'));
  const state={catalog,architecture:'amd64',installed:[],state:{completed:false,selected:[]},state_valid:true,job:{running:false},missing:[],unknown_selected:[],unsupported_selected:[],authentication:{password_configured:password,sudo_password_required:true}};
  const installs=[];
  await page.route('**/*', async route=>{
    const url=new URL(route.request().url());
    if(url.origin!==origin) return route.abort();
    const path=url.pathname;
    const json=value=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(value)});
    if(path==='/auth/session') return json({authenticated:true,csrf:'isolated-browser-fixture'});
    if(path==='/setup/api/state') return json(state);
    if(path==='/setup/api/password') {state.authentication.password_configured=true;return json({authentication:state.authentication});}
    if(path==='/setup/api/install') {installs.push(route.request().postDataJSON());return json({ok:true});}
    if(path==='/setup/api/log') return json({running:false,ok:true,log:'',next_offset:0});
    if(path==='/api/v1/status') return json({services:{editor:{state:editor?'RUNNING':'STOPPED'}}});
    if(path==='/api/v1/display') return json({resolution:'1280x800',availableResolutions:['1280x800']});
    if(path==='/novnc/core/rfb.js') return route.fulfill({contentType:'application/javascript',body:fakeRfb});
    if(path==='/terminal/'||path==='/editor/') return route.fulfill({contentType:'text/html',body:'<!doctype html><p>Full-screen workspace content</p>'});
    if(route.request().method()!=='GET') return route.fulfill({status:403,body:'Unexpected mutation blocked'});
    const mappings={'/':'desktop/launcher.html','/launcher.js':'desktop/launcher.js','/launcher.css':'desktop/launcher.css','/vnc/':'desktop/index.html','/setup/':'setup/index.html','/auth.js':'web/public/auth.js'};
    let file=mappings[path] || (path.startsWith('/vnc/')?'desktop/'+path.slice(5):path.startsWith('/setup/')?'setup/'+path.slice(7):null);
    if(!file || file.includes('..')) return route.fulfill({status:404,body:''});
    try {const body=await readFile(new URL(file,root));return route.fulfill({contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',body});}
    catch {return route.fulfill({status:404,body:''});}
  });
  return {state,installs};
}

test('desktop landing and forced Apps sidebar lead to searchable packs without losing selection',async({page},testInfo)=>{
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await fixture(page);
  await page.goto(origin+'/?panel=apps');
  await expect(page).toHaveURL(origin+'/vnc/?panel=apps');
  await expect(page.locator('#apps-dialog')).toBeVisible();
  await expect(page.locator('#desktop-stage')).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('apps-sidebar.png')});
  await page.getByRole('link',{name:'Browse apps and packs'}).click();
  await page.screenshot({path:testInfo.outputPath('apps-fullscreen.png')});
  await expect(page.getByRole('heading',{name:'Apps and packs'})).toBeVisible();
  await page.locator('.preset').filter({hasText:'Recommended'}).click();
  const count=await page.locator('#count').textContent();
  await page.getByRole('searchbox').fill('Godot');
  await expect(page.locator('#groups .item')).toHaveCount(1);
  await expect(page.locator('#groups')).toContainText('Godot');
  await expect(page.locator('#count')).toHaveText(count);
  await page.getByRole('searchbox').fill('no-matching-app-here');
  await expect(page.locator('#search-empty')).toBeVisible();
  await page.getByRole('link',{name:'Back to Desktop',exact:true}).click();
  await expect(page.locator('#desktop-stage')).toBeVisible();
  await expect(page.locator('#apps-dialog')).not.toBeVisible();
  expect(errors).toEqual([]);
});

test('Terminal and Editor fill the workspace and browser Back returns to Desktop',async({page})=>{
  await fixture(page);
  await page.goto(origin+'/');
  await expect(page.locator('#desktop-stage')).toBeVisible();
  await page.getByRole('tab',{name:'Terminal',exact:true}).click();
  await expect(page.locator('#terminal-frame')).toBeVisible();
  await page.getByRole('tab',{name:'Editor',exact:true}).click();
  await expect(page.locator('#editor-frame')).toBeVisible();
  await expect(page.locator('#desktop-stage')).not.toBeVisible();
  await expect(page.locator('#terminal-stage')).not.toBeVisible();
  await page.goBack();
  await expect(page.locator('#desktop-stage')).toBeVisible();
  await page.goto(origin+'/vnc/?view=editor');
  await expect(page.locator('#editor-frame')).toBeVisible();
  await page.locator('#workspace-back').click();
  await expect(page.locator('#desktop-stage')).toBeVisible();
});

test('unavailable core Editor offers recovery, and Settings opens Apps in a sidebar',async({page})=>{
  await fixture(page,{editor:false});
  await page.goto(origin+'/vnc/?view=editor');
  await expect(page.locator('#editor-unavailable')).toContainText('Editor is starting');
  await expect(page.locator('#editor-frame')).not.toHaveAttribute('src',/./);
  await page.locator('#workspace-back').click();
  await page.getByRole('button',{name:'Settings',exact:true}).first().click();
  await expect(page.locator('#settings-dialog')).toBeVisible();
  await page.getByRole('button',{name:'Apps and packs',exact:true}).click();
  await expect(page.locator('#settings-dialog')).not.toBeVisible();
  await expect(page.locator('#apps-dialog')).toBeVisible();
});

test('a mocked first password submission opens Desktop with Apps',async({page})=>{
  await fixture(page,{password:false});
  await page.goto(origin+'/');
  await expect(page.getByRole('heading',{name:'Create your Linux password'})).toBeVisible();
  const value=randomUUID();
  await page.locator('#linux-password').fill(value);
  await page.locator('#linux-password-confirmation').fill(value);
  await page.getByRole('button',{name:'Save password',exact:true}).click();
  await expect(page).toHaveURL(origin+'/vnc/?panel=apps');
  await expect(page.locator('#apps-dialog')).toBeVisible();
  await expect(page.locator('#desktop-stage')).toBeVisible();
});

test('a pack deep link selects its components and only Install submits them',async({page})=>{
  const {installs}=await fixture(page);
  await page.goto(origin+'/setup/?force=1&screen=apps&pack=clis');
  await expect(page.locator('.preset').filter({hasText:'Terminal only'})).toHaveAttribute('aria-pressed','true');
  expect(installs).toEqual([]);
  await page.getByRole('button',{name:'Install',exact:true}).click();
  await expect.poll(()=>installs.length).toBe(1);
  expect(installs[0].components.sort()).toEqual(['claude-code','codex-cli','node','opencode'].sort());
});
