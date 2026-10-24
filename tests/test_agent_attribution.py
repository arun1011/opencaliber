import copy
import unittest
from opencaliber.agent_engine import evaluate_trace,validate_trace

class AttributionTests(unittest.TestCase):
    def trace(self):
        return {'agent':{'id':'invoice-agent','version':'v2'},'workflow_id':'wf-1','task':{'goal':'Read invoices','allowed_tools':['database.read'],'read_only':True},'actions':[{'id':'a2','tool':'http.send','resource':'https://outside.test','data_class':'pii'}]}
    def test_identity_and_guidance_export(self):
        trace=self.trace();result=evaluate_trace(trace)
        self.assertEqual(result['agent'],trace['agent']);self.assertEqual(result['workflow_id'],'wf-1')
        findings=result['actions'][0]['findings']
        self.assertTrue(findings)
        for finding in findings:
            self.assertEqual(set(finding['remediation']),{'change','verify','basis'})
            self.assertIn('a2',finding['evidence_ids'])
        self.assertIn('redact',next(f for f in findings if f['code']=='SENSITIVE_EXTERNAL_TRANSFER')['remediation']['change'])
        result['agent']['version']='changed';self.assertEqual(trace['agent']['version'],'v2')
    def test_legacy_is_unattributed(self):
        trace=self.trace();del trace['agent'];del trace['workflow_id']
        result=evaluate_trace(trace);self.assertIsNone(result['agent']);self.assertIsNone(result['workflow_id'])
    def test_invalid_metadata(self):
        for value in [None,{}, {'id':'x'}, {'id':'x','version':' '},{'id':'x','version':'v','extra':'x'}]:
            trace=self.trace();trace['agent']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate_trace(trace)
        trace=self.trace();trace['workflow_id']=False
        with self.assertRaises(ValueError):validate_trace(trace)
