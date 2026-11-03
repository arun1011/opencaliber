import copy,json,tempfile,unittest
from pathlib import Path
from opencaliber.comparison import compare,run_versions
from opencaliber.comparison_demo import demo_bundle
from opencaliber.agent_engine import DEFAULT_CONFIG
from opencaliber import agent_server as store
from opencaliber.comparison_store import save,list_reports,get_report
class ComparisonTests(unittest.TestCase):
 def setUp(self):self.bundle=demo_bundle()
 def test_demo_distinguishes_task_quality_from_policy_compliance(self):
  r=compare(self.bundle);self.assertEqual(r['baseline']['task_successes'],2);self.assertEqual(r['candidate']['task_successes'],3)
  self.assertEqual(r['baseline']['policy_violations'],2);self.assertEqual(r['candidate']['policy_violations'],0)
  c=next(c for c in r['cases'] if c['id']=='summary-quality');self.assertFalse(c['candidate']['task_success']);self.assertEqual(c['candidate']['assessment'],'clear')
  self.assertTrue(any(p['type']=='improvement' and 'summary-quality' in p['case_ids'] for p in r['proposals']))
 def test_comparison_never_mutates_policy_or_bundle(self):
  before=copy.deepcopy(self.bundle);compare(self.bundle);self.assertEqual(self.bundle,before)
 def test_missing_measurements_are_unknown_not_zero(self):
  for c in self.bundle['cases']:
   c['candidate'].update(task_success=None,cost_usd=None,cost_source='not_reported',latency_ms=None,latency_source='not_reported')
  r=compare(self.bundle);self.assertIsNone(r['candidate']['task_success_rate']);self.assertIsNone(r['deltas']['total_cost_usd']);self.assertIsNone(r['deltas']['mean_latency_ms']);self.assertTrue(any(p['type']=='measurement' for p in r['proposals']))
 def test_runner_clones_inputs_and_validates_before_dispatch(self):
  seen=[]
  def callback(p):
   seen.append(copy.deepcopy(p));p['items'].append('changed')
   return {'trace':{'task':{'goal':'Read','allowed_tools':['database.read']},'actions':[{'id':'a','tool':'database.read','resource':'tickets'}]},'task_success':True,'cost_usd':None,'cost_source':'not_reported'}
  cases=[{'id':'one','input':{'items':[]},'expected':{'assessment':'clear','required_codes':[]}}]
  run_versions(cases,callback,callback,agent_id='a',baseline_version='1',candidate_version='2');self.assertEqual(seen,[{'items':[]},{'items':[]}]);self.assertEqual(cases[0]['input'],{'items':[]})
  with self.assertRaises(ValueError):run_versions(cases,callback,callback,agent_id='a',baseline_version='1',candidate_version='1')
  self.assertEqual(len(seen),2)
 def test_exception_is_not_a_clean_trace_or_secret_leak(self):
  def fail(p):raise RuntimeError('PRIVATE-ERROR-CONTENT')
  cases=[{'id':'one','input':{},'expected':{'assessment':'clear','required_codes':[]}}]
  b=run_versions(cases,fail,fail,agent_id='a',baseline_version='1',candidate_version='2');r=compare(b)
  self.assertEqual(r['candidate']['execution_errors'],1);self.assertEqual(r['candidate']['evaluated_traces'],0);self.assertNotIn('PRIVATE-ERROR-CONTENT',json.dumps(r))
 def test_invalid_pairing_metrics_and_identity_are_rejected(self):
  edits=[lambda b:b.update(candidate_version=b['baseline_version']),lambda b:b['cases'].append(copy.deepcopy(b['cases'][0])),lambda b:b['cases'][0]['candidate'].update(cost_usd=float('nan')),lambda b:b['cases'][0]['candidate'].update(latency_ms=-1),lambda b:b['cases'][0]['candidate']['trace']['agent'].update(version='wrong'),lambda b:b['cases'][0].update(input_sha256='bad')]
  for edit in edits:
   b=copy.deepcopy(self.bundle);edit(b)
   with self.assertRaises(ValueError):compare(b)
 def test_expected_negative_test_contract_is_distinct(self):
  self.bundle['cases'][1]['expected']={'assessment':'violation','required_codes':['RECORD_BUDGET']}
  r=compare(self.bundle);self.assertTrue(r['cases'][1]['baseline']['contract_passed']);self.assertEqual(r['cases'][1]['baseline']['assessment'],'violation')
 def test_partial_trace_evidence_cannot_appear_as_violation_improvement(self):
  c=self.bundle['cases'][0]['candidate'];c['trace']=None;c['error_type']='TimeoutError';c['task_success']=False
  r=compare(self.bundle);self.assertIsNone(r['deltas']['policy_violations'])
 def test_complete_cost_and_latency_deltas_have_evidence(self):
  for c in self.bundle['cases']:
   c['baseline'].update(cost_usd=1,cost_source='estimated',latency_ms=100,latency_source='reported')
   c['candidate'].update(cost_usd=2,cost_source='estimated',latency_ms=150,latency_source='reported')
  r=compare(self.bundle);self.assertEqual(r['deltas']['total_cost_usd'],4);self.assertEqual(r['deltas']['mean_latency_ms'],50)
  self.assertTrue(any('cost' in p['title'] for p in r['proposals']));self.assertTrue(any('latency' in p['title'] for p in r['proposals']))
 def test_proposals_are_review_only(self):
  for p in compare(self.bundle)['proposals']:self.assertTrue(p['review_required']);self.assertFalse(p['applied']);self.assertTrue(p['case_ids'])
 def test_saved_reports_exclude_raw_trace_and_persist(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
   prev=store.DB;store.DB=Path(folder)/'test.sqlite3'
   try:
    store.initialize();saved=save(self.bundle,store.connect,store.timestamp);store.initialize();loaded=get_report(saved['id'],store.connect)
    self.assertEqual(loaded['report']['agent_id'],self.bundle['agent_id']);self.assertEqual(len(list_reports(store.connect)),1)
    self.assertNotIn('/private/report.txt',json.dumps(loaded));self.assertNotIn('"trace":',json.dumps(loaded))
   finally:store.DB=prev
if __name__=='__main__':unittest.main()
