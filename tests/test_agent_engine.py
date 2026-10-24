import copy
import json
import unittest
from pathlib import Path
from opencaliber.agent_engine import DEFAULT_CONFIG,evaluate_trace,validate_config,validate_trace

FIXTURES=json.loads((Path(__file__).resolve().parents[1]/'data/agent_cases.json').read_text(encoding='utf-8'))['cases']


class AgentCaseTests(unittest.TestCase):
    pass


def build_test(case):
    def run(self):
        source=copy.deepcopy(case['trace']);cfg={**DEFAULT_CONFIG,**case['config_patch']}
        result=evaluate_trace(source,cfg)
        self.assertEqual(result['assessment'],case['expected']['assessment'])
        codes={f['code'] for a in result['actions'] for f in a['findings']}
        self.assertTrue(set(case['expected']['required_codes'])<=codes)
        self.assertEqual(source,case['trace'],'Evaluation must not mutate the trace')
        self.assertEqual(result['score_type'],'heuristic_not_probability')
        ids={a['id'] for a in source['actions']}
        self.assertTrue(all(set(f['evidence_ids'])<=ids for a in result['actions'] for f in a['findings']))
    return run


for case in FIXTURES:
    setattr(AgentCaseTests,'test_'+case['id'].replace('-','_'),build_test(case))


class AgentSchemaTests(unittest.TestCase):
    def test_unique_cases_and_minimum_count(self):
        self.assertGreaterEqual(len(FIXTURES),50)
        self.assertEqual(len({c['name'] for c in FIXTURES}),len(FIXTURES))
    def test_duplicate_action_rejected(self):
        t=copy.deepcopy(FIXTURES[0]['trace']);t['actions']*=2
        with self.assertRaises(ValueError):validate_trace(t)
    def test_negative_and_boolean_records_rejected(self):
        for n in (-1,True,1.5):
            t=copy.deepcopy(FIXTURES[0]['trace']);t['actions'][0]['arguments']={'records':n}
            with self.assertRaises(ValueError):validate_trace(t)
    def test_invented_fields_rejected(self):
        t=copy.deepcopy(FIXTURES[0]['trace']);t['actions'][0]['execute']=True
        with self.assertRaises(ValueError):validate_trace(t)
    def test_invalid_config_rejected(self):
        for change in ({'max_calls':0},{'max_records':True},{'allowed_hosts':['*.company.test']},{'allowed_file_roots':['/a/../b']},{'require_scope':'yes'}):
            with self.assertRaises(ValueError):validate_config({**DEFAULT_CONFIG,**change})
    def test_cumulative_evidence_references_prior_actions(self):
        c=next(c for c in FIXTURES if c['name']=='Split-volume reads exceed cumulative budget')
        r=evaluate_trace(c['trace'])
        f=next(f for a in r['actions'] for f in a['findings'] if f['code']=='CUMULATIVE_RECORD_BUDGET')
        self.assertEqual(f['evidence_ids'],['a1','a2'])
    def test_empty_allowlists_deny(self):
        c=next(c for c in FIXTURES if c['name']=='Approved documentation fetch')
        self.assertEqual(evaluate_trace(c['trace'],{**DEFAULT_CONFIG,'allowed_hosts':[]})['assessment'],'violation')
    def test_low_severity_is_not_permission(self):
        c=next(c for c in FIXTURES if c['name']=='Missing structured scope requires review')
        result=evaluate_trace(c['trace'],{**DEFAULT_CONFIG,'review_score':99})
        self.assertEqual(result['assessment'],'review')
        self.assertEqual(result['actions'][0]['priority'],'low')


if __name__=='__main__':unittest.main()
