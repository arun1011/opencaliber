import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

from opencaliber.connect import Observer, main
from opencaliber import agent_server as store
from opencaliber.connected_platform import collected
from opencaliber.tracking import TrackingClient
from opencaliber.tracking_store import checked, ingest


class Client:
    last_status = 'delivered'
    def __init__(self): self.events = []
    def emit(self, event): self.events.append(copy.deepcopy(event))


class ConnectTests(unittest.TestCase):
    def test_sql_results_privacy_and_restore(self):
        original = sqlite3.connect
        client = Client()
        with Observer('demo', client=client):
            with closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE secret_table(secret TEXT)')
                db.execute('INSERT INTO secret_table VALUES (?)', ('private-value',))
                self.assertEqual(db.execute('SELECT secret FROM secret_table').fetchall(), [('private-value',)])
        self.assertIs(sqlite3.connect, original)
        raw = json.dumps(client.events)
        self.assertNotIn('private-value', raw)
        self.assertNotIn('secret_table', raw)
        final = client.events[-1]
        checked(final)
        self.assertEqual(final['phase'], 'completed')
        self.assertIsNone(final['metrics']['task_success'])
        self.assertEqual([a['tool'] for a in final['trace']['actions']],
                         ['unmapped.sqlite.statement','database.write','database.read'])
        self.assertTrue(all(a['outcome']['status']=='unknown' for a in final['trace']['actions']))

    def test_exception_preserved_and_hooks_restored(self):
        original = urllib.request.OpenerDirector.open
        client = Client()
        with self.assertRaises(sqlite3.OperationalError):
            with Observer('failure', client=client):
                with closing(sqlite3.connect(':memory:')) as db: db.execute('SELECT missing')
        self.assertIs(urllib.request.OpenerDirector.open, original)
        self.assertEqual(client.events[-1]['phase'], 'workflow_failed')
        self.assertNotIn('SELECT missing', json.dumps(client.events))

    def test_http_payload_excluded_default_timeout_preserved(self):
        client = Client()
        with patch.object(urllib.request.OpenerDirector, 'open', return_value='response') as original:
            with Observer('http', client=client):
                request = urllib.request.Request('https://example.org/private?token=secret',
                                                 data=b'private-body', headers={'Authorization':'Bearer secret'})
                self.assertEqual(urllib.request.build_opener().open(request), 'response')
        raw = json.dumps(client.events)
        self.assertNotIn('secret',raw); self.assertNotIn('private',raw)
        self.assertEqual(client.events[-1]['trace']['actions'][0]['resource'],'https://example.org')
        import socket
        self.assertIs(original.call_args.args[-1],socket._GLOBAL_DEFAULT_TIMEOUT)

    def test_limit_and_telemetry_failure_dont_block(self):
        class Broken(Client):
            def emit(self, event): raise RuntimeError('offline')
        with Observer('limit', client=Broken()) as observer:
            for _ in range(202): self.assertEqual(observer.call('database.read','sqlite',{},lambda:42),42)
        self.assertEqual(len(observer.trace['actions']),200)
        self.assertEqual(observer.dropped,2)

    def test_console_persists_observe_even_under_enforcement(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            old = store.DB
            try:
                store.DB=Path(directory)/'console.sqlite3'; store.initialize()
                with store.connect() as c:
                    from opencaliber.connected_platform import initialize
                    initialize(c); c.execute("UPDATE platform_settings SET mode='enforce'")
                client=TrackingClient(sender=lambda raw:ingest(json.loads(raw),store.connect,store.timestamp,store.configuration()),
                                      spool_dir=Path(directory)/'spool',enabled=True)
                with Observer('persist',client=client) as observer:
                    self.assertEqual(observer.call('database.delete','sqlite',{},lambda:'dispatched'),'dispatched')
                self.assertEqual(client.last_status,'delivered')
                row=collected(store.connect)[0]
                self.assertEqual(row['mode'],'observe'); self.assertEqual(row['connection'],'launcher')
                self.assertEqual(row['assessment'],'violation')
                self.assertIsNone(row['metrics']['task_success'])
            finally: store.DB=old

    def test_script_arguments_and_exit(self):
        import sys
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory)/'agent.py'
            path.write_text("import sys\nassert sys.argv[1:]==['--option','value']\nraise SystemExit(0)\n")
            client=Client(); before=sys.path[:]
            with patch('opencaliber.connect.TrackingClient',return_value=client), patch.object(sys,'argv',['connect','--agent-id','cli','--',str(path),'--option','value']):
                with self.assertRaises(SystemExit) as caught: main()
            self.assertEqual(caught.exception.code,0)
            self.assertEqual(sys.path,before); self.assertEqual(client.events[-1]['phase'],'completed')

    def test_optional_httpx_sync_and_restore(self):
        try: import httpx
        except ImportError: self.skipTest('httpx not installed')
        original=httpx.Client.send; client=Client()
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'private':'value'}))) as http:
            with Observer('sdk',client=client):
                response=http.get('https://api.example.org/private?secret=value')
                self.assertEqual(response.json(),{'private':'value'})
        self.assertIs(httpx.Client.send,original)
        self.assertEqual(len(client.events[-1]['trace']['actions']),1)
        self.assertNotIn('private',json.dumps(client.events))

    def test_optional_requests_sync(self):
        try: import requests
        except ImportError: self.skipTest('requests not installed')
        response=requests.Response(); response.status_code=200
        response._content=b'private-result'
        client=Client()
        with patch.object(requests.Session,'send',return_value=response):
            with Observer('requests',client=client):
                with requests.Session() as session:
                    self.assertEqual(session.get('https://example.org/private?secret=value').content,b'private-result')
        self.assertEqual(len(client.events[-1]['trace']['actions']),1)
        self.assertNotIn('private',json.dumps(client.events))

    def test_nested_observer_rejected_without_restoring_outer_hooks(self):
        with Observer('outer',client=Client()):
            hooked=sqlite3.connect
            with self.assertRaises(RuntimeError):
                with Observer('inner',client=Client()): pass
            self.assertIs(sqlite3.connect,hooked)


if __name__=='__main__': unittest.main()
