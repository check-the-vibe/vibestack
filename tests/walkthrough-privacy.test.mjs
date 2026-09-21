// Isolated instrumentation contract; no live password or onboarding mutations.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source=readFileSync(new URL('../desktop/walkthrough.js',import.meta.url),'utf8');
function harness(enabled=true, Socket=class { addEventListener(){} }) {
  const events=[], calls=[], listeners={};
  const storage=new Map();
  const window={fetch:async (...args)=>{calls.push(args);return {status:200,ok:true,json:async()=>({csrf:'csrf-sentinel'})};},WebSocket:Socket,addEventListener:(name,fn)=>{listeners[name]=fn;}};
  const document={addEventListener(){},getElementById(){return null;}};
  const context={window,document,URL,location:{href:'https://example.test/setup/'+(enabled?'?walkthrough=1':''),pathname:'/setup/',host:'example.test'},crypto:{randomUUID:()=> 'abcdef01-abcd-abcd-abcd-abcdef012345'},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},performance:{now:()=>5},MutationObserver:class{observe(){}}};
  vm.runInNewContext(source, context);
  return {window,listeners,calls,events:()=>calls.filter(x=>x[0]==='/api/v1/diagnostics/events').map(x=>JSON.parse(x[1].body))};
}
test('disabled by default',async()=>{
  const h=harness(false);
  await h.window.fetch('/setup/api/state');
  assert.equal(h.events().length,0);
});
test('bodies, queries and exception messages never enter diagnostics',async()=>{
  const h=harness();
  const body=JSON.stringify({privateContent:'content-sentinel'});
  await h.window.fetch('/setup/api/state?token=query-sentinel',{method:'POST',body});
  h.listeners.error({target:h.window,error:{name:'TypeError',message:'exception-sentinel'},lineno:3,colno:4});
  await new Promise(setImmediate);
  const serialized=JSON.stringify(h.events());
  for(const secret of ['content-sentinel','query-sentinel','exception-sentinel','csrf-sentinel']) assert.ok(!serialized.includes(secret));
  assert.ok(h.events().some(e=>e.kind==='request'&&e.endpoint==='/setup/api/state'&&e.status===200));
  assert.equal(h.calls.find(x=>x[0].includes('query-sentinel'))[1].body,body);
});

test('socket logging preserves the native instance prototype required by noVNC',async()=>{
  class NativeSocket {
    static OPEN=1;
    constructor() { this.binaryType='blob'; this.onerror=null; this.onmessage=null; this.onopen=null; this.protocol=''; this.readyState=0; this.listeners={}; }
    send() {}
    close() {}
    addEventListener(kind, listener) { this.listeners[kind]=listener; }
  }
  const h=harness(true,NativeSocket);
  const socket=new h.window.WebSocket('wss://example.test/vnc/websockify');
  assert.equal(Object.getPrototypeOf(socket),NativeSocket.prototype);
  assert.ok(socket instanceof NativeSocket);
  assert.ok(socket instanceof h.window.WebSocket);
  assert.equal(h.window.WebSocket.OPEN,1);
  // This is noVNC 1.7's raw channel compatibility check, including own prototype methods.
  const properties=[...Object.keys(socket),...Object.getOwnPropertyNames(Object.getPrototypeOf(socket))];
  for(const key of ['send','close','binaryType','onerror','onmessage','onopen','protocol','readyState']) assert.ok(properties.includes(key),key);
  socket.listeners.open();
  await new Promise(setImmediate);
  assert.ok(h.events().some(e=>e.kind==='socket_open'&&e.endpoint==='/vnc/websockify'));
});
