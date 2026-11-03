import json,sqlite3,tempfile,unittest
from contextlib import contextmanager
from pathlib import Path
from opencaliber import agent_server
from opencaliber.agent_engine import DEFAULT_CONFIG
from opencaliber.tracking import TrackedExecutor,TrackingClient
from opencaliber.tracking_store import ingest
from opencaliber.connected_diagnosis import runs,run_report

class ConnectedDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.previous=agent_server.DB;agent_server.DB=Path(self.temp.name)/'console.sqlite3';agent_server.initialize()
        self.config={**DEFAULT_CONFIG,'max_records':1}
        self.events=[]
        def sender(raw):
            body=json.loads(raw);self.events.append(body)
            return ingest(body,agent_server.connect,agent_server.timestamp,self.config)
        self.tracker=TrackingClient(sender=sender,spool_dir=Path(self.temp.name)/'spool',enabled=True,mode='observe')
    def tearDown(self):agent_server.DB=self.previous;self.temp.cleanup()
    def execute(self,enabled=True,capture=None):
        with TrackedExecutor(agent={'id':'connected','version':'1'},task={'goal':'Find unresolved tickets','allowed_tools':['database.read'],'allowed_resources':['tickets']},
              tracker=self.tracker,diagnosis=enabled,capture_output=capture or (lambda a,v:{'statuses':v}),
              diagnosis_verifications=[{'id':'unresolved','action_id':'read','path':['statuses'],'expected':['unresolved','unresolved'],'source':'fixture'}]) as a:
            a.run({'id':'read','tool':'database.read','resource':'tickets','arguments':{'records':2}},lambda:['resolved','resolved'],success=lambda v:bool(v))
        return runs(agent_server.connect)[0]['id']
    def test_capture_and_automatic_diagnosis(self):
        rid=self.execute();row=runs(agent_server.connect)[0]
        self.assertTrue(row['context_available']);self.assertEqual(row['captured_outputs'],1);self.assertEqual(row['assessment'],'failure_detected')
        r=run_report(rid,agent_server.connect);self.assertEqual(r['verification'][0]['status'],'failed')
    def test_recorded_policy_not_current_default(self):
        rid=self.execute();self.config=DEFAULT_CONFIG
        r=run_report(rid,agent_server.connect);self.assertEqual(r['policy_assessment'],'violation')
    def test_old_run_never_replays_redacted_data(self):
        rid=self.execute(False);r=run_report(rid,agent_server.connect,True)
        self.assertFalse(r['context_available']);self.assertEqual(r['assessment'],'insufficient_evidence');self.assertEqual(r['policy_assessment'],'violation')
    def test_goal_only_sent_with_opt_in(self):
        self.execute(False);self.assertEqual(self.events[-1]['trace']['task']['goal'],'Instrumented agent workflow');self.assertNotIn('diagnosis',self.events[-1])
    def test_capture_failure_does_not_fail_action(self):
        def bad(a,v):raise ValueError('capture unavailable')
        with self.assertWarns(RuntimeWarning):rid=self.execute(capture=bad)
        self.assertEqual(run_report(rid,agent_server.connect)['captured_outputs'],0)
    def test_offline_spool_excludes_output_context(self):
        self.execute()
        body=self.events[-1]
        def unavailable(raw):raise OSError('offline')
        spool=Path(self.temp.name)/'offline'
        client=TrackingClient(sender=unavailable,spool_dir=spool,enabled=True)
        client.emit(body)
        queued=json.loads(next(spool.glob('*.json')).read_text())
        self.assertNotIn('diagnosis',queued)
        self.assertTrue(queued['redacted'])

    def test_duplicate_does_not_overwrite_capture(self):
        rid=self.execute();body=self.events[-1]
        self.assertEqual(ingest(body,agent_server.connect,agent_server.timestamp,self.config)['status'],'duplicate')
        self.assertEqual(run_report(rid,agent_server.connect)['captured_outputs'],1)

if __name__=='__main__':unittest.main()
