import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from opencaliber import agent_server as store
from opencaliber.library_runtime import LibraryExecutor,capture,draft_success
from opencaliber.tracking import TrackingClient
from opencaliber.tracking_store import ingest
from opencaliber.trajectory import Trajectory,save
from opencaliber.connected_platform import collected,compare,cohort_key
class LibraryRuntimeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.old=store.DB;store.DB=Path(self.temp.name)/'db.sqlite3';store.initialize()
 def tearDown(self):store.DB=self.old;self.temp.cleanup()
 def run_version(self,version,success=True):
  client=TrackingClient(sender=lambda raw:ingest(json.loads(raw),store.connect,store.timestamp,store.configuration()),spool_dir=Path(self.temp.name)/version,enabled=True)
  config={'title':'Library example','diagnosis_enabled':True,'capture_fields':{'database.read':['count']},'evaluation':{'experiment_id':'library','case_id':'one','input_sha256':'a'*64,'success_criterion':'expected-count','assignment':'paired'}}
  def graph(*args,**kwargs):
   kwargs['sender']=lambda body:save(body,store.connect,store.timestamp)
   return Trajectory(*args,**kwargs)
  with patch('opencaliber.library_runtime.Trajectory',side_effect=graph):
   with LibraryExecutor(library_config=config,root=Path(self.temp.name),tracker=client,agent={'id':'example','version':version},task={'goal':'Read records','allowed_tools':['database.read']}) as agent:
    agent.run({'id':'read','tool':'database.read','resource':'records','arguments':{'records':1}},lambda:{'count':1,'secret':'never capture'},success=lambda value:value['count']==1)
    agent.record_outcome(success)
  self.assertEqual(client.last_status,'delivered');return collected(store.connect)[0]
 def test_outcome_version_graph_and_opted_in_capture(self):
  row=self.run_version('2.0');self.assertEqual(row['agent']['version'],'2.0');self.assertTrue(row['metrics']['task_success']);self.assertTrue(row['context_available'])
  with store.connect() as c:
   bundle=json.loads(c.execute('SELECT bundle FROM run_diagnosis WHERE run_id=?',(row['id'],)).fetchone()[0]);self.assertEqual(bundle['outputs']['read']['count'],1);self.assertNotIn('secret',bundle['outputs']['read'])
   self.assertEqual(c.execute('SELECT COUNT(*) FROM trajectory_spans WHERE trajectory_id=?',(row['metrics']['trajectory_id'],)).fetchone()[0],2)
 def test_versions_match_on_supplied_metadata(self):
  a=self.run_version('1.0',False);b=self.run_version('2.0',True);r=compare({'baseline':cohort_key(a),'candidate':cohort_key(b)},store.connect);self.assertEqual(r['matched']['count'],1);self.assertEqual(r['matched']['success_rate_delta'],1)
 def test_default_capture_excludes_contents(self):
  self.assertEqual(capture({}, {'tool':'file.read'},b'private document'),{'result_type':'bytes','length':16})
 def test_artifact_success_checks(self):
  self.assertTrue(draft_success({'success_checks':{'required_phrases':['hello']}},'hello','hello'))
  self.assertFalse(draft_success({'success_checks':{'required_phrases':['hello']}},'different','different'))
  self.assertFalse(draft_success({},'hello','altered'))
if __name__=='__main__':unittest.main()
