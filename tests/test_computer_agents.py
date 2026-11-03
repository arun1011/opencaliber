import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools.build_computer_agents import COMPUTER_AGENTS, build_computer_agent


class ComputerWorkflowTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{'OPENCALIBER_TRACKING':'off'});env.start();self.addCleanup(env.stop)
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.spec = COMPUTER_AGENTS[0]
        with zipfile.ZipFile(io.BytesIO(build_computer_agent(self.spec))) as archive:
            archive.extractall(self.directory.name)
        self.folder = Path(self.directory.name)/self.spec['id']
        spec = importlib.util.spec_from_file_location('computer_workflow_test',self.folder/'agent.py')
        self.agent = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.agent)
        self.config = json.loads((self.folder/'config.json').read_text())
        self.agent.ROOT = self.folder

    def test_all_four_extract_and_run_offline_with_tests(self):
        for entry in COMPUTER_AGENTS:
            with self.subTest(agent=entry['id']):
                with zipfile.ZipFile(io.BytesIO(build_computer_agent(entry))) as archive:
                    archive.extractall(self.directory.name)
                    self.assertIsNone(archive.testzip())
                folder = Path(self.directory.name)/entry['id']
                run = subprocess.run([sys.executable,'agent.py','--demo'],cwd=folder,capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stderr)
                evidence = json.loads((folder/'outputs/evaluation.json').read_text())
                self.assertEqual(evidence['assessment'],'clear')
                self.assertEqual(evidence['workflow_status'],'completed')
                tests = subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],cwd=folder,capture_output=True,text=True)
                self.assertEqual(tests.returncode,0,tests.stderr)

    def test_shipped_policy_matches_runtime(self):
        self.assertEqual(json.loads((self.folder/'policy.json').read_text()),self.agent.policy(self.config))

    def test_live_requires_explicit_configuration_review(self):
        run = subprocess.run([sys.executable,'agent.py','--run'],cwd=self.folder,capture_output=True,text=True)
        self.assertNotEqual(run.returncode,0)
        self.assertIn('--approve-config',run.stderr)
        self.assertFalse((self.folder/'outputs').exists())

    def test_unapproved_target_is_rejected(self):
        for url in ['https://example.com.attacker.test','https://sub.example.com','http://example.com','https://u:p@example.com']:
            config = copy.deepcopy(self.config);config['targets'][0]['url']=url
            with self.subTest(url=url),self.assertRaises(ValueError):self.agent.validate(config)

    def test_path_traversal_and_outside_outputs(self):
        with self.assertRaises(ValueError):self.agent.inside(self.folder,'../escape')
        with self.assertRaises(ValueError):self.agent.inside(self.folder,'.')

    def test_input_budget_and_missing_fields(self):
        config = copy.deepcopy(self.config);config['max_input_bytes']=1
        with self.assertRaises(ValueError):self.agent.document_workflow(config,self.agent.make_guard(config))
        entries = self.agent.extract_entries('invoice_id: DEMO\nowner: Example','.txt',['invoice_id','owner','total'])
        self.assertEqual(entries[0]['total'],'')

    def test_invalid_limits_methods_and_login_settings(self):
        for changes in [{'max_pages':6},{'allowed_methods':['DELETE']},{'manual_login':True,'headless':True},
                        {'fields':['nested.key']},{'browser_channel':'arbitrary'},{'download_extension':'.exe'}]:
            config = {**self.config,**changes}
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.agent.validate(config)

    def test_source_url_omits_query_credentials(self):
        self.assertEqual(self.agent.source_url('https://example.com/report?token=private#fragment'),'https://example.com/report')

    def fake_browser(self):
        page = Mock()
        page.goto.return_value = types.SimpleNamespace(status=200)
        page.title.return_value = 'Example Domain'
        page.url = 'https://example.com?token=private'
        page.locator.return_value.inner_text.return_value = 'Example Domain: test evidence'
        context = Mock();context.new_page.return_value=page
        browser = Mock();browser.new_context.return_value=context
        pw = Mock();pw.chromium.launch.return_value=browser
        manager = Mock();manager.__enter__=Mock(return_value=pw);manager.__exit__=Mock(return_value=False)
        module = types.ModuleType('playwright.sync_api');module.sync_playwright=lambda:manager
        return module,pw,browser,context,page

    def test_browser_execution_uses_routes_and_records_sources(self):
        module,pw,browser,context,page = self.fake_browser()
        output = self.folder/'outputs';output.mkdir()
        with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':module}):
            result=self.agent.browser_workflow(self.config,self.agent.make_guard(self.config),output)
        self.assertEqual(result['sources'][0]['url'],'https://example.com')
        self.assertIn('test evidence',result['sources'][0]['excerpt'])
        context.close.assert_called_once();browser.close.assert_called_once()
        self.assertEqual(browser.new_context.call_args.kwargs['service_workers'],'block')
        route_handler=context.route.call_args.args[1]
        for url,method,allowed in [('https://example.com','GET',True),('https://outside.test','GET',False),
                                   ('http://example.com','GET',False),('https://example.com','DELETE',False)]:
            route=Mock();route.request=types.SimpleNamespace(url=url,method=method)
            route_handler(route)
            self.assertEqual(route.continue_.called,allowed)
            self.assertEqual(route.abort.called,not allowed)

    def test_ui_assertion_failure_and_screenshot_action(self):
        module,pw,browser,context,page=self.fake_browser()
        config={**self.config,'kind':'testing','targets':[{'url':'https://example.com','must_contain':'MISSING'}]}
        output=self.folder/'outputs';output.mkdir()
        guard=self.agent.make_guard(config)
        with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':module}):
            result=self.agent.browser_workflow(config,guard,output)
        self.assertFalse(result['assertions'][0]['passed'])
        page.screenshot.assert_called_once()
        self.assertEqual(guard.trace['actions'][-1]['tool'],'file.write')

    def test_navigation_exception_closes_context_and_retains_unknown(self):
        module,pw,browser,context,page=self.fake_browser();page.goto.side_effect=TimeoutError('test timeout')
        guard=self.agent.make_guard(self.config)
        with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':module}),self.assertRaises(TimeoutError):
            self.agent.browser_workflow(self.config,guard,self.folder)
        context.close.assert_called_once();browser.close.assert_called_once()
        self.assertEqual(guard.trace['actions'][0]['outcome']['status'],'unknown')

    def test_report_download_requires_approval_and_has_a_guarded_save(self):
        module,pw,browser,context,page=self.fake_browser()
        sample=self.folder/'download.csv';sample.write_text('id,total\n1,12\n')
        item=Mock();item.path.return_value=str(sample);item.suggested_filename='portal-report.csv'
        manager=Mock();manager.__enter__=Mock(return_value=types.SimpleNamespace(value=item));manager.__exit__=Mock(return_value=False)
        page.expect_download.return_value=manager
        config={**self.config,'kind':'reports'};guard=self.agent.make_guard(config)
        output=self.folder/'outputs';output.mkdir()
        with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':module}),patch.object(self.agent,'manual_checkpoint') as approve:
            result=self.agent.browser_workflow(config,guard,output)
        approve.assert_called_once()
        item.save_as.assert_called_once_with(str(output/'report-1.csv'))
        self.assertEqual(result['sources'][0]['saved_file'],'report-1.csv')
        self.assertEqual(guard.trace['actions'][-1]['tool'],'file.write')

    def test_oversized_report_is_not_saved(self):
        module,pw,browser,context,page=self.fake_browser()
        sample=self.folder/'download.csv';sample.write_text('too many bytes')
        item=Mock();item.path.return_value=str(sample);item.suggested_filename='report.csv'
        manager=Mock();manager.__enter__=Mock(return_value=types.SimpleNamespace(value=item));manager.__exit__=Mock(return_value=False)
        page.expect_download.return_value=manager
        config={**self.config,'kind':'reports','max_download_bytes':1}
        with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':module}),patch.object(self.agent,'manual_checkpoint'),self.assertRaises(ValueError):
            self.agent.browser_workflow(config,self.agent.make_guard(config),self.folder)
        item.save_as.assert_not_called()
        browser.close.assert_called_once()


if __name__=='__main__':unittest.main()
