"""Idempotent ingestion of agent-reported, minimized workflow snapshots."""
import copy
import hashlib
import json
import re

from .agent_engine import validate_trace,validate_config,evaluate_trace
from .privacy import minimize_evidence
from .tracking import PHASES,digest
from .policy_readiness import summarize_scope,readiness


def initialize(connection):
    connection.executescript('''
    CREATE TABLE IF NOT EXISTS tracking_workflows (
      run_id TEXT PRIMARY KEY, last_sequence INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS tracking_events (
      event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
      digest TEXT NOT NULL, received_at TEXT NOT NULL, phase TEXT NOT NULL,
      action_id TEXT, assessment TEXT NOT NULL, risk_score INTEGER NOT NULL,
      codes TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS tracking_event_workflow ON tracking_events(run_id,sequence);
    CREATE TABLE IF NOT EXISTS tracking_agents (
      tracking_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, policy TEXT,
      mode TEXT NOT NULL DEFAULT 'observe', last_seen TEXT NOT NULL);
    ''')

    columns={r[1] for r in connection.execute('PRAGMA table_info(tracking_agents)')}
    for name in ('scope','ack_policy_sha256','ack_mode','ack_at'):
        if name not in columns:connection.execute('ALTER TABLE tracking_agents ADD COLUMN '+name+' TEXT')


def checked(body):
    if not isinstance(body,dict) or set(body)-{'reliability','diagnosis','metrics','connection'}!={'event_id','sequence','phase','policy_sha256','trace','result','tracking_id','redacted','error_type'}:
        raise ValueError('Invalid tracking event fields')
    if body.get('connection','wrapper') not in ('wrapper','launcher'):
        raise ValueError('Unsupported connection mode')
    if not isinstance(body['tracking_id'],str) or re.fullmatch('[A-Za-z0-9._-]{1,120}',body['tracking_id']) is None or type(body['redacted']) is not bool:
        raise ValueError('Invalid tracking ID or privacy flag')
    if body['error_type'] is not None and (not isinstance(body['error_type'],str) or re.fullmatch('[A-Za-z0-9_]{1,80}',body['error_type']) is None):
        raise ValueError('Send only a bounded error type, not exception text')
    if not isinstance(body['event_id'],str) or re.fullmatch('[0-9a-f]{32}',body['event_id']) is None:
        raise ValueError('Invalid event ID')
    if type(body['sequence']) is not int or not 1<=body['sequence']<=10000 or body['phase'] not in PHASES:
        raise ValueError('Invalid tracking sequence or phase')
    if not isinstance(body['policy_sha256'],str) or re.fullmatch('[0-9a-f]{64}',body['policy_sha256']) is None:
        raise ValueError('Invalid policy fingerprint')
    if 'reliability' in body:
        from .executability import validate_report
        validate_report(body['reliability'])
    if 'metrics' in body:
        from .run_metrics import validate
        validate(body['metrics'])
    trace=body['trace']
    if not isinstance(trace,dict) or not {'agent','workflow_id','task','actions'}<=set(trace):
        raise ValueError('Tracking requires agent, workflow, task and actions')
    if not isinstance(trace['actions'],list):raise ValueError('Actions must be a list')
    if trace['actions']:
        validate_trace(trace)
    else:
        # Lifecycle-only snapshots have zero actions; reuse the canonical schema
        # validator for other fields without persisting/evaluating a dummy action.
        validate_trace({**trace,'actions':[{'id':'schema-check','tool':'file.read','resource':'/schema'}]})
    if 'diagnosis' in body:
        from .connected_diagnosis import capture_context
        capture_context(body['diagnosis'],trace)
    result=copy.deepcopy(body['result'])
    if result is None:
        result={'engine_version':'not_evaluated','config_sha256':body['policy_sha256'],
                'assessment':'review','risk_score':0,'score_type':'heuristic_not_probability',
                'action_count':len(trace['actions']),'finding_count':0,
                'actions':[{'action_id':a['id'],'tool':a['tool'],'source_tool':a.get('source_tool',a['tool']),
                            'resource':a['resource'],'assessment':'review','priority':'low','risk_score':0,
                            'score_type':'heuristic_not_probability','policy_result':'not_evaluated',
                            'task_consistency':'not_established','findings':[],'sequence_checks':[]}
                           for a in trace['actions']],
                'limitations':['This lifecycle event has no evaluation result yet.']}
    required={'engine_version','config_sha256','assessment','risk_score','score_type','action_count','finding_count','actions','limitations'}
    if not isinstance(result,dict) or not required<=set(result) or set(result)-required-{'agent','workflow_id','context','storage_mode','replayable'}:
        raise ValueError('Invalid tracking result schema')
    if result['config_sha256']!=body['policy_sha256'] or result['assessment'] not in ('clear','review','violation') or result['score_type']!='heuristic_not_probability':
        raise ValueError('Invalid tracking assessment or policy fingerprint')
    if type(result['risk_score']) is not int or not 0<=result['risk_score']<=100:
        raise ValueError('Invalid tracking score')
    if not isinstance(result['engine_version'],str) or not 0<len(result['engine_version'])<=80:
        raise ValueError('Invalid tracking engine version')
    if not isinstance(result['actions'],list) or len(result['actions'])!=len(trace['actions']) or result['action_count']!=len(trace['actions']):
        raise ValueError('Tracking action counts differ')
    ids={a['id'] for a in trace['actions']}
    count=0
    for action,original in zip(result['actions'],trace['actions']):
        if not isinstance(action,dict) or action.get('action_id')!=original['id'] or action.get('tool')!=original['tool'] or action.get('assessment') not in ('clear','review','violation'):
            raise ValueError('Tracking action identity differs')
        if not isinstance(action.get('findings'),list) or len(action['findings'])>100:
            raise ValueError('Invalid tracking findings')
        for finding in action['findings']:
            if (not isinstance(finding,dict) or not {'code','category','score','message','explicit_violation','evidence_ids'}<=set(finding) or
                not isinstance(finding['code'],str) or re.fullmatch('[A-Z0-9_]{1,100}',finding['code']) is None or
                type(finding['score']) is not int or not 0<=finding['score']<=100 or
                not isinstance(finding['evidence_ids'],list) or any(i not in ids for i in finding['evidence_ids'])):
                raise ValueError('Invalid tracking finding')
            count+=1
    if result['finding_count']!=count:raise ValueError('Tracking finding count differs')
    if not isinstance(result['limitations'],list) or any(not isinstance(v,str) or len(v)>2000 for v in result['limitations']):
        raise ValueError('Invalid limitations')
    # Apply minimization again at the receiving boundary; never replay this trace.
    trace,result=minimize_evidence(trace,result)
    result['limitations'].append('Agent-reported evaluation and identity; not independently verified by the console. Policy values remain on the agent; this console stores the fingerprint.')
    return trace,result


