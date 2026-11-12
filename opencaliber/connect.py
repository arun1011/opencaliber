"""Observe supported Python boundaries without modifying an agent's source.

Run: python -m opencaliber.connect --agent-id example -- agent.py
This launcher never gates dispatch. It does not instrument child processes.
"""
import argparse
import copy
import importlib
import re
import runpy
import sqlite3
import socket
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .agent_engine import DEFAULT_CONFIG, validate_trace
from .tracking import TrackingClient, digest


class Observer:
    """Process-wide opt-in hooks; one observer per process, no payload capture."""
    active = False
    def __init__(self, agent_id, version='v1', tracking_id=None, client=None):
        self.client = client or TrackingClient(mode='observe')
        self.trace = {'agent': {'id': agent_id, 'version': version},
                      'workflow_id': uuid.uuid4().hex,
                      'task': {'goal': 'Observed Python workload; business objective not supplied'},
                      'actions': []}
        self.tracking_id = tracking_id or agent_id
        if not isinstance(self.tracking_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', self.tracking_id):
            raise ValueError('Invalid tracking ID')
        validate_trace({**self.trace, 'actions': [{'id':'schema','tool':'database.read','resource':'sqlite'}]})
        self.sequence = 0
        self.lock = threading.RLock()
        self.local = threading.local()
        self.started = time.monotonic()
        self.dropped = 0

    def emit(self, phase, error=None):
        # Telemetry itself must never appear as application HTTP activity.
        self.local.suppressed = True
        try:
            self.sequence += 1
            self.client.emit({'event_id': uuid.uuid4().hex, 'sequence': self.sequence,
                'phase': phase, 'policy_sha256': digest(DEFAULT_CONFIG),
                'trace': copy.deepcopy(self.trace), 'result': None,
                'tracking_id': self.tracking_id, 'redacted': False,
                'error_type': error, 'connection': 'launcher',
                'metrics': {'trajectory_id': self.trace['workflow_id'], 'evaluation': None,
                    'task_success': None, 'cost_usd': None, 'cost_source': 'not_reported',
                    'latency_ms': (time.monotonic()-self.started)*1000}})
        except Exception:
            # Monitoring failure must not replace an application result/exception.
            pass
        finally:
            self.local.suppressed = False

    def call(self, tool, resource, arguments, callback):
        if getattr(self.local, 'suppressed', False):
            return callback()
        # Only dispatch order is recorded. Parallel causality is not inferred.
        with self.lock:
            if len(self.trace['actions']) >= 200:
                self.dropped += 1
                action = None
            else:
                action = {'id': uuid.uuid4().hex, 'tool': tool, 'resource': resource,
                          'arguments': arguments,
                          'outcome': {'status': 'unknown', 'source': 'unknown'}}
                self.trace['actions'].append(action)
        try:
            result = callback()
        except BaseException as exc:
            with self.lock:
                # A failed transport can have partial remote effects.
                self.emit('failed', type(exc).__name__)
            raise
        with self.lock:
            # Completed API calls are not proof of transaction/business success.
            self.emit('succeeded')
        return result

    def __enter__(self):
        if Observer.active:
            raise RuntimeError('Only one launcher observer may be active per process')
        # Optional adapters load before activation. The launcher installs no libraries.
        optional = []
        for name, target in [('requests.sessions', 'Session'), ('httpx', 'Client')]:
            try:
                optional.append((name, getattr(importlib.import_module(name), target)))
            except ImportError:
                pass
        Observer.active = True
        self.extra_hooks = []
        self.original_connect = sqlite3.connect
        self.original_open = urllib.request.OpenerDirector.open
        owner = self

        class Cursor(sqlite3.Cursor):
            def execute(self, sql, parameters=(), /):
                return owner.sql(sql, lambda: super(Cursor, self).execute(sql, parameters))

            def executemany(self, sql, parameters, /):
                return owner.sql(sql, lambda: super(Cursor, self).executemany(sql, parameters))

            def executescript(self, sql, /):
                return owner.call('unmapped.sqlite.script', 'sqlite', {},
                                  lambda: super(Cursor, self).executescript(sql))

        class Connection(sqlite3.Connection):
            def cursor(self, factory=Cursor):
                return super().cursor(factory)

            def execute(self, sql, parameters=(), /):
                return self.cursor().execute(sql, parameters)

            def executemany(self, sql, parameters, /):
                return self.cursor().executemany(sql, parameters)

            def executescript(self, sql, /):
                return self.cursor().executescript(sql)

        def connect(*args, **kwargs):
            # Respect application-owned factories. They are not instrumented.
            if len(args) < 6 and 'factory' not in kwargs:
                kwargs['factory'] = Connection
            return owner.original_connect(*args, **kwargs)

        def open_url(opener, fullurl, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
            url = fullurl.full_url if isinstance(fullurl, urllib.request.Request) else fullurl
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https'):
                return owner.original_open(opener, fullurl, data, timeout)
            host = parsed.hostname or 'unknown'
            host = '['+host+']' if ':' in host else host
            resource = parsed.scheme+'://'+host
            method = fullurl.get_method() if isinstance(fullurl, urllib.request.Request) else ('POST' if data is not None else 'GET')
            return owner.call('http.get' if method in ('GET','HEAD') else 'http.send',
                              resource, {'method': method},
                              lambda: owner.original_open(opener, fullurl, data, timeout))

        sqlite3.connect = connect
        urllib.request.OpenerDirector.open = open_url
        for name, cls in optional:
            original = cls.send
            self.extra_hooks.append((cls, original))
            def send(instance, request, *args, _original=original, **kwargs):
                if getattr(owner.local, 'suppressed', False):
                    return _original(instance, request, *args, **kwargs)
                parsed = urlsplit(str(request.url))
                host = parsed.hostname or 'unknown'
                host = '['+host+']' if ':' in host else host
                def dispatch():
                    # requests handles redirects via nested send calls. Keep those
                    # visible, but HTTPX redirects are internal and not separately seen.
                    return _original(instance, request, *args, **kwargs)
                return owner.call('http.get' if request.method in ('GET','HEAD') else 'http.send',
                                  parsed.scheme+'://'+host, {'method':request.method}, dispatch)
            cls.send = send
        self.emit('started')
        return self

    def sql(self, sql, callback):
        # Never send SQL text, parameters, database paths or result rows.
        match = re.match(r'\s*(SELECT|INSERT|UPDATE|DELETE)\b', sql, re.I) if isinstance(sql, str) else None
        kind = match.group(1).upper() if match else None
        tool = {'SELECT': 'database.read', 'INSERT': 'database.write',
                'UPDATE': 'database.write', 'DELETE': 'database.delete'}.get(kind, 'unmapped.sqlite.statement')
        return self.call(tool, 'sqlite', {}, callback)

    def __exit__(self, kind, value, traceback):
        sqlite3.connect = self.original_connect
        urllib.request.OpenerDirector.open = self.original_open
        for cls, original in self.extra_hooks:
            cls.send = original
        Observer.active = False
        ok = kind is None or (kind is SystemExit and value.code in (None, 0))
        self.emit('completed' if ok else 'workflow_failed', None if ok else kind.__name__)
        print(f'OpenCaliber: {len(self.trace["actions"])} actions observed; '
              f'{self.dropped} beyond capture limit; delivery={self.client.last_status}. '
              'Observation only; task success and unsupported operations are unknown.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent-id', required=True)
    parser.add_argument('--version', default='v1')
    parser.add_argument('--tracking-id')
    parser.add_argument('script')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', args.tracking_id or args.agent_id):
        parser.error('Use 1–120 letters, numbers, dots, underscores or hyphens for identity')
    original_argv, original_path = sys.argv[:], sys.path[:]
    try:
        sys.argv = [args.script, *args.arguments]
        sys.path.insert(0, str(Path(args.script).resolve().parent))
        with Observer(args.agent_id, args.version, args.tracking_id):
            runpy.run_path(args.script, run_name='__main__')
    finally:
        sys.argv[:], sys.path[:] = original_argv, original_path


if __name__ == '__main__':
    main()
