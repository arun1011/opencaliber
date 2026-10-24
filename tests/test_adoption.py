import copy
import json
import socket
import subprocess
import sys
import threading
import time
import tempfile
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from opencaliber.adapters import normalize_response, validate_policy
from opencaliber.sdk import Client, EvaluationUnavailable, evaluate_response
from opencaliber.privacy import minimize_evidence
from opencaliber.regression import run_suite

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=json.loads((ROOT/'examples/adoption/bundle.json').read_text(encoding='utf-8'))


def context():
    return {k:copy.deepcopy(BUNDLE[k]) for k in ('agent','policy','task','session_id','workflow_id')}


class AdapterTests(unittest.TestCase):
    def test_provider_cases_and_projection(self):
        for provider,responses in BUNDLE['responses'].items():
            for scenario,response in responses.items():
                with self.subTest(provider=provider,scenario=scenario):
                    evaluated=evaluate_response(provider,response,**context())
                    self.assertEqual(evaluated['result']['assessment'],'violation' if scenario=='unsafe' else 'clear')
                    trace=evaluated['trace']
                    self.assertEqual(trace['actions'][0]['source_tool'],'lookup_invoices')
                    self.assertEqual(trace['context']['response_id'],response['id'])
                    self.assertNotIn('fixture-secret',json.dumps(trace))
                    self.assertNotIn('report',trace['actions'][1]['arguments'])
                    self.assertEqual(len(trace['context']['policy_sha256']),64)

    def test_sdk_model_dump(self):
        class Response:
            def model_dump(self,mode):return BUNDLE['responses']['anthropic']['unsafe']
        result=evaluate_response('anthropic',Response(),**context())
        self.assertEqual(result['result']['assessment'],'violation')

    def test_unmapped_tool_never_silently_clear(self):
        ctx=context();ctx['policy']['tools']={}
        result=evaluate_response('anthropic',BUNDLE['responses']['anthropic']['corrected'],**ctx)['result']
        self.assertEqual(result['assessment'],'review')
        self.assertTrue(all(a['task_consistency']=='not_established' for a in result['actions']))
        self.assertTrue(all('UNKNOWN_TOOL' in {f['code'] for f in a['findings']} for a in result['actions']))

    def test_missing_projected_argument_rejected(self):
        ctx=context();ctx['policy']['tools']['lookup_invoices']['arguments']['records']='missing.limit'
        with self.assertRaisesRegex(ValueError,'missing'):
            normalize_response('anthropic',BUNDLE['responses']['anthropic']['unsafe'],**ctx)

    def test_invalid_mapping_rejected(self):
        for patch in [{'tool':'arbitrary.eval'},{'resource_from':'url'}, {'data_class':'model_says_safe'}, {'arguments':{'payload':'payload'}}]:
            ctx=context();ctx['policy']['tools']['lookup_invoices'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_policy(ctx['policy'])

    def test_duplicate_call_ids_rejected(self):
        response=copy.deepcopy(BUNDLE['responses']['anthropic']['unsafe']);response['content'][1]['id']=response['content'][0]['id']
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            normalize_response('anthropic',response,**context())

    def test_malformed_or_unsupported_calls_rejected(self):
        variants=[{'status':'in_progress','output':[]},{'output':[{'type':'web_search_call'}]},
                  {'output':[{'type':'function_call','call_id':'x','name':'x','arguments':'[]'}]},
                  {'output':[None]},{'output':[]},
                  {'output':[{'type':'function_call','call_id':'x','name':'x','arguments':'not json'}]}]
        for response in variants:
            with self.subTest(response=response),self.assertRaises(ValueError):normalize_response('openai-responses',response,**context())
        response={'stop_reason':'tool_use','content':[{'type':'tool_use','id':'x','name':'click','toolset_name':'computer','input':{}}]}
        with self.assertRaises(ValueError):normalize_response('anthropic',response,**context())

    def test_nested_selectors_and_policy_digest(self):
        ctx=context();response=copy.deepcopy(BUNDLE['responses']['anthropic']['corrected'])
        response['content'][0]['input']={'request':{'limit':25}}
        ctx['policy']['tools']['lookup_invoices']['arguments']['records']='request.limit'
        before=normalize_response('anthropic',response,**ctx)
        reordered={**ctx,'policy':{'tools':ctx['policy']['tools'],'version':ctx['policy']['version']}}
        self.assertEqual(before['context']['policy_sha256'],normalize_response('anthropic',response,**reordered)['context']['policy_sha256'])
        ctx['policy']['version']='changed'
        self.assertNotEqual(before['context']['policy_sha256'],normalize_response('anthropic',response,**ctx)['context']['policy_sha256'])

    def test_privacy_after_evaluation(self):
        evaluated=evaluate_response('anthropic',BUNDLE['responses']['anthropic']['unsafe'],**context())
        original=copy.deepcopy(evaluated)
        trace,result=minimize_evidence(evaluated['trace'],evaluated['result'])
        self.assertEqual(result['assessment'],'violation')
        self.assertFalse(result['replayable'])
        self.assertNotIn('/upload',json.dumps([trace,result]))
        self.assertNotIn(BUNDLE['task']['goal'],json.dumps(trace))
        self.assertEqual(evaluated,original)
        self.assertEqual(trace['actions'][0]['arguments']['records'],25)

    def test_regression_and_failure_exit(self):
        suite=json.loads((ROOT/'examples/adoption/regression-suite.json').read_text())
        self.assertEqual(run_suite(suite)['passed'],6)
        suite['cases'][0]['expected_assessment']='clear'
        self.assertEqual(run_suite(suite)['failed'],1)
        proc=subprocess.run([sys.executable,'-m','opencaliber.agent_cli','evaluate','--input','examples/agent_trace.json','--fail-on','review'],cwd=ROOT,capture_output=True)
        self.assertEqual(proc.returncode,0)
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as directory:
            path=Path(directory)/'mismatch.json';path.write_text(json.dumps(suite),encoding='utf-8')
            report=Path(directory)/'report.json'
            proc=subprocess.run([sys.executable,'-m','opencaliber.agent_cli','regression','--input',str(path),'--output',str(report)],cwd=ROOT,capture_output=True)
            self.assertEqual(proc.returncode,1)
            self.assertEqual(json.loads(report.read_text())['failed'],1)
            self.assertNotIn('fixture-secret',report.read_text())


    def test_python_node_adapter_parity(self):
        script="""
import {readFileSync} from 'node:fs';
import {normalizeResponse} from './sdk/typescript/opencaliber.mjs';
const b=JSON.parse(readFileSync('examples/adoption/bundle.json','utf8'));
const {policy,agent,task,session_id,workflow_id}=b;
console.log(JSON.stringify(Object.entries(b.responses).flatMap(([provider,rs])=>Object.values(rs).map(r=>normalizeResponse(provider,r,{policy,agent,task,session_id,workflow_id})))));
"""
        proc=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        python=[normalize_response(p,r,**context()) for p,rs in BUNDLE['responses'].items() for r in rs.values()]
        self.assertEqual(json.loads(proc.stdout),python)


class ClientTests(unittest.TestCase):
    def test_loopback_and_timeout_validation(self):
        for endpoint in ['https://external.test','http://127.0.0.1:8787/other','http://user:secret@localhost:8787','http://localhost:8787?x=1']:
            with self.assertRaises(ValueError):Client(endpoint)
        for timeout in [0,-1,float('nan'),True,60]:
            with self.assertRaises(ValueError):Client(timeout=timeout)

    def test_unavailable_never_becomes_clear(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            # Socket is bound, not listening.
            trace=normalize_response('anthropic',BUNDLE['responses']['anthropic']['unsafe'],**context())
            client=Client(f'http://127.0.0.1:{port}',timeout=.2)
            observed=client.observe(trace)
            self.assertEqual(observed['status'],'error');self.assertIsNone(observed['assessment'])
            with self.assertRaises(EvaluationUnavailable):Client(client.endpoint,timeout=.2,failure_mode='raise').observe(trace)

    def test_slow_and_malformed_responses(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                time.sleep(.15)
                self.send_response(200);self.end_headers()
                try:self.wfile.write(b'{"result":{"assessment":"clear"}}')
                except OSError:pass
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            trace=normalize_response('anthropic',BUNDLE['responses']['anthropic']['unsafe'],**context())
            endpoint='http://127.0.0.1:'+str(http.server_address[1])
            self.assertEqual(Client(endpoint,timeout=.03).observe(trace)['status'],'error')
            self.assertEqual(Client(endpoint,timeout=1).observe(trace)['status'],'error')
        finally:http.shutdown();http.server_close();thread.join()
