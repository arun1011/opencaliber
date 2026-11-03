import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from opencaliber import agent_server as store
from opencaliber import custom_checks as checks,check_models as models
from opencaliber.tracking import TrackingClient,TrackedExecutor
from opencaliber.tracking_store import ingest
from opencaliber.execution import ActionBlocked
from opencaliber.connected_platform import collected,dashboard,compare,cohort_key

def example():
    return {'id':'budget','name':'Budget','description':'Reject over 25 requested records','tool':'database.read','tracking_ids':[],
      'stage':'before','requires':['action.arguments.records'],'code':'def check(ctx):\n    return field("action.arguments.records") > 25',
      'message':'Too many records','remediation':'Request fewer records','tests':[
        {'name':'pass','context':{'action':{'tool':'database.read','arguments':{'records':10}}},'expected':'passed'},
        {'name':'fail','context':{'action':{'tool':'database.read','arguments':{'records':30}}},'expected':'failed'}]}

class ChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.old=store.DB;store.DB=Path(self.temp.name)/'db.sqlite3';store.initialize()
    def tearDown(self):store.DB=self.old;self.temp.cleanup()
    def install(self,spec=None):
        spec=spec or example();r=checks.save({'spec':spec,'revision':0},store.connect)
        body={'id':spec['id'],'revision':r['revision'],'operation':'test'}
        self.assertTrue(checks.manage(body,store.connect)['report']['passed'])
        checks.manage({**body,'operation':'enable'},store.connect)
        return spec
    def run_agent(self,records=10,version='v1',tracking_id='reader',capture=True):
        client=TrackingClient(sender=lambda raw:ingest(json.loads(raw),store.connect,store.timestamp,store.configuration()),spool_dir=Path(self.temp.name)/version,enabled=True,mode='enforce')
        with TrackedExecutor(agent={'id':'reader','version':version},tracking_id=tracking_id,
             task={'goal':'Read records','allowed_tools':['database.read'],'allowed_resources':['tickets']},tracker=client,
             diagnosis=capture,capture_output=lambda a,v:{'count':len(v)},
             evaluation={'experiment_id':'exp','case_id':'case','input_sha256':'a'*64,'success_criterion':'correct','assignment':'paired'}) as a:
            a.run({'id':'read','tool':'database.read','resource':'tickets','arguments':{'records':records}},lambda:[1],success=lambda _:True)
            a.record_outcome(True)
        self.assertEqual(client.last_status,'delivered')
        return collected(store.connect)[0]
    def test_missing_field_tests_added(self):
        r=checks.test(example());self.assertTrue(r['passed']);self.assertEqual(r['cases'][-1]['status'],'unknown')
    def test_bad_types_unknown(self):
        self.assertEqual(checks.evaluate(example(),{'action':{'arguments':{'records':'many'}}})['status'],'unknown')
    def test_unsafe_code_rejected(self):
        for code in ['import os\ndef check(ctx): return True','def check(ctx): return __import__("os")','def check(ctx): return ctx.__class__','def check(ctx):\n while True: pass','def check(ctx): return [x for x in []]','@print\ndef check(ctx): return True','def check(ctx): return field("action.secret")']:
            with self.subTest(code=code),self.assertRaises(ValueError):checks.validate({**example(),'code':code})
    def test_cannot_enable_untested(self):
        checks.save({'spec':example(),'revision':0},store.connect)
        with self.assertRaises(ValueError):checks.manage({'id':'budget','revision':1,'operation':'enable'},store.connect)
    def test_edit_disables_and_invalidates_tests(self):
        self.install();checks.save({'spec':{**example(),'message':'Changed'},'revision':1},store.connect)
        row=checks.listing(store.connect)[0];self.assertFalse(row['enabled']);self.assertIsNone(row['tested_hash'])
    def test_conflicting_revision_rejected(self):
        self.install()
        with self.assertRaises(ValueError):checks.save({'spec':example(),'revision':0},store.connect)
    def test_checks_survive_initialize(self):
        self.install();store.initialize();self.assertTrue(checks.listing(store.connect)[0]['enabled'])
    def test_online_enforcement_blocks(self):
        self.install()
        with self.assertRaises(ActionBlocked):self.run_agent(30)
        self.assertTrue(any(f['code']=='CUSTOM_BUDGET' for f in collected(store.connect)[0]['findings']))
    def test_tracking_scope(self):
        self.install({**example(),'tracking_ids':['other']});self.run_agent(30)
    def test_after_check_reports_without_blocking_initial_dispatch(self):
        spec=example();spec.update(stage='after',requires=['output.count'],code='def check(ctx): return field("output.count") > 0')
        spec['tests']=[{'name':'pass','context':{'action':{'tool':'database.read'},'output':{'count':0}},'expected':'passed'},{'name':'fail','context':{'action':{'tool':'database.read'},'output':{'count':1}},'expected':'failed'}]
        self.install(spec);r=self.run_agent();self.assertEqual(r['custom_checks'][0]['status'],'failed')
    def test_after_without_capture_is_unknown(self):
        spec=example();spec.update(stage='after',requires=['output.count'],code='def check(ctx): return field("output.count") > 0')
        spec['tests']=[{'name':'pass','context':{'action':{'tool':'database.read'},'output':{'count':0}},'expected':'passed'},{'name':'fail','context':{'action':{'tool':'database.read'},'output':{'count':1}},'expected':'failed'}]
        self.install(spec);r=self.run_agent(capture=False);self.assertEqual(r['custom_checks'][0]['status'],'unknown')
        self.assertTrue(any('Missing evidence' in g for g in dashboard(store.connect,store.configuration(),[])['agents'][0]['gaps']))
    def test_before_output_rejected(self):
        with self.assertRaises(ValueError):checks.validate({**example(),'requires':['action.arguments.records','output.count']})
    def test_comparison_requires_same_custom_checks(self):
        a=self.run_agent();self.install();b=self.run_agent(version='v2')
        r=compare({'baseline':cohort_key(a),'candidate':cohort_key(b)},store.connect);self.assertEqual(r['matched']['count'],0)
    def test_delete_preserves_findings_and_audit(self):
        self.install()
        with self.assertRaises(ActionBlocked):self.run_agent(30)
        checks.manage({'id':'budget','revision':1,'operation':'delete'},store.connect)
        self.assertFalse(checks.listing(store.connect));self.assertTrue(collected(store.connect)[0]['findings'])
        with store.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM detector_audit').fetchone()[0],4)
    def test_sequence_helper_only_prior_success(self):
        spec={**example(),'requires':['action.resource'],'code':'def check(ctx): return not previous_succeeded("file.backup", field("action.resource"))'}
        ctx={'action':{'resource':'a'},'history':[{'tool':'file.backup','resource':'a','outcome':{'status':'failed'}}]}
        self.assertEqual(checks.evaluate(spec,ctx)['status'],'failed');ctx['history'][0]['outcome']['status']='succeeded';self.assertEqual(checks.evaluate(spec,ctx)['status'],'passed')
    def test_model_key_encrypted_and_not_returned(self):
        from cryptography.fernet import Fernet
        with patch.dict('os.environ',{'OPENCALIBER_SECRET_KEY':Fernet.generate_key().decode()}):
            r=models.save({'kind':'service','provider':'openai','model':'user-model','api_key':'test-key-private','enabled':True},store.connect)
            self.assertNotIn('test-key-private',json.dumps(r));_,secret=models.read(store.connect);self.assertNotIn('test-key-private',secret);self.assertEqual(models.protect(secret,True),'test-key-private')
    def test_model_draft_requires_consent_and_enable(self):
        with self.assertRaises(ValueError):models.generate({'spec':example(),'consent':False},store.connect)
        with self.assertRaises(ValueError):models.generate({'spec':example(),'consent':True},store.connect)
    def test_model_draft_never_auto_installs(self):
        with patch.object(models,'read',return_value=({'enabled':True,'kind':'service','provider':'openai','model':'x'},'secret')),patch.object(models,'protect',return_value='key'),patch.object(models,'service',return_value=json.dumps({'code':example()['code'],'requires':example()['requires']})):
            r=models.generate({'spec':example(),'consent':True},store.connect);self.assertFalse(r['enabled']);self.assertFalse(checks.listing(store.connect))
    def test_malicious_model_output_rejected(self):
        with patch.object(models,'read',return_value=({'enabled':True,'kind':'service','provider':'google','model':'x'},'secret')),patch.object(models,'protect',return_value='key'),patch.object(models,'service',return_value=json.dumps({'code':'def check(ctx): return __import__("os")','requires':[]})),self.assertRaises(ValueError):
            models.generate({'spec':example(),'consent':True},store.connect)
    def test_provider_payloads_and_text_parsing(self):
        class Response:
            def __init__(self,value):self.value=value
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return json.dumps(self.value).encode()
        cases=[('openai',{'output':[{'content':[{'type':'output_text','text':'ok'}]}]},'api.openai.com'),('anthropic',{'content':[{'type':'text','text':'ok'}]},'api.anthropic.com'),('google',{'candidates':[{'content':{'parts':[{'text':'ok'}]}}]},'generativelanguage.googleapis.com')]
        for provider,response,host in cases:
            with self.subTest(provider=provider),patch.object(models.urllib.request,'build_opener') as opener:
                opener.return_value.open.return_value=Response(response)
                self.assertEqual(models.service({'provider':provider,'model':'model-name'},'secret-value','draft'),'ok')
                request=opener.return_value.open.call_args.args[0]
                self.assertIn(host,request.full_url);self.assertNotIn('secret-value',request.full_url);self.assertNotIn('secret-value',request.data.decode())
    def test_local_model_delete_disables_selected_model(self):
        model='test/model';folder=models.directory(store.connect,model);folder.mkdir(parents=True)
        (folder/'opencaliber-model.json').write_text(json.dumps({'model':model,'revision':'test'}))
        models.save({'kind':'local','provider':'huggingface','model':model,'api_key':'','enabled':True},store.connect)
        models.local_operation({'model':model,'operation':'delete'},store.connect)
        self.assertFalse(folder.exists());self.assertFalse(models.status(store.connect)['config']['enabled'])
    def test_gap_clears_only_after_current_revision_evidence(self):
        from opencaliber.check_gaps import enrich
        spec=example();spec.update(requires=['action.arguments.match_mode'],code='def check(ctx): return field("action.arguments.match_mode") != "exact"')
        spec['tests']=[{'name':'pass','context':{'action':{'tool':'database.read','arguments':{'match_mode':'exact'}}},'expected':'passed'},{'name':'fail','context':{'action':{'tool':'database.read','arguments':{'match_mode':'other'}}},'expected':'failed'}]
        self.install(spec)
        gap='database.read: No explicit argument constraints for: match_mode. Review whether these fields need limits or allowlists.'
        agent={'tracking_id':'reader','gaps':[gap],'readiness':{'tools':[{'tool':'database.read'}]}}
        enrich(agent,None,store.connect);self.assertIn(gap,agent['gaps'])
        agent['gaps']=[gap]
        enrich(agent,{'custom_checks':[{'id':'budget','revision':1,'status':'passed'}]},store.connect)
        self.assertNotIn(gap,agent['gaps'])
    def test_unreferenced_requirement_does_not_clear_gap(self):
        from opencaliber.check_gaps import enrich
        spec=example();spec['requires'].append('action.arguments.match_mode')
        for t in spec['tests']:t['context']['action']['arguments']['match_mode']='exact'
        self.install(spec)
        gap='database.read: No explicit argument constraints for: match_mode. Review whether these fields need limits or allowlists.'
        agent={'tracking_id':'reader','gaps':[gap],'readiness':{'tools':[{'tool':'database.read'}]}}
        enrich(agent,{'custom_checks':[{'id':'budget','revision':1,'status':'passed'}]},store.connect)
        self.assertIn(gap,agent['gaps'])

    def test_local_name_cannot_escape(self):
        with self.assertRaises(ValueError):models.local_operation({'operation':'delete','model':'../../escape'},store.connect)

if __name__=='__main__':unittest.main()
