import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from opencaliber.local_package import build_package


class PackageTests(unittest.TestCase):
    def test_allowlist_excludes_private_state(self):
        with zipfile.ZipFile(io.BytesIO(build_package())) as z:
            self.assertIsNone(z.testzip())
            names=z.namelist()
            self.assertIn('opencaliber/ingestion.py',names);self.assertIn('profiles/backup-before-delete.json',names);self.assertIn('web/adoption.js',names)
            self.assertIn(b"/api/adoption/profiles",z.read('opencaliber/agent_server.py'))
            self.assertIn('run.py',names);self.assertIn('web/console.html',names)
            self.assertNotIn('web/index.html',names)
            self.assertFalse(any(n.startswith(('web/media/','tests/','tools/','notebooks/')) for n in names))
            self.assertNotIn('web/marketing.js',names)
            self.assertNotIn('opencaliber/local_package.py',names)
            self.assertNotIn('index.html',z.read('web/console.html').decode())
            self.assertNotIn('walkthrough',z.read('web/console.js').decode())
            self.assertIn('examples/integrate_agent.py',names)
            self.assertFalse(any('sqlite' in n or 'private/' in n or '.safetensors' in n or '.git/' in n for n in names))
    def test_extracted_cli_independent_of_checkout(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with zipfile.ZipFile(io.BytesIO(build_package())) as z:
                self.assertIn('opencaliber/tool_policies.py',z.namelist())
                self.assertIn('examples/tool-policy-config.json',z.namelist())
                z.extractall(directory)
            p=subprocess.run([sys.executable,'-m','opencaliber.agent_cli','benchmark'],cwd=directory,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(p.stdout)['passed'],70)
            p=subprocess.run([sys.executable,'examples/integrate_agent.py'],cwd=directory,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(p.stdout)['assessment'],'clear')
            p=subprocess.run([sys.executable,'-m','opencaliber.agent_cli','regression','--input','examples/adoption/regression-suite.json'],cwd=directory,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(p.stdout)['passed'],6)
            for provider in ('openai-responses','openai-chat','anthropic'):
                p=subprocess.run([sys.executable,'examples/adoption/provider_demo.py','--provider',provider],cwd=directory,capture_output=True,text=True,check=True)
                self.assertEqual([r['assessment'] for r in json.loads(p.stdout)['results']],['violation','clear'])

    def test_extracted_console_and_api(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with zipfile.ZipFile(io.BytesIO(build_package())) as z:
                self.assertIn('opencaliber/tool_policies.py',z.namelist())
                self.assertIn('examples/tool-policy-config.json',z.namelist())
                z.extractall(directory)
            script="""
import json,threading,urllib.request
from http.server import ThreadingHTTPServer
from opencaliber import agent_server as s
s.initialize()
http=ThreadingHTTPServer(('127.0.0.1',0),s.Handler)
t=threading.Thread(target=http.serve_forever,daemon=True);t.start()
base='http://127.0.0.1:'+str(http.server_address[1])
try:
    with urllib.request.urlopen(base+'/') as r:
        html=r.read().decode();assert 'id="app"' in html and 'index.html' not in html
    data=json.dumps({'trace':s.cases()['cases'][0]['trace']}).encode()
    req=urllib.request.Request(base+'/api/evaluate',data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req) as r:assert r.status==201 and 'assessment' in json.load(r)['result']
    from opencaliber.sdk import Client
    from pathlib import Path
    bundle=json.loads(Path('examples/adoption/bundle.json').read_text())
    context={k:bundle[k] for k in ('policy','task','agent','session_id','workflow_id')}
    observed=Client(base,failure_mode='raise').observe_response('anthropic',bundle['responses']['anthropic']['unsafe'],**context)
    assert observed['result']['assessment']=='violation' and not observed['result']['replayable']
    assert observed['result']['storage_mode']=='redacted'
    import subprocess,os
    env={**os.environ,'OPENCALIBER_TEST_ENDPOINT':base}
    node="import {readFileSync} from 'node:fs';import {Client} from './sdk/typescript/opencaliber.mjs';const b=JSON.parse(readFileSync('examples/adoption/bundle.json','utf8'));const {policy,agent,task,session_id,workflow_id}=b;const r=await new Client({endpoint:process.env.OPENCALIBER_TEST_ENDPOINT,failureMode:'raise'}).observeResponse('openai-responses',b.responses['openai-responses'].unsafe,{policy,agent,task,session_id,workflow_id});if(r.result.assessment!=='violation'||r.result.replayable)process.exit(1);"
    done=subprocess.run(['node','--input-type=module','-e',node],capture_output=True,text=True,env=env)
    assert done.returncode==0,done.stderr
finally:
    http.shutdown();http.server_close();t.join()
"""
            result=subprocess.run([sys.executable,'-c',script],cwd=directory,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)



if __name__=='__main__':unittest.main()
