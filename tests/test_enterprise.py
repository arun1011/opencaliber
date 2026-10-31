import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from opencaliber.profiles import available_profiles,validate_profile,export_profile
from opencaliber.agent_engine import DEFAULT_CONFIG,evaluate_trace
from opencaliber.ingestion import normalize_mcp,normalize_databricks
from opencaliber.coverage import coverage_report
from opencaliber.execution import GuardedExecutor,ActionBlocked,EvaluationFailed
from opencaliber.ci import run_checks,markdown
ROOT=Path(__file__).resolve().parents[1]
def fixture(name):return json.loads((ROOT/'examples/enterprise'/name).read_text())
class EnterpriseTests(unittest.TestCase):
    def setUp(self):
        self.trace=json.loads((ROOT/'examples/sequence_trace.json').read_text());self.cfg=json.loads((ROOT/'examples/sequence_config.json').read_text())
        self.context=fixture('mcp-context.json');self.events=fixture('mcp-events.json')
    def executor(self,**options):return GuardedExecutor(agent=self.trace['agent'],task=self.trace['task'],workflow_id='test',config=self.cfg,**options)
    def test_profile_roundtrip(self):
        profiles=available_profiles();self.assertEqual(len(profiles),3)
        for p in profiles.values():self.assertEqual(validate_profile(p),p)
        p=export_profile(DEFAULT_CONFIG);p['config']['denied_tools'].append('file.read');self.assertNotIn('file.read',DEFAULT_CONFIG['denied_tools'])
    def test_invalid_profiles(self):
        for p in [{}, {'schema_version':True,'name':'test','config':DEFAULT_CONFIG},{'schema_version':1,'name':'','config':DEFAULT_CONFIG}]:
            with self.assertRaises(ValueError):validate_profile(p)
    def test_enforce_never_dispatches_blocked_delete(self):
        seen=[];ex=self.executor(mode='enforce')
        with self.assertRaises(ActionBlocked):ex.run(self.trace['actions'][1],lambda:seen.append('deleted'),success=lambda x:True)
        self.assertEqual(seen,[]);self.assertEqual(ex.trace['actions'],[])
    def test_backup_then_delete_dispatch(self):
        ex=self.executor(mode='enforce');backup=copy.deepcopy(self.trace['actions'][0]);backup.pop('outcome');seen=[]
        ex.run(backup,lambda:True,success=lambda v:v is True)
        ex.run(self.trace['actions'][1],lambda:seen.append('deleted'),success=lambda v:True)
        self.assertEqual(seen,['deleted']);self.assertEqual(ex.trace['actions'][0]['outcome']['status'],'succeeded')
    def test_observe_is_explicitly_not_a_blocker(self):
        seen=[];ex=self.executor();ex.run(self.trace['actions'][1],lambda:seen.append('deleted'),success=lambda v:True)
        self.assertEqual(seen,['deleted']);self.assertEqual(ex.last_evaluation['assessment'],'violation')
    def test_evaluation_failure_fails_closed_in_both_modes(self):
        for mode in ['observe','enforce']:
            seen=[];ex=self.executor(mode=mode,evaluator=lambda *args:None)
            with self.assertRaises(EvaluationFailed):ex.run(self.trace['actions'][1],lambda:seen.append('deleted'),success=lambda v:True)
            self.assertEqual(seen,[])
    def test_callback_error_is_unknown_and_not_retried(self):
        ex=self.executor();backup=copy.deepcopy(self.trace['actions'][0]);backup.pop('outcome');calls=[]
        def fail():calls.append(1);raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):ex.run(backup,fail,success=lambda v:True)
        self.assertEqual(calls,[1]);self.assertEqual(ex.trace['actions'][0]['outcome']['status'],'unknown')
    def test_failed_backup_does_not_authorize(self):
        ex=self.executor(mode='enforce');backup=copy.deepcopy(self.trace['actions'][0]);backup.pop('outcome');ex.run(backup,lambda:False,success=lambda v:v)
        with self.assertRaises(ActionBlocked):ex.run(self.trace['actions'][1],lambda:None,success=lambda v:True)
    def test_no_predeclared_success(self):
        with self.assertRaises(ValueError):self.executor().run(self.trace['actions'][0],lambda:True,success=lambda v:True)
    def test_mcp_success_and_error_precedence(self):
        trace=normalize_mcp(self.events,**self.context);self.assertEqual(evaluate_trace(trace,self.cfg)['assessment'],'clear')
        self.events[0]['result']['isError']=True;trace=normalize_mcp(self.events,**self.context)
        self.assertEqual(trace['actions'][0]['outcome']['status'],'failed');self.assertEqual(evaluate_trace(trace,self.cfg)['assessment'],'violation')
    def test_mcp_transport_success_is_unknown(self):
        self.context.pop('success_selectors');trace=normalize_mcp(self.events,**self.context)
        self.assertEqual(trace['actions'][0]['outcome']['status'],'unknown');self.assertEqual(evaluate_trace(trace,self.cfg)['assessment'],'violation')
    def test_mcp_args_cannot_assert_outcome(self):
        self.events[0]['arguments']['success']=True;self.events[0]['result']={};trace=normalize_mcp(self.events,**self.context)
        self.assertEqual(trace['actions'][0]['outcome']['status'],'unknown');self.assertNotIn('result',trace['actions'][0])
    def test_unknown_mapping_is_reviewable(self):
        self.context['policy']['tools']={};self.context.pop('success_selectors');trace=normalize_mcp(self.events,**self.context)
        self.assertTrue(all(a['tool']=='unmapped.tool' for a in trace['actions']));self.assertEqual(evaluate_trace(trace)['assessment'],'review')
    def test_mcp_invalid_and_duplicate_events(self):
        for events in [[], self.events+self.events, [{**self.events[0],'result':{'isError':'false'}}]]:
            with self.assertRaises(ValueError):normalize_mcp(events,**self.context)
    def test_databricks_audit_200_does_not_prove_business_success(self):
        trace=normalize_databricks(fixture('databricks-rows.json'),**fixture('databricks-context.json'));self.assertEqual(trace['actions'][0]['outcome']['status'],'unknown');self.assertEqual(evaluate_trace(trace)['assessment'],'clear')
    def test_databricks_failed_and_unmapped(self):
        rows=fixture('databricks-rows.json');rows[0]['response']['status_code']=403
        self.assertEqual(normalize_databricks(rows,**fixture('databricks-context.json'))['actions'][0]['outcome']['status'],'failed')
        rows[0]['action_name']='unmapped';self.assertEqual(normalize_databricks(rows,**fixture('databricks-context.json'))['actions'][0]['tool'],'unmapped.tool')
    def test_databricks_order_and_encoded_columns_rejected(self):
        rows=fixture('databricks-rows.json');other=copy.deepcopy(rows[0]);other['request_id']='next'
        with self.assertRaises(ValueError):normalize_databricks(rows+[other],**fixture('databricks-context.json'))
        rows[0]['request_params']='{}'
        with self.assertRaises(ValueError):normalize_databricks(rows,**fixture('databricks-context.json'))
    def test_coverage_is_evidence_not_accuracy(self):
        r=coverage_report(self.trace,self.cfg,['file.backup','file.delete','file.read']);self.assertEqual(r['inventory_not_observed'],['file.read']);self.assertEqual(r['missing_application_outcome_ids'],['delete-01']);self.assertEqual(r['enabled_checks']['sequence_rule_ids'],['backup-before-delete']);self.assertNotIn('accuracy',r)
    def test_coverage_unmapped_and_invalid_inventory(self):
        self.trace['actions'][0]['tool']='unmapped.tool';self.assertEqual(coverage_report(self.trace)['unmapped_tools'],['unmapped.tool'])
        with self.assertRaises(ValueError):coverage_report(self.trace,inventory='all')
    def test_ci_expected_violation_passes_and_payloads_omitted(self):
        r=run_checks(fixture('ci-suite.json'),self.cfg);self.assertEqual(r['failed'],0);self.assertEqual(r['passed'],2);self.assertNotIn('/workspace/report.csv',json.dumps(r));self.assertIn('\n| Case',markdown(r))
    def test_ci_mismatch_and_duplicate_ids(self):
        suite=fixture('ci-suite.json');suite['cases'][0]['expected_assessment']='violation';self.assertEqual(run_checks(suite,self.cfg)['failed'],1)
        suite['cases']*=2
        with self.assertRaises(ValueError):run_checks(suite,self.cfg)
    def test_cli_gating_and_offline_import(self):
        with tempfile.TemporaryDirectory() as temp:
            command=[sys.executable,'-m','opencaliber.ci','--suite','examples/enterprise/ci-suite.json','--config','examples/sequence_config.json','--output-dir',temp]
            self.assertEqual(subprocess.run(command,cwd=ROOT,capture_output=True).returncode,0)
            self.assertEqual(subprocess.run(command+['--fail-on','violation'],cwd=ROOT,capture_output=True).returncode,1)
            imported=subprocess.run([sys.executable,'-m','opencaliber.enterprise_cli','import-mcp','--input','examples/enterprise/mcp-events.json','--context','examples/enterprise/mcp-context.json'],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(imported.returncode,0,imported.stderr);self.assertEqual(len(json.loads(imported.stdout)['actions']),2)
if __name__=='__main__':unittest.main()
