import copy
import json
from pathlib import Path
import unittest

from opencaliber.agent_engine import DEFAULT_CONFIG, evaluate_trace, validate_config, validate_trace
from opencaliber.adapters import normalize_response
from opencaliber.coverage import coverage_report
from opencaliber.execution import GuardedExecutor, ActionBlocked
from opencaliber.privacy import minimize_evidence
from opencaliber.profiles import validate_profile


class ToolPolicyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.trace = {'task': {'goal': 'Read reports', 'allowed_tools': ['file.read','file.write','http.send']},
                      'actions': [{'id': 'a', 'tool': 'file.read', 'resource': '/workspace/reports/a.txt'}]}

    def result(self):
        return evaluate_trace(self.trace, self.cfg)

    def policy(self, tool='file.read', **rule):
        self.cfg['tool_policies'] = {tool: rule}

    def assertViolation(self, field):
        result = self.result()
        self.assertEqual(result['assessment'], 'violation')
        findings = result['actions'][0]['findings']
        self.assertTrue(any(f['code']=='TOOL_FIELD_NOT_ALLOWED' and f['field']==field and f['explicit_violation'] for f in findings))

    def test_legacy_and_empty_policies(self):
        del self.cfg['tool_policies']
        self.assertEqual(self.result()['assessment'], 'clear')
        self.assertEqual(validate_config(self.cfg)['tool_policies'], {})

    def test_separate_read_write_roots(self):
        self.cfg['tool_policies'] = {'file.read': {'resource': {'path_roots':['/workspace/reports']}},
                                     'file.write': {'resource': {'path_roots':['/workspace/exports']}}}
        self.assertEqual(self.result()['assessment'], 'clear')
        self.trace['actions'][0]['tool'] = 'file.write'
        self.assertViolation('resource')
        self.trace['actions'][0]['resource']='/workspace/exports/a.txt'
        self.assertEqual(self.result()['assessment'], 'clear')

    def test_path_bypasses(self):
        self.policy(resource={'path_roots':['/workspace/reports']})
        for path in ['/workspace/reports2/a','/workspace/reports/../reports/a','//workspace/reports/a',
                     r'/workspace/reports\a','/workspace/reports/\x00a','relative']:
            with self.subTest(path=path):
                self.trace['actions'][0]['resource']=path
                self.assertViolation('resource')

    def test_path_root_itself_and_descendant(self):
        self.policy(resource={'path_roots':['/workspace/reports']})
        for path in ['/workspace/reports','/workspace/reports/a','/workspace/reports/./a']:
            self.trace['actions'][0]['resource']=path
            self.assertEqual(self.result()['assessment'],'clear')

    def test_global_and_task_denials_cannot_be_overridden(self):
        self.policy(resource={'path_roots':['/other']})
        self.trace['actions'][0]['resource']='/other/a'
        self.assertIn('FILE_BOUNDARY',[f['code'] for f in self.result()['actions'][0]['findings']])
        self.trace['task']['allowed_tools']=[]
        self.assertIn('OUTSIDE_TASK_TOOLS',[f['code'] for f in self.result()['actions'][0]['findings']])
        self.cfg['denied_tools']=['file.read']
        self.assertIn('DENIED_TOOL',[f['code'] for f in self.result()['actions'][0]['findings']])

    def test_host_exactness_and_url_bypasses(self):
        self.policy('http.send',arguments={'destination':{'hosts':['API.company.test']}})
        action=self.trace['actions'][0];action.update(tool='http.send',resource='request')
        for url in ['https://api.company.test/v1','https://API.company.test:443/v1']:
            action['arguments']={'destination':url}
            self.assertEqual(self.result()['assessment'],'clear')
        for url in ['https://api.company.test.evil.test','https://sub.api.company.test','https://api.company.test.',
                    'https://u@api.company.test','ftp://api.company.test','https://api.company.test:99999',
                    'https://api.company.test\n','https://api.company.test\\evil','https://[bad']:
            with self.subTest(url=url):
                action['arguments']={'destination':url};self.assertViolation('arguments.destination')

    def test_required_argument_and_typed_values(self):
        self.policy(arguments={'account_id':{'allowed_values':['acct-a']}})
        self.assertViolation('arguments.account_id')
        for value in ['acct-b',1,True]:
            self.trace['actions'][0]['arguments']={'account_id':value};self.assertViolation('arguments.account_id')
        self.trace['actions'][0]['arguments']={'account_id':'acct-a'}
        self.assertEqual(self.result()['assessment'],'clear')
        self.policy(arguments={'account_id':{'allowed_values':[1]}})
        self.trace['actions'][0]['arguments']={'account_id':True};self.assertViolation('arguments.account_id')

    def test_numeric_bounds_and_wrong_types(self):
        self.policy(arguments={'amount':{'min':0,'max':100}})
        for value in [0,100,1.5]:
            self.trace['actions'][0]['arguments']={'amount':value};self.assertEqual(self.result()['assessment'],'clear')
        for value in [-1,101,True,'10']:
            self.trace['actions'][0]['arguments']={'amount':value};self.assertViolation('arguments.amount')

    def test_combined_checks_and_empty_allowlist(self):
        self.policy(resource={'path_roots':['/workspace'],'allowed_values':['/workspace/reports/b.txt']})
        self.assertViolation('resource')
        self.policy(resource={'allowed_values':[]});self.assertViolation('resource')

    def test_unconfigured_tool_and_extra_field(self):
        self.policy('file.write',resource={'path_roots':[]})
        self.trace['actions'][0]['arguments']={'other':'value'}
        self.assertEqual(self.result()['assessment'],'clear')

    def test_invalid_policy_schema(self):
        bad=[[],{'custom.tool':{'resource':{'allowed_values':['a']}}}, {'file.read':{}},
             {'file.read':{'arguments':{}}}, {'file.read':{'resource':{}}},
             {'file.read':{'resource':{'regex':'.*'}}}, {'file.read':{'resource':{'hosts':['*.test']}}},
             {'file.read':{'resource':{'path_roots':['/a/../b']}}},
             {'file.read':{'resource':{'min':True}}}, {'file.read':{'resource':{'max':float('inf')}}},
             {'file.read':{'resource':{'min':2,'max':1}}},
             {'file.read':{'resource':{'hosts':[],'path_roots':[]}}},
             {'file.read':{'arguments':{'nested.key':{'allowed_values':['a']}}}},
             {'file.read':{'resource':{'allowed_values':[None]}}}]
        for policy in bad:
            with self.subTest(policy=policy):
                self.cfg['tool_policies']=policy
                with self.assertRaises(ValueError):validate_config(self.cfg)

    def test_argument_schema_limits(self):
        for args in [{'x':{}},{'x':[]},{'x':None},{'x':float('nan')},{'x':float('inf')},
                     {'x':10**1000},{'x':'a'*8001},{'records':True},{'destination':1}, {'bad.key':'x'},
                     {f'k{i}':'x' for i in range(51)}]:
            with self.subTest(keys=list(args)):
                self.trace['actions'][0]['arguments']=args
                with self.assertRaises(ValueError):validate_trace(self.trace)

    def test_redaction_and_coverage(self):
        self.policy(arguments={'account_id':{'allowed_values':['private-value']}})
        self.trace['actions'][0]['arguments']={'account_id':'private-value','amount':1.5}
        result=self.result();trace,redacted=minimize_evidence(self.trace,result)
        self.assertNotIn('private-value',json.dumps([trace,redacted]))
        coverage=coverage_report(self.trace,self.cfg)
        self.assertEqual(coverage['enabled_checks']['tool_policy_fields'],{'file.read':['arguments.account_id']})
        self.assertNotIn('private-value',json.dumps(coverage))
        self.assertEqual(self.trace['actions'][0]['arguments']['account_id'],'private-value')

    def test_enforce_never_dispatches_disallowed_argument(self):
        self.policy(arguments={'account_id':{'allowed_values':['approved']}})
        guard=GuardedExecutor(agent={'id':'demo','version':'1'},task=self.trace['task'],workflow_id='test',config=self.cfg,mode='enforce')
        called=[]
        with self.assertRaises(ActionBlocked):guard.run(self.trace['actions'][0],lambda:called.append(True),success=lambda value:True)
        self.assertEqual(called,[])

    def test_profile_roundtrip_and_example(self):
        self.policy(resource={'path_roots':['/workspace/reports']})
        profile=validate_profile({'schema_version':1,'name':'Example','config':self.cfg})
        self.assertEqual(profile['config']['tool_policies'],self.cfg['tool_policies'])
        config=json.loads((Path(__file__).resolve().parents[1]/'examples/tool-policy-config.json').read_text())
        validate_config(config)

    def test_provider_projection_of_custom_scalar(self):
        policy={'version':'1','tools':{'read':{'tool':'file.read','resource_from':'path','data_class':'public','arguments':{'account_id':'payload.account'}}}}
        response={'id':'r','output':[{'type':'function_call','call_id':'a','name':'read','arguments':json.dumps({'path':'/workspace/reports/a','payload':{'account':'approved'}})}]}
        trace=normalize_response('openai-responses',response,policy=policy,agent={'id':'demo','version':'1'},task=self.trace['task'],session_id='s')
        self.assertEqual(trace['actions'][0]['arguments'],{'account_id':'approved'})


if __name__=='__main__':unittest.main()
