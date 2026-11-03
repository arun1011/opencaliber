"""Shared library instrumentation: explicit outcomes, bounded capture and tool graphs."""
import copy
import os
from .tracking import TrackedExecutor,TrackingClient
from .trajectory import Trajectory


def capture(config,action,value):
    result={'result_type':type(value).__name__}
    if isinstance(value,(str,bytes,list,dict,tuple)):result['length']=len(value)
    # Exact output fields are opt-in. Never copy arbitrary strings/documents.
    fields=config.get('capture_fields',{}).get(action['tool'],[])
    if not isinstance(fields,list) or len(fields)>20 or any(not isinstance(k,str) for k in fields):raise ValueError('capture_fields requires up to 20 object keys per tool')
    if isinstance(value,dict):
        for key in fields:
            if key in value:result[key]=copy.deepcopy(value[key])
    return result


class LibraryExecutor(TrackedExecutor):
    def __init__(self,*,library_config,**kwargs):
        config=library_config
        if config.get('allowed_resources') is not None:
            kwargs['task']={**kwargs['task'],'allowed_resources':config['allowed_resources']}
        tracker=kwargs.pop('tracker',None) or TrackingClient.from_environment(kwargs['root'])
        self.graph=Trajectory(trajectory_id=config.get('trajectory_id') or None,endpoint=tracker.endpoint,token=tracker.token,
                              sender=None if tracker.enabled else lambda body:None)
        self.graph_scope=self.graph.span(config.get('title',kwargs['agent']['id']),kwargs['agent']['id'],kind='agent',parent_id=config.get('parent_span_id') or None)
        self.graph_root=self.graph_scope.__enter__()
        self.library_config=config
        try:
            super().__init__(tracker=tracker,trajectory_id=self.graph.id,evaluation=config.get('evaluation'),
                diagnosis=config.get('diagnosis_enabled',True),capture_output=lambda action,value:capture(config,action,value),**kwargs)
        except BaseException as exc:
            self.graph_scope.__exit__(type(exc),exc,exc.__traceback__);raise

    def run(self,action,call,**kwargs):
        with self.graph.span(action['tool'],self.trace['agent']['id'],parent_id=self.graph_root['id']):
            return super().run(action,call,**kwargs)

    def finish(self,status='completed'):
        if self.finished:return
        failed=status!='completed' or self.last_phase in ('blocked','evaluation_error','unknown','failed')
        if failed and self.metrics['task_success'] is None:self.record_outcome(False)
        # Unreported business outcome stays unknown; callers record actual assertions.
        try:super().finish(status)
        finally:
            if failed or self.metrics['task_success'] is False:self.graph_root['status']='failed'
            self.graph_scope.__exit__(None,None,None)


def draft_success(config,draft,saved):
    """Artifact expectations only; never presented as semantic model accuracy."""
    checks=config.get('success_checks',{})
    minimum=checks.get('minimum_characters',1);phrases=checks.get('required_phrases',[])
    if type(minimum) is not int or not 1<=minimum<=1000000 or not isinstance(phrases,list) or len(phrases)>50 or any(not isinstance(p,str) or len(p)>1000 for p in phrases):raise ValueError('Invalid success_checks')
    return isinstance(draft,str) and saved==draft and len(draft)>=minimum and all(p in draft for p in phrases)
