import {test,expect} from './fixtures.mjs';

test('actual desktop connects behind the collapsed agent and remains available after closing it',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/vnc/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','connected',{timeout:25000});
  await expect(page.locator('#screen canvas')).toBeVisible();
  await expect(page.locator('#agent-panel')).toBeHidden();
  await page.getByRole('button',{name:'Open VibeStack agent',exact:true}).click();
  await expect(page.locator('#agent-panel')).toBeVisible();
  await expect(page.getByLabel('Provider',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Close agent',exact:true}).click();
  await expect(page.locator('#agent-panel')).toBeHidden();
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','connected');
  expect(errors).toEqual([]);
});

test('service worker keeps API state private and the shell is installable',async({page})=>{
  await page.goto('/vnc/');
  await page.waitForFunction(()=>Boolean(navigator.serviceWorker?.controller),null,{timeout:20000});
  const result=await page.evaluate(async()=>{
    const manifest=await (await fetch('/manifest.webmanifest')).json();
    const cached=[];for(const name of await caches.keys()){const cache=await caches.open(name);cached.push(...(await cache.keys()).map(r=>new URL(r.url).pathname));}
    return {scope:(await navigator.serviceWorker.ready).scope,manifest,privateEntries:cached.filter(p=>p.startsWith('/api/')||p.startsWith('/auth/')||p.startsWith('/mcp')||p==='/vnc/websockify')};
  });
  expect(result.scope).toMatch(/\/$/);expect(result.manifest).toMatchObject({start_url:'/',scope:'/',display:'standalone'});expect(result.manifest.shortcuts).toBeUndefined();expect(result.privateEntries).toEqual([]);
});
