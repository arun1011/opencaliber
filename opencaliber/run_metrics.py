"""Bounded application-reported experiment context and measured run telemetry."""
import math,re

def validate(value):
    if not isinstance(value,dict) or set(value)!={'trajectory_id','evaluation','task_success','cost_usd','cost_source','latency_ms'}:raise ValueError('Invalid run metrics')
    def text(v):return isinstance(v,str) and bool(re.fullmatch('[A-Za-z0-9._-]{1,120}',v))
    if value['trajectory_id'] is not None and not text(value['trajectory_id']):raise ValueError('Invalid trajectory ID')
    e=value['evaluation']
    if e is not None:
        if not isinstance(e,dict) or set(e)!={'experiment_id','case_id','input_sha256','success_criterion','assignment'}:raise ValueError('Evaluation requires experiment_id, case_id, input_sha256, success_criterion and assignment')
        if any(not text(e[k]) for k in ('experiment_id','case_id','success_criterion')) or not isinstance(e['input_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',e['input_sha256']):raise ValueError('Invalid evaluation identifiers')
        if e['assignment'] not in ('paired','randomized','observational'):raise ValueError('Invalid assignment design')
    if value['task_success'] is not None and type(value['task_success']) is not bool:raise ValueError('Task success must be bool or null')
    for k in ('cost_usd','latency_ms'):
        n=value[k]
        if n is not None and (type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1e12):raise ValueError('Invalid '+k)
    if value['cost_source'] not in ('estimated','provider_reported','not_reported') or (value['cost_usd'] is None)!=(value['cost_source']=='not_reported'):raise ValueError('Cost requires provenance')
    return value
