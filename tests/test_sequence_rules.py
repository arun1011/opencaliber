import copy
import json
from pathlib import Path
import unittest
from opencaliber.agent_engine import DEFAULT_CONFIG,evaluate_trace,validate_config,validate_trace
from opencaliber.privacy import minimize_evidence
ROOT=Path(__file__).resolve().parents[1]

class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.trace=json.loads((ROOT/'examples/sequence_trace.json').read_text())
        self.cfg=json.loads((ROOT/'examples/sequence_config.json').read_text())
    def result(self):return evaluate_trace(self.trace,self.cfg)
    def blocked(self):
        result=self.result();findings=[f for a in result['actions'] for f in a['findings'] if f['code']=='SEQUENCE_PREREQUISITE_MISSING']
        self.assertTrue(findings);self.assertEqual(result['assessment'],'violation');self.assertEqual(findings[-1]['rule_id'],'backup-before-delete');return findings[-1]
    def test_success_and_evidence(self):
        before=copy.deepcopy(self.trace);r=self.result();self.assertEqual(r['assessment'],'clear');self.assertEqual(r['actions'][1]['sequence_checks'][0]['evidence_ids'],['backup-01','delete-01']);self.assertEqual(self.trace,before)
    def test_no_backup(self):
        self.trace['actions'].pop(0);self.assertEqual(self.blocked()['evidence_ids'],['delete-01'])
    def test_backup_later_cannot_authorize(self):
        self.trace['actions'].reverse();self.blocked()
    def test_wrong_resource(self):
        self.trace['actions'][0]['resource']='/workspace/other.csv';self.blocked()
    def test_unsuccessful_or_untrusted_outcomes(self):
        for outcome in [None,{'status':'failed','source':'application'},{'status':'unknown','source':'application'},{'status':'succeeded','source':'agent'},{'status':'succeeded','source':'unknown'}]:
            with self.subTest(outcome=outcome):
                if outcome is None:self.trace['actions'][0].pop('outcome',None)
                else:self.trace['actions'][0]['outcome']=outcome
                self.blocked()
    def test_missing_or_different_versions(self):
        for version in [None,'revision-8']:
            if version is None:self.trace['actions'][1].pop('resource_version')
            else:self.trace['actions'][1]['resource_version']=version
            self.blocked()
    def test_unversioned_supported_with_limits(self):
        for a in self.trace['actions']:a.pop('resource_version')
        self.assertEqual(self.result()['assessment'],'clear')
    def test_writes_invalidate_even_if_failed(self):
        self.trace['actions'].insert(1,{'id':'write-01','tool':'file.write','resource':'/workspace/report.csv','outcome':{'status':'failed','source':'application'}})
        self.assertEqual(self.blocked()['evidence_ids'],['write-01','delete-01'])
    def test_other_resource_write_does_not_invalidate(self):
        self.trace['task']['allowed_resources'].append('/workspace/other.csv')
        self.trace['actions'].insert(1,{'id':'write-01','tool':'file.write','resource':'/workspace/other.csv'})
        self.assertEqual(self.result()['assessment'],'clear')
    def test_new_backup_after_write_restores(self):
        backup=copy.deepcopy(self.trace['actions'][0]);backup['id']='backup-02'
        self.trace['actions'][1:1]=[{'id':'write-01','tool':'file.write','resource':'/workspace/report.csv'},backup]
        r=self.result();self.assertEqual(r['assessment'],'clear');self.assertEqual(r['actions'][-1]['sequence_checks'][0]['evidence_ids'],['backup-02','delete-01'])
    def test_latest_failed_backup_supersedes_success(self):
        backup=copy.deepcopy(self.trace['actions'][0]);backup['id']='backup-02';backup['outcome']['status']='failed';self.trace['actions'].insert(1,backup);self.assertEqual(self.blocked()['evidence_ids'],['backup-02','delete-01'])
    def test_two_deletes_require_fresh_backup(self):
        delete=copy.deepcopy(self.trace['actions'][-1]);delete['id']='delete-02';self.trace['actions'].append(delete);self.trace['task']['approved_action_ids'].append('delete-02');self.assertEqual(self.blocked()['evidence_ids'],['delete-01','delete-02'])
    def test_prerequisite_with_policy_violation_cannot_authorize(self):
        self.cfg['denied_tools'].append('file.backup');self.blocked()
    def test_approval_still_required(self):
        self.trace['task']['approved_action_ids']=[];r=self.result();self.assertTrue(r['actions'][1]['sequence_checks'][0]['satisfied']);self.assertIn('APPROVAL_MISSING',[f['code'] for f in r['actions'][1]['findings']])
    def test_no_cross_trace_state(self):
        self.assertEqual(self.result()['assessment'],'clear');self.trace['actions'].pop(0);self.blocked()
    def test_multiple_rules_all_required(self):
        self.cfg['sequence_rules'].append({'id':'read-before-delete','tool':'file.delete','requires_tool':'file.read','invalidate_on':[]})
        r=self.result();checks=r['actions'][-1]['sequence_checks'];self.assertEqual([c['satisfied'] for c in checks],[True,False])
    def test_disabled_and_legacy_settings(self):
        self.cfg.pop('sequence_rules');self.trace['actions'].pop(0);self.assertEqual(evaluate_trace(self.trace,self.cfg)['assessment'],'clear');self.assertEqual(validate_config(self.cfg)['sequence_rules'],[])
    def test_database_rule(self):
        for a in self.trace['actions']:a['tool']=a['tool'].replace('file.','database.');a['resource']='invoices'
        self.trace['task']['allowed_resources']=['invoices'];self.trace['task']['allowed_tools']=['database.backup','database.delete']
        self.cfg['sequence_rules']=[{'id':'db-backup','tool':'database.delete','requires_tool':'database.backup','invalidate_on':['database.write']}]
        self.assertEqual(self.result()['assessment'],'clear')
    def test_invalid_rules_rejected(self):
        valid=self.cfg['sequence_rules'][0]
        for value in [None,{},[{}],[{**valid,'tool':'unknown'}],[{**valid,'requires_tool':'file.delete'}],[valid,valid],[{**valid,'invalidate_on':['file.backup']}],[{**valid,'invalidate_on':'file.write'}]]:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_config({**DEFAULT_CONFIG,'sequence_rules':value})
    def test_invalid_outcome_schema(self):
        for value in [True,{}, {'status':'completed','source':'application'}, {'status':'succeeded','source':'application','payload':'no'}, {'status':'succeeded','source':'model'}]:
            self.trace['actions'][0]['outcome']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate_trace(self.trace)
    def test_redaction_removes_versions_after_evaluation(self):
        trace,result=minimize_evidence(self.trace,self.result());self.assertEqual(trace['actions'][0]['resource_version'],'[redacted-version]');self.assertFalse(result['replayable']);self.assertEqual(result['actions'][1]['sequence_checks'][0]['evidence_ids'],['backup-01','delete-01'])

if __name__=='__main__':unittest.main()
