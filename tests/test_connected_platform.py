import json,tempfile,unittest
from pathlib import Path
from opencaliber import agent_server as store
from opencaliber.agent_engine import DEFAULT_CONFIG
from opencaliber.tracking import TrackingClient,TrackedExecutor
from opencaliber.tracking_store import ingest,save_policy
from opencaliber.connected_platform import dashboard,compare,cohort_key,collected,save_settings,contract_from_run
from opencaliber.run_metrics import validate

class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.old=store.DB;store.DB=Path(self.temp.name)/'db.sqlite3';store.initialize()
    def tearDown(self):store.DB=self.old;self.temp.cleanup()
    def run_agent(self,version,success=True,case='one',criterion='correct',capture=True,experiment=True):
        def sender(raw):return ingest(json.loads(raw),store.connect,store.timestamp,store.configuration())
        client=TrackingClient(sender=sender,spool_dir=Path(self.temp.name)/'queue',enabled=True)
        with TrackedExecutor(agent={'id':'reader','version':version},tracking_id='reader-'+version,
             task={'goal':'Read ticket','allowed_tools':['database.read'],'allowed_resources':['tickets']},tracker=client,
             diagnosis=capture,capture_output=lambda a,v:{'count':len(v)},
             evaluation={'experiment_id':'exp','case_id':case,'input_sha256':'a'*64,'success_criterion':criterion,'assignment':'paired'} if experiment else None) as a:
            a.run({'id':'read','tool':'database.read','resource':'tickets','arguments':{'records':1}},lambda:[1],success=lambda value:True)
            a.record_outcome(success,cost_usd=0,cost_source='estimated')
        self.assertEqual(client.last_status,'delivered')
        return collected(store.connect)[0]
    def paired(self):
        a=self.run_agent('v1',False);b=self.run_agent('v2',True)
        return compare({'baseline':cohort_key(a),'candidate':cohort_key(b)},store.connect)
    def test_matched_comparison_uses_connected_outcomes(self):
        r=self.paired();self.assertEqual(r['matched']['count'],1);self.assertEqual(r['matched']['success_rate_delta'],1)
    def test_mismatched_success_criterion_excluded(self):
        a=self.run_agent('v1',criterion='first');b=self.run_agent('v2',criterion='second')
        r=compare({'baseline':cohort_key(a),'candidate':cohort_key(b)},store.connect);self.assertEqual(r['matched']['count'],0)
    def test_observational_without_pairing_metadata(self):
        a=self.run_agent('v1',experiment=False);b=self.run_agent('v2',experiment=False)
        r=compare({'baseline':cohort_key(a),'candidate':cohort_key(b)},store.connect);self.assertIsNone(r['matched']['success_rate_delta'])
    def test_repeated_case_uses_latest_only(self):
        self.run_agent('v1',False);a=self.run_agent('v1',True);b=self.run_agent('v2',True)
        r=compare({'baseline':cohort_key(a),'candidate':cohort_key(b)},store.connect);self.assertEqual(r['matched']['count'],1);self.assertEqual(r['baseline']['runs'],2)
    def test_policy_changes_prevent_matching(self):
        a=self.run_agent('v1');save_settings({'config':{**DEFAULT_CONFIG,'max_records':5},'mode':'observe','replace_overrides':False},store.connect);b=self.run_agent('v2')
        self.assertEqual(compare({'baseline':cohort_key(a),'candidate':cohort_key(b)},store.connect)['matched']['count'],0)
    def test_missing_capture_highlighted(self):
        self.run_agent('v1',capture=False)
        data=dashboard(store.connect,store.configuration(),store.cases()['cases'])
        self.assertTrue(any('not captured' in gap for gap in data['agents'][0]['gaps']))
    def test_contract_created_from_run(self):
        r=self.run_agent('v1')
        body={'run_id':r['id'],'id':'MY-CONTRACT','name':'Connected read','assessment':'clear','required_codes':[],'save':True}
        result=contract_from_run(body,store.connect,store.configuration(),store.cases()['cases'],store.timestamp)
        self.assertTrue(result['saved']);self.assertTrue(result['preview']['passed'])
    def test_contract_rejects_minimized_history(self):
        r=self.run_agent('v1',capture=False)
        with self.assertRaises(ValueError):contract_from_run({'run_id':r['id'],'id':'X','name':'X','assessment':'clear','required_codes':[],'save':False},store.connect,store.configuration(),[],store.timestamp)
    def test_platform_settings_preserve_override_unless_requested(self):
        self.run_agent('v1');save_policy({'tracking_id':'reader-v1','mode':'observe','config':DEFAULT_CONFIG},store.connect)
        save_settings({'config':DEFAULT_CONFIG,'mode':'enforce','replace_overrides':False},store.connect)
        with store.connect() as c:self.assertIsNotNone(c.execute('SELECT policy FROM tracking_agents').fetchone()[0])
        save_settings({'config':DEFAULT_CONFIG,'mode':'enforce','replace_overrides':True},store.connect)
        with store.connect() as c:self.assertIsNone(c.execute('SELECT policy FROM tracking_agents').fetchone()[0])
    def test_new_agent_inherits_platform_mode(self):
        save_settings({'config':DEFAULT_CONFIG,'mode':'enforce','replace_overrides':False},store.connect);self.run_agent('v1')
        with store.connect() as c:self.assertEqual(c.execute('SELECT mode FROM tracking_agents').fetchone()[0],'enforce')
    def test_missing_success_is_not_workflow_success(self):
        r=self.run_agent('v1',success=None);self.assertIsNone(r['metrics']['task_success'])
    def test_invalid_metrics_rejected(self):
        with self.assertRaises(ValueError):validate({'trajectory_id':None,'evaluation':None,'task_success':'yes','cost_usd':None,'cost_source':'not_reported','latency_ms':0})

if __name__=='__main__':unittest.main()
