"""Bounded, evidence-based analysis of application-reported execution graphs."""
import json
import re
import uuid
import urllib.request
from contextlib import contextmanager

ID=re.compile(r'[A-Za-z0-9._-]{1,120}\Z')

def identifier(value):
    if not isinstance(value,str) or not ID.fullmatch(value):raise ValueError('Use bounded IDs containing letters, numbers, dots, underscores or hyphens')
    return value

def checked(body):
    if not isinstance(body,dict) or set(body)!={'trajectory_id','span'}:raise ValueError('Provide trajectory_id and span')
    identifier(body['trajectory_id']);s=body['span']
    required={'id','agent_id','kind','name','status','sequence','parent_id','retry_of','depends_on','work_key','error_source','dependency_status'}
    if not isinstance(s,dict) or set(s)!=required:raise ValueError('Invalid span fields')
    for k in ('id','agent_id'):identifier(s[k])
    for k in ('parent_id','retry_of','error_source'):
        if s[k] is not None:identifier(s[k])
        if s[k]==s['id']:raise ValueError('A span cannot reference itself')
    if s['kind'] not in ('agent','tool','handoff') or s['status'] not in ('running','succeeded','failed','blocked','unknown'):raise ValueError('Invalid span kind/status')
    if not isinstance(s['name'],str) or not 1<=len(s['name'])<=120:raise ValueError('Name must be 1–120 characters')
    if type(s['sequence']) is not int or not 1<=s['sequence']<=10000:raise ValueError('Invalid sequence')
    if not isinstance(s['depends_on'],list) or len(s['depends_on'])>50 or any(not isinstance(d,str) for d in s['depends_on']) or len(set(s['depends_on']))!=len(s['depends_on']):raise ValueError('Invalid dependency list')
    for dep in s['depends_on']:
        identifier(dep)
        if dep==s['id']:raise ValueError('Self dependency')
    if s['work_key'] is not None:identifier(s['work_key'])
    ds=s['dependency_status']
    if not isinstance(ds,dict) or set(ds)!=set(s['depends_on']) or any(v not in ('succeeded','failed','blocked','running','unknown') for v in ds.values()):raise ValueError('Record dependency status at dispatch for every dependency')
    return body

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS trajectory_spans (trajectory_id TEXT, span_id TEXT, sequence INTEGER, body TEXT, updated_at TEXT, PRIMARY KEY(trajectory_id,span_id))')

def save(body,connect,timestamp):
    checked(body);s=body['span'];encoded=json.dumps(s,sort_keys=True)
    with connect() as c:
        initialize(c)
        old=c.execute('SELECT sequence,body FROM trajectory_spans WHERE trajectory_id=? AND span_id=?',(body['trajectory_id'],s['id'])).fetchone()
        if old:
            previous=json.loads(old['body'])
            if any(previous[k]!=s[k] for k in s if k not in ('sequence','status','error_source')):raise ValueError('Span identity and dispatch evidence are immutable')
            if s['sequence']<old['sequence']:return {'status':'stale'}
            if s['sequence']==old['sequence']:
                if old['body']!=encoded:raise ValueError('Conflicting duplicate span')
                return {'status':'duplicate'}
            if previous['status']!='running':raise ValueError('Completed span cannot be rewritten')
        elif c.execute('SELECT count(*) FROM trajectory_spans WHERE trajectory_id=?',(body['trajectory_id'],)).fetchone()[0]>=500:raise ValueError('Trajectory limit is 500 spans')
        c.execute('INSERT INTO trajectory_spans VALUES(?,?,?,?,?) ON CONFLICT(trajectory_id,span_id) DO UPDATE SET sequence=excluded.sequence,body=excluded.body,updated_at=excluded.updated_at',(body['trajectory_id'],s['id'],s['sequence'],encoded,timestamp()))
    return {'status':'accepted'}

def listing(connect):
    with connect() as c:
        initialize(c)
        return [dict(r) for r in c.execute('SELECT trajectory_id,count(*) AS spans,max(updated_at) AS updated_at FROM trajectory_spans GROUP BY trajectory_id ORDER BY updated_at DESC LIMIT 100')]

def report(ident,connect):
    identifier(ident)
    with connect() as c:
        initialize(c);rows=c.execute('SELECT body FROM trajectory_spans WHERE trajectory_id=? ORDER BY rowid',(ident,)).fetchall()
    return analyze(ident,[json.loads(r['body']) for r in rows])

