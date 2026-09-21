// Fault injection ahead of the real nginx origin. Disposable fixtures only:
// no payloads, credentials, command output or SDK exception details are logged.
import { constants, open, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, isAbsolute } from 'node:path';
import { randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

let stage = 'configuration', directory, proxy;
const clients = [], held = new Set();
const check = condition => { if (!condition) throw new Error(); };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
  check(process.env.VIBESTACK_ALLOW_MUTATING_MCP_TESTS === '1');
  const origin = new URL(process.env.VIBESTACK_MCP_BASE_URL);
  check(origin.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname) && origin.pathname === '/' && !origin.username && !origin.password && !origin.search && !origin.hash);
  const command = process.env.VIBESTACK_MCP_CLI;
  check(isAbsolute(command ?? ''));
  const file = await open(process.env.VIBESTACK_MCP_CREDENTIAL_FILE, constants.O_RDONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
  let credential;
  try {
    const stat = await file.stat();
    check(stat.isFile() && stat.nlink === 1 && stat.uid === process.getuid() && !(stat.mode & 0o077) && stat.size <= 4096);
    credential = (await file.readFile('utf8')).trim();
    check(/^vss_[A-Za-z0-9_-]{43}$/.test(credential));
  } finally { await file.close(); }
  const discovery = await (await fetch(new URL('/.well-known/vibestack', origin), { redirect:'error' })).json();
  const identity = discovery.identity;
  check(/^[a-f0-9]{32}$/.test(identity));
  const headers = { Authorization:`Bearer ${credential}`, 'Content-Type':'application/json', 'X-VibeStack-Expected-Instance':identity };
  const direct = async (name, input) => {
    const response = await fetch(new URL(`/api/v1/capabilities/${name}/invoke`, origin), { method:'POST', headers, body:JSON.stringify(input), redirect:'error', signal:AbortSignal.timeout(15000) });
    const value = await response.json();
    check(value.instance_id === identity && !JSON.stringify(value).includes(credential));
    return value;
  };
  const result = async (name, input) => { const value = await direct(name,input); check(value.result && !value.error); return value.result; };
  let fault = null, intercepted = null, counts = new Map();
  proxy = createServer(async (request,response) => {
    try {
      check(request.url === '/mcp' || /^\/api\/v1\/capabilities\/[A-Za-z][A-Za-z0-9_]{0,63}\/invoke$/.test(request.url));
      const chunks = []; let size = 0;
      for await (const chunk of request) { size += chunk.length; check(size <= 1 << 20); chunks.push(chunk); }
      const body = Buffer.concat(chunks);
      let frame, name;
      if (body.length) {
        frame = JSON.parse(body);
        name = request.url === '/mcp' ? (frame.method === 'tools/call' ? frame.params.name : undefined) : request.url.split('/')[4];
      }
      if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
      const upstreamHeaders = {};
      for (const key of ['authorization','content-type','accept','mcp-protocol-version','x-vibestack-expected-instance']) if (request.headers[key]) upstreamHeaders[key] = request.headers[key];
      const upstream = await fetch(new URL(request.url,origin), { method:request.method, headers:upstreamHeaders, body:body.length ? body : undefined, redirect:'error', signal:AbortSignal.timeout(30000) });
      const bytes = Buffer.from(await upstream.arrayBuffer());
      check(bytes.length <= 24 << 20);
      if (fault && fault.name === name) {
        const selected = fault; fault = null;
        const value = JSON.parse(bytes.toString('utf8'));
        intercepted = request.url === '/mcp' ? value.result.structuredContent : value;
        if (selected.kind === 'drop') { response.destroy(); return; }
        if (selected.kind === 'hold') { held.add(response); response.on('close',()=>held.delete(response)); return; }
        if (selected.kind === 'partial') {
          response.writeHead(upstream.status, { 'Content-Type':upstream.headers.get('content-type'), 'Content-Length':bytes.length });
          response.write(bytes.subarray(0,Math.max(1,bytes.length/2)),()=>response.destroy());
          return;
        }
      }
      response.writeHead(upstream.status, { 'Content-Type':upstream.headers.get('content-type') ?? 'application/json' });
      response.end(bytes);
    } catch { response.destroy(); }
  });
  await new Promise(resolve=>proxy.listen(0,'127.0.0.1',resolve));
  const proxyOrigin = `http://127.0.0.1:${proxy.address().port}`;
  directory = await mkdtemp(join(tmpdir(),'vibestack-recovery-'));
  const config = join(directory,'profiles.json');
  await writeFile(config,JSON.stringify({version:1,profiles:{fixture:{name:'fixture',kind:'workspace',authentication_mode:'paired',identity,url:proxyOrigin,credential}}}),{mode:0o600,flag:'wx'});
  const runCLI = (name,input) => new Promise((resolve,reject)=>{
    const child = spawn(command,['--profile','fixture','capability','call',name,'--input','-'],{env:{PATH:process.env.PATH,VIBESTACK_CONFIG:config},stdio:['pipe','pipe','pipe'],timeout:15000});
    let out='', diagnostics='';
    child.stdout.on('data',data=>{out+=data;if(out.length>24<<20)child.kill();});
    child.stderr.on('data',data=>{diagnostics+=data;if(diagnostics.length>8192)child.kill();});
    child.on('error',reject); child.stdin.on('error',reject);
    child.on('close',code=>{
      try {
        if ((out+diagnostics).includes(credential)) reject(new Error());
        else resolve({failed:code!==0,value:code===0?JSON.parse(out):null});
      } catch { reject(new Error()); }
    });
    child.stdin.end(JSON.stringify(input));
  });
  let unexpectedDiagnostics=false;
  const mcpClient = async kind => {
    const client = new Client({name:`vibestack-recovery-${kind}`,version:'1'},{capabilities:{}});
    clients.push(client);
    let transport;
    if(kind==='stdio') {
      transport = new StdioClientTransport({command,args:['--profile','fixture','mcp'],env:{PATH:process.env.PATH,VIBESTACK_CONFIG:config},stderr:'pipe',maxBufferSize:24<<20});
      transport.stderr.on('data',()=>{unexpectedDiagnostics=true;});
    } else {
      transport = new StreamableHTTPClientTransport(new URL('/mcp',proxyOrigin),{requestInit:{headers,redirect:'error'},reconnectionOptions:{maxRetries:0}});
    }
    await client.connect(transport);
    return async (name,input,options={})=>{
      try {
        const value = await client.callTool({name,arguments:input},undefined,{timeout:5000,...options});
        check(!JSON.stringify(value).includes(credential));
        return {failed:Boolean(value.isError),value:value.structuredContent};
      } catch { return {failed:true}; }
    };
  };
  const finish = async id => {
    let job;
    for(let n=0;n<200;n++) {
      ({job}=await result('getWorkspaceJob',{id}));
      if(!['queued','running'].includes(job.status))return job;
      await delay(50);
    }
    throw new Error();
  };
  const probe = `vst-recovery-${randomUUID()}`;
  const appendInput = (path,seconds=0)=>({argv:['/usr/bin/python3','-c',`import time; time.sleep(${seconds}); open(${JSON.stringify('/projects/'+path)},'a').write('execution\\n')`],root:'projects',timeout_seconds:30});
  const fileText = async path => Buffer.from((await result('readProjectFile',{path})).data_base64,'base64').toString('utf8');
  for(const kind of ['http','stdio','cli']) {
    stage = `${kind} dropped accepted command reply`;
    const call = kind==='cli' ? runCLI : await mcpClient(kind);
    const path = `${probe}-${kind}.txt`;
    counts = new Map(); intercepted = null; fault={name:'submitArgvCommand',kind:'drop'};
    const response = await call('submitArgvCommand',appendInput(path));
    check(response.failed && intercepted?.result?.job?.id && counts.get('submitArgvCommand')===1);
    const job = await finish(intercepted.result.job.id);
    check(job.status==='succeeded' && await fileText(path)==='execution\n');
    await delay(100);
    check(counts.get('submitArgvCommand')===1);
  }
  const call = await mcpClient('http');
  stage = 'truncated response';
  counts = new Map(); fault={name:'workspaceStatus',kind:'partial'};
  check((await call('workspaceStatus',{})).failed && counts.get('workspaceStatus')===1);
  stage = 'cancelled request preserves accepted job until explicit cancellation';
  const controller = new AbortController();
  counts = new Map(); intercepted=null; fault={name:'submitArgvCommand',kind:'hold'};
  const pending = call('submitArgvCommand',appendInput(`${probe}-cancel.txt`,10),{signal:controller.signal});
  for(let n=0;n<100&&!intercepted;n++)await delay(50);
  check(intercepted?.result?.job?.id);
  const id = intercepted.result.job.id;
  controller.abort(); check((await pending).failed);
  const running = await result('getWorkspaceJob',{id});
  check(['queued','running'].includes(running.job.status) && counts.get('submitArgvCommand')===1);
  await result('cancelWorkspaceJob',{id});
  check((await finish(id)).status==='cancelled');
  stage = 'explicit duplicate commands have distinct jobs and execute once each';
  const duplicatePath = `${probe}-duplicate.txt`, input = appendInput(duplicatePath);
  const first = await result('submitArgvCommand',input), second = await result('submitArgvCommand',input);
  check(first.job.id!==second.job.id);
  check((await finish(first.job.id)).status==='succeeded' && (await finish(second.job.id)).status==='succeeded');
  check(await fileText(duplicatePath)==='execution\nexecution\n');
  stage = 'lost conditional write reply and explicit retry precondition';
  const conditionalPath=`${probe}-conditional.txt`, write={path:conditionalPath,data_base64:Buffer.from('conditional').toString('base64'),if_none_match:'*'};
  counts = new Map(); fault={name:'writeProjectFile',kind:'drop'};
  check((await call('writeProjectFile',write)).failed && counts.get('writeProjectFile')===1);
  check(await fileText(conditionalPath)==='conditional');
  check((await direct('writeProjectFile',write)).error?.code==='precondition_failed');
  stage = 'bounded job output retains honest truncation metadata';
  const outputJob=await result('submitArgvCommand',{argv:['/usr/bin/python3','-c','import sys; sys.stdout.buffer.write(b"x" * (4 * 1024 * 1024 + 1))'],root:'projects',timeout_seconds:30});
  const outputDone=await finish(outputJob.job.id);
  check(outputDone.status==='succeeded' && outputDone.output.stdout_bytes===4*1024*1024 && outputDone.output.stdout_truncated===true);
  const last=await result('getWorkspaceJobOutput',{id:outputJob.job.id,stream:'stdout',cursor:4*1024*1024-128,limit:256});
  check(last.eof===true && last.truncated===true && Buffer.from(last.data,'base64').toString('utf8')==='x'.repeat(128));
  stage = 'nginx framing and anonymous admission';
  const raw = JSON.stringify({jsonrpc:'2.0',id:'x'.repeat(65536),method:'tools/call',params:{name:'workspaceStatus',arguments:{}}});
  const oversized = await fetch(new URL('/mcp',origin),{method:'POST',headers:{...headers,Accept:'application/json, text/event-stream'},body:raw,redirect:'error'});
  const denied=await oversized.text(); check(oversized.status===413 && denied.length<2048 && denied.includes('limit_exceeded'));
  const anonymous = await fetch(new URL('/mcp',origin),{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',redirect:'error'});
  check(anonymous.status===401);
  check(!unexpectedDiagnostics);
  console.log('PASS real nginx faults: dropped accepted replies over HTTP MCP, CLI stdio and generic CLI did not replay; truncation failed honestly; request cancellation preserved the job until explicit cancel; duplicates and conditional retries followed their contracts; framing stayed bounded');
}
main().catch(()=>{console.error(`FAIL MCP recovery at ${stage} (payload and credential details suppressed)`);process.exitCode=1;}).finally(async()=>{
  for(const response of held)response.destroy();
  for(const client of clients){try{await client.close();}catch{}}
  if(proxy){proxy.closeAllConnections();await new Promise(resolve=>proxy.close(resolve));}
  if(directory)await rm(directory,{recursive:true,force:true});
});
