import {test,expect} from '@playwright/test';

test('the built-in editor serves its real workbench and is absent from Apps',async({page,request})=>{
  const status=await request.get('/api/v1/status');
  expect((await status.json()).services.editor.state).toBe('RUNNING');
  const setup=await request.get('/setup/api/state');
  const state=await setup.json();
  expect(state.catalog.components.some(component=>component.id==='browser-editor')).toBe(false);
  expect(state.catalog.presets.some(pack=>pack.components.includes('browser-editor'))).toBe(false);
  await page.goto('/editor/');
  await expect(page.locator('.monaco-workbench')).toBeVisible({timeout:25000});
});
