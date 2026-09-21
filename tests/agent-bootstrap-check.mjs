// Guide-URL-only service discovery, actual CLI connect and independent MCP client.
// Acceptance supplies a disposable operator-issued credential through a file.
// No repository/service URL knowledge beyond the given guide URL is used.
import { open, constants, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, isAbsolute } from 'node:path';
import { spawn } from 'node:child_process';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

let stage = 'configuration';
let directory;
async function main() {
  const guideURL = new URL(process.env.VIBESTACK_GUIDE_URL);
  if (guideURL.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(guideURL.hostname) || guideURL.pathname !== '/AGENTS.md' || guideURL.search || guideURL.hash || guideURL.username || guideURL.password) throw new Error();
  const command = process.env.VIBESTACK_MCP_CLI;
  if (!isAbsolute(command ?? '')) throw new Error();
  const file = await open(process.env.VIBESTACK_MCP_CREDENTIAL_FILE, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
  let credential;
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== process.getuid() || stat.mode & 0o077 || stat.size > 4096) throw new Error();
    credential = (await file.readFile('utf8')).trim();
    if (!/^vss_[A-Za-z0-9_-]{43}$/.test(credential)) throw new Error();
  } finally { await file.close(); }
  const get = path => fetch(new URL(path, guideURL), { redirect: 'error', signal: AbortSignal.timeout(15000) });
  stage = 'Markdown guide';
  const guideResponse = await get(guideURL.pathname);
  if (!guideResponse.ok || !guideResponse.headers.get('content-type')?.includes('text/markdown')) throw new Error();
  const guide = await guideResponse.text();
  for (const term of ['/.well-known/vibestack', 'capability call workspaceStatus', '--token-stdin', 'github-gateway.token', '/mcp', '/vnc/?view=desktop', '0.3.1']) if (!guide.includes(term)) throw new Error();
  stage = 'sanitized discovery and version manifest';
  const discovery = await (await get('/.well-known/vibestack')).json();
  const manifest = await (await get('/release-manifest.json')).json();
  if (discovery.kind !== 'workspace' || !/^[a-f0-9]{32}$/.test(discovery.identity) || manifest.version !== discovery.version || manifest.version !== '0.3.1') throw new Error();
  for (const name of ['capabilities', 'projects', 'credentials', 'clients', 'jobs']) if (Object.hasOwn(discovery, name)) throw new Error();
  if ((await get('/api/v1/capabilities')).status !== 401) throw new Error();
  directory = await mkdtemp(join(tmpdir(), 'vibestack-guide-check-'));
  const config = join(directory, 'profiles.json');
  const env = { PATH: process.env.PATH, VIBESTACK_CONFIG: config };
  const cli = (args, input = '') => new Promise((resolve, reject) => {
    const child = spawn(command, args, { env, stdio: ['pipe', 'pipe', 'pipe'], timeout: 45000 });
    const buffers = [];
    let size = 0, diagnostics = false;
    child.stdout.on('data', data => { size += data.length; if (size > 24 << 20) { child.kill(); reject(new Error()); } else buffers.push(data); });
    child.stderr.on('data', () => { diagnostics = true; });
    child.on('error', reject);
    child.on('close', code => {
      const text = Buffer.concat(buffers).toString('utf8');
      if (code !== 0 || diagnostics || text.includes(credential)) reject(new Error()); else resolve(text);
    });
    child.stdin.on('error', reject);
    child.stdin.end(input);
  });
  stage = 'native CLI connect';
  if ((await cli(['version'])).trim() !== discovery.version) throw new Error();
  await cli(['connect', '--name', 'guide', '--url', guideURL.origin, '--token-stdin'], credential + '\n');
  const selected = JSON.parse(await cli(['--profile', 'guide', 'capability', 'list']));
  if (selected.instance_id !== discovery.identity || !selected.capabilities.some(item => item.id === 'workspaceStatus')) throw new Error();
  const schema = JSON.parse(await cli(['--profile', 'guide', 'capability', 'schema']));
  if (schema.openapi !== '3.1.0') throw new Error();
  stage = 'authenticated generic CLI operation';
  const status = JSON.parse(await cli(['--profile', 'guide', 'capability', 'call', 'workspaceStatus']));
  if (status.instance_id !== discovery.identity || status.capability !== 'workspaceStatus' || !status.result) throw new Error();
  stage = 'independent MCP stdio operation';
  const transport = new StdioClientTransport({ command, args: ['--profile', 'guide', 'mcp'], env, stderr: 'pipe', maxBufferSize: 24 << 20 });
  let diagnostics = false;
  transport.stderr.on('data', () => { diagnostics = true; });
  const client = new Client({ name: 'vibestack-guide-bootstrap', version: '1' }, { capabilities: {} });
  try {
    await client.connect(transport);
    const { tools } = await client.listTools();
    if (!tools.some(tool => tool.name === 'workspaceStatus')) throw new Error();
    const result = await client.callTool({ name: 'workspaceStatus', arguments: {} });
    if (result.isError || result.structuredContent?.instance_id !== discovery.identity || result.structuredContent?.capability !== 'workspaceStatus' || JSON.stringify(result).includes(credential) || diagnostics) throw new Error();
  } finally { await client.close(); }
  console.log('PASS guide URL → Markdown/discovery/version → protected CLI connect → schema/status → independent MCP stdio status; no credential output');
}
main().catch(() => { console.error(`FAIL guide bootstrap at ${stage} (payload and credential details suppressed)`); process.exitCode = 1; }).finally(async () => {
  if (directory) await rm(directory, { recursive: true, force: true });
});
