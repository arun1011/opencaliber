import copy
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from opencaliber import agent_server as server
from opencaliber.agent_engine import DEFAULT_CONFIG


class QuietHandler(server.Handler):
    def log_message(self,*args):pass


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        cls.previous=server.DB;server.DB=Path(cls.tmp.name)/'test.sqlite3';server.initialize()
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        cls.url='http://127.0.0.1:'+str(cls.http.server_address[1])
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join();server.DB=cls.previous;cls.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        h={'Content-Type':'application/json',**(headers or {})}
        request=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:
            with urllib.request.urlopen(request) as r:return r.status,json.loads(r.read())
        except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
    def test_adoption_endpoints(self):
        code,profiles=self.request('/api/adoption/profiles');self.assertEqual(code,200);self.assertIn('backup-before-delete',profiles)
        code,examples=self.request('/api/adoption/examples');self.assertEqual(code,200)
        code,normalized=self.request('/api/adoption/mcp',{'events':examples['mcp-events.json'],'context':examples['mcp-context.json']});self.assertEqual(code,200)
        code,coverage=self.request('/api/adoption/coverage',{'trace':normalized['trace']});self.assertEqual(code,200);self.assertEqual(coverage['unmapped_tools'],[])
        self.assertEqual(self.request('/api/adoption/profile',{'profile':profiles['backup-before-delete']})[0],200)
        self.assertEqual(self.request('/api/adoption/mcp',{'events':[],'context':{}})[0],400)

    def test_sequence_configuration_evaluation_and_persistence(self):
        cfg=json.loads((server.ROOT/'examples/sequence_config.json').read_text())
        trace=json.loads((server.ROOT/'examples/sequence_failed_trace.json').read_text())
        previous=server.configuration()
        try:
            self.assertEqual(self.request('/api/config',cfg)[0],200)
            status,created=self.request('/api/evaluate',{'trace':trace,'storage':'redacted'})
            self.assertEqual(status,201)
            saved=self.request('/api/runs/'+created['id'])[1]
            check=saved['result']['actions'][-1]['sequence_checks'][0]
            self.assertFalse(check['satisfied'])
            self.assertEqual(check['evidence_ids'],['backup-01','delete-01'])
            self.assertEqual(saved['trace']['actions'][0]['resource_version'],'[redacted-version]')
            self.assertEqual(saved['config']['sequence_rules'],cfg['sequence_rules'])
        finally:self.request('/api/config',previous)

    def test_agent_identity_survives_persistence_and_state(self):
        trace=copy.deepcopy(server.cases()['cases'][0]['trace'])
        trace['agent']={'id':'api-agent','version':'commit-123'};trace['workflow_id']='workflow-456'
        status,created=self.request('/api/evaluate',{'trace':trace});self.assertEqual(status,201)
        saved=self.request('/api/runs/'+created['id'])[1]
        self.assertEqual(saved['trace']['agent'],trace['agent'])
        self.assertEqual(saved['result']['agent'],trace['agent'])
        run=next(r for r in self.request('/api/state')[1]['runs'] if r['id']==created['id'])
        self.assertEqual(run['agent'],trace['agent']);self.assertEqual(run['workflow_id'],trace['workflow_id'])

    def test_normalize_redact_and_persist_provider_calls(self):
        bundle=self.request('/api/integration-examples')[1]
        context={k:bundle[k] for k in ('policy','agent','task','session_id','workflow_id')}
        code,normalized=self.request('/api/normalize',{'provider':'anthropic','response':bundle['responses']['anthropic']['unsafe'],'context':context})
        self.assertEqual(code,200)
        self.assertNotIn('fixture-secret',json.dumps(normalized))
        status,created=self.request('/api/evaluate',{'trace':normalized['trace'],'storage':'redacted'})
        self.assertEqual(status,201);self.assertEqual(created['result']['assessment'],'violation')
        saved=self.request('/api/runs/'+created['id'])[1]
        self.assertFalse(saved['result']['replayable']);self.assertEqual(saved['result']['storage_mode'],'redacted')
        self.assertNotIn('/upload',json.dumps(saved));self.assertNotIn(bundle['task']['goal'],json.dumps(saved))
        state=self.request('/api/state')[1]
        run=next(r for r in state['runs'] if r['id']==created['id'])
        self.assertEqual(run['context']['session_id'],bundle['session_id'])
        found=[f for f in state['findings'] if f['run_id']==created['id']]
        self.assertTrue(found);self.assertEqual(found[0]['context']['provider'],'anthropic')
        self.assertEqual(self.request('/api/normalize',{'provider':'anthropic','response':{},'context':context})[0],400)
        self.assertEqual(self.request('/api/evaluate',{'trace':normalized['trace'],'storage':'invalid'})[0],400)

    def test_full_evaluation_and_review_lifecycle(self):
        trace=server.cases()['cases'][0]['trace'];status,result=self.request('/api/evaluate',{'trace':trace})
        self.assertEqual(status,201);rid=result['id']
        self.assertEqual(self.request('/api/runs/'+rid)[1]['trace'],trace)
        self.assertEqual(self.request('/api/review',{'id':rid,'status':'reviewed','note':'Verified owner context'})[0],200)
        self.assertEqual(self.request('/api/runs/'+rid)[1]['note'],'Verified owner context')
    def test_config_snapshot_does_not_change(self):
        rid=self.request('/api/evaluate',{'trace':server.cases()['cases'][0]['trace']})[1]['id']
        self.request('/api/config',{**DEFAULT_CONFIG,'max_records':200})
        self.assertEqual(self.request('/api/runs/'+rid)[1]['config']['max_records'],1000)
        self.request('/api/config',DEFAULT_CONFIG)
    def test_benchmark_and_state_persistence(self):
        status,r=self.request('/api/benchmark',{})
        self.assertEqual(status,200);self.assertEqual(r['passed'],70)
        state=self.request('/api/state')[1];self.assertEqual(state['benchmark']['total'],70)
    def test_cross_origin_rejected(self):
        self.assertEqual(self.request('/api/evaluate',{},headers={'Origin':'https://evil.test'})[0],403)
    def test_untrusted_host_rejected(self):
        self.assertEqual(self.request('/api/state',headers={'Host':'evil.test'})[0],403)
    def test_malformed_input_returns_400(self):
        self.assertEqual(self.request('/api/evaluate',{'trace':{}})[0],400)
        self.assertEqual(self.request('/api/config',{'max_records':10})[0],400)
    def test_unknown_run_404(self):
        self.assertEqual(self.request('/api/runs/absent')[0],404)
    def test_invalid_benchmark_selection(self):
        self.assertEqual(self.request('/api/benchmark',{'case_ids':['absent']})[0],400)
    def test_download_package_is_a_zip(self):
        with urllib.request.urlopen(self.url+'/api/package') as response:
            self.assertIn('opencaliber-local.zip',response.headers['Content-Disposition'])
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                self.assertIn('run.py',archive.namelist())
    def test_video_byte_range_for_chapter_seeking(self):
        request=urllib.request.Request(self.url+'/media/opencaliber-walkthrough.mp4',headers={'Range':'bytes=0-63'})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status,206);self.assertEqual(response.headers['Accept-Ranges'],'bytes')
            self.assertEqual(len(response.read()),64)
    def test_video_unsatisfiable_range(self):
        request=urllib.request.Request(self.url+'/media/opencaliber-walkthrough.mp4',headers={'Range':'bytes=999999999-9999999999'})
        with self.assertRaises(urllib.error.HTTPError) as raised:urllib.request.urlopen(request)
        self.assertEqual(raised.exception.code,416)


if __name__=='__main__':unittest.main()
