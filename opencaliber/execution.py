"""Opt-in application execution wrapper. The observer SDK remains observe-only."""
import copy
from .agent_engine import evaluate_trace,validate_config,DEFAULT_CONFIG,validate_trace

class ActionBlocked(RuntimeError):pass
class EvaluationFailed(RuntimeError):pass

class GuardedExecutor:
    """One synchronous workflow; no concurrent dispatch, automatic retries or rollback."""
    def __init__(self,*,agent,task,workflow_id,config=None,mode='observe',evaluator=evaluate_trace):
        if mode not in ('observe','enforce'):raise ValueError('mode must be observe or enforce')
        self.config=validate_config(DEFAULT_CONFIG if config is None else config)
        self.mode,self.evaluator=mode,evaluator
        self.trace={'agent':copy.deepcopy(agent),'task':copy.deepcopy(task),'workflow_id':workflow_id,'actions':[]}
        self.last_evaluation=None
    def run(self,action,call,*,success):
        if not callable(call) or not callable(success):raise ValueError('Supply application-owned execution and success callbacks')
        if 'outcome' in action:raise ValueError('A proposed action must not assert its own outcome')
        proposed=copy.deepcopy(self.trace);proposed['actions'].append(copy.deepcopy(action));validate_trace(proposed)
        try:
            report=self.evaluator(copy.deepcopy(proposed),copy.deepcopy(self.config))
            if not isinstance(report,dict) or report.get('assessment') not in ('clear','review','violation'):raise ValueError('Malformed evaluation result')
        except Exception:raise EvaluationFailed('Evaluation unavailable; no action dispatched') from None
        self.last_evaluation=report
        if self.mode=='enforce' and report['assessment']!='clear':raise ActionBlocked('Action not dispatched; inspect last_evaluation')
        record=copy.deepcopy(action)
        # Mark unknown before calling: the operation may have side effects even when it raises.
        record['outcome']={'status':'unknown','source':'application'};self.trace['actions'].append(record)
        try:
            value=call()
            status=success(value)
            if type(status) is not bool:raise ValueError('Success predicate must return bool')
            record['outcome']['status']='succeeded' if status else 'failed'
            return value
        except Exception:
            # Unknown retains uncertainty; never retry or reinterpret an exception as success.
            raise
