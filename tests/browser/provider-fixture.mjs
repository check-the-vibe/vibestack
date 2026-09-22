import {readFile} from 'node:fs/promises';
const root = new URL('../../',import.meta.url);
export const origin = 'http://vibestack.test';
const fakeRFB = `export default class extends EventTarget {
 constructor(target){super();const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=800;target.append(canvas);window.__rfb=this;window.__rfbConnections=(window.__rfbConnections||0)+1;this.focusCalls=0;this.blurCalls=0;queueMicrotask(()=>this.dispatchEvent(new Event('connect')));}
 focus(){this.focusCalls++;} blur(){this.blurCalls++;} disconnect(){queueMicrotask(()=>this.dispatchEvent(new CustomEvent('disconnect',{detail:{clean:true}})));}
}`;
export async function providerFixture(page,{authenticated=true,password=true,owner=true,dropSubmit=false}={}) {
  const state={authenticated,password,owner,activations:0,submissions:[],approvalAnswers:[],passwordSubmissions:0,events:[],approvals:[],conversations:[],seq:0,dropSubmit};
  // A third provider identity verifies that the UI consumes catalog data, not
  // vendor-specific installer or launch logic. No real provider/model is used.
  const provider={id:'fixture',name:'Fixture Agent',version:'1.0',installed:false,phase:'idle',process:'stopped',authentication:'unknown',readiness:'unverified',models:[]};
  const other={...provider,id:'alternative',name:'Alternative Agent'};
  state.providers=[provider,other];
  state.emit=(kind,text,extra={})=>{
    const c=state.conversations.at(-1),op=c?.operations.at(-1);
    const event={sequence:++state.seq,kind,text,operation_id:op?.id||'',...extra};state.events.push(event);
    if(kind==='approval')state.approvals.push(event);
    if(kind==='completed'&&op)op.status=extra.outcome;
  };
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname;
    if(url.origin!==origin)return route.abort();
    const json=(value,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
    if(path==='/auth/session'){
      if(req.method()==='POST'){if(req.headers().authorization!=='Bearer disposable-browser-fixture')return json({error:{code:'unauthorized'}},401);state.authenticated=true;}
      if(req.method()==='DELETE'){state.authenticated=false;return json({});}
      return state.authenticated?json({authenticated:true,csrf:'fixture-csrf',instance_id:'a'.repeat(32),owner:state.owner}):json({error:{code:'unauthorized'}},401);
    }
    if(path==='/setup/api/state')return json({authentication:{password_configured:state.password}});
    if(path==='/setup/api/password'){
      if(req.headers()['x-vibestack-csrf']!=='fixture-csrf'||!state.owner)return json({error:{code:'forbidden'}},403);
      state.passwordSubmissions++;state.password=true;return json({authentication:{password_configured:true}});
    }
    const match=path.match(/^\/api\/v1\/capabilities\/([A-Za-z]+)\/invoke$/);
    if(match){
      if(!state.authenticated)return json({error:{code:'unauthorized'}},401);
      if(req.headers()['x-vibestack-csrf']!=='fixture-csrf'||req.headers()['x-vibestack-expected-instance']!=='a'.repeat(32))return json({error:{code:'forbidden'}},403);
      const id=match[1],input=req.postDataJSON();let result;
      const selected=state.providers.find(p=>p.id===input.provider);
      switch(id){
        case 'listProviders':result={providers:state.providers};break;
        case 'getProviderStatus':result={provider:selected};break;
        case 'activateProvider':state.activations++;Object.assign(selected,{installed:true,phase:'active',process:'running',authentication:'configured',models:[{id:'fixture/model',name:'Fixture Model',default:true}]});result={provider:selected};break;
        case 'stopProvider':Object.assign(selected,{phase:'stopped',process:'stopped'});result={provider:selected};break;
        case 'openProviderApp':result={opened:true};break;
        case 'listProviderConversations':result={conversations:state.conversations};break;
        case 'createProviderConversation':{
          let c=state.conversations.find(c=>c.id===input.id);
          if(!c){c={...input,status:'idle',operations:[],created_at:Date.now()};state.conversations.push(c);}
          result={conversation:c};break;
        }
        case 'submitProviderMessage':{
          state.submissions.push(input);const c=state.conversations.find(c=>c.id===input.conversation);
          c.operations.push({id:input.operation_id,status:'running',created_at:Date.now()});
          if(state.dropSubmit)return route.abort('failed');result={conversation:c};break;
        }
        case 'readProviderEvents':result={conversation:state.conversations.find(c=>c.id===input.conversation),events:state.events.filter(e=>e.sequence>(input.cursor||0)),cursor:state.seq,gap:state.gap||false,approvals:state.approvals};break;
        case 'answerProviderApproval':state.approvalAnswers.push(input);state.approvals=state.approvals.filter(a=>a.approval_id!==input.approval_id);result={answered:true};break;
        case 'interruptProviderTurn':{
          const c=state.conversations.find(c=>c.id===input.conversation);c.operations.find(o=>o.id===input.operation_id).status='interrupted';result={conversation:c};break;
        }
        default:return json({error:{code:'not_found'}},404);
      }
      return json({instance_id:'a'.repeat(32),capability:id,result});
    }
    if(path==='/novnc/core/rfb.js')return route.fulfill({contentType:'application/javascript',body:fakeRFB});
    if(path==='/api/v1/diagnostics/events')return json({});
    if(req.method()!=='GET')return json({error:{code:'forbidden'}},403);
    const mapped={'/':'desktop/launcher.html','/launcher.js':'desktop/launcher.js','/launcher.css':'desktop/launcher.css','/vnc/':'desktop/index.html'};
    const file=mapped[path]||(path.startsWith('/vnc/')?'desktop/'+path.slice(5):null);
    if(!file||file.includes('..'))return route.fulfill({status:404,body:''});
    try{const body=await readFile(new URL(file,root));return route.fulfill({contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',body});}
    catch{return route.fulfill({status:404,body:''});}
  });
  return state;
}
