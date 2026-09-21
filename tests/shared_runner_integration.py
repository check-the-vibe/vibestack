#!/usr/bin/env python3
"""Disposable trusted-tailnet acceptance. Secrets stay in RAM/stdin only.
Never targets the live registry; removes only this registry's exact resources.
"""
import argparse
import base64
import http.client
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = '/api/v1/runner'

def command(*args, input=None, expected=0, env=None):
    result = subprocess.run(args, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode != expected:
        raise RuntimeError('local command failed: ' + args[0])
    return result.stdout

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runner', required=True)
    parser.add_argument('--client', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--public-host', default='server.tail14a7e5.ts.net')
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    folder = Path(tempfile.mkdtemp(prefix='vibestack-shared-integration-'))
    config, state = folder/'config.json', folder/'state'
    local = 'http://127.0.0.1:18089'
    public = 'https://'+args.public_host+':13443'
    before = json.loads(command('tailscale','serve','status','--json'))
    assert not any(k.endswith(':13443') or any(k.endswith(':'+str(p)) for p in range(13080,13180)) for k in before.get('Web',{}))
    command(args.runner,'init','--config',str(config),'--state-dir',str(state))
    cfg=json.loads(config.read_text())
    cfg.update(authentication_mode='trusted-tailnet',listen='127.0.0.1:18089',public_url=public,port_min=13080,port_max=13179,max_instances=4,default_memory_bytes=2<<30,default_nano_cpus=1_000_000_000,manage_tailscale_serve=True)
    config.write_text(json.dumps(cfg))
    command(args.runner,'templates','--config',str(config),'add','desktop',args.image)
    process=None
    log=open(folder/'runner.log','ab')
    instances=[]
    passwords=[secrets.token_urlsafe(32),secrets.token_urlsafe(32)]
    def request(method,path,body=None,expected=None,base=public,headers=None):
        data=None if body is None else json.dumps(body).encode()
        h={'Content-Type':'application/json'};h.update(headers or {})
        req=urllib.request.Request(base+path,data=data,headers=h,method=method)
        try:
            with urllib.request.urlopen(req,timeout=70) as response: status,raw=response.status,response.read()
        except urllib.error.HTTPError as error: status,raw=error.code,error.read()
        if expected is not None: assert status==expected,(path,status,expected)
        elif status>=400: raise RuntimeError('HTTP '+str(status)+' '+path+' '+raw.decode()[:300])
        if not raw:return None
        if raw.startswith(b'\x89PNG'):return raw
        try:return json.loads(raw)
        except json.JSONDecodeError:
            if expected is not None and expected>=400:return raw
            raise
    def api(method,path,body=None,expected=None,headers=None):return request(method,ROOT+path,body,expected,headers=headers)
    def start():
        nonlocal process
        process=subprocess.Popen([args.runner,'serve','--config',str(config)],stdout=log,stderr=log)
        for _ in range(60):
            if process.poll() is not None:raise RuntimeError('runner exited')
            try:request('GET','/.well-known/vibestack',base=local);return
            except OSError:time.sleep(1)
        raise RuntimeError('runner unavailable')
    def stop():
        nonlocal process
        if process is not None:process.terminate();process.wait(timeout=60);process=None
    def wait(op):
        for _ in range(420):
            op=tool('operation_get',{'operation_id':op['id']})['operation']
            if op['status']=='succeeded':return op
            if op['status']=='failed':raise RuntimeError('operation failed: '+op.get('error_message',''))
            time.sleep(1)
        raise RuntimeError('operation timed out')
    def get(i):return api('GET','/instances/'+i['id'])['instance']
    def action(i,kind):return wait(tool('instance_action',{'instance_id':i['id'],'action':kind})['operation'])
    def mcp(method,params,ident=1,expected=None,headers=None):
        body={'jsonrpc':'2.0','method':method,'params':params}
        if ident is not None:body['id']=ident
        h={'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-03-26'};h.update(headers or {})
        return request('POST','/mcp',body,expected,headers=h)
    def tool(name,arguments):
        value=mcp('tools/call',{'name':name,'arguments':arguments})
        if 'error' in value:raise RuntimeError('MCP protocol failed '+str(value['error']))
        result=value['result']
        assert not result.get('isError'),result
        if 'structuredContent' in result:return result['structuredContent']
        return json.loads(result['content'][0]['text'])
    def linux_auth(i,password,ok=True):
        result=subprocess.run(['docker','exec','-i','-u','vibe',i['container_id'],'sudo','-S','-k','-p','','/usr/bin/true'],input=(password+'\n').encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        assert (result.returncode==0)==ok,'Linux authentication mismatch'
    def leaks():
        log.flush()
        blobs=[(folder/'runner.log').read_bytes()]
        blobs.extend(p.read_bytes() for p in state.glob('runner.db*'))
        for i in instances:
            current=get(i)
            blobs.append(command('docker','inspect',current['container_id']))
            blobs.append(command('docker','logs',current['container_id']))
            script="""import json,sys
from pathlib import Path
secrets=json.load(sys.stdin)
for p in Path('/data/logs/vibestack').rglob('*'):
 if p.is_file():
  b=p.read_bytes()
  assert all(s.encode() not in b for s in secrets), 'plaintext found in shared logs'
"""
            command('docker','exec','-i',current['container_id'],'python3','-c',script,input=json.dumps(passwords).encode())
        assert all(secret.encode() not in blob for secret in passwords for blob in blobs),'plaintext leaked'
    try:
        start();command('tailscale','serve','--bg','--https=13443',local)
        discovery=request('GET','/.well-known/vibestack')
        assert discovery['authentication_mode']=='trusted-tailnet' and discovery['mcp_url']==public+'/mcp' and 'pairing' not in discovery
        profiles=[]
        for n in range(2):
            env=dict(os.environ,VIBESTACK_CONFIG=str(folder/('client'+str(n))/'profiles.json'))
            command(args.client,'connect','--url',public,'--name','shared',env=env)
            profile=json.loads(Path(env['VIBESTACK_CONFIG']).read_text())['profiles']['shared']
            assert profile['authentication_mode']=='trusted-tailnet' and not profile.get('credential')
            profiles.append(env)
        initialized=mcp('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'independent-python-acceptance','version':'1'}})
        assert 'result' in initialized
        mcp('notifications/initialized',{},ident=None,expected=202)
        tools=mcp('tools/list',{})['result']['tools'];assert len(tools)==11 and not any('password' in t['name'] for t in tools)
        for name in ['shared-one','shared-two']:
            op=tool('instance_create',{'name':name,'template':'desktop','idempotency_key':name})['operation']
            instances.append({'id':op['instance_id']});wait(op)
        instances[:]=[get(i) for i in instances]
        one,two=instances
        for env in profiles:
            values=json.loads(command(args.client,'--profile','shared','--json','instances','list',env=env))['instances']
            assert {i['id'] for i in values}=={one['id'],two['id']}
        drive=api('POST','/drives',{'name':'shared-files'})['drive']
        for env in profiles:
            assert drive['id'] in command(args.client,'--profile','shared','api',ROOT+'/drives',env=env).decode()
        api('POST','/environment-sets',{'name':'tools','values':{'SHARED_CHECK':'present'}})
        assert len(api('GET','/environment-sets')['environment_sets'])==1
        print('PASS two credential-free CLI clients share desktops/storage; independent MCP initializes and provisions through HTTPS',flush=True)
        for i,password in zip(instances,passwords):
            assert i['infrastructure_ready'] and i['password_status']=='required' and i['onboarding_required']
            assert i['linux_username']=='vibe' and i['reachability']['ssh']=='host-local' and 'ssh' not in i['urls']
            api('POST','/instances/'+i['id']+'/password',{'password':'x'},expected=400)
            command(args.client,'--profile','shared','instances','password',i['id'],'--password-stdin',input=(password+'\n').encode(),env=profiles[0])
            assert get(i)['password_status']=='configured'
            linux_auth(i,password)
        linux_auth(one,passwords[1],False);linux_auth(two,passwords[0],False)
        for i in instances:
            assert get(i)['onboarding_required'],'app onboarding should remain distinct'
            for path in ['/vnc/','/terminal/','/editor/']:
                with urllib.request.urlopen(i['urls']['browser']+path,timeout=20) as response:assert response.status==200
        action(one,'restart');one=get(one);linux_auth(one,passwords[0])
        wait(api('POST','/instances/'+one['id']+'/update',{'template':'desktop'},headers={'Idempotency-Key':'replacement'})['operation'])
        one=get(one);instances[0]=one;linux_auth(one,passwords[0])
        action(two,'stop');api('POST','/instances/'+two['id']+'/password',{'password':passwords[1]},expected=409);action(two,'start');two=get(two);instances[1]=two
        print('PASS independent Linux authentication; policy/stopped conflicts; restart/replacement password persistence',flush=True)
        # Helper failure must be sanitized and cannot record a secret operation.
        command('docker','exec',two['container_id'],'mv','/usr/local/bin/vibestack-password','/usr/local/bin/vibestack-password.real')
        try:api('POST','/instances/'+two['id']+'/password',{'password':passwords[1]},expected=502)
        finally:command('docker','exec',two['container_id'],'mv','/usr/local/bin/vibestack-password.real','/usr/local/bin/vibestack-password')
        # A delayed disposable helper makes overlap and disconnect deterministic.
        command('docker','exec',two['container_id'],'mv','/usr/local/bin/vibestack-password','/usr/local/bin/vibestack-password.real')
        wrapper=b'#!/bin/sh\nsleep 2\nexec /usr/local/bin/vibestack-password.real "$@"\n'
        command('docker','exec','-i',two['container_id'],'tee','/usr/local/bin/vibestack-password',input=wrapper)
        command('docker','exec',two['container_id'],'chmod','755','/usr/local/bin/vibestack-password')
        try:
            connection=http.client.HTTPSConnection(args.public_host,13443,timeout=10)
            connection.request('POST',ROOT+'/instances/'+two['id']+'/password',json.dumps({'password':passwords[1]}),{'Content-Type':'application/json'})
            time.sleep(.4)
            api('POST','/instances/'+two['id']+'/password',{'password':passwords[1]},expected=409)
            connection.close()
            stopped=api('POST','/instances/'+two['id']+'/stop',{})['operation'];wait(stopped)
        finally:command('docker','cp',str(Path('bin/vibestack-password').resolve()),two['container_id']+':/usr/local/bin/vibestack-password')
        action(two,'start');two=get(two);instances[1]=two;linux_auth(two,passwords[1])
        print('PASS sanitized helper failure and interrupted password request serialized with lifecycle',flush=True)
        stop();start()
        assert len(api('GET','/instances')['instances'])==2
        output=command(args.client,'--profile','shared','--instance',one['id'],'exec','--','/usr/bin/printf','42',env=profiles[1]);assert output==b'42'
        job=tool('workspace_command',{'instance_id':two['id'],'argv':['/usr/bin/printf','42']})['job']
        for _ in range(60):
            status=tool('workspace_job',{'instance_id':two['id'],'job_id':job['id']})['job']
            if status['status']=='succeeded':break
            time.sleep(.3)
        assert status['status']=='succeeded'
        page=tool('workspace_output',{'instance_id':two['id'],'job_id':job['id'],'stream':'stdout'})
        assert base64.b64decode(page['data'])==b'42'
        shot=mcp('tools/call',{'name':'workspace_screenshot','arguments':{'instance_id':two['id']}})['result']
        assert base64.b64decode(shot['content'][0]['data']).startswith(b'\x89PNG')
        mcp('tools/list',{},expected=403,headers={'Origin':'https://invalid.example'})
        bad=mcp('tools/call',{'name':'workspace_job','arguments':{'instance_id':one['id'],'job_id':'invalid'}})
        assert bad['result']['isError']
        malformed=request('POST','/mcp',{'not':'jsonrpc'},expected=400,headers={'Accept':'application/json, text/event-stream'})
        action(two,'stop')
        absent=mcp('tools/call',{'name':'workspace_command','arguments':{'instance_id':two['id'],'argv':['true']}})
        assert absent['result']['isError'];action(two,'start')
        leaks()
        print('PASS mediated CLI/MCP jobs, output, PNG; invalid origin/malformed/unavailable requests; plaintext scans',flush=True)
        if args.browser:
            env=dict(os.environ,VIBESTACK_BASE_URL=one['urls']['browser'],VIBESTACK_ALLOW_MUTATING_BROWSER_TESTS='1')
            result=subprocess.run(['npm','run','test:browser','--','--grep','custom shell connects|embedded terminal loads|editor'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (folder/'browser.log').write_bytes(result.stdout)
            assert result.returncode==0,'browser flow failed; inspect browser.log'
            print('PASS real private HTTPS browser desktop, terminal and editor flows',flush=True)
        (folder/'passed').write_text('passed\n')
    finally:
        if process is not None and process.poll() is None:
            for i in instances:
                try:action(i,'remove')
                except Exception:pass
        stop();log.close()
        db=sqlite3.connect(state/'runner.db')
        for (cid,) in db.execute("select container_id from instances where container_id is not null"):
            subprocess.run(['docker','rm','-f',cid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for (volume,) in db.execute("select source from drives where kind='volume' union select volume from snapshots"):
            subprocess.run(['docker','volume','rm',volume],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        db.close()
        after=json.loads(command('tailscale','serve','status','--json'))
        site=after.get('Web',{}).get(args.public_host+':13443',{})
        if site.get('Handlers',{}).get('/',{}).get('Proxy')==local:command('tailscale','serve','--https=13443','off')
        final=json.loads(command('tailscale','serve','status','--json'))
        for key,value in before.get('Web',{}).items():assert final.get('Web',{}).get(key)==value,'unrelated Serve mapping changed'
        print('Evidence: '+str(folder),flush=True)

if __name__=='__main__':main()
