import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from opencaliber.executability import assess,aggregate,validate_report
from opencaliber.tracking import TrackedExecutor,TrackingClient
from opencaliber.execution import ActionBlocked,ExecutionEvidenceFailed
C={'database.read':{'arguments':{'records':'integer'},'required':['records'],'outputs':{'id':'string'},'effects':{'loaded':True}},'file.write':{'arguments':{'record_id':'string'},'required':['record_id'],'preconditions':{'loaded':True}}}
def action(tool='database.read',ident='read',args=None):return {'id':ident,'tool':tool,'resource':'tickets' if tool=='database.read' else '/workspace/report.txt','arguments':{'records':1} if args is None else args}
def attempt(ident='read',act=None,**changes):
 r={'attempt_id':ident,'action':act or action(),'execution':'succeeded','disposition':'executed','transition_accepted':True,'outputs':{'id':'T1'},'state_updates':{'loaded':True},'references':{}};r.update(changes);return r
def evidence(rows,contracts=None,complete=True,state=None):return {'contracts':copy.deepcopy(C if contracts is None else contracts),'initial_state':{'loaded':False} if state is None else state,'attempts':rows,'complete':complete}
class StepCheckTests(unittest.TestCase):
 def executor(self,contracts=C):return TrackedExecutor(agent={'id':'test','version':'1'},task={'goal':'Read then write','allowed_tools':['database.read','file.write'],'allowed_resources':['tickets','/workspace/report.txt']},tool_contracts=contracts,initial_state={'loaded':False},contract_mode='enforce',tracker=TrackingClient(enabled=False))
 def test_rejected_call_remains_after_successful_recovery(self):
  called=[]
  with self.executor() as g:
   with self.assertRaises(ActionBlocked):g.run(action('file.write','early',{'record_id':'guess'}),lambda:called.append('early'),success=lambda _:True,references={'record_id':{'attempt_id':'attempt-2','output':'id'}})
   g.run(action(),lambda:'T1',success=lambda _:True,extract_outputs=lambda v:{'id':v},state_updates=lambda v:{'loaded':True})
   g.run(action('file.write','write',{'record_id':'T1'}),lambda:called.append('write'),success=lambda _:True,references={'record_id':{'attempt_id':'attempt-2','output':'id'}})
  r=g.reliability_report();self.assertEqual(called,['write']);self.assertEqual(r['first_invalid_step'],1);self.assertFalse(r['all_calls_valid']);self.assertEqual(r['attempt_count'],3)
  self.assertEqual(aggregate([(r,True)])['recovery_success_rate'],1)
 def test_missing_contract_does_not_prove_validity(self):
  r=assess(evidence([attempt()],contracts={}));self.assertIsNone(r['all_calls_valid']);self.assertEqual(r['unknown_attempts'],1)
 def test_unknown_state_is_not_false_state(self):
  r=assess(evidence([attempt('write',action('file.write','write',{'record_id':'T1'}),outputs={},state_updates={})],state={}));self.assertIsNone(r['all_calls_valid'])
 def test_wrong_typed_argument_never_dispatches(self):
  called=[]
  with self.executor() as g:
   with self.assertRaises(ActionBlocked):g.run(action(args={'records':'one'}),lambda:called.append(True),success=lambda _:True)
  self.assertEqual(called,[]);self.assertEqual(g.reliability_report()['attempts'][0]['code'],'ARGUMENT_TYPE_MISMATCH')
 def test_post_call_bad_output_is_not_a_pre_dispatch_failure(self):
  with self.executor() as g:
   with self.assertRaises(ExecutionEvidenceFailed):g.run(action(),lambda:1,success=lambda _:True,extract_outputs=lambda v:{'id':v},state_updates=lambda v:{'loaded':True})
  self.assertEqual(g.attempts[0]['execution'],'succeeded');self.assertFalse(g.reliability_report()['all_calls_valid'])
 def test_timeout_is_unknown_and_invalidates_uncertain_state(self):
  rows=[attempt(execution='unknown',transition_accepted=None,outputs={},state_updates={}),attempt('write',action('file.write','write',{'record_id':'T1'}),outputs={},state_updates={})]
  r=assess(evidence(rows,state={'loaded':False}));self.assertIsNone(r['all_calls_valid']);self.assertIsNone(r['first_invalid_step'])
 def test_missing_output_is_unknown_not_a_fabricated_value(self):
  r=assess(evidence([attempt(outputs={})]));self.assertIsNone(r['all_calls_valid']);self.assertEqual(r['attempts'][0]['code'],'OUTPUT_NOT_OBSERVED')
 def test_reference_must_match_actual_produced_value(self):
  rows=[attempt(),attempt('write',action('file.write','write',{'record_id':'wrong'}),outputs={},state_updates={},references={'record_id':{'attempt_id':'read','output':'id'}})]
  r=assess(evidence(rows));self.assertEqual(r['first_invalid_step'],2);self.assertEqual(r['validated_progress'],.5)
 def test_consumed_reference_cannot_be_reused(self):
  c=copy.deepcopy(C);c['file.write']['consumes']=['record_id']
  w=attempt('w1',action('file.write','w1',{'record_id':'T1'}),outputs={},state_updates={},references={'record_id':{'attempt_id':'read','output':'id'}})
  w2=copy.deepcopy(w);w2['attempt_id']='w2';w2['action']['id']='w2'
  r=assess(evidence([attempt(),w,w2],contracts=c));self.assertEqual(r['first_invalid_step'],3)
 def test_no_failure_means_no_recovery_denominator(self):
  r=assess(evidence([attempt()]));a=aggregate([(r,True)]);self.assertEqual(a['valid_run_rate'],1);self.assertIsNone(a['recovery_success_rate'])
 def test_variable_horizon_and_short_completion(self):
  good=assess(evidence([attempt()]));bad=assess(evidence([attempt(),attempt('bad',action(args={'records':'bad'}))]))
  a=aggregate([(good,True),(bad,False)]);self.assertEqual(a['valid_run_rate'],.5);self.assertEqual(a['validated_progress'],.75);self.assertEqual(a['step_curve'][1]['value'],0);self.assertEqual(a['step_curve'][1]['active_runs'],1)
 def test_unknown_before_invalid_does_not_invent_exact_first_step(self):
  r=assess(evidence([attempt(execution='unknown',transition_accepted=None,outputs={},state_updates={}),attempt('bad',action(args={'records':'bad'}))]));self.assertIsNone(r['first_invalid_step']);self.assertEqual(r['first_observed_invalid_step'],2);self.assertIsNone(r['validated_progress'])
 def test_incomplete_log_cannot_be_a_fully_valid_run(self):
  r=assess(evidence([attempt()],complete=False));self.assertIsNone(r['all_calls_valid']);self.assertIsNone(r['validated_progress'])
 def test_no_tool_permission_is_explicit(self):
  e=evidence([]);self.assertIsNone(assess(e)['all_calls_valid']);e['no_tool_completion_allowed']=True;self.assertTrue(assess(e)['all_calls_valid'])
 def test_public_summary_rejects_tampered_metrics_and_has_no_values(self):
  r=assess(evidence([attempt(outputs={'id':'PRIVATE-ID'})]));self.assertNotIn('PRIVATE-ID',json.dumps(r));self.assertEqual(validate_report(r),r)
  r['all_calls_valid']=False
  with self.assertRaises(ValueError):validate_report(r)
 def test_legacy_action_names_remain_observable(self):
  row=attempt(act={'id':'step 1 / read','tool':'custom/tools.read','resource':'tickets','arguments':{}})
  r=assess(evidence([row],contracts={}));self.assertIsNone(r['all_calls_valid']);self.assertEqual(validate_report(r)['attempts'][0]['action_id'],'step 1 / read')
 def test_public_copy_uses_product_terms_only(self):
  import re
  root=Path(__file__).resolve().parents[1]
  pattern=re.compile(r'prefix executability|first.error depth|\b(?:auc-pec|pec|ter|fed|rr)\b|arxiv\.org|neurips',re.I)
  for name in ('web/index.html','web/developer-guide.js','web/reliability.js','docs/step-reliability.md','web/media/opencaliber-transcript.txt'):
   self.assertIsNone(pattern.search((root/name).read_text(encoding='utf-8')),name)
if __name__=='__main__':unittest.main()