def ingest(body, connect, timestamp, default_config):
    trace,result=checked(body)
    with connect() as c:
        from .connected_platform import initialize as platform_initialize
        platform_initialize(c)
        default_mode=c.execute('SELECT mode FROM platform_settings WHERE id=1').fetchone()[0]
        existing=c.execute('SELECT agent_id FROM tracking_agents WHERE tracking_id=?',(body['tracking_id'],)).fetchone()
        if existing and existing['agent_id']!=trace['agent']['id']:raise ValueError('Tracking ID belongs to another agent; use a distinct tracking ID')
        c.execute('INSERT INTO tracking_agents(tracking_id,agent_id,last_seen,mode) VALUES(?,?,?,?) ON CONFLICT(tracking_id) DO UPDATE SET last_seen=excluded.last_seen',
                  (body['tracking_id'],trace['agent']['id'],timestamp(),default_mode))
        agent=c.execute('SELECT * FROM tracking_agents WHERE tracking_id=?',(body['tracking_id'],)).fetchone()
        if agent['agent_id']!=trace['agent']['id']:raise ValueError('Tracking ID belongs to another agent')
    connection=body.get('connection','wrapper')
    mode='observe' if connection=='launcher' else agent['mode']
    cfg=validate_config(json.loads(agent['policy']) if agent['policy'] else default_config)
    assignment={'tracking_id':body['tracking_id'],'agent_id':agent['agent_id'],'source':'agent_override' if agent['policy'] else 'workspace_default','config_sha256':digest(cfg),'mode':mode}
    central=not body['redacted']
    # Online events are evaluated against console-owned policy before minimization.
    # Offline minimized events cannot be re-evaluated faithfully; label them as
    # agent-reported instead of pretending their original boundaries were checked.
    if central and body['trace']['actions']:
        result=evaluate_trace(body['trace'],cfg)
        from .custom_checks import apply as apply_custom_checks
        result=apply_custom_checks(body,result,connect)
        trace,result=minimize_evidence(body['trace'],result)
    if not central or not body['trace']['actions']:
        from .custom_checks import apply as apply_custom_checks
        result=apply_custom_checks(body,result,connect)
    if central:
        result['limitations']=[v for v in result['limitations'] if not v.startswith('Agent-reported evaluation')]
    rid=hashlib.sha256(json.dumps([body['tracking_id'],trace['agent'],trace['workflow_id']],sort_keys=True).encode()).hexdigest()[:16]
    normalized=copy.deepcopy(body)
    normalized['trace'],minimal=minimize_evidence(normalized['trace'],normalized['result'] or {'actions':[]})
    normalized['result']=minimal if normalized['result'] is not None else None
    normalized['redacted']=True
    fingerprint=hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    now=timestamp()
    state='completed' if body['phase']=='completed' else 'failed' if body['phase']=='workflow_failed' else 'running'
    result['tracking']={'source':'console_evaluated' if central else 'offline_agent_reported',
                        'tracking_id':body['tracking_id'],'mode':mode,'connection':connection,
                        'phase':body['phase'],'workflow_status':state,
                        'sequence':body['sequence'],'received_at':now,'error_type':body['error_type'],'policy_source':assignment['source']}
    if connection=='launcher':
        result['limitations'].append('Observation only: Python urllib, installed synchronous Requests/HTTPX clients and default SQLite connections, up to 200 actions. No dispatch blocking, business outcomes, SQL content, fetched row counts, custom connection factories, subprocesses or inferred cross-agent dependencies. Action outcomes remain unknown.')
    if 'reliability' in body:
        from .executability import validate_report
        result['reliability']=validate_report(body['reliability'])
    codes=sorted({f['code'] for a in result['actions'] for f in a['findings']})
    with connect() as c:
        # Serialize sequence comparison + upsert across request threads/processes.
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT digest FROM tracking_events WHERE event_id=?',(body['event_id'],)).fetchone()
        if old:
            if old['digest']!=fingerprint:raise ValueError('Event ID reused with different content')
            return {'id':rid,'status':'duplicate','mode':mode,'policy':assignment,'result':result if body['phase']=='proposed' else None}
        previous=c.execute('SELECT last_sequence FROM tracking_workflows WHERE run_id=?',(rid,)).fetchone()
        stale=previous is not None and body['sequence']<=previous['last_sequence']
        c.execute('INSERT INTO tracking_events VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (body['event_id'],rid,body['sequence'],fingerprint,now,body['phase'],
                   trace['actions'][-1]['id'] if trace['actions'] else None,result['assessment'],result['risk_score'],json.dumps(codes)))
        if stale:return {'id':rid,'status':'stale','mode':mode,'policy':assignment,'result':result if body['phase']=='proposed' else None}
        if central:
            c.execute('UPDATE tracking_agents SET scope=?,ack_policy_sha256=?,ack_mode=?,ack_at=? WHERE tracking_id=?',(json.dumps(summarize_scope(body['trace'],body['phase'])),digest(cfg),mode,now,body['tracking_id']))
        # A workflow is one dashboard record; snapshots replace its displayed state.
        c.execute('INSERT INTO tracking_workflows VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET last_sequence=excluded.last_sequence',(rid,body['sequence']))
        config=cfg if central else {'policy_source':'agent','sha256':body['policy_sha256'],'values_stored':False}
        c.execute('''INSERT INTO runs(id,created_at,name,trace,result,config) VALUES(?,?,?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET created_at=excluded.created_at,name=excluded.name,
          trace=excluded.trace,result=excluded.result,config=excluded.config,status='open' ''',
          (rid,now,trace.get('name',trace['agent']['id']),json.dumps(trace),json.dumps(result),json.dumps(config)))
        from .connected_diagnosis import record
        record(c,rid,body,cfg)
        from .connected_platform import record as record_metrics
        record_metrics(c,rid,body)
    return {'id':rid,'status':'accepted','mode':mode,'policy':assignment,'result':result if body['phase']=='proposed' else None}


