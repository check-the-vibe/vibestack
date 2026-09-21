// Independent pinned TypeScript SDK client. Accepts paths, never token argv or
// token environment variables. Errors deliberately omit SDK/request payloads.
import { open, constants } from 'node:fs/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

let stage = 'configuration';

async function credential(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await file.stat();
    if (!info.isFile() || info.size > 4096 || (info.mode & 0o077) || info.nlink !== 1 || info.uid !== process.getuid()) throw new Error();
    const token = (await file.readFile('utf8')).trim();
    if (!/^vss_[A-Za-z0-9_-]{43}$/.test(token)) throw new Error();
    return token;
  } finally { await file.close(); }
}

async function main() {
  const origin = new URL(process.env.VIBESTACK_MCP_BASE_URL);
  if (origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash || !(origin.protocol === 'https:' || (origin.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname)))) throw new Error();
  const token = await credential(process.env.VIBESTACK_MCP_CREDENTIAL_FILE);
  const gateway = process.env.VIBESTACK_MCP_GATEWAY_FILE ? await credentialGateway(process.env.VIBESTACK_MCP_GATEWAY_FILE) : '';
  const headers = { Authorization: `Bearer ${token}` };
  if (gateway) headers['X-GitHub-Token'] = gateway;
  if (process.env.VIBESTACK_MCP_EXPECTED_INSTANCE) headers['X-VibeStack-Expected-Instance'] = process.env.VIBESTACK_MCP_EXPECTED_INSTANCE;
  let protocol;
  const safeFetch = async (input, init) => {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
    if (url.origin !== origin.origin) throw new Error();
    const response = await fetch(input, { ...init, redirect: 'error', signal: init?.signal ?? AbortSignal.timeout(10000) });
    const version = new Headers(init?.headers).get('mcp-protocol-version');
    if (version) protocol = version;
    return response;
  };
  const transport = new StreamableHTTPClientTransport(new URL('/mcp', origin), {
    requestInit: { headers }, fetch: safeFetch,
    reconnectionOptions: { maxRetries: 0, initialReconnectionDelay: 100, maxReconnectionDelay: 100, reconnectionDelayGrowFactor: 1 },
  });
  const client = new Client({ name: 'vibestack-typescript-acceptance', version: '1' }, { capabilities: {} });
  try {
    stage = 'connect';
    await client.connect(transport);
    stage = 'list tools';
    const tools = await client.listTools();
    if (!tools.tools.some(t => t.name === 'project_summary') || tools.tools.some(t => ['instance_create', 'host_inspect'].includes(t.name))) throw new Error();
    stage = 'call tool';
    const result = await client.callTool({ name: 'project_summary', arguments: { project: 'vst-mcp-client-probe' } });
    const value = result.structuredContent;
    if (result.isError || value?.capability !== 'project_summary' || !/^[a-f0-9]{32}$/.test(value?.request_id) || !/^[a-f0-9]{32}$/.test(value?.instance_id) || value?.result?.project !== 'vst-mcp-client-probe') throw new Error();
    if (process.env.VIBESTACK_MCP_EXPECTED_INSTANCE && value.instance_id !== process.env.VIBESTACK_MCP_EXPECTED_INSTANCE) throw new Error();
    stage = 'schema denial';
    const bad = await client.callTool({ name: 'project_summary', arguments: { project: '../data' } });
    if (!bad.isError || bad.structuredContent?.error?.code !== 'invalid_input') throw new Error();
    stage = 'protocol/session';
    if (transport.sessionId !== undefined || protocol !== '2025-11-25') throw new Error();
    console.log(`PASS TypeScript SDK 1.30.0 protocol ${protocol}: authenticated discovery, tool list, call, schema denial; stateless`);
  } finally { await client.close(); }
}

async function credentialGateway(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await file.stat();
    if (!info.isFile() || info.size > 4096 || (info.mode & 0o077) || info.nlink !== 1 || info.uid !== process.getuid()) throw new Error();
    const value = (await file.readFile('utf8')).trim();
    if (!/^[A-Za-z0-9_]+$/.test(value)) throw new Error();
    return value;
  } finally { await file.close(); }
}

main().catch(() => { console.error(`FAIL TypeScript MCP client verification at ${stage} (credential and payload details suppressed)`); process.exitCode = 1; });
