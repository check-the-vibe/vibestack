// Disposable acceptance only. Installs/activates real pinned providers through
// the public service, but never signs in or sends a model prompt.
import { open, constants, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, isAbsolute } from 'node:path';
import { randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

let stage = 'configuration', directory, client;
const check = value => { if (!value) throw new Error('provider fixture assertion'); };
async function main() {
  check(process.env.VIBESTACK_ALLOW_PROVIDER_TESTS === '1');
  const origin = new URL(process.env.VIBESTACK_MCP_BASE_URL);
  check(origin.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(origin.hostname) && !origin.username && !origin.password && origin.pathname === '/' && !origin.search && !origin.hash);
  const binary = process.env.VIBESTACK_MCP_CLI;
  check(binary && isAbsolute(binary));
  const file = await open(process.env.VIBESTACK_MCP_CREDENTIAL_FILE, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  let credential;
  try {
    const info = await file.stat();
    check(info.isFile() && info.nlink === 1 && info.uid === process.getuid() && !(info.mode & 0o077) && info.size < 4096);
    credential = (await file.readFile('utf8')).trim();
    check(/^vss_[A-Za-z0-9_-]{43}$/.test(credential));
  } finally { await file.close(); }
  const fetchJSON = async (path, options = {}) => {
    const response = await fetch(new URL(path, origin), { ...options, redirect: 'error', signal: AbortSignal.timeout(35000) });
    const bytes = new Uint8Array(await response.arrayBuffer());
    check(bytes.length <= 1 << 20);
    const text = new TextDecoder().decode(bytes);
    check(!text.includes(credential));
    return { status: response.status, value: JSON.parse(text) };
  };
  const identity = (await fetchJSON('/.well-known/vibestack')).value.identity;
  check(/^[a-f0-9]{32}$/.test(identity));
  const headers = { Authorization: `Bearer ${credential}`, 'Content-Type': 'application/json', 'X-VibeStack-Expected-Instance': identity };
  directory = await mkdtemp(join(tmpdir(), 'vibestack-provider-check-'));
  const config = join(directory, 'profiles.json');
  await writeFile(config, JSON.stringify({ version: 1, profiles: { fixture: { name: 'fixture', kind: 'workspace', authentication_mode: 'paired', identity, url: origin.origin, credential } } }), { mode: 0o600, flag: 'wx' });
  const cli = (id, input) => new Promise((resolve, reject) => {
    const process = spawn(binary, ['--profile', 'fixture', 'capability', 'call', id, '--input', '-'], { env: { VIBESTACK_CONFIG: config }, stdio: ['pipe', 'pipe', 'pipe'], timeout: 35000 });
    let output = '', diagnostics = '';
    process.stdout.on('data', data => { output += data; if (output.length > 1 << 20) process.kill(); });
    process.stderr.on('data', data => { diagnostics += data; if (diagnostics.length > 4096) process.kill(); });
    process.on('error', () => reject(new Error()));
    process.stdin.on('error', () => reject(new Error()));
    process.on('close', code => { try { check(code === 0 && !diagnostics && output.length < 1 << 20 && !output.includes(credential)); resolve(JSON.parse(output)); } catch { reject(new Error()); } });
    process.stdin.end(JSON.stringify(input));
  });
  client = new Client({ name: 'vibestack-provider-acceptance', version: '1' }, { capabilities: {} });
  await client.connect(new StreamableHTTPClientTransport(new URL('/mcp', origin), { requestInit: { headers }, reconnectionOptions: { maxRetries: 0 }, fetch: (url, init) => fetch(url, { ...init, redirect: 'error' }) }));
  const call = async (surface, id, input) => {
    let value;
    if (surface === 'rest') value = (await fetchJSON(`/api/v1/capabilities/${id}/invoke`, { method: 'POST', headers, body: JSON.stringify(input) })).value;
    else if (surface === 'cli') value = await cli(id, input);
    else { const reply = await client.callTool({ name: id, arguments: input }); check(!reply.isError); value = reply.structuredContent; }
    check(value?.instance_id === identity && value?.capability === id && value.result && !value.error);
    return value.result;
  };
  stage = 'shared authentication and strict activation input';
  check((await fetchJSON('/api/v1/providers')).status === 401);
  const denied = await fetchJSON('/api/v1/providers/activate', { method: 'POST', headers, body: JSON.stringify({ provider: 'codex', installer: 'https://invalid.example/install' }) });
  check(denied.status === 400);
  const names = new Set((await client.listTools()).tools.map(tool => tool.name));
  check(!names.has('answerProviderApproval') && !names.has('openProviderApp') && names.has('activateProvider'));
  for (const provider of ['codex', 'opencode']) {
    stage = `${provider} real installation and concurrent activation`;
    const initial = await Promise.all(['rest', 'cli', 'mcp'].map(surface => call(surface, 'activateProvider', { provider })));
    const operation = initial[0].provider.operation_id;
    check(operation && initial.every(result => result.provider.operation_id === operation));
    let state;
    const until = Date.now() + 30 * 60 * 1000;
    while (Date.now() < until) {
      state = (await call('mcp', 'getProviderStatus', { provider })).provider;
      if (state.phase === 'active' || state.phase === 'failed') break;
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
    check(state?.phase === 'active' && state.installed === true && state.process === 'running' && state.readiness !== 'verified');
    check((await call('cli', 'activateProvider', { provider })).provider.operation_id === operation);
    if (provider === 'codex') check(state.authentication === 'needs_sign_in');
    else {
      check(state.models.length > 0);
      stage = 'native OpenCode conversation without a model call';
      const id = randomBytes(16).toString('hex');
      const input = { id, provider, project: 'vst-mcp-client-probe', model: state.models[0].id };
      await call('rest', 'createProviderConversation', input);
      let page;
      for (let count = 0; count < 30; count++) {
        page = await call('mcp', 'readProviderEvents', { conversation: id });
        if (page.conversation.status !== 'creating') break;
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      check(page?.conversation.status === 'idle' && page.conversation.operations.length === 0);
      check((await call('cli', 'createProviderConversation', input)).conversation.id === id);
    }
    stage = `${provider} stop and reactivate`;
    check((await call('rest', 'stopProvider', { provider })).provider.process === 'stopped');
    await call('rest', 'activateProvider', { provider });
    for (let count = 0; count < 45; count++) {
      state = (await call('rest', 'getProviderStatus', { provider })).provider;
      if (state.phase === 'active' || state.phase === 'failed') break;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    check(state.phase === 'active' && state.installed === true);
    await call('rest', 'stopProvider', { provider });
  }
  console.log('PASS real pinned provider catalog installation and private adapters through REST, native CLI and MCP: duplicate activation, absent Codex login, safe OpenCode model/session metadata, explicit stop/reactivation; no model call or human sign-in claimed');
}
main().catch(() => { console.error(`FAIL provider acceptance at ${stage} (private payloads suppressed)`); process.exitCode = 1; }).finally(async () => { await client?.close(); if (directory) await rm(directory, { recursive: true, force: true }); });
