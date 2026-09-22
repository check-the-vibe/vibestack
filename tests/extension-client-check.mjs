// Called only by extension-authoring-check.py for its disposable container.
import {constants, open, mkdtemp, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {isAbsolute, join} from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from '@playwright/test';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';

let stage = 'configuration', directory, browser;
const clients = [];
const check = value => { if (!value) throw new Error('extension invariant'); };
async function readCredential(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await file.stat();
    check(info.isFile() && info.nlink === 1 && info.uid === process.getuid() && !(info.mode & 0o077) && info.size < 4096);
    const value = (await file.readFile('utf8')).trim();
    check(/^vss_[A-Za-z0-9_-]{43}$/.test(value));
    return value;
  } finally { await file.close(); }
}
async function main() {
  check(process.env.VIBESTACK_DISPOSABLE_EXTENSION_TEST === '1');
  const mode = process.argv[2];
  check(['absent','present'].includes(mode));
  const present = mode === 'present', id = 'acceptance_echo', route = '/api/v1/acceptance-echo';
  const origin = new URL(process.env.VIBESTACK_MCP_BASE_URL);
  check(origin.protocol === 'http:' && ['127.0.0.1','localhost'].includes(origin.hostname) && origin.pathname === '/' && !origin.username && !origin.password && !origin.search && !origin.hash);
  const binary = process.env.VIBESTACK_MCP_CLI;
  check(isAbsolute(binary || ''));
  const owner = await readCredential(process.env.VIBESTACK_MCP_CREDENTIAL_FILE);
  const scoped = await readCredential(process.env.VIBESTACK_PARITY_SCOPED_FILE);
  const request = async (path, options = {}) => {
    const response = await fetch(new URL(path, origin), {...options, redirect:'error', signal:AbortSignal.timeout(15000)});
    const text = await response.text();
    check(text.length < 1 << 20 && !text.includes(owner) && !text.includes(scoped));
    return {status:response.status, value:JSON.parse(text)};
  };
  const identity = (await request('/.well-known/vibestack')).value.identity;
  check(/^[a-f0-9]{32}$/.test(identity));
  const headers = token => ({Authorization:`Bearer ${token}`, 'Content-Type':'application/json', 'X-VibeStack-Expected-Instance':identity});
  directory = await mkdtemp(join(tmpdir(),'vibestack-extension-clients-'));
  const config = join(directory,'profiles.json');
  const profiles = Object.fromEntries(Object.entries({owner,scoped}).map(([name,credential]) => [name,{name,kind:'workspace',authentication_mode:'paired',identity,url:origin.origin,credential}]));
  await writeFile(config,JSON.stringify({version:1,profiles}),{mode:0o600,flag:'wx'});
  const cli = (profile,args,input) => new Promise((resolve,reject) => {
    const child = spawn(binary,['--profile',profile,'capability',...args],{env:{VIBESTACK_CONFIG:config},stdio:['pipe','pipe','pipe'],timeout:20000});
    let output='',diagnostics='';
    child.stdout.on('data',chunk=>{output+=chunk;if(output.length>1<<20)child.kill();});
    child.stderr.on('data',chunk=>{diagnostics+=chunk;if(diagnostics.length>8192)child.kill();});
    child.on('error',reject); child.stdin.on('error',reject);
    child.on('close',code=>{
      try {
        check(![output,diagnostics].some(text=>text.includes(owner)||text.includes(scoped)));
        if(code===0) {check(!diagnostics);resolve(JSON.parse(output));}
        else {const error=/^vibestack: ([a-z_]+):/.exec(diagnostics);check(!output&&error);resolve({error:{code:error[1]}});}
      }catch{reject(new Error('CLI result'));}
    });
    child.stdin.end(input ? JSON.stringify(input) : '');
  });
  browser = await chromium.launch({headless:true});
  for (const [name,token] of Object.entries({owner,scoped})) {
    stage = `${mode} ${name} discovery`;
    const client = new Client({name:'vibestack-extension-demo',version:'1'},{capabilities:{}});
    clients.push(client);
    await client.connect(new StreamableHTTPClientTransport(new URL('/mcp',origin),{requestInit:{headers:headers(token),redirect:'error'},reconnectionOptions:{maxRetries:0}}));
    const catalog = (await request('/api/v1/capabilities',{headers:headers(token)})).value.capabilities;
    const schema = (await request('/api/capabilities.openapi.json',{headers:headers(token)})).value;
    const advertised = present && name === 'owner';
    check(catalog.some(entry=>entry.id===id)===advertised);
    check((await client.listTools()).tools.some(tool=>tool.name===id)===advertised);
    check(Boolean(schema.paths[route])===advertised);
    check((await cli(name,['list'])).capabilities.some(entry=>entry.id===id)===advertised);
    const context = await browser.newContext();
    const response = await fetch(new URL('/auth/session',origin),{method:'POST',headers:headers(token),redirect:'error'});
    check(response.ok);
    const cookie = response.headers.getSetCookie().find(value=>value.startsWith('vibestack_session='))?.split(';',1)[0].split('=',2)[1];
    check(cookie);
    await context.addCookies([{name:'vibestack_session',value:cookie,url:origin.origin,httpOnly:true,sameSite:'Strict'}]);
    const page = await context.newPage();
    await page.goto(new URL('/status.txt',origin).href);
    const calls = {
      rest:async input=>(await request(`/api/v1/capabilities/${id}/invoke`,{method:'POST',headers:headers(token),body:JSON.stringify(input)})).value,
      friendly:async input=>(await request(route,{method:'POST',headers:headers(token),body:JSON.stringify(input)})).value,
      mcp:async input=>(await client.callTool({name:id,arguments:input})).structuredContent,
      cli:input=>cli(name,['call',id,'--input','-'],input),
      web:input=>page.evaluate(async ({id,input,identity})=>{
        const session=await(await fetch('/auth/session')).json();
        return(await fetch(`/api/v1/capabilities/${id}/invoke`,{method:'POST',headers:{'Content-Type':'application/json','X-VibeStack-CSRF':session.csrf,'X-VibeStack-Expected-Instance':identity},body:JSON.stringify(input)})).json();
      },{id,input,identity}),
    };
    for (const [surface,call] of Object.entries(calls)) {
      stage = `${mode} ${name} ${surface} invocation`;
      const result=await call({message:'extension-demo'});
      if(advertised) {
        check(result.instance_id===identity && result.capability===id && result.result.message==='extension-demo' && !result.error);
        check((await call({message:'extension-demo',unexpected:true})).error?.code==='invalid_input');
      } else check(result.error?.code===(present?'forbidden':'not_found'));
    }
    await context.close();
  }
  stage='unauthenticated new route';
  if(present) for(const extra of [{},{Authorization:'Bearer invalid'},{'X-Forwarded-User':'owner'}]) {
    check((await request(route,{method:'POST',headers:{'Content-Type':'application/json',...extra},body:'{"message":"extension-demo"}'})).status===401);
  }
  console.log(`PASS extension ${mode}: REST, MCP, CLI, Chromium session, schema and grant parity`);
}
main().catch(()=>{console.error(`FAIL extension clients at ${stage} (private payloads suppressed)`);process.exitCode=1;}).finally(async()=>{
  for(const client of clients){try{await client.close();}catch{}}
  await browser?.close();
  if(directory)await rm(directory,{recursive:true,force:true});
});
