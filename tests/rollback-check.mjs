// Checks accepted image changes on disposable mounts; never targets live state.
import { constants, open, writeFile, readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { isAbsolute } from 'node:path';
let stage='configuration';
async function main(){
  const phase=process.argv[2], snapshot=process.env.VIBESTACK_ROLLBACK_SNAPSHOT;
  if(!['prepare','previous','candidate'].includes(phase)||!isAbsolute(snapshot??'')||process.env.VIBESTACK_ALLOW_MUTATING_MCP_TESTS!=='1')throw new Error();
  const origin=new URL(process.env.VIBESTACK_MCP_BASE_URL);
  if(origin.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(origin.hostname)||origin.pathname!=='/'||origin.username||origin.password||origin.search||origin.hash)throw new Error();
  const file=await open(process.env.VIBESTACK_MCP_CREDENTIAL_FILE,constants.O_RDONLY|constants.O_NONBLOCK|constants.O_NOFOLLOW);
  let credential;
  try{const s=await file.stat();if(!s.isFile()||s.nlink!==1||s.uid!==process.getuid()||s.mode&0o077||s.size>4096)throw new Error();credential=(await file.readFile('utf8')).trim();if(!/^vss_[A-Za-z0-9_-]{43}$/.test(credential))throw new Error();}finally{await file.close();}
  const discovery=await(await fetch(new URL('/.well-known/vibestack',origin),{redirect:'error'})).json();
  const identity=discovery.identity;
  if(!/^[a-f0-9]{32}$/.test(identity))throw new Error();
  const call=async(name,input)=>{
    const response=await fetch(new URL(`/api/v1/capabilities/${name}/invoke`,origin),{method:'POST',headers:{Authorization:`Bearer ${credential}`,'Content-Type':'application/json','X-VibeStack-Expected-Instance':identity},body:JSON.stringify(input),redirect:'error',signal:AbortSignal.timeout(15000)});
    const value=await response.json();if(!response.ok||value.error||value.instance_id!==identity||JSON.stringify(value).includes(credential))throw new Error();return value.result;
  };
  let saved;
  stage=phase;
  if(phase==='prepare'){
    const path=`vst-rollback-${randomUUID()}.txt`, content='rollback-persistence-fixture';
    await call('writeProjectFile',{path,data_base64:Buffer.from(content).toString('base64'),if_none_match:'*'});
    const current=await call('readProjectFile',{path});
    let {job}=await call('submitArgvCommand',{argv:['/usr/bin/true'],root:'projects',timeout_seconds:30});
    for(let n=0;n<100&&['queued','running'].includes(job.status);n++){await new Promise(resolve=>setTimeout(resolve,50));({job}=await call('getWorkspaceJob',{id:job.id}));}
    if(job.status!=='succeeded')throw new Error();
    saved={identity,path,content,etag:current.etag,job:job.id};
    await writeFile(snapshot,JSON.stringify(saved),{mode:0o600,flag:'wx'});
  }else{saved=JSON.parse(await readFile(snapshot,'utf8'));}
  if(saved.identity!==identity)throw new Error();
  await call('workspaceStatus',{});
  const current=await call('readProjectFile',{path:saved.path});
  const {job}=await call('getWorkspaceJob',{id:saved.job});
  if(current.etag!==saved.etag||Buffer.from(current.data_base64,'base64').toString('utf8')!==saved.content||job.id!==saved.job||job.status!=='succeeded')throw new Error();
  console.log(`PASS disposable ${phase}: service identity, existing credential, project bytes/ETag and completed job preserved`);
}
main().catch(()=>{console.error(`FAIL disposable rollback at ${stage} (payload and credential details suppressed)`);process.exitCode=1;});
