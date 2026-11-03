"""Diagnosis of connected runs using explicitly captured context and recorded policy."""
import copy
import hashlib
import json
import re
from .diagnosis import diagnose,validate

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS run_diagnosis (run_id TEXT PRIMARY KEY, sequence INTEGER, bundle TEXT, report TEXT)')

def capture_context(context,trace):
    if not isinstance(context,dict) or set(context)!={'outputs','constraints','verifications'}:raise ValueError('Invalid diagnosis context')
    bundle={'trace':trace,**context}
    if trace['actions']:validate(bundle)
    elif context['outputs'] or context['verifications']:raise ValueError('No output evidence without actions')
    else:
        # Validate lifecycle-only context without retaining a placeholder action.
        validate({**bundle,'trace':{**trace,'actions':[{'id':'validate-only','tool':'file.read','resource':'/placeholder'}]}})
    return copy.deepcopy(context)

def record(c,run_id,body,config):
    initialize(c)
    if body['redacted'] or 'diagnosis' not in body:return
    if not body['trace']['actions']:return
    bundle={'trace':body['trace'],**body['diagnosis'],'config':config}
    validate(bundle)
    result=diagnose(bundle) if body['phase'] in ('completed','workflow_failed') else None
    c.execute('INSERT INTO run_diagnosis VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET sequence=excluded.sequence,bundle=excluded.bundle,report=excluded.report',
              (run_id,body['sequence'],json.dumps(bundle),json.dumps(result) if result else None))

def runs(connect):
    with connect() as c:
        initialize(c)
        rows=c.execute('SELECT r.id,r.created_at,r.name,r.result,d.bundle,d.report FROM runs r LEFT JOIN run_diagnosis d ON d.run_id=r.id ORDER BY r.created_at DESC LIMIT 100').fetchall()
    result=[]
    for row in rows:
        report=json.loads(row['result']);tracking=report.get('tracking')
        if not tracking:continue
        bundle=json.loads(row['bundle']) if row['bundle'] else None
        saved=json.loads(row['report']) if row['report'] else None
        result.append({'id':row['id'],'agent':row['name'],'created_at':row['created_at'],'tracking_id':tracking['tracking_id'],
                       'phase':tracking['phase'],'context_available':bool(bundle),'captured_outputs':len(bundle['outputs']) if bundle else 0,
                       'assessment':saved['assessment'] if saved else 'not_diagnosed','policy_source':tracking.get('policy_source')})
    return result

def run_report(run_id,connect,use_semantic=False):
    if not isinstance(run_id,str) or not re.fullmatch('[0-9a-f]{16}',run_id):raise ValueError('Invalid run ID')
    with connect() as c:
        initialize(c)
        row=c.execute('SELECT r.result,r.config,d.bundle,d.sequence FROM runs r LEFT JOIN run_diagnosis d ON d.run_id=r.id WHERE r.id=?',(run_id,)).fetchone()
    if not row:raise ValueError('Run not found')
    saved=json.loads(row['result'])
    if not saved.get('tracking'):raise ValueError('Choose a connected-agent run')
    if not row['bundle']:
        return {'assessment':'insufficient_evidence','policy_assessment':saved['assessment'],'findings':[
            {'layer':'policy','code':f['code'],'action_ids':[a['action_id']],'reason':f['message']} for a in saved['actions'] for f in a['findings']],
            'semantic':{'status':'unavailable','assessment':'unknown','model':None,'prompt_version':None},'verification':[],
            'run_id':run_id,'captured_outputs':0,'context_available':False,'advisory_only':True,
            'limits':['This run did not capture diagnosis context. Recorded policy findings are shown without re-evaluating redacted inputs. Enable diagnosis in the wrapper and run the agent again.']}
    bundle=json.loads(row['bundle']);result=diagnose(bundle,use_semantic=use_semantic)
    result.update(run_id=run_id,context_available=True,captured_outputs=len(bundle['outputs']),
                  policy_source='recorded_run_snapshot',policy_sha256=hashlib.sha256(json.dumps(bundle['config'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),context_sequence=row['sequence'])
    result['limits'].append('Uses the policy snapshot recorded with this run, not current edited settings. Earlier actions may have been evaluated under different settings if policy changed mid-run.')
    if len(bundle['outputs'])<len(bundle['trace']['actions']):result['limits'].append('Some actions have no captured output. Missing contents cannot be inferred from policy compliance.')
    with connect() as c:
        # Never let a slow model overwrite the report for a newer workflow snapshot.
        c.execute('UPDATE run_diagnosis SET report=? WHERE run_id=? AND sequence=?',(json.dumps(result),run_id,row['sequence']))
    return result
