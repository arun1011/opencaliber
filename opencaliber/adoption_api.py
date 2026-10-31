"""Shared desktop/hosted request handlers for non-persisting adoption utilities."""
from .profiles import available_profiles,validate_profile
from .coverage import coverage_report
from .ingestion import normalize_mcp,normalize_databricks
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]

def examples():
    return {name:json.loads((ROOT/'examples/enterprise'/name).read_text(encoding='utf-8')) for name in ('mcp-events.json','mcp-context.json','databricks-rows.json','databricks-context.json')}

def handle(operation,body,config):
    if operation=='coverage':
        if set(body)-{'trace','inventory'} or 'trace' not in body:raise ValueError('Provide trace and optional inventory')
        return coverage_report(body['trace'],config,body.get('inventory'))
    if operation=='profile':
        if set(body)!={'profile'}:raise ValueError('Provide a profile')
        return validate_profile(body['profile'])
    if operation in ('mcp','databricks'):
        if set(body)!={'events','context'} or not isinstance(body['context'],dict):raise ValueError('Provide events and context')
        return {'trace':(normalize_mcp if operation=='mcp' else normalize_databricks)(body['events'],**body['context'])}
    raise ValueError('Unsupported adoption operation')
