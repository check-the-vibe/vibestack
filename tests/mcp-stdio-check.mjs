// Actual CLI subprocess + independent TypeScript SDK. Disposable acceptance only:
// creates one named probe file, submits jobs and captures a screenshot. Tokens
// stay in private files; stdout contains fixed test metadata, never tool payloads.
import { open, constants, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, isAbsolute } from 'node:path';
import { randomUUID } from 'node:crypto';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

let stage = 'configuration';
let privateDirectory;

async function main() {
  if (process.env.VIBESTACK_ALLOW_MUTATING_MCP_TESTS !== '1') throw new Error();
  const origin = new URL(process.env.VIBESTACK_MCP_BASE_URL);
  if (origin.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname) || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error();
  const command = process.env.VIBESTACK_MCP_CLI;
  if (!command || !isAbsolute(command)) throw new Error();
  const project = process.env.VIBESTACK_MCP_PROBE_PROJECT;
  const sourceRoot = process.env.VIBESTACK_MCP_SOURCE_ROOT;
  if (Boolean(project) !== Boolean(sourceRoot) || (project && (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(project) || !isAbsolute(sourceRoot)))) throw new Error();
  const file = await open(process.env.VIBESTACK_MCP_CREDENTIAL_FILE, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  let credential;
  try {
    const info = await file.stat();
    if (!info.isFile() || info.size > 4096 || info.nlink !== 1 || info.uid !== process.getuid() || (info.mode & 0o077)) throw new Error();
    credential = (await file.readFile('utf8')).trim();
    if (!/^vss_[A-Za-z0-9_-]{43}$/.test(credential)) throw new Error();
  } finally { await file.close(); }
  const response = await fetch(new URL('/.well-known/vibestack', origin), { redirect: 'error', signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error();
  const discovery = await response.json();
  if (discovery.kind !== 'workspace' || !/^[a-f0-9]{32}$/.test(discovery.identity)) throw new Error();
  privateDirectory = await mkdtemp(join(tmpdir(), 'vibestack-stdio-check-'));
  const config = join(privateDirectory, 'profiles.json');
  await writeFile(config, JSON.stringify({ version: 1, profiles: { acceptance: { name: 'acceptance', kind: 'workspace', authentication_mode: 'paired', identity: discovery.identity, url: origin.origin, credential } } }), { mode: 0o600, flag: 'wx' });
  const transport = new StdioClientTransport({ command, args: ['--profile', 'acceptance', 'mcp'], env: { VIBESTACK_CONFIG: config }, stderr: 'pipe', maxBufferSize: 24 << 20 });
  let diagnostics = false;
  transport.stderr.on('data', () => { diagnostics = true; });
  const client = new Client({ name: 'vibestack-stdio-acceptance', version: '1' }, { capabilities: {} });
  const call = async (name, args) => {
    const value = await client.callTool({ name, arguments: args });
    if (value.isError || value.structuredContent?.capability !== name || value.structuredContent?.instance_id !== discovery.identity) throw new Error();
    // Only test fixtures are handled here; never print returned data.
    if (JSON.stringify(value).includes(credential)) throw new Error();
    return value.structuredContent.result;
  };
  const job = async (argv) => {
    let { job } = await call('submitArgvCommand', { argv, root: 'projects', timeout_seconds: 30 });
    if (!/^[0-9a-f]{32}$/.test(job?.id)) throw new Error();
    const id = job.id;
    for (let count = 0; count < 100 && ['queued', 'running'].includes(job.status); count++) {
      await new Promise(resolve => setTimeout(resolve, 100));
      ({ job } = await call('getWorkspaceJob', { id }));
      if (job.id !== id) throw new Error();
    }
    if (job.status !== 'succeeded' || job.exit_code !== 0) throw new Error();
    return id;
  };
  const filename = `vst-stdio-probe-${randomUUID()}.txt`;
  const path = project ? `${project}/${filename}` : filename;
  let created = false;
  try {
    stage = 'stdio connection';
    await client.connect(transport);
    stage = 'tool coverage';
    const { tools } = await client.listTools();
    const names = new Set(tools.map(tool => tool.name));
    for (const name of ['workspaceStatus', 'submitArgvCommand', 'getWorkspaceJob', 'getWorkspaceJobOutput', 'readProjectFile', 'writeProjectFile', 'captureWorkspaceScreenshot']) if (!names.has(name)) throw new Error();
    for (const name of ['setLinuxPassword', 'readWorkspaceClipboard', 'writeWorkspaceClipboard', 'addWorkspaceSSHKey', 'listWorkspaceClients', 'instance_create', 'host_inspect']) if (names.has(name)) throw new Error();
    stage = 'workspace status';
    await call('workspaceStatus', {});
    stage = 'argv job and output';
    const id = await job(['/usr/bin/printf', 'vst-stdio-job-ok']);
    const output = await call('getWorkspaceJobOutput', { id, stream: 'stdout', limit: 128 });
    if (output.encoding !== 'base64' || Buffer.from(output.data, 'base64').toString('utf8') !== 'vst-stdio-job-ok' || !output.eof) throw new Error();
    stage = 'conditional project file';
    const first = Buffer.from('vst-stdio-created\n');
    await call('writeProjectFile', { path, data_base64: first.toString('base64'), if_none_match: '*' });
    created = true;
    const initial = await call('readProjectFile', { path });
    if (!Buffer.from(initial.data_base64, 'base64').equals(first)) throw new Error();
    const updated = Buffer.from('vst-stdio-updated\n');
    await call('writeProjectFile', { path, data_base64: updated.toString('base64'), if_match: initial.etag });
    const stale = await client.callTool({ name: 'writeProjectFile', arguments: { path, data_base64: first.toString('base64'), if_match: initial.etag } });
    if (!stale.isError || stale.structuredContent?.error?.code !== 'precondition_failed') throw new Error();
    const current = await call('readProjectFile', { path });
    if (!Buffer.from(current.data_base64, 'base64').equals(updated)) throw new Error();
    if (sourceRoot) {
      stage = 'shared source visibility';
      const visible = await open(join(sourceRoot, filename), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
      try {
        const info = await visible.stat();
        if (!info.isFile() || info.nlink !== 1 || info.size !== updated.length || !(await visible.readFile()).equals(updated)) throw new Error();
      } finally { await visible.close(); }
    }
    stage = 'screenshot';
    const screenshot = await call('captureWorkspaceScreenshot', {});
    const png = Buffer.from(screenshot.data_base64, 'base64');
    if (screenshot.content_type !== 'image/png' || !png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) throw new Error();
    stage = 'cleanup';
    await job(['/usr/bin/rm', '--', `/projects/${path}`]);
    created = false;
    if (diagnostics) throw new Error();
    console.log('PASS TypeScript SDK 1.30.0 → CLI stdio → authenticated HTTP: tool coverage, status, argv job/output, conditional project update, stale-write denial, PNG screenshot; no diagnostic or credential output');
    if (sourceRoot) console.log('PASS MCP project update was visible in the outer source checkout; probe file removed');
  } finally {
    if (created) { try { await job(['/usr/bin/rm', '--', `/projects/${path}`]); } catch { /* disposable fixture cleanup owns the remaining file */ } }
    await client.close();
  }
}

main().catch(() => { console.error(`FAIL stdio client verification at ${stage} (credential and payload details suppressed)`); process.exitCode = 1; }).finally(async () => {
  if (privateDirectory) await rm(privateDirectory, { recursive: true, force: true });
});
