import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from fastapi.testclient import TestClient
from opencaliber.cloud_app import Settings,create_app,authorized
from opencaliber import agent_server as store
from deploy.build_bundle import build

TOKEN='development-test-token-'+'x'*32


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.settings=Settings('https://opencaliber.test',TOKEN,Path(self.temp.name).resolve(),False)
        self.client=TestClient(create_app(self.settings),base_url='https://opencaliber.test')
        self.client.__enter__()
        self.headers={'Authorization':'Bearer '+TOKEN}

    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()

    def test_adoption_routes_require_auth_and_normalize(self):
        self.assertEqual(self.client.get('/api/adoption/profiles').status_code,401)
        profiles=self.client.get('/api/adoption/profiles',headers=self.headers).json();self.assertIn('read-only-analytics',profiles)
        examples=self.client.get('/api/adoption/examples',headers=self.headers).json()
        imported=self.client.post('/api/adoption/databricks',json={'events':examples['databricks-rows.json'],'context':examples['databricks-context.json']},headers=self.headers)
        self.assertEqual(imported.status_code,200)
        coverage=self.client.post('/api/adoption/coverage',json={'trace':imported.json()['trace']},headers=self.headers)
        self.assertEqual(coverage.status_code,200);self.assertEqual(coverage.json()['missing_application_outcome_ids'],['db-audit-01'])
        self.assertEqual(self.client.post('/api/adoption/profile',json={'profile':{}},headers=self.headers).status_code,400)

    def test_sequence_rules_in_hosted_api(self):
        cfg=json.loads((store.ROOT/'examples/sequence_config.json').read_text())
        trace=json.loads((store.ROOT/'examples/sequence_trace.json').read_text())
        self.assertEqual(self.client.post('/api/config',json=cfg,headers=self.headers).status_code,200)
        response=self.client.post('/api/evaluate',json={'trace':trace},headers=self.headers)
        self.assertEqual(response.status_code,201)
        check=response.json()['result']['actions'][-1]['sequence_checks'][0]
        self.assertTrue(check['satisfied'])
        self.assertEqual(check['evidence_ids'],['backup-01','delete-01'])

    def test_clean_page_routes_and_redirects(self):
        for old,new in (('/index.html','/'),('/agents.html','/agents'),('/console.html','/console'),('/agents/','/agents'),('/console/','/console')):
            response=self.client.get(old+'?review=links',headers=self.headers,follow_redirects=False)
            self.assertEqual(response.status_code,308)
            self.assertEqual(response.headers['location'],new+'?review=links')
        self.assertEqual(self.client.get('/agents').status_code,200)
        self.assertEqual(self.client.get('/console',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/console').status_code,401)
        self.assertEqual(self.client.get('/console/').status_code,401)

    def test_public_site_and_library_without_auth(self):
        for path in ('/','/index.html','/agents.html','/assets/logo.svg','/agents.json','/health/live','/health/ready'):
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,200)
        entries=self.client.get('/agents.json').json();self.assertEqual(len(entries),64)
        response=self.client.get('/'+entries[-1]['download']);self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:self.assertIsNone(archive.testzip())

    def test_private_auth_and_boundary(self):
        for path in ('/console.html','/api/state','/api/runs/not-found','https://opencaliber.test//console.html','/%63onsole.html'):
            with self.subTest(path=path):self.assertIn(self.client.get(path).status_code,(401,404))
        self.assertEqual(self.client.get('/api/state',headers=self.headers).status_code,200)
        basic=base64.b64encode(('admin:'+TOKEN).encode()).decode()
        self.assertEqual(self.client.get('/console.html',headers={'Authorization':'Basic '+basic}).status_code,200)
        self.assertEqual(self.client.get('/api/state',headers={'Authorization':'Bearer wrong'}).status_code,401)
        self.assertEqual(self.client.get('/api/state',headers={**self.headers,'Host':'outside.test'}).status_code,403)
        self.assertEqual(self.client.post('/api/benchmark',json={},headers={**self.headers,'Origin':'https://outside.test'}).status_code,403)
        self.assertEqual(self.client.get('http://opencaliber.test/api/state',headers=self.headers).status_code,403)

    def test_cloud_evaluate_redacts_and_review_persists(self):
        bundle=self.client.get('/api/integration-examples',headers=self.headers).json()
        ctx={k:bundle[k] for k in ('policy','agent','task','session_id','workflow_id')}
        normalized=self.client.post('/api/normalize',json={'provider':'anthropic','response':bundle['responses']['anthropic']['unsafe'],'context':ctx},headers=self.headers)
        self.assertEqual(normalized.status_code,200)
        response=self.client.post('/api/evaluate',json={'trace':normalized.json()['trace']},headers=self.headers)
        self.assertEqual(response.status_code,201);data=response.json()
        self.assertEqual(data['result']['assessment'],'violation');self.assertFalse(data['result']['replayable'])
        saved=self.client.get('/api/runs/'+data['id'],headers=self.headers).json()
        self.assertNotIn('/upload',json.dumps(saved));self.assertNotIn(bundle['task']['goal'],json.dumps(saved))
        self.assertEqual(self.client.post('/api/review',json={'id':data['id'],'status':'reviewed','note':'Inspect destination'},headers=self.headers).status_code,200)
        state=self.client.get('/api/state',headers=self.headers).json()
        self.assertEqual(state['runs'][0]['status'],'reviewed');self.assertTrue(state['findings'])
        self.assertTrue((self.settings.data_dir/'agent-console.sqlite3').is_file())

    def test_raw_opt_in_and_benchmark(self):
        trace=store.cases()['cases'][0]['trace']
        response=self.client.post('/api/evaluate',json={'trace':trace,'storage':'raw'},headers=self.headers)
        self.assertTrue(response.json()['result']['replayable'])
        report=self.client.post('/api/benchmark',json={},headers=self.headers)
        self.assertEqual(report.json()['passed'],70)
        cfg=self.client.get('/api/state',headers=self.headers).json()['config']
        self.assertEqual(self.client.post('/api/config',json=cfg,headers=self.headers).status_code,200)

    def test_request_errors(self):
        self.assertEqual(self.client.post('/api/evaluate',json={'trace':{}},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/evaluate',content=b'bad',headers=self.headers).status_code,415)
        self.assertEqual(self.client.post('/api/evaluate',content=b'x'*1048577,headers={**self.headers,'Content-Type':'application/json'}).status_code,413)
        self.assertEqual(self.client.get('/api/runs/missing',headers=self.headers).status_code,404)

    def test_public_runtime_download_and_video_seek(self):
        response=self.client.get('/api/package');self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertNotIn('opencaliber/cloud_app.py',archive.namelist())
            self.assertFalse(any(n.endswith('.sqlite3') or n.startswith('deploy/') for n in archive.namelist()))
        response=self.client.get('/media/opencaliber-walkthrough.mp4',headers={'Range':'bytes=0-63'})
        self.assertEqual(response.status_code,206);self.assertEqual(len(response.content),64)

    def test_configuration_fails_closed(self):
        with self.assertRaises(RuntimeError):Settings('http://outside.test',TOKEN,self.settings.data_dir,False).validate()
        with self.assertRaises(RuntimeError):Settings(self.settings.public_origin,'short',self.settings.data_dir,False).validate()
        with patch('opencaliber.cloud_app.os.path.ismount',return_value=False):
            with self.assertRaises(RuntimeError):Settings(self.settings.public_origin,TOKEN,self.settings.data_dir,True).validate()
        user=base64.b64encode(('ünknown:'+TOKEN).encode()).decode()
        self.assertFalse(authorized('Basic '+user,TOKEN))


class BundleTests(unittest.TestCase):
    def test_release_bundle_allowlist(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            with zipfile.ZipFile(build(Path(temp)/'release.zip')) as archive:
                names=archive.namelist();self.assertIsNone(archive.testzip())
                for name in ('application.py','Procfile','requirements.txt','deploy/bootstrap.py','.ebextensions/01_runtime.config','web/index.html'):
                    self.assertIn(name,names)
                self.assertEqual(len([n for n in names if n.startswith('web/downloads/agents/')]),64)
                self.assertFalse(any(n.startswith(('artifacts/','notebooks/','tests/')) or n.endswith(('.sqlite3','.env','.safetensors')) for n in names))
                self.assertNotIn('torch',archive.read('requirements.txt').decode())


class BootstrapGuardTests(unittest.TestCase):
    def test_invalid_volume_rejected_before_aws(self):
        from deploy import bootstrap
        with self.assertRaises(RuntimeError):bootstrap.mount_volume({'OPENCALIBER_DATA_VOLUME_ID':'not-a-volume'},{},None)

    def test_existing_filesystem_is_never_formatted(self):
        from deploy import bootstrap
        from unittest.mock import Mock
        instance={'instanceId':'i-demo','availabilityZone':'ap-south-1a'}
        ec2=Mock()
        ec2.describe_volumes.return_value={'Volumes':[{'AvailabilityZone':'ap-south-1a','Attachments':[{'InstanceId':'i-demo','State':'attached','Device':'/dev/sdf'}]}]}
        with patch.object(bootstrap,'volume_device',return_value='/dev/fake-data'),patch.object(bootstrap.subprocess,'run',return_value=Mock(returncode=0,stdout='xfs')),patch.object(bootstrap,'run') as command:
            with self.assertRaisesRegex(RuntimeError,'no existing filesystem was overwritten'):
                bootstrap.mount_volume({'OPENCALIBER_DATA_VOLUME_ID':'vol-123abc'},instance,ec2,sleep=lambda _:None)
            command.assert_not_called()

    def test_wrong_az_rejected(self):
        from deploy import bootstrap
        from unittest.mock import Mock
        ec2=Mock();ec2.describe_volumes.return_value={'Volumes':[{'AvailabilityZone':'ap-south-1b'}]}
        with self.assertRaisesRegex(RuntimeError,'same availability zone'):
            bootstrap.mount_volume({'OPENCALIBER_DATA_VOLUME_ID':'vol-123abc'},{'availabilityZone':'ap-south-1a'},ec2,sleep=lambda _:None)
        ec2.attach_volume.assert_not_called()
