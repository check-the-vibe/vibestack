#!/usr/bin/env python3
"""Disposable real-Docker runner acceptance; never uses the standalone desktop.
Run with --baseline OLD_RUNNER --runner NEW_RUNNER --image ACCEPTED_IMAGE.
All credential values stay in memory/private files; stdout is assertions only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = '/api/v1/runner'

def command(*args, input=None):
    value = subprocess.run(args, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if value.returncode:
        raise RuntimeError('local command failed: ' + args[0])
    return value.stdout

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--runner', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--public-host', default='server.tail14a7e5.ts.net')
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    folder = Path(tempfile.mkdtemp(prefix='vibestack-runner-integration-'))
    config = folder / 'config.json'
    state = folder / 'state'
    base = 'http://127.0.0.1:18079'
    public = 'https://' + args.public_host + ':12443'
    before = json.loads(command('tailscale', 'serve', 'status', '--json'))
    if any(address.endswith(':12443') for address in before.get('Web', {})):
        raise RuntimeError('integration Serve port occupied')
    command(args.baseline, 'init', '--config', str(config), '--state-dir', str(state))
    cfg = json.loads(config.read_text())
    cfg.update(listen='127.0.0.1:18079', public_url=public, port_min=12080, port_max=12179, max_instances=6, provisioning_concurrency=1, default_memory_bytes=2<<30, default_nano_cpus=1_000_000_000, manage_tailscale_serve=True)
    config.write_text(json.dumps(cfg))
    command(args.baseline, 'templates', '--config', str(config), 'add', 'desktop', args.image)
    process = None
    log = open(folder / 'runner.log', 'ab')
    instances = []
    tokens = {}
    def api(method, path, body=None, owner='one', key=None, expected=None, origin=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {'Content-Type': 'application/json'}
        if owner in tokens: headers['Authorization'] = 'Bearer ' + tokens[owner]
        if key: headers['Idempotency-Key'] = key
        request = urllib.request.Request((origin or base)+path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=70) as response:
                code, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            code, raw = error.code, error.read()
        if expected is not None:
            assert code == expected, (path, code, expected)
        elif code >= 400:
            raise RuntimeError('API failed: '+path+' status='+str(code))
        if not raw: return None
        return json.loads(raw)
    def start(binary):
        nonlocal process
        process = subprocess.Popen([binary, 'serve', '--config', str(config)], stdout=log, stderr=log)
        for _ in range(90):
            if process.poll() is not None: raise RuntimeError('runner exited; inspect private log')
            try:
                api('GET', '/.well-known/vibestack', owner=None)
                return
            except (OSError, RuntimeError): time.sleep(1)
        raise RuntimeError('runner start timed out')
    def stop():
        nonlocal process
        if process is not None:
            process.terminate(); process.wait(timeout=30); process=None
    def pair(label,binary):
        request = api('POST',ROOT+'/pairing/requests',{'device_label':'integration-'+label,'permissions':['instances:read','instances:write']},owner=None)
        command(binary,'pairings','--config',str(config),'approve',request['verification_code'])
        result=api('POST',ROOT+'/pairing/requests/'+request['pairing_id']+'/poll',{'polling_secret':request['polling_secret']},owner=None)
        tokens[label]=result['credential']
        return result['client_id']
    def wait(op, success=True):
        for _ in range(480):
            result=api('GET',ROOT+'/operations/'+op['id'])['operation']
            if result['status'] in ('succeeded','failed'):
                if success and result['status']!='succeeded':
                    raise RuntimeError('operation failed: '+str(result.get('error_code'))+' '+str(result.get('error_message')))
                if not success: assert result['status']=='failed'
                return result
            time.sleep(1)
        raise RuntimeError('operation timed out')
    def create(name, **extra):
        op=api('POST',ROOT+'/instances',dict(name=name,template='desktop',**extra),key=name)['operation']
        instances.append(op['instance_id']);wait(op)
        return api('GET',ROOT+'/instances/'+op['instance_id'])['instance']
    def action(instance,kind):
        return wait(api('POST',ROOT+'/instances/'+instance['id']+'/'+kind,{})['operation'])
    def get(instance): return api('GET',ROOT+'/instances/'+instance['id'])['instance']
    def put_file(instance,name,content):
        request=urllib.request.Request(base+ROOT+'/instances/'+instance['id']+'/workspace/api/v1/automation/projects/'+name,data=content,headers={'Authorization':'Bearer '+tokens['one'],'Content-Type':'application/octet-stream'},method='PUT')
        with urllib.request.urlopen(request,timeout=15) as response: assert response.status in (200,201)
    def exec_container(instance,script):
        return command('docker','exec',instance['container_id'],'python3','-I','-c',script)
    try:
        start(args.baseline)
        owner=pair('one',args.baseline)
        original=create('integration-empty')
        assert original['infrastructure_ready'] and original['onboarding_required']
        with urllib.request.urlopen(original['urls']['browser']+'/setup/',timeout=20) as response: assert response.status==200
        print('PASS existing runner: empty desktop reaches onboarding through private Tailscale',flush=True)
        stop();start(args.runner)
        command('tailscale','serve','--bg','--https=12443',base)
        with urllib.request.urlopen(public+'/AGENTS.md',timeout=20) as response: assert public.encode() in response.read()
        pair('two',args.runner)
        api('GET',ROOT+'/instances/'+original['id'],owner='two',expected=404)
        api('GET',ROOT+'/host',owner=None,expected=401)
        drives=api('GET',ROOT+'/drives')['drives'];assert len(drives)==2
        print('PASS registry migration and authenticated broker guide; cross-owner access rejected',flush=True)
        # Only this disposable desktop gets a random onboarding password, by body.
        password=secrets.token_urlsafe(32)
        request=urllib.request.Request(original['urls']['browser']+'/setup/api/password',data=json.dumps({'password':password,'confirmation':password}).encode(),headers={'Content-Type':'application/json','Origin':original['urls']['browser']},method='POST')
        with urllib.request.urlopen(request,timeout=30) as response: assert response.status==200
        password=None
        # Finish existing onboarding with the empty optional application selection.
        request=urllib.request.Request(original['urls']['browser']+'/setup/api/install',data=json.dumps({'components':[]}).encode(),headers={'Content-Type':'application/json','Origin':original['urls']['browser']},method='POST')
        with urllib.request.urlopen(request,timeout=30) as response: assert response.status in (200,202)
        action(original,'stop')
        host_folder=folder/'projects';host_folder.mkdir(mode=0o755)
        registered=json.loads(command(args.runner,'drives','--config',str(config),'register','host-projects',owner,str(host_folder)))['drive']
        api('PUT',ROOT+'/instances/'+original['id']+'/attachments',{'project_drive':registered['id'],'file_drives':[]})
        original=get(original);action(original,'start');original=get(original)
        put_file(original,'runner-acceptance.txt',b'registered host folder\n')
        assert (host_folder/'runner-acceptance.txt').read_bytes()==b'registered host folder\n'
        job=api('POST',ROOT+'/instances/'+original['id']+'/workspace/api/v1/automation/commands',{'argv':['/usr/bin/python3','-c','print(6*7)'],'root':'projects','cwd':'','timeout_seconds':30})['job']
        for _ in range(30):
            job=api('GET',ROOT+'/instances/'+original['id']+'/workspace/api/v1/automation/jobs/'+job['id'])['job']
            if job['status'] in ('succeeded','failed','cancelled','timed_out'): break
            time.sleep(1)
        assert job['status']=='succeeded','mediated agent command failed'

        api('PUT',ROOT+'/instances/'+original['id']+'/attachments',{'project_drive':registered['id'],'file_drives':[]},expected=409)
        api('POST',ROOT+'/instances',{'name':'integration-conflict','template':'desktop','project_drive':registered['id']},key='writer-conflict',expected=409)
        api('POST',ROOT+'/instances',{'name':'integration-port-conflict','template':'desktop','ports':{'http':original['ports']['http']}},key='port-conflict',expected=409)
        print('PASS host project file mediation; running attachment, writer and occupied-port conflicts rejected',flush=True)
        exec_container(original,"from pathlib import Path; p=Path('/data/keyrings/acceptance-state');p.write_text('application-state');p.chmod(0o600);j=Path('/data/vibestack/automation/jobs');j.mkdir(parents=True,exist_ok=True);(j/'excluded-job').write_text('old-operation')")
        envsecret=secrets.token_urlsafe(24)
        env=api('POST',ROOT+'/environment-sets',{'name':'tools','values':{'ACCEPTANCE_SECRET':envsecret}})['environment_set']
        api('POST',ROOT+'/environment-sets',{'name':'blocked','values':{'VIBESTACK_ALLOWED_HOSTS':envsecret}},expected=409)
        action(original,'restart');stop();start(args.runner);original=get(original)
        assert (host_folder/'runner-acceptance.txt').exists()
        assert exec_container(original,"from pathlib import Path;assert Path('/data/keyrings/acceptance-state').read_text()=='application-state'")==b''
        print('PASS runner/desktop restart recovery and persistent application state',flush=True)
        def fingerprints(i):
            return json.loads(exec_container(i,"import hashlib,json;from pathlib import Path;p=Path('/data'); names=['.vibestack-auth-v1/vibe.shadow','.vibestack-auth-v1/ssh_host_ed25519_key','vibestack/automation.token'];print(json.dumps([hashlib.sha256((p/n).read_bytes()).hexdigest() for n in names]))"))
        f0=fingerprints(original)
        # An agent's inbound SSH authorization must not propagate into clones.
        ssh_key=folder/'agent-key'
        command('ssh-keygen','-q','-t','ed25519','-N','','-f',str(ssh_key))
        api('POST',ROOT+'/instances/'+original['id']+'/workspace/api/v1/automation/ssh-keys',{'public_key':ssh_key.with_suffix('.pub').read_text().strip()})
        assert len(api('GET',ROOT+'/instances/'+original['id']+'/workspace/api/v1/automation/ssh-keys')['keys'])==1
        action(original,'stop')
        snapshot_op=api('POST',ROOT+'/instances/'+original['id']+'/snapshot',{'name':'configured'},key='snapshot')['operation']
        snap=wait(snapshot_op)['result']['snapshot']
        # Clones receive fresh projects volumes and independent private state.
        one=create('integration-clone-one',state_seed=snap['id'],environment_set=env['id'])
        two=create('integration-clone-two',state_seed=snap['id'],environment_set=env['id'])
        f1,f2=map(fingerprints,(one,two))
        assert f0[0]==f1[0]==f2[0]
        assert len({f0[1],f1[1],f2[1]})==3 and len({f0[2],f1[2],f2[2]})==3
        identities=[]
        for i in (one,two):
            assert api('GET',ROOT+'/instances/'+i['id']+'/workspace/api/v1/automation/ssh-keys')['keys']==[]
            with urllib.request.urlopen(i['urls']['browser']+'/.well-known/vibestack',timeout=20) as response: identities.append(json.load(response)['identity'])
            assert exec_container(i,"from pathlib import Path;assert Path('/data/keyrings/acceptance-state').read_text()=='application-state';assert not Path('/data/vibestack/automation/jobs/excluded-job').exists()")==b''
            assert exec_container(i,"import os;assert os.environ['ACCEPTANCE_SECRET']") == b''
        assert identities[0]!=identities[1]
        exec_container(one,"from pathlib import Path;Path('/data/keyrings/acceptance-state').write_text('clone-one-only')")
        assert exec_container(two,"from pathlib import Path;assert Path('/data/keyrings/acceptance-state').read_text()=='application-state'")==b''
        put_file(one,'only-one.txt',b'clone one')
        assert exec_container(two,"from pathlib import Path;assert not Path('/projects/only-one.txt').exists()")==b''
        report=api('GET',ROOT+'/host',origin=public)
        assert envsecret not in json.dumps(report) and str(host_folder) not in json.dumps(report)
        assert len(report['managed_containers'])==3
        assert api('GET',ROOT+'/snapshots',owner='two')['snapshots']==[]
        assert api('GET',ROOT+'/environment-sets',owner='two')['environment_sets']==[]
        print('PASS independent snapshot clones, preserved password/state, distinct machine authority and secret-free metadata',flush=True)
        if args.browser:
            browser=subprocess.run(['npm','run','test:browser','--','--project=desktop-chromium','--grep','custom shell connects|embedded terminal loads'],env=dict(os.environ,VIBESTACK_BASE_URL=one['urls']['browser'],VIBESTACK_ALLOW_MUTATING_BROWSER_TESTS='1'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (folder/'browser.log').write_bytes(browser.stdout)
            assert browser.returncode==0,'clone browser check failed; inspect private browser.log'
            print('PASS cloned desktop and authenticated terminal browser flows through private HTTPS',flush=True)
        action(one,'remove');action(two,'remove');action(original,'remove')
        assert api('GET',ROOT+'/snapshots')['snapshots'][0]['id']==snap['id']
        assert (host_folder/'runner-acceptance.txt').exists()
        print('PASS removal retains registered files, drives and snapshots',flush=True)
        (folder/'passed').write_text('passed\n')
    finally:
        # Cleanup only IDs owned by this disposable registry; retain failure evidence.
        if process is not None and process.poll() is None:
            for instance_id in instances:
                try: wait(api('POST',ROOT+'/instances/'+instance_id+'/remove',{})['operation'])
                except Exception: pass
        stop();log.close()
        after=json.loads(command('tailscale','serve','status','--json'))
        site=after.get('Web',{}).get(args.public_host+':12443',{})
        if site.get('Handlers',{}).get('/',{}).get('Proxy')==base:
            command('tailscale','serve','--https=12443','off')
        final=json.loads(command('tailscale','serve','status','--json'))
        for key,value in before.get('Web',{}).items(): assert final['Web'][key]==value
        print('Evidence retained at '+str(folder),flush=True)

if __name__=='__main__': main()
