import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools.build_agent_library import AGENTS,build_agent


class AgentLibraryTests(unittest.TestCase):
    def test_packs_run_without_checkout_or_credentials(self):
        for spec in AGENTS:
            with self.subTest(agent=spec['id']),tempfile.TemporaryDirectory() as temp:
                with zipfile.ZipFile(io.BytesIO(build_agent(spec))) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertFalse(any(n.endswith('/.env') or '/outputs/' in n for n in archive.namelist()))
                    archive.extractall(temp)
                folder=Path(temp)/spec['id']
                env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','OPENAI_MODEL','ANTHROPIC_API_KEY','ANTHROPIC_MODEL')}
                demo=subprocess.run([sys.executable,'agent.py','--demo'],cwd=folder,env=env,capture_output=True,text=True)
                self.assertEqual(demo.returncode,0,demo.stderr)
                self.assertIn('DEMO',(folder/'outputs/draft.txt').read_text(encoding='utf-8'))
                result=json.loads((folder/'outputs/evaluation.json').read_text())
                self.assertEqual(result['agent']['id'],spec['id']);self.assertEqual(result['assessment'],'clear')
                again=subprocess.run([sys.executable,'agent.py','--demo'],cwd=folder,env=env,capture_output=True,text=True)
                self.assertNotEqual(again.returncode,0);self.assertIn('Output exists',again.stderr)
                live=subprocess.run([sys.executable,'agent.py','--run','--overwrite'],cwd=folder,env=env,capture_output=True,text=True)
                self.assertNotEqual(live.returncode,0);self.assertIn('OPENAI_API_KEY',live.stderr)
                tests=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],cwd=folder,env=env,capture_output=True,text=True)
                self.assertEqual(tests.returncode,0,tests.stderr)

    def test_provider_requests_with_mock_transport(self):
        # Provider wiring is exercised with fake responses; no paid API calls.
        spec=importlib.util.spec_from_file_location('starter',Path(__file__).resolve().parents[1]/'agent_templates/agent.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Response:
            def __init__(self,payload):self.payload=payload
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(self.payload).encode()
        for provider in ('openai','anthropic'):
            config={'provider':provider,'instructions':'Draft a summary','max_output_tokens':100,'timeout_seconds':2}
            payload={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Draft text'}]}]} if provider=='openai' else {'stop_reason':'end_turn','content':[{'type':'text','text':'Draft text'}]}
            class Opener:
                def open(self,request,timeout):
                    self_url=request.full_url
                    assert self_url==('https://api.openai.com/v1/responses' if provider=='openai' else 'https://api.anthropic.com/v1/messages')
                    assert 'fake-test-key' not in request.data.decode()
                    return Response(payload)
            prefix='OPENAI' if provider=='openai' else 'ANTHROPIC'
            with patch.dict(os.environ,{prefix+'_API_KEY':'fake-test-key',prefix+'_MODEL':'test-model'}),patch.object(module.urllib.request,'build_opener',return_value=Opener()):
                self.assertEqual(module.provider_draft(config,[('sample.txt','Sample data')]),'Draft text')

    def test_input_size_limit(self):
        spec=importlib.util.spec_from_file_location('starter',Path(__file__).resolve().parents[1]/'agent_templates/agent.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/'sample.txt').write_text('sample data')
            with self.assertRaisesRegex(ValueError,'max_input_bytes'):
                module.read_inputs({'input_dir':temp,'max_files':2,'max_input_bytes':3})
