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
import urllib.error
from urllib.parse import urlsplit
import uuid

from .agent_engine import evaluate_trace
from .execution import GuardedExecutor, ActionBlocked, EvaluationFailed, ExecutionEvidenceFailed
from .privacy import minimize_evidence
from .executability import assess,validate_contracts

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
        self.last_error = None
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
                    self.last_error=None
                    self.flush()
                    return ack
                except Exception as exc:
                    self.last_error=self.connection_error(exc)
                    self.retry_at=time.monotonic()+5
            # Offline queue never stores exact paths, commands or custom values.
            event=copy.deepcopy(event)
            event['trace'],minimal=minimize_evidence(event['trace'],event['result'] or {'actions':[]})
            event['result']=minimal if event['result'] is not None else None
            event.pop('diagnosis',None)  # Offline spool must not retain opted-in raw output context.
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
            self._warn('OpenCaliber tracking queued: '+(self.last_error or 'console did not acknowledge the event'))
        except Exception:
            self.last_status='queue_error'
            self._warn('OpenCaliber tracking could not queue an event. Local evaluation still applies.')

    @staticmethod
    def connection_error(exc):
        if isinstance(exc,urllib.error.HTTPError):
            if exc.code in (400,404,422):return 'HTTP '+str(exc.code)+': console rejected the tracking schema or endpoint. Restart the console from the updated package; check agent metadata if it persists.'
            if exc.code in (401,403):return 'HTTP '+str(exc.code)+': console authentication or origin rejected. Check endpoint and token.'
            return 'HTTP '+str(exc.code)+': console service error.'
        if isinstance(exc,(TimeoutError,urllib.error.URLError,OSError)):return 'Console unreachable or request timed out. Check that the console is running at OPENCALIBER_ENDPOINT.'
        return 'Console acknowledgement was invalid. Restart the console from the matching package.'

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
                 tracker=None, root=None, evaluator=evaluate_trace,tracking_id=None,
                 tool_contracts=None,initial_state=None,contract_mode="observe",
                 diagnosis=False,capture_output=None,diagnosis_constraints=None,diagnosis_verifications=None,
                 trajectory_id=None,evaluation=None):
        super().__init__(agent=agent,task=task,workflow_id=workflow_id or uuid.uuid4().hex,
                         config=config,mode=mode,evaluator=evaluator)
        self.tracker=tracker or TrackingClient.from_environment(root or Path.cwd())
        self.tool_contracts=validate_contracts(tool_contracts or {})
        self.initial_state=copy.deepcopy(initial_state or {})
        self.attempts=[]
        self.attempt_limit_exceeded=False
        self.contract_mode=contract_mode
        if contract_mode not in ('observe','enforce'):raise ValueError('contract_mode must be observe or enforce')
        if type(diagnosis) is not bool:raise ValueError('diagnosis must be a boolean')
        self.diagnosis_enabled=diagnosis
        if capture_output is not None and not callable(capture_output):raise ValueError('capture_output must be a callback')
        self.capture_output=capture_output
        self.diagnosis_outputs={}
        self.diagnosis_constraints=copy.deepcopy(diagnosis_constraints or [])
        self.diagnosis_verifications=copy.deepcopy(diagnosis_verifications or [])
        self.diagnosis_capture_errors=[]
        from .run_metrics import validate as validate_metrics
        self.started_at=time.perf_counter()
        self.metrics=validate_metrics({'trajectory_id':trajectory_id,'evaluation':copy.deepcopy(evaluation),
            'task_success':None,'cost_usd':None,'cost_source':'not_reported','latency_ms':None})
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
            # Callback evidence is sent only through explicit diagnosis capture.
            # Exact paths/domains/argument values are needed for console policies.
            if not self.diagnosis_enabled:trace['task']['goal']='Instrumented agent workflow'
            self.sequence+=1
            event={'event_id':uuid.uuid4().hex,'sequence':self.sequence,'phase':phase,
                   'policy_sha256':digest(self.config),'trace':trace,
                   'result':report,'tracking_id':self.tracking_id,'redacted':False,'error_type':error_type,'reliability':self.reliability_report(),'metrics':copy.deepcopy(self.metrics)}
            if self.diagnosis_enabled:
                ids={a['id'] for a in trace['actions']}
                event['diagnosis']={'outputs':{k:v for k,v in self.diagnosis_outputs.items() if k in ids},
                                    'constraints':self.diagnosis_constraints,
                                    'verifications':[v for v in self.diagnosis_verifications if v.get('action_id') in ids]}
            if 'diagnosis' in event:
                try:
                    from .diagnosis import validate
                    check_trace=trace if trace['actions'] else {**trace,'actions':[{'id':'context-check','tool':'file.read','resource':'/placeholder'}]}
                    validate({'trace':check_trace,**event['diagnosis'],'config':self.config})
                except Exception as exc:
                    event.pop('diagnosis',None)
                    trace['task']['goal']='Instrumented agent workflow'
                    self.diagnosis_capture_errors.append(type(exc).__name__)
                    import warnings
                    warnings.warn('Diagnosis context unavailable; ordinary tracking continues',RuntimeWarning)
            ack=self.tracker.emit(event)
            if ack and isinstance(ack.get('policy'),dict):self.policy_status=ack['policy']
            return ack
        except Exception:
            # Instrumentation failures never turn a violation into an allowed action.
            self.tracker.last_status='instrumentation_error'

    def execution_evidence(self):
        """Explicit export can contain scalar IDs/state. Keep this artifact private."""
        return {'contracts':copy.deepcopy(self.tool_contracts),'initial_state':copy.deepcopy(self.initial_state),
                'attempts':copy.deepcopy(self.attempts),'complete':self.finished and not self.attempt_limit_exceeded}

    def reliability_report(self):
        return assess(self.execution_evidence())

    def run(self,action,call,*,success,references=None,extract_outputs=None,state_updates=None):
        if len(self.attempts)>=200:
            self.attempt_limit_exceeded=True
            self._emit('evaluation_error',error_type='AttemptLimitExceeded')
            raise ValueError('Workflow reached the 200-attempt limit; evidence is incomplete')
        if not callable(call) or not callable(success):raise ValueError('Provide execution and business-success callbacks')
        for extractor in (extract_outputs,state_updates):
            if extractor is not None and not callable(extractor):raise ValueError('Evidence extractors must be callable')
        attempt={'attempt_id':'attempt-'+str(len(self.attempts)+1),'action':copy.deepcopy(action),'execution':'not_dispatched',
                 'disposition':'proposed','transition_accepted':None,'outputs':{},'state_updates':{},'references':copy.deepcopy(references or {})}
        self.attempts.append(attempt)
        preflight=assess(self.execution_evidence(),preflight_last=True)['attempts'][-1]
        proposed=copy.deepcopy(self.trace);proposed['actions'].append(copy.deepcopy(action))
        if self.contract_mode=='enforce' and preflight['validity']!='valid':
            attempt['disposition']='contract_blocked'
            self._emit('blocked',trace=self.trace,error_type='ToolContractViolation')
            raise ActionBlocked('Tool contract is invalid or unknown; callback not dispatched: '+preflight['code'])
        ack=self._emit('proposed',trace=proposed)
        if self.tracker.enabled and self.tracker.mode=='enforce':
            if not ack or not isinstance(ack.get('result'),dict):
                attempt['disposition']='evaluation_unavailable'
                self._emit('evaluation_error',trace=proposed,error_type='ConsoleUnavailable')
                raise EvaluationFailed('Console evaluation unavailable; no action dispatched. '+(self.tracker.last_error or 'No valid online acknowledgement. Check the console process and endpoint.'))
            if ack['result'].get('assessment')!='clear':
                attempt['disposition']='policy_blocked'
                self._emit('blocked',trace=proposed,error_type='ConsolePolicyViolation')
                raise ActionBlocked('Console policy rejected the action; no callback dispatched')
        def dispatch():
            attempt['disposition']='executed';attempt['execution']='unknown'
            self._emit('executing',trace=proposed,report=self.last_evaluation)
            return call()
        try:
            value=super().run(action,dispatch,success=success)
        except ActionBlocked:
            attempt['disposition']='policy_blocked'
            self._emit('blocked',trace=proposed,report=self.last_evaluation,error_type='LocalPolicyViolation')
            raise
        except EvaluationFailed:
            attempt['disposition']='evaluation_unavailable'
            self._emit('evaluation_error',trace=proposed,error_type='EvaluationUnavailable')
            raise
        except BaseException as exc:
            attempt['execution']='unknown';attempt['error_type']=type(exc).__name__
            self._emit('unknown',report=evaluate_trace(self.trace,self.config) if self.trace['actions'] else None,error_type=type(exc).__name__)
            raise
        if self.diagnosis_enabled and self.capture_output is not None:
            try:
                selected=self.capture_output(copy.deepcopy(action),value)
                if selected is not None:
                    candidate={**self.diagnosis_outputs,action['id']:selected}
                    if len(json.dumps(candidate,allow_nan=False).encode())>100000:raise ValueError('Captured output limit is 100 KB per run')
                    self.diagnosis_outputs=json.loads(json.dumps(candidate,allow_nan=False))
            except Exception as exc:
                self.diagnosis_capture_errors.append(type(exc).__name__)
                import warnings
                warnings.warn('Diagnosis output capture failed; output remains unavailable',RuntimeWarning)
        phase=self.trace['actions'][-1]['outcome']['status']
        attempt['execution']=phase;attempt['transition_accepted']=True if phase=='succeeded' else None
        try:
            contract=self.tool_contracts.get(action['tool'],{})
            if phase=='succeeded' and extract_outputs is not None:
                outputs=extract_outputs(value)
                if not isinstance(outputs,dict):raise ValueError('Output evidence must be a dictionary')
                attempt['outputs']={key:outputs[key] for key in contract.get('outputs',{}) if key in outputs}
            if phase=='succeeded' and state_updates is not None:
                updates=state_updates(value)
                if not isinstance(updates,dict):raise ValueError('State evidence must be a dictionary')
                attempt['state_updates']={key:updates[key] for key in contract.get('effects',{}) if key in updates}
            assess(self.execution_evidence())
        except Exception as exc:
            attempt['outputs']={};attempt['state_updates']={};attempt['transition_accepted']=None
            attempt['error_type']=type(exc).__name__
            self._emit('unknown',report=evaluate_trace(self.trace,self.config),error_type='EvidenceExtractionFailed')
            raise ExecutionEvidenceFailed('Tool ran but evidence extraction failed; reconcile state before retrying') from None
        verdict=assess(self.execution_evidence())['attempts'][-1]
        if self.contract_mode=='enforce' and verdict['validity']!='valid':
            self._emit('unknown',report=evaluate_trace(self.trace,self.config),error_type='PostExecutionEvidenceFailed')
            raise ExecutionEvidenceFailed('Tool ran but its contract or transition is invalid/unknown; reconcile state')
        self._emit(phase,report=evaluate_trace(self.trace,self.config))
        return value

    def record_outcome(self,task_success,*,cost_usd=None,cost_source='not_reported'):
        """Record a business assertion, not inferred success from a completed callback."""
        from .run_metrics import validate
        if self.finished:raise ValueError('Record outcomes before the executor exits')
        self.metrics=validate({**self.metrics,'task_success':task_success,'cost_usd':cost_usd,'cost_source':cost_source})

    def finish(self, status='completed'):
        if not self.finished:
            self.metrics['latency_ms']=round((time.perf_counter()-self.started_at)*1000,3)
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
