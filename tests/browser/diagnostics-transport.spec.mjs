import {test,expect} from '@playwright/test';

// Exercise the actual pinned noVNC module and live WebSocket, with no transport mocks.
for (const enabled of [true,false]) {
  test(`real desktop connects with walkthrough logging ${enabled?'enabled':'disabled'}`,async({page})=>{
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    const events=[];
    page.on('request',request=>{
      if(new URL(request.url()).pathname==='/api/v1/diagnostics/events') events.push(request.postDataJSON());
    });
    await page.goto(`/vnc/?walkthrough=${enabled?'1':'0'}`);
    await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state','connected',{timeout:25000});
    await expect(page.locator('#screen canvas')).toBeVisible();
    await expect(page.getByTestId('connection-panel')).toBeHidden();
    expect(errors).toEqual([]);
    if(enabled) expect(events.some(event=>event.kind==='socket_open'&&event.endpoint==='/vnc/websockify')).toBe(true);
    else expect(events).toEqual([]);
  });
}
