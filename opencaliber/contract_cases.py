"""Workspace-owned contract cases, kept separate from shipped fixtures."""
import json
import re
from .agent_engine import DEFAULT_CONFIG,evaluate_trace,validate_trace,validate_config

MAX_CUSTOM_CASES=500

def initialize(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS custom_cases (id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL)')

def validate_case(case):
    if not isinstance(case,dict) or set(case)!={'id','name','trace','expected','config_patch'}:
        raise ValueError('Provide id, name, trace, expected and config_patch')
    if not isinstance(case['id'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',case['id']):
        raise ValueError('Case ID must be 1–80 letters, numbers, dots, hyphens or underscores')
    if not isinstance(case['name'],str) or not case['name'].strip() or len(case['name'])>200:
        raise ValueError('Provide a case name of at most 200 characters')
    validate_trace(case['trace'])
    expected=case['expected']
    if not isinstance(expected,dict) or set(expected)!={'assessment','required_codes'} or expected['assessment'] not in ('clear','review','violation'):
        raise ValueError('Expected assessment must be clear, review or violation')
    codes=expected['required_codes']
    if not isinstance(codes,list) or len(codes)>100 or any(not isinstance(v,str) or not re.fullmatch('[A-Z][A-Z0-9_]{0,99}',v) for v in codes) or len(set(codes))!=len(codes):
        raise ValueError('Required codes must be unique uppercase finding codes')
    if expected['assessment']=='clear' and codes:
        raise ValueError('A clear case cannot require finding codes')
    patch=case['config_patch']
    if not isinstance(patch,dict) or set(patch)-set(DEFAULT_CONFIG):raise ValueError('Unsupported policy override fields')
    validate_config({**DEFAULT_CONFIG,**patch})
    if len(json.dumps(case,allow_nan=False).encode())>200_000:raise ValueError('Case exceeds 200 KB')
    return case

def preview(case,config):
    validate_case(case)
    result=evaluate_trace(case['trace'],validate_config({**config,**case['config_patch']}))
    codes=sorted({f['code'] for a in result['actions'] for f in a['findings']})
    return {'assessment':result['assessment'],'codes':codes,'passed':result['assessment']==case['expected']['assessment'] and set(case['expected']['required_codes'])<=set(codes),'risk_score':result['risk_score']}

def list_cases(connect):
    with connect() as c:rows=c.execute('SELECT body FROM custom_cases ORDER BY created_at,id').fetchall()
    return [{**json.loads(row['body']),'source':'workspace'} for row in rows]

def save(case,connect,builtin_ids,config,timestamp):
    observed=preview(case,config)
    if case['id'] in builtin_ids:raise ValueError('This ID belongs to an included case; choose a new ID')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM custom_cases WHERE id=?',(case['id'],)).fetchone():raise ValueError('Case ID already exists; choose a new ID')
        if c.execute('SELECT COUNT(*) FROM custom_cases').fetchone()[0]>=MAX_CUSTOM_CASES:raise ValueError('Workspace limit of 500 custom cases reached')
        c.execute('INSERT INTO custom_cases VALUES(?,?,?)',(case['id'],json.dumps(case,allow_nan=False),timestamp()))
    return {'saved':True,'id':case['id'],'preview':observed}
