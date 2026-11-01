import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from opencaliber import agent_server as store
from opencaliber.agent_engine import DEFAULT_CONFIG
from opencaliber.tracking import TrackedExecutor,TrackingClient,digest
from opencaliber.tracking_store import ingest,save_policy,agents
from opencaliber.policy_readiness import summarize_scope,readiness
class PolicyAssignmentTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.prev=store.DB;store.DB=Path(self.temp.name)/'test.sqlite3';store.initialize()
  self.cfg={**DEFAULT_CONFIG,'allowed_file_roots':['/workspace']};self.events=[]
  def send(raw):
   body=json.loads(raw);self.events.append(body);ack=ingest(body,store.connect,store.timestamp,self.cfg);self.client.mode=ack['mode'];return ack
  self.client=TrackingClient(sender=send,spool_dir=Path(self.temp.name)/'queue')
 def tearDown(self):store.DB=self.prev;self.temp.cleanup()
 def executor(self):return TrackedExecutor(agent={'id':'writer','version':'1'},tracking_id='writer-dev',task={'goal':'Write','allowed_tools':['file.write'],'allowed_resources':['/workspace/report.txt']},config=self.cfg,tracker=self.client)
 def action(self):return {'id':'write','tool':'file.write','resource':'/workspace/report.txt'}
 def test_wrapper_resolves_default_then_override(self):
  with self.executor() as agent:
   self.assertEqual(agent.policy_status['source'],'workspace_default')
   save_policy({'tracking_id':'writer-dev','mode':'observe','config':{**self.cfg,'max_calls':99}},store.connect)
   agent.run(self.action(),lambda:True,success=lambda v:v)
   self.assertEqual(agent.policy_status['source'],'agent_override');self.assertEqual(agent.policy_status['config_sha256'],digest({**self.cfg,'max_calls':99}))
 def test_saved_change_is_pending_until_next_event(self):
  agent=self.executor();self.assertTrue(agents(store.connect,self.cfg)[0]['assignment']['acknowledged'])
  save_policy({'tracking_id':'writer-dev','mode':'enforce','config':self.cfg},store.connect)
  self.assertFalse(agents(store.connect,self.cfg)[0]['assignment']['acknowledged'])
  agent.run(self.action(),lambda:True,success=lambda v:v);agent.finish()
  self.assertTrue(agents(store.connect,self.cfg)[0]['assignment']['acknowledged'])
 def test_default_change_does_not_replace_individual_policy(self):
  agent=self.executor();save_policy({'tracking_id':'writer-dev','mode':'observe','config':self.cfg},store.connect)
  changed={**self.cfg,'max_calls':3};self.assertEqual(agents(store.connect,changed)[0]['assignment']['config_sha256'],digest(self.cfg));agent.finish()
 def test_tracking_id_collision_rejected(self):
  agent=self.executor();bad=copy.deepcopy(self.events[0]);bad['trace']['agent']['id']='other-agent'
  with self.assertRaises(ValueError):ingest(bad,store.connect,store.timestamp,self.cfg)
  agent.finish()
 def test_scope_does_not_store_exact_resources_or_values(self):
  agent=self.executor();agent.run(self.action(),lambda:True,success=lambda v:v);agent.finish()
  scope=agents(store.connect,self.cfg)[0]['scope'];self.assertNotIn('/workspace/report.txt',json.dumps(scope));self.assertEqual(scope['declared_tools'],['file.write'])
 def test_readiness_reports_unmapped_and_missing_metadata(self):
  trace={'agent':{'id':'db','version':'1'},'workflow_id':'w','task':{'goal':'Read','allowed_tools':['database.read','custom.export']},'actions':[{'id':'a','tool':'database.read','resource':'SECRET-TABLE'}]}
  report=readiness(summarize_scope(trace,'completed'),self.cfg,'db')
  self.assertEqual(report['status'],'gaps_to_review');self.assertIn('custom.export',report['unobserved_tools']);self.assertTrue(any('records' in g for g in report['gaps']));self.assertNotIn('SECRET-TABLE',json.dumps(report))
 def test_environment_id_override_is_explicit(self):
  with patch.dict(os.environ,{'OPENCALIBER_TRACKING_ID':'writer-staging'}):
   agent=self.executor();self.assertEqual(agent.tracking_id,'writer-staging');agent.finish()
 def test_schema_upgrade_preserves_policy(self):
  agent=self.executor();save_policy({'tracking_id':'writer-dev','mode':'enforce','config':self.cfg},store.connect);store.initialize()
  self.assertEqual(agents(store.connect,self.cfg)[0]['policy'],self.cfg);agent.finish()
if __name__=='__main__':unittest.main()
