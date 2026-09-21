import {readFileSync} from 'node:fs';
import {test as base, expect} from '@playwright/test';

function credential() {
  const path = process.env.VIBESTACK_BROWSER_CREDENTIAL_FILE;
  return path ? readFileSync(path, 'utf8').trim() : '';
}

export const test = base.extend({
  context: async ({context, baseURL}, use) => {
    const token = credential();
    if (token) {
      // Node fetch keeps the one-time sign-in exchange out of Playwright traces.
      const response = await fetch(new URL('/auth/session', baseURL), {method:'POST', headers:{Authorization:`Bearer ${token}`}});
      if (!response.ok) throw new Error('Disposable browser authentication failed.');
      const value = response.headers.getSetCookie().find(value => value.startsWith('vibestack_session='))?.split(';', 1)[0].split('=', 2)[1];
      if (!value) throw new Error('Disposable browser session cookie missing.');
      await context.addCookies([{name:'vibestack_session',value,url:baseURL,httpOnly:true,sameSite:'Strict',secure:baseURL.startsWith('https://')}]);
    }
    await use(context);
  },
  request: async ({playwright, baseURL}, use) => {
    const token = credential();
    const request = await playwright.request.newContext({baseURL,extraHTTPHeaders:token ? {Authorization:`Bearer ${token}`} : {}});
    try { await use(request); } finally { await request.dispose(); }
  },
});

export {expect};