def analyze(ident,spans):
    nodes={s['id']:s for s in spans};edges=[];findings=[]
    def finding(code,ids,message):findings.append({'code':code,'span_ids':ids,'message':message})
    for s in spans:
        for relation,refs in [('parent',[s['parent_id']]),('retry',[s['retry_of']]),('dependency',s['depends_on']),('error',[s['error_source']])]:
            for ref in filter(None,refs):
                edges.append({'from':ref,'to':s['id'],'kind':relation})
                if ref not in nodes:finding('MISSING_EVIDENCE',[s['id'],ref],'Referenced span has not been received; execution may be incomplete or arrive out of order.')
        for dep,status in s['dependency_status'].items():
            if status!='succeeded':finding('DEPENDENCY_NOT_READY',[s['id'],dep],f'Dependency was reported {status} when this span started.')
        if s['error_source']:
            source=nodes.get(s['error_source'])
            if source and source['status'] in ('failed','blocked','unknown') and s['status'] in ('failed','blocked','unknown'):
                finding('ERROR_PROPAGATION',[s['error_source'],s['id']],'Application attributed this outcome to an upstream error; this is reported attribution, not inferred causality.')
        seen={s['id']};cursor=s;ancestor_agents=[]
        while cursor.get('parent_id') in nodes:
            cursor=nodes[cursor['parent_id']]
            if cursor['id'] in seen:
                finding('EXECUTION_CYCLE',sorted(seen),'Parent links contain a cycle. Check instrumentation.');break
            seen.add(cursor['id'])
            if cursor['kind']=='agent':ancestor_agents.append(cursor['agent_id'])
        if s['kind']=='agent' and s['agent_id'] in ancestor_agents:
            finding('CIRCULAR_DELEGATION',[s['id'],*sorted(seen-{s['id']})],'An agent delegates through descendants back to the same agent. Review whether this recursion is intended.')
    # Detect dependency cycles independently of parent hierarchy.
    for s in spans:
        stack=[(s['id'],[])];visited=set()
        while stack:
            current,path=stack.pop()
            if current in path:
                finding('DEPENDENCY_CYCLE',path[path.index(current):],'Dependencies form a cycle; no valid prerequisite order exists.');break
            if current in visited:continue
            visited.add(current)
            stack.extend((d,path+[current]) for d in nodes.get(current,{}).get('depends_on',[]) if d in nodes)
    groups={}
    for s in spans:
        if s['work_key'] and not s['retry_of'] and s['status']=='succeeded':groups.setdefault((s['kind'],s['name'],s['work_key']),[]).append(s['id'])
    for ids in groups.values():
        if len(ids)>1:finding('POSSIBLE_REDUNDANT_WORK',ids,'Successful spans share an explicitly supplied work key. Confirm whether repetition was intentional.')
    unique={ (f['code'],tuple(sorted(f['span_ids']))):f for f in findings }
    return {'trajectory_id':ident,'nodes':spans,'edges':edges,'findings':list(unique.values()),
            'coverage':'Recorded spans only. Missing instrumentation and unreported branches cannot be reconstructed.',
            'running':sum(s['status']=='running' for s in spans),'agents':len({s['agent_id'] for s in spans})}

class Trajectory:
    """Explicit graph instrumentation alongside TrackedExecutor policy evaluation."""
    def __init__(self,trajectory_id=None,endpoint='http://127.0.0.1:8787',token=None,sender=None):
        from .tracking import TrackingClient,NoRedirect
        self.client=TrackingClient(endpoint=endpoint,token=token)
        self.id=identifier(trajectory_id or uuid.uuid4().hex);self.spans={};self.delivery_errors=[]
        def send(body):
            headers={'Content-Type':'application/json'}
            if self.client.token:headers['Authorization']='Bearer '+self.client.token
            req=urllib.request.Request(self.client.endpoint+'/api/trajectories/spans',data=json.dumps(body).encode(),headers=headers)
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=5) as response:return json.load(response)
        self.sender=sender or send
    def emit(self,span):
        body={'trajectory_id':self.id,'span':span};checked(body)
        try:self.sender(body)
        except Exception as exc:
            self.delivery_errors.append(type(exc).__name__)
            import warnings
            warnings.warn('Trajectory event not delivered: '+type(exc).__name__,RuntimeWarning)
    @contextmanager
    def span(self,name,agent_id,kind='tool',parent_id=None,retry_of=None,depends_on=(),work_key=None,dependency_status=None):
        s={'id':uuid.uuid4().hex,'name':name,'agent_id':agent_id,'kind':kind,'parent_id':parent_id,'retry_of':retry_of,
           'depends_on':list(depends_on),'dependency_status':dependency_status or {d:self.spans.get(d,{}).get('status','unknown') for d in depends_on},
           'work_key':work_key,'status':'running','sequence':1,'error_source':None}
        checked({'trajectory_id':self.id,'span':s});self.spans[s['id']]=s;self.emit(s)
        try:
            yield s
        except BaseException as exc:
            s['status']='blocked' if type(exc).__name__=='ActionBlocked' else 'failed';raise
        else:
            if s['status']=='running':s['status']='succeeded'
        finally:s['sequence']=2;self.emit(s)
