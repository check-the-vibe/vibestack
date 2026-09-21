// Real nginx → workspace service checks. Only disposable acceptance credentials
// and fixture data are used; no payloads, browser traces or secrets are logged.
import { constants, open, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { isAbsolute, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { chromium } from '@playwright/test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

let stage = 'configuration', directory, browser;
const clients = [];
const check = (condition, reason) => { if (!condition) { const error = new Error(reason); error.name = 'ParityInvariant'; throw error; } };
async function credential(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
  try {
    const stat = await file.stat();
    check(stat.isFile() && stat.nlink === 1 && stat.uid === process.getuid() && !(stat.mode & 0o077) && stat.size <= 4096, 'private fixture file');
    const value = (await file.readFile('utf8')).trim();
    check(/^vss_[A-Za-z0-9_-]{43}$/.test(value), 'fixture format');
    return value;
  } finally { await file.close(); }
}
async function main() {
  check(process.env.VIBESTACK_ALLOW_MUTATING_MCP_TESTS === '1', 'explicit disposable run');
  const origin = new URL(process.env.VIBESTACK_MCP_BASE_URL);
  check(origin.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname) && origin.pathname === '/' && !origin.username && !origin.password && !origin.search && !origin.hash, 'loopback origin');
  const command = process.env.VIBESTACK_MCP_CLI;
  check(isAbsolute(command ?? ''), 'native CLI path');
  const owner = await credential(process.env.VIBESTACK_MCP_CREDENTIAL_FILE);
  const scoped = await credential(process.env.VIBESTACK_PARITY_SCOPED_FILE);
  const fetchJSON = async (path, options = {}) => {
    const response = await fetch(new URL(path, origin), { redirect: 'error', signal: AbortSignal.timeout(30000), ...options });
    const text = await response.text();
    check(text.length < 24 << 20 && !text.includes(owner) && !text.includes(scoped), 'bounded secret-free response');
    return { status: response.status, value: JSON.parse(text) };
  };
  const discovery = (await fetchJSON('/.well-known/vibestack')).value;
  const instance = discovery.identity;
  check(/^[a-f0-9]{32}$/.test(instance), 'workspace identity');
  const wrong = instance === 'f'.repeat(32) ? 'e'.repeat(32) : 'f'.repeat(32);
  const headers = (token, selected = instance) => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-VibeStack-Expected-Instance': selected });
  directory = await mkdtemp(join(tmpdir(), 'vibestack-parity-'));
  const config = join(directory, 'profiles.json'), profiles = {};
  for (const [name, token] of Object.entries({ owner, scoped })) {
    for (const [suffix, identity] of [['', instance], ['-wrong', wrong]]) {
      profiles[name + suffix] = { name: name + suffix, kind: 'workspace', authentication_mode: 'paired', identity, url: origin.origin, credential: token };
    }
  }
  await writeFile(config, JSON.stringify({ version: 1, profiles }), { mode: 0o600, flag: 'wx' });
  const cli = (profile, id, raw) => new Promise((resolve, reject) => {
    const child = spawn(command, ['--profile', profile, 'capability', 'call', id, '--input', '-'], { env: { PATH: process.env.PATH, VIBESTACK_CONFIG: config }, stdio: ['pipe', 'pipe', 'pipe'], timeout: 45000 });
    let out = '', err = '';
    const collect = (kind, data) => {
      if (kind === 'out') out += data; else err += data;
      if (out.length + err.length > 24 << 20) { child.kill(); reject(new Error('bounded CLI output')); }
    };
    child.stdout.on('data', data => collect('out', data)); child.stderr.on('data', data => collect('err', data));
    child.on('error', () => reject(new Error('CLI process failed')));
    child.stdin.on('error', () => reject(new Error('CLI input failed')));
    child.on('close', code => {
      try {
        check(!out.includes(owner) && !out.includes(scoped) && !err.includes(owner) && !err.includes(scoped), 'secret-free CLI output');
        if (code === 0) { check(!err, 'clean CLI diagnostics'); resolve(JSON.parse(out)); }
        else { const match = /^vibestack: ([a-z_]+):/.exec(err); check(!out && match, 'CLI canonical error'); resolve({ error: { code: match[1] }, exit: code }); }
      } catch { reject(new Error('CLI envelope')); }
    });
    child.stdin.end(raw);
  });
  browser = await chromium.launch({ headless: true });
  const makeAdapters = async (name, token) => {
    const client = new Client({ name: `vibestack-parity-${name}`, version: '1' }, { capabilities: {} });
    clients.push(client);
    await client.connect(new StreamableHTTPClientTransport(new URL('/mcp', origin), { requestInit: { headers: headers(token), redirect: 'error' }, reconnectionOptions: { maxRetries: 0 } }));
    const context = await browser.newContext();
    const response = await fetch(new URL('/auth/session', origin), { method: 'POST', headers: headers(token), redirect: 'error' });
    check(response.ok, 'browser session exchange');
    const cookie = response.headers.getSetCookie().find(value => value.startsWith('vibestack_session='))?.split(';', 1)[0].split('=', 2)[1];
    check(cookie, 'browser session cookie');
    await context.addCookies([{ name: 'vibestack_session', value: cookie, url: origin.origin, httpOnly: true, sameSite: 'Strict' }]);
    const page = await context.newPage();
    await page.goto(new URL('/status.txt', origin).href);
    const wireMCP = async (id, raw, selected = instance) => {
      const response = await fetchJSON('/mcp', { method: 'POST', headers: { ...headers(token, selected), Accept: 'application/json, text/event-stream' }, body: `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":${JSON.stringify(id)},"arguments":${raw}}}` });
      return response.status === 200 ? response.value.result.structuredContent : response.value;
    };
    return {
      client, page, wireMCP,
      rest: async (id, raw, selected = instance) => (await fetchJSON(`/api/v1/capabilities/${id}/invoke`, { method: 'POST', headers: headers(token, selected), body: raw })).value,
      mcp: async (id, raw, selected = instance) => {
        if (selected !== instance) return wireMCP(id, raw, selected);
        const result = await client.callTool({ name: id, arguments: JSON.parse(raw) });
        check(Boolean(result.isError) === Boolean(result.structuredContent?.error), 'MCP error flag');
        return result.structuredContent;
      },
      cli: (id, raw, selected = instance) => cli(name + (selected === instance ? '' : '-wrong'), id, raw),
      web: (id, raw, selected = instance) => page.evaluate(async ({ id, raw, selected }) => {
        const session = await (await fetch('/auth/session')).json();
        const response = await fetch(`/api/v1/capabilities/${id}/invoke`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-VibeStack-CSRF': session.csrf, 'X-VibeStack-Expected-Instance': selected }, body: raw });
        return response.json();
      }, { id, raw, selected }),
    };
  };
  stage = 'authenticated clients';
  const full = await makeAdapters('owner', owner), limited = await makeAdapters('scoped', scoped);
  const surfaces = ['rest', 'mcp', 'cli', 'web'];
  const call = async (surface, id, input) => {
    const value = await full[surface](id, JSON.stringify(input));
    check(value?.instance_id === instance && value.capability === id && value.result && !value.error && /^[a-f0-9]{32}$/.test(value.request_id), `${surface} success envelope`);
    return value.result;
  };
  stage = 'catalog and declared MCP exclusions';
  const catalog = (await fetchJSON('/api/v1/capabilities', { headers: headers(owner) })).value.capabilities;
  const tools = new Set((await full.client.listTools()).tools.map(tool => tool.name));
  for (const entry of catalog) {
    check((entry.mcp === 'implemented') === tools.has(entry.id), 'catalog matches MCP discovery');
    if (entry.mcp !== 'implemented') check(entry.next_action?.length > 0, 'excluded capability guidance');
    if (entry.definition) check(entry.rest === 'implemented' && entry.web === 'implemented' && entry.cli === 'implemented', 'registered surface coverage');
  }
  const granted = (await fetchJSON('/api/v1/capabilities', { headers: headers(scoped) })).value.capabilities;
  check(granted.length === 1 && granted[0].id === 'project_summary', 'scoped catalog');
  check((await limited.client.listTools()).tools.length === 1, 'scoped tools');
  const project = `vst-parity-${randomUUID()}`;
  for (const surface of surfaces) {
    stage = `${surface} extension and denial matrix`;
    const result = await call(surface, 'project_summary', { project });
    check(JSON.stringify(result) === JSON.stringify({ entry_count: 0, exists: false, project, truncated: false }), 'extension result parity');
    await call(surface, 'workspaceStatus', {});
    for (const [id, input, code] of [
      ['project_summary', { project: '../data', unexpected: 'fixture' }, 'invalid_input'],
      ['project_summary', { project: 'x'.repeat(4200) }, 'limit_exceeded'],
      ['not_a_registered_capability', {}, 'not_found'],
      ['getWorkspaceJobOutput', { id: '0'.repeat(32), limit: 262145 }, 'invalid_input'],
    ]) {
      const value = await full[surface](id, JSON.stringify(input));
      check(value?.error?.code === code, `${surface} ${code}`);
    }
    check((await limited[surface]('workspaceStatus', '{}'))?.error?.code === 'forbidden', `${surface} grant denial`);
    check((await full[surface]('workspaceStatus', '{}', wrong))?.error?.code === 'wrong_instance', `${surface} identity pin`);
    const duplicate = '{"project":"a","project":"b"}';
    const value = surface === 'mcp' ? await full.wireMCP('project_summary', duplicate) : await full[surface]('project_summary', duplicate);
    check(value?.error?.code === 'invalid_input', `${surface} duplicate-key denial`);
  }
  stage = 'browser CSRF and MCP human policy';
  const noCSRF = await full.page.evaluate(async () => (await fetch('/api/v1/capabilities/workspaceStatus/invoke', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).status);
  check(noCSRF === 401, 'browser mutation requires CSRF');
  check((await full.mcp('listWorkspaceClients', '{}')).error?.code === 'forbidden', 'owner grant cannot enable an excluded MCP tool');
  stage = 'conditional file writes across clients';
  const path = `${project}.txt`;
  await call('rest', 'writeProjectFile', { path, data_base64: Buffer.from('initial').toString('base64'), if_none_match: '*' });
  let current = await call('rest', 'readProjectFile', { path });
  for (const surface of surfaces) {
    const before = current.etag, content = `updated-by-${surface}`;
    await call(surface, 'writeProjectFile', { path, data_base64: Buffer.from(content).toString('base64'), if_match: before });
    const stale = await full[surface]('writeProjectFile', JSON.stringify({ path, data_base64: '', if_match: before }));
    check(stale.error?.code === 'precondition_failed', `${surface} stale write`);
    for (const reader of surfaces) {
      current = await call(reader, 'readProjectFile', { path });
      check(Buffer.from(current.data_base64, 'base64').toString('utf8') === content, 'shared file authority');
    }
  }
  for (const surface of surfaces) {
    stage = `${surface} argv jobs and bounded output`;
    const expected = `job-${surface}-literal-$(not-a-shell)`;
    let { job } = await call(surface, 'submitArgvCommand', { argv: ['/usr/bin/printf', '%s', expected], root: 'projects', timeout_seconds: 30 });
    const id = job.id;
    for (let n = 0; n < 100 && ['queued', 'running'].includes(job.status); n++) {
      await new Promise(resolve => setTimeout(resolve, 50));
      ({ job } = await call(surfaces[(surfaces.indexOf(surface) + 1) % 4], 'getWorkspaceJob', { id }));
    }
    check(job.id === id && job.status === 'succeeded' && job.exit_code === 0, 'same job identity and result');
    for (const reader of surfaces) {
      const page = await call(reader, 'getWorkspaceJobOutput', { id, stream: 'stdout', limit: 7 });
      check(page.encoding === 'base64' && Buffer.from(page.data, 'base64').toString('utf8') === expected.slice(0, 7) && page.next_cursor === 7 && page.eof === false, 'bounded cursor output');
    }
  }
  const legacy = process.env.VIBESTACK_LEGACY_CLI;
  if (legacy) {
    stage = 'pinned historical 0.2 client compatibility';
    check(isAbsolute(legacy), 'pinned legacy executable');
    const run = (binary, args) => new Promise((resolve, reject) => {
      const child = spawn(binary, ['--profile', 'owner', ...args], { env: { PATH: process.env.PATH, VIBESTACK_CONFIG: config }, stdio: ['ignore', 'pipe', 'pipe'], timeout: 45000 });
      let stdout = '', stderr = '';
      child.stdout.on('data', data => { stdout += data; if (stdout.length > 1 << 20) child.kill(); });
      child.stderr.on('data', data => { stderr += data; if (stderr.length > 8192) child.kill(); });
      child.on('error', reject);
      child.on('close', code => {
        if ([stdout, stderr].some(text => text.includes(owner) || text.includes(scoped))) reject(new Error('unsafe compatibility output'));
        else resolve({ code, stdout, stderr });
      });
    });
    check((await run(legacy, ['version'])).stdout.trim() === '0.2.0', 'actual historical CLI version');
    check((await run(command, ['version'])).stdout.trim() === '0.3.0', 'current CLI version');
    for (const binary of [legacy, command]) {
      const result = await run(binary, ['--json', 'exec', '--', '/usr/bin/printf', '%s', 'legacy-argv-$(literal)']);
      check(result.code === 0 && !result.stderr, 'legacy argv execution');
      const value = JSON.parse(result.stdout);
      check(value.job.status === 'succeeded' && Buffer.from(value.stdout_base64, 'base64').toString('utf8') === 'legacy-argv-$(literal)', 'legacy job/output shape');
      const current = await call('rest', 'getWorkspaceJob', { id: value.job.id });
      check(current.job.id === value.job.id && current.job.status === 'succeeded', 'legacy/new job identity');
      check((await run(binary, ['api', '/api/v1/status'])).code === 0, 'authenticated compatibility route');
    }
    check((await run(legacy, ['status'])).code === 4, 'old unauthenticated shortcut remains denied');
    check((await run(command, ['status'])).code === 0, 'new authenticated shortcut works');
    console.log('PASS pinned source-built CLI 0.2 and current CLI 0.3: preserved argv/job/output and authenticated raw API; documented old unauthenticated status migration');
  }
  console.log('PASS real nginx REST / TypeScript MCP / native CLI / Chromium session: catalog, grants, instance pinning, malformed/oversized/duplicate input, conditional file writes, argv jobs and bounded output; no payload or credential logging');
}
main().catch(error => { console.error(`FAIL capability parity at ${stage}${error.name === 'ParityInvariant' ? ': ' + error.message : ''} (payloads suppressed)`); process.exitCode = 1; }).finally(async () => {
  for (const client of clients) { try { await client.close(); } catch {} }
  if (browser) await browser.close();
  if (directory) await rm(directory, { recursive: true, force: true });
});
