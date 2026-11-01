import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from opencaliber import agent_server as store
from opencaliber.agent_engine import DEFAULT_CONFIG
from opencaliber.tracking import TrackingClient,TrackedExecutor
from opencaliber.tracking_store import ingest,save_policy,agents,events
from opencaliber.execution import ActionBlocked,EvaluationFailed

class TrackingFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(dir=Path(__file__).parent)
        self.previous=store.DB;store.DB=Path(self.temp.name)/'test.sqlite3';store.initialize()
        self.cfg={**DEFAULT_CONFIG,'allowed_file_roots':['/workspace']}
        self.sent=[]
        def sender(body):
            body=json.loads(body)
            self.sent.append(body)
            result=ingest(body,store.connect,store.timestamp,self.cfg)
            self.tracker.mode=result["mode"]
            return result
        self.tracker=TrackingClient(sender=sender,spool_dir=Path(self.temp.name)/'queue')
    def tearDown(self):
        store.DB=self.previous;self.temp.cleanup()
    def executor(self):
        return TrackedExecutor(agent={'id':'test-agent','version':'1'},tracking_id='test-project',task={'goal':'Write report','allowed_tools':['file.write']},config=self.cfg,tracker=self.tracker)
    def action(self,path='/workspace/report.txt'):
        return {'id':'write-1','tool':'file.write','resource':path}
    def test_success_has_every_execution_phase_and_one_workflow(self):
        with self.executor() as agent:
            agent.run(self.action(),lambda:True,success=lambda v:v is True)
        self.assertEqual([e['phase'] for e in self.sent],['started','proposed','executing','succeeded','completed'])
        with store.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM runs').fetchone()[0],1)
            row=c.execute('SELECT * FROM runs').fetchone()
        self.assertEqual(json.loads(row['result'])['tracking']['workflow_status'],'completed')
        self.assertEqual(len(events(row['id'],store.connect)),5)
        self.assertEqual(agents(store.connect)[0]['tracking_id'],'test-project')
    def test_console_rejects_before_callback(self):
        called=[]
        with self.assertRaises(ActionBlocked):
            with self.executor() as agent:
                save_policy({'tracking_id':'test-project','mode':'enforce','config':{**self.cfg,'allowed_file_roots':['/workspace/exports']}},store.connect)
                agent.run(self.action(),lambda:called.append(True),success=lambda v:True)
        self.assertEqual(called,[])
        self.assertEqual(self.sent[-1]['phase'],'workflow_failed')
        self.assertIn('blocked',[e['phase'] for e in self.sent])
    def test_report_only_records_without_rejecting(self):
        called=[]
        with self.executor() as agent:
            save_policy({'tracking_id':'test-project','mode':'observe','config':{**self.cfg,'allowed_file_roots':['/workspace/exports']}},store.connect)
            agent.run(self.action(),lambda:called.append(True),success=lambda v:True)
        self.assertEqual(called,[True])
        with store.connect() as c:result=json.loads(c.execute('SELECT result FROM runs').fetchone()[0])
        self.assertEqual(result['assessment'],'violation')
    def test_failed_success_predicate_does_not_finish_completed(self):
        with self.executor() as agent:
            agent.run(self.action(),lambda:False,success=lambda v:v is True)
        self.assertEqual(self.sent[-1]['phase'],'workflow_failed')
    def test_exception_message_not_collected(self):
        with self.assertRaises(ValueError):
            with self.executor() as agent:
                def fail():raise ValueError('PRIVATE-EXCEPTION-CONTENT')
                agent.run(self.action(),fail,success=lambda v:True)
        self.assertNotIn('PRIVATE-EXCEPTION-CONTENT',json.dumps(self.sent))
        self.assertEqual(self.sent[-1]['error_type'],'ValueError')
    def test_missing_console_enforce_never_dispatches(self):
        def unavailable(body):raise OSError('offline')
        self.tracker.sender=unavailable;self.tracker.mode='enforce'
        called=[]
        with self.assertRaises(EvaluationFailed):
            with self.executor() as agent:
                agent.run(self.action(),lambda:called.append(True),success=lambda v:True)
        self.assertEqual(called,[])

if __name__=='__main__':unittest.main()
