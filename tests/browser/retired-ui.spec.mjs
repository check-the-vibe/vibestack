import {test,expect} from './fixtures.mjs';

test('old bookmarks lead to the overlay without old assets or mutation forwarding',async({page,request})=>{
  for(const path of ['/setup','/setup/','/setup/index.html','/terminal','/terminal/','/editor','/editor/']){
    const response=await request.get(path+'?force=1&view=editor',{maxRedirects:0});
    expect(response.status()).toBe(302);expect(response.headers().location).toBe('/vnc/');
    expect((await request.post(path,{maxRedirects:0})).status()).toBe(405);
  }
  for(const path of ['/setup/app.js','/setup/style.css','/terminal/ws','/editor/workbench','/vnc/navigation.js']){
    expect((await request.get(path,{maxRedirects:0})).status()).toBe(404);
  }
  await page.goto('/setup/?force=1&screen=apps');
  await expect(page).toHaveURL(/\/vnc\/$/);
  await expect(page.getByRole('button',{name:'Open VibeStack agent',exact:true})).toBeVisible();
  const status=await request.get('/api/v1/status');expect(status.ok()).toBe(true);
  const services=(await status.json()).services;
  expect(Object.keys(services).sort()).toEqual(['desktop','native-vnc','setup','ssh','vnc']);
  expect((await request.get('/setup/api/state')).ok()).toBe(true);
});
