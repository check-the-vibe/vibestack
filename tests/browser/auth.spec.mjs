import {readFileSync} from 'node:fs';
import {test, expect} from './fixtures.mjs';

test('browser credential exchange creates a private session and rejects missing CSRF', async ({page, context}) => {
  test.skip(!process.env.VIBESTACK_BROWSER_CREDENTIAL_FILE, 'Requires the disposable credential fixture.');
  await context.clearCookies();
  await page.goto('/connect.html?return=/status.txt');
  const input = page.getByLabel('Workspace credential', {exact:true});
  await input.fill(readFileSync(process.env.VIBESTACK_BROWSER_CREDENTIAL_FILE, 'utf8').trim());
  await page.getByRole('button', {name:'Connect', exact:true}).click();
  await expect(page).toHaveURL(/\/status\.txt$/);
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('body')).toContainText('VibeStack published files are available.');
  const properties = (await context.cookies()).filter(c => c.name === 'vibestack_session')
    .map(({httpOnly, sameSite, path}) => ({httpOnly, sameSite, path}));
  expect(properties).toEqual([{httpOnly:true, sameSite:'Strict', path:'/'}]);
  const result = await page.evaluate(async () => {
    const session = await fetch('/auth/session');
    const denied = await fetch('/auth/session', {method:'DELETE'});
    const value = await session.json();
    const ended = await fetch('/auth/session', {method:'DELETE',headers:{'X-VibeStack-CSRF':value.csrf}});
    return {session:session.status,denied:denied.status,ended:ended.status,
      remaining:(await fetch('/api/v1/status')).status,
      browserStorage:localStorage.length + sessionStorage.length};
  });
  expect(result).toEqual({session:200,denied:401,ended:200,remaining:401,browserStorage:0});
});

test('failed browser sign-in clears the input and keeps credentials out of the URL', async ({page, context}) => {
  await context.clearCookies();
  await page.goto('/connect.html');
  await page.getByLabel('Workspace credential', {exact:true}).fill('invalid-disposable-credential');
  await page.getByRole('button', {name:'Connect', exact:true}).click();
  await expect(page.getByRole('status')).toHaveText('Connection failed. Check your workspace credential and try again.');
  await expect(page.getByLabel('Workspace credential', {exact:true})).toHaveValue('');
  await expect(page).toHaveURL(/\/connect\.html$/);
});