def agents(connect,default_config=None,cases=()):
    from .agent_engine import DEFAULT_CONFIG
    default_config=DEFAULT_CONFIG if default_config is None else default_config
    with connect() as c:rows=c.execute('SELECT * FROM tracking_agents ORDER BY last_seen DESC').fetchall()
    case_index={}
    for case in cases:
        if case.get('source')=='workspace':case_index.setdefault(case['trace'].get('agent',{}).get('id'),[]).append(case)
    result=[]
    for r in rows:
        policy=json.loads(r['policy']) if r['policy'] else None;effective=policy or default_config
        scope=json.loads(r['scope']) if r['scope'] else None
        result.append({'tracking_id':r['tracking_id'],'agent_id':r['agent_id'],'mode':r['mode'],'last_seen':r['last_seen'],'policy':policy,
                       'scope':scope,'assignment':{'source':'agent_override' if policy else 'workspace_default','config_sha256':digest(effective),'acknowledged':r['ack_policy_sha256']==digest(effective) and r['ack_mode']==r['mode'],'last_ack_at':r['ack_at']},
                       'readiness':readiness(scope,effective,r['agent_id'],case_index.get(r['agent_id'],[]))})
    return result


def save_policy(body, connect):
    if not isinstance(body,dict) or set(body)!={'tracking_id','mode','config'} or not isinstance(body['tracking_id'],str) or re.fullmatch('[A-Za-z0-9._-]{1,120}',body['tracking_id']) is None:
        raise ValueError('Provide tracking ID, mode and config')
    if body['mode'] not in ('observe','enforce'):raise ValueError('Invalid monitoring mode')
    cfg=None if body['config'] is None else validate_config(body['config'])
    with connect() as c:
        row=c.execute('UPDATE tracking_agents SET policy=?,mode=? WHERE tracking_id=?',
                      (json.dumps(cfg) if cfg is not None else None,body['mode'],body['tracking_id']))
        if not row.rowcount:raise ValueError('Run the agent once so its tracking ID is registered')
    return {'saved':True}


def events(run_id, connect):
    if not isinstance(run_id,str) or re.fullmatch('[0-9a-f]{16}',run_id) is None:raise ValueError('Invalid workflow record ID')
    with connect() as c:
        rows=c.execute('SELECT sequence,received_at,phase,action_id,assessment,risk_score,codes FROM tracking_events WHERE run_id=? ORDER BY sequence DESC LIMIT 400',(run_id,)).fetchall()
    return [{**dict(r),'codes':json.loads(r['codes'])} for r in reversed(rows)]
