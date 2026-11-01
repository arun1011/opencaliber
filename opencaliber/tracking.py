"""Automatic, minimized workflow tracking; transport never grants execution permission."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

from .agent_engine import evaluate_trace
from .execution import GuardedExecutor, ActionBlocked, EvaluationFailed
from .privacy import minimize_evidence

PHASES = {'started','proposed','executing','succeeded','failed','unknown','blocked',
          'evaluation_error','completed','workflow_failed'}


def digest(config):
    return hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


class TrackingClient:
    """One configurable destination; bounded disk queue and request timeout."""
    def __init__(self, *, endpoint=None, token=None, spool_dir=None, enabled=None, sender=None,mode=None):
        self.enabled = os.environ.get('OPENCALIBER_TRACKING','on').lower() not in ('off','0','false') if enabled is None else enabled
        self.endpoint = (endpoint or os.environ.get('OPENCALIBER_ENDPOINT','http://127.0.0.1:8787')).rstrip('/')
        self.token = token if token is not None else os.environ.get('OPENCALIBER_TOKEN','')
        parsed = urlsplit(self.endpoint)
        local = parsed.hostname in ('127.0.0.1','localhost','::1')
        if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username is not None or
            parsed.password is not None or parsed.path or parsed.query or parsed.fragment or
            (not local and (parsed.scheme!='https' or not self.token))):
            raise ValueError('Tracking requires loopback HTTP or an explicit HTTPS endpoint and token')
        if self.token and (not 32<=len(self.token)<=512 or any(ord(c)<33 or ord(c)>126 for c in self.token)):
            raise ValueError('Tracking token must be 32–512 printable characters')
        self.timeout = .35 if local else 3.0
        self.spool = Path(spool_dir or 'outputs/.opencaliber-tracking')
        self.sender = sender or self._send
        self.retry_at = 0
        self.last_policy = None
        self.last_status = 'disabled' if not self.enabled else 'ready'
        self.warned = False
        self.mode = mode or os.environ.get('OPENCALIBER_MODE','observe')
        if self.mode not in ('observe','enforce'):raise ValueError('OPENCALIBER_MODE must be observe or enforce')
        try:
            saved=json.loads((self.spool/'.settings').read_text(encoding='utf-8'))
            if saved.get('endpoint')==self.endpoint and saved.get('mode')=='enforce':self.mode='enforce'
        except (OSError,ValueError):pass

    @classmethod
    def from_environment(cls, root):
        try:
            return cls(spool_dir=Path(root)/'outputs/.opencaliber-tracking')
        except ValueError:
            # Invalid analytics configuration must not change local policy decisions.
            client = cls(enabled=False,endpoint='http://127.0.0.1:8787',token='',
                         spool_dir=Path(root)/'outputs/.opencaliber-tracking',mode='observe')
            client.last_status='invalid_configuration'
            print('OpenCaliber tracking disabled: check endpoint/token configuration.',file=sys.stderr)
            return client

    def _send(self, body):
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        request=urllib.request.Request(self.endpoint+'/api/tracking/events',data=body,headers=headers)
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=self.timeout) as response:
            raw=response.read(1_048_577)
            if len(raw)>1_048_576:raise ValueError("Tracking acknowledgement exceeds limit")
            ack=json.loads(raw)
        if not isinstance(ack,dict) or ack.get('status') not in ('accepted','duplicate','stale'):
            raise ValueError('Invalid tracking acknowledgement')
        self.last_policy=ack.get('policy')
        if ack.get('mode')=='enforce':self.mode='enforce'
        elif ack.get('mode')=='observe' and os.environ.get('OPENCALIBER_MODE')!='enforce':self.mode='observe'
        try:
            if not self.spool.is_symlink():
                self.spool.mkdir(parents=True,exist_ok=True,mode=0o700)
                cache=self.spool/'.settings'
                if not cache.is_symlink():
                    cache.write_text(json.dumps({'endpoint':self.endpoint,'mode':self.mode}),encoding='utf-8')
        except OSError:pass
        return ack

    def emit(self, event):
        if not self.enabled:return
        try:
            body=json.dumps(event,separators=(',',':'),allow_nan=False).encode()
            if len(body)>900000:raise ValueError('Tracking event exceeds transport limit')
            if time.monotonic()>=self.retry_at:
                try:
                    ack=self.sender(body)
                    self.last_status='delivered'
                    self.flush()
                    return ack
                except Exception:
                    self.retry_at=time.monotonic()+5
            # Offline queue never stores exact paths, commands or custom values.
            event=copy.deepcopy(event)
            event['trace'],minimal=minimize_evidence(event['trace'],event['result'] or {'actions':[]})
            event['result']=minimal if event['result'] is not None else None
            event['redacted']=True
            body=json.dumps(event,separators=(',',':'),allow_nan=False).encode()
            if self.spool.is_symlink():raise ValueError('Tracking queue must not be a symlink')
            self.spool.mkdir(parents=True,exist_ok=True,mode=0o700)
            queued=list(self.spool.glob('*.json'))
            if len(queued)>=1000 or sum(p.stat().st_size for p in queued if not p.is_symlink())+len(body)>10_000_000:
                raise ValueError('Tracking queue is full')
            path=self.spool/(event['event_id']+'.json')
            with path.open('xb') as out:out.write(body)
            try:path.chmod(0o600)
            except OSError:pass
            self.last_status='queued'
            self._warn('OpenCaliber console unavailable; minimized tracking queued for retry.')
        except Exception:
            self.last_status='queue_error'
            self._warn('OpenCaliber tracking could not queue an event. Local evaluation still applies.')

    def _warn(self, message):
        if not self.warned:
            print(message,file=sys.stderr);self.warned=True

    def flush(self, *, force=False):
        if not self.enabled or (not force and time.monotonic()<self.retry_at):return
        try:
            # Atomic complete files only; concurrent senders are safe via server deduplication.
            paths=sorted((p for p in self.spool.glob('*.json') if re.fullmatch('[0-9a-f]{32}\\.json',p.name) and not p.is_symlink()),
                         key=lambda p:p.stat().st_mtime_ns)[:20]
            for path in paths:
                try:body=path.read_bytes()
                except FileNotFoundError:continue
                if len(body)>900000:raise ValueError('Invalid queue entry')
                self.sender(body)
                path.unlink(missing_ok=True)
            self.last_status='delivered' if not any(self.spool.glob('*.json')) else 'queued'
        except Exception:
            self.retry_at=time.monotonic()+5
            self.last_status='queued'
            self._warn('OpenCaliber console unavailable; tracking queued for retry. Local evaluation still applies.')


class TrackedExecutor(GuardedExecutor):
    """Drop-in synchronous action wrapper with automatic workflow lifecycle events."""
    def __init__(self, *, agent, task, workflow_id=None, config=None, mode='enforce',
                 tracker=None, root=None, evaluator=evaluate_trace,tracking_id=None):
        super().__init__(agent=agent,task=task,workflow_id=workflow_id or uuid.uuid4().hex,
                         config=config,mode=mode,evaluator=evaluator)
        self.tracker=tracker or TrackingClient.from_environment(root or Path.cwd())
        self.sequence=0
        self.finished=False
        self.tracking_id=os.environ.get('OPENCALIBER_TRACKING_ID') or tracking_id or agent['id']
        self.last_tracking_trace=None
        self.last_tracking_report=None
        self.last_phase='started'
        self.last_error_type=None
        self.policy_status=None
        self._emit('started',report=None)

    def _emit(self, phase, *, trace=None, report=None,error_type=None):
        try:
            trace=copy.deepcopy(self.trace if trace is None else trace)
            self.last_tracking_trace=copy.deepcopy(trace)
            self.last_tracking_report=copy.deepcopy(report)
            self.last_phase=phase
            self.last_error_type=error_type
            # Only canonical action metadata is sent, never callback inputs/results.
            # Exact paths/domains/argument values are needed for console policies.
            trace['task']['goal']='Instrumented agent workflow'
            self.sequence+=1
            event={'event_id':uuid.uuid4().hex,'sequence':self.sequence,'phase':phase,
                   'policy_sha256':digest(self.config),'trace':trace,
                   'result':report,'tracking_id':self.tracking_id,'redacted':False,'error_type':error_type}
            ack=self.tracker.emit(event)
            if ack and isinstance(ack.get('policy'),dict):self.policy_status=ack['policy']
            return ack
        except Exception:
            # Instrumentation failures never turn a violation into an allowed action.
            self.tracker.last_status='instrumentation_error'

    def run(self,action,call,*,success):
        proposed=copy.deepcopy(self.trace);proposed['actions'].append(copy.deepcopy(action))
        ack=self._emit('proposed',trace=proposed)
        if self.tracker.enabled and self.tracker.mode=='enforce':
            if not ack or not isinstance(ack.get('result'),dict):
                self._emit('evaluation_error',trace=proposed,error_type='ConsoleUnavailable')
                raise EvaluationFailed('Console evaluation unavailable; no action dispatched')
            if ack['result'].get('assessment')!='clear':
                self._emit('blocked',trace=proposed,error_type='ConsolePolicyViolation')
                raise ActionBlocked('Console policy rejected the action; no callback dispatched')
        def dispatch():
            self._emit('executing',trace=proposed,report=self.last_evaluation)
            return call()
        try:
            value=super().run(action,dispatch,success=success)
        except ActionBlocked:
            self._emit('blocked',trace=proposed,report=self.last_evaluation,error_type='LocalPolicyViolation')
            raise
        except EvaluationFailed:
            self._emit('evaluation_error',trace=proposed,error_type='EvaluationUnavailable')
            raise
        except BaseException as exc:
            self._emit('unknown',report=evaluate_trace(self.trace,self.config) if self.trace['actions'] else None,
                       error_type=type(exc).__name__)
            raise
        phase=self.trace['actions'][-1]['outcome']['status']
        self._emit(phase,report=evaluate_trace(self.trace,self.config))
        return value

    def finish(self, status='completed'):
        if not self.finished:
            self.finished=True
            failed=self.last_phase in ('blocked','evaluation_error','unknown','failed')
            self._emit('completed' if status=='completed' and not failed else 'workflow_failed',
                       trace=self.last_tracking_trace if failed else None,
                       report=self.last_tracking_report if failed else evaluate_trace(self.trace,self.config) if self.trace['actions'] else None,
                       error_type=self.last_error_type if failed else None)
            self.tracker.flush(force=True)

    def __enter__(self):return self

    def __exit__(self, kind, value, traceback):
        self.finish('failed' if kind is not None else 'completed')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Retry queued OpenCaliber tracking events')
    parser.add_argument('command',choices=['flush'])
    parser.add_argument('--spool',type=Path,default=Path('outputs/.opencaliber-tracking'))
    args=parser.parse_args()
    client=TrackingClient(spool_dir=args.spool);client.flush(force=True)
    print(client.last_status)
