"""Versioned console-authored detectors using a bounded Python expression interpreter.

Never exec/eval generated code. A check is a single return expression over explicit
evidence, with no imports, attribute access, loops, I/O or access to Python objects.
"""
import ast
import copy
import hashlib
import json
import re
from functools import lru_cache

SPEC = '''Write exactly one function: def check(ctx): return <boolean expression>.
True means a problem; False means passed. Use field("action.arguments.records"),
field("action.resource"), field("output.some_field"), field("task.goal") to read evidence.
Available: contains(container, value), lower(text), count(list_or_text),
previous_succeeded("tool.name", field("action.resource")). Boolean and/or/not,
comparisons == != < <= > >= in not in, literal strings/numbers/lists are supported.
No imports, attributes, subscripts, assignments, loops, comprehensions or Python execution.
Declare all field() paths in requires. Missing evidence produces unknown, never passed.
Checks over output are post-action monitoring, not pre-dispatch protection.'''

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS custom_detectors (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, spec TEXT NOT NULL, enabled INTEGER NOT NULL, tested_hash TEXT, report TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS detector_audit (id INTEGER PRIMARY KEY, detector_id TEXT, revision INTEGER, event TEXT, spec TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')

def fingerprint(spec):
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()

@lru_cache(maxsize=256)
def expression(code):
    if not isinstance(code,str) or len(code)>8000:raise ValueError('Check code must be at most 8,000 characters')
    try:tree=ast.parse(code)
    except (SyntaxError,RecursionError):raise ValueError('Invalid Python check syntax') from None
    if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef):raise ValueError('Provide only def check(ctx): return <boolean expression>')
    f=tree.body[0]
    if (f.name!='check' or f.decorator_list or f.returns or f.type_comment or getattr(f,'type_params',[]) or len(f.body)!=1 or not isinstance(f.body[0],ast.Return)
        or len(f.args.args)!=1 or f.args.args[0].arg!='ctx' or f.args.args[0].annotation or f.args.defaults or f.args.kw_defaults or f.args.kwonlyargs or f.args.posonlyargs or f.args.vararg or f.args.kwarg):
        raise ValueError('Use one unannotated check(ctx) function containing one return')
    nodes=list(ast.walk(f.body[0].value))
    allowed=(ast.Constant,ast.List,ast.Tuple,ast.Load,ast.Call,ast.Name,ast.BoolOp,ast.And,ast.Or,ast.UnaryOp,ast.Not,ast.USub,ast.Compare,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE,ast.In,ast.NotIn)
    if len(nodes)>250 or any(not isinstance(n,allowed) for n in nodes):raise ValueError('Unsupported code. Use the documented restricted Python operations')
    fields=[]
    arities={'field':1,'contains':2,'lower':1,'count':1,'previous_succeeded':2}
    for n in nodes:
        if isinstance(n,ast.Name) and n.id not in arities:raise ValueError('Unknown helper: '+n.id)
        if isinstance(n,ast.Call):
            if not isinstance(n.func,ast.Name) or n.func.id not in arities or n.keywords or len(n.args)!=arities[n.func.id]:raise ValueError('Invalid helper call')
            if n.func.id=='field':
                if not isinstance(n.args[0],ast.Constant) or not isinstance(n.args[0].value,str):raise ValueError('field() needs a literal evidence path')
                fields.append(n.args[0].value)
        if isinstance(n,ast.Constant) and (type(n.value) not in (str,int,float,bool,type(None)) or len(str(n.value))>2000):raise ValueError('Invalid literal')
    return f.body[0].value,fields

def validate(spec):
    keys={'id','name','description','tool','tracking_ids','stage','requires','code','message','remediation','tests'}
    if not isinstance(spec,dict) or set(spec)!=keys:raise ValueError('Invalid detector fields')
    for key,limit in [('id',60),('name',120),('description',2000),('tool',100),('message',500),('remediation',500)]:
        if not isinstance(spec[key],str) or not 1<=len(spec[key])<=limit:raise ValueError('Invalid '+key)
    if not re.fullmatch('[a-z][a-z0-9_-]{0,59}',spec['id']):raise ValueError('Use a lowercase check ID with letters, digits, hyphens or underscores')
    if not re.fullmatch('[A-Za-z][A-Za-z0-9_.-]{0,99}',spec['tool']):raise ValueError('Specify one tool name')
    if spec['stage'] not in ('before','after'):raise ValueError('Choose before or after action')
    if not isinstance(spec['tracking_ids'],list) or len(spec['tracking_ids'])>100 or any(not isinstance(x,str) or not re.fullmatch('[A-Za-z0-9._-]{1,120}',x) for x in spec['tracking_ids']):raise ValueError('Invalid tracking scope')
    if not isinstance(spec['requires'],list) or len(spec['requires'])>30 or any(not isinstance(x,str) or not re.fullmatch(r'(action|output|task)(\.[A-Za-z0-9_-]+)+',x) for x in spec['requires']):raise ValueError('Declare evidence paths starting action., output. or task.')
    _,fields=expression(spec['code'])
    if not set(fields)<=set(spec['requires']):raise ValueError('Every field() path must be declared in required evidence')
    if spec['stage']=='before' and any(p.startswith(('output.','action.outcome.')) for p in spec['requires']):raise ValueError('Outputs and outcomes require an after-action check')
    tests=spec['tests']
    if not isinstance(tests,list) or not 2<=len(tests)<=30:raise ValueError('Provide 2–30 tests, including passed and failed examples')
    for t in tests:
        if not isinstance(t,dict) or set(t)!={'name','context','expected'} or not isinstance(t['name'],str) or not 1<=len(t['name'])<=120 or not isinstance(t['context'],dict) or t['expected'] not in ('passed','failed','unknown'):raise ValueError('Invalid test case')
        if t['context'].get('action',{}).get('tool')!=spec['tool']:raise ValueError('Each test action must use the selected tool')
    if not {'passed','failed'}<={t['expected'] for t in tests}:raise ValueError('Tests need both passed and failed expectations')
    if len(json.dumps(spec,allow_nan=False))>150000:raise ValueError('Check and tests exceed 150 KB')
    return spec

class EvidenceMissing(ValueError):pass

def field(ctx,path):
    value=ctx
    for key in path.split('.'):
        if not isinstance(value,dict) or key not in value:raise EvidenceMissing(path)
        value=value[key]
    if value is None:raise EvidenceMissing(path)
    return value

def interpret(node,ctx):
    if isinstance(node,ast.Constant):return node.value
    if isinstance(node,(ast.List,ast.Tuple)):return [interpret(n,ctx) for n in node.elts]
    if isinstance(node,ast.BoolOp):
        values=[interpret(n,ctx) for n in node.values]
        if any(type(v) is not bool for v in values):raise ValueError('and/or need boolean expressions')
        return all(values) if isinstance(node.op,ast.And) else any(values)
    if isinstance(node,ast.UnaryOp):
        v=interpret(node.operand,ctx)
        if isinstance(node.op,ast.Not):return not v
        if type(v) not in (int,float):raise ValueError('Unary minus needs a number')
        return -v
    if isinstance(node,ast.Compare):
        left=interpret(node.left,ctx)
        for op,right_node in zip(node.ops,node.comparators):
            right=interpret(right_node,ctx)
            if isinstance(op,ast.Eq):ok=left==right
            elif isinstance(op,ast.NotEq):ok=left!=right
            elif isinstance(op,ast.Lt):ok=left<right
            elif isinstance(op,ast.LtE):ok=left<=right
            elif isinstance(op,ast.Gt):ok=left>right
            elif isinstance(op,ast.GtE):ok=left>=right
            elif isinstance(op,ast.In):ok=left in right
            else:ok=left not in right
            if not ok:return False
            left=right
        return True
    if isinstance(node,ast.Call):
        values=[interpret(a,ctx) for a in node.args];name=node.func.id
        if name=='field':return field(ctx,values[0])
        if name=='contains':return values[1] in values[0]
        if name=='lower':
            if not isinstance(values[0],str):raise ValueError('lower needs text')
            return values[0].lower()
        if name=='count':
            if not isinstance(values[0],(str,list,dict)):raise ValueError('count needs text, list or object')
            return len(values[0])
        if name=='previous_succeeded':
            if not isinstance(ctx.get('history'),list):raise EvidenceMissing('history')
            return any(a.get('tool')==values[0] and a.get('resource')==values[1] and a.get('outcome',{}).get('status')=='succeeded' for a in ctx['history'])
    raise ValueError('Unsupported expression')

def evaluate(spec,ctx):
    try:
        for path in spec['requires']:field(ctx,path)
        value=interpret(expression(spec['code'])[0],ctx)
        if type(value) is not bool:raise ValueError('Return a boolean')
        return {'status':'failed' if value else 'passed','reason':spec['message'] if value else 'Check passed'}
    except EvidenceMissing as exc:return {'status':'unknown','reason':'Missing evidence: '+str(exc)}
    except (TypeError,ValueError,KeyError,IndexError,RecursionError):return {'status':'unknown','reason':'Evidence type or check expression could not be evaluated'}

def test(spec):
    validate(spec)
    rows=[{'name':t['name'],'expected':t['expected'],**evaluate(spec,t['context'])} for t in spec['tests']]
    # Independently remove each required field from a passing example.
    base=next(t['context'] for t in spec['tests'] if t['expected']=='passed')
    for path in spec['requires']:
        ctx=copy.deepcopy(base);parent=ctx
        for key in path.split('.')[:-1]:parent=parent.get(key,{}) if isinstance(parent,dict) else {}
        if isinstance(parent,dict):parent.pop(path.split('.')[-1],None)
        rows.append({'name':'Missing '+path,'expected':'unknown',**evaluate(spec,ctx)})
    return {'passed':all(r['expected']==r['status'] for r in rows),'cases':rows,'hash':fingerprint(spec)}

def listing(connect):
    with connect() as c:
        initialize(c);rows=c.execute('SELECT * FROM custom_detectors ORDER BY id').fetchall()
    return [{'spec':json.loads(r['spec']),'revision':r['revision'],'enabled':bool(r['enabled']),'tested_hash':r['tested_hash'],'report':json.loads(r['report']) if r['report'] else None} for r in rows]

def save(body,connect):
    if set(body)!={'spec','revision'} or type(body['revision']) is not int:raise ValueError('Provide spec and current revision (0 for new)')
    spec=validate(body['spec'])
    with connect() as c:
        initialize(c);c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT revision FROM custom_detectors WHERE id=?',(spec['id'],)).fetchone()
        if (old['revision'] if old else 0)!=body['revision']:raise ValueError('Check changed in another session. Reload before saving')
        if not old and c.execute('SELECT COUNT(*) FROM custom_detectors').fetchone()[0]>=100:raise ValueError('Workspace limit: 100 custom checks')
        rev=body['revision']+1
        c.execute('INSERT INTO custom_detectors VALUES(?,?,?,0,NULL,NULL) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,spec=excluded.spec,enabled=0,tested_hash=NULL,report=NULL',(spec['id'],rev,json.dumps(spec)))
        c.execute('INSERT INTO detector_audit(detector_id,revision,event,spec) VALUES(?,?,?,?)',(spec['id'],rev,'saved_disabled',json.dumps(spec)))
    return {'saved':True,'revision':rev,'enabled':False}

def manage(body,connect):
    if set(body)!={'id','revision','operation'} or not isinstance(body['id'],str) or type(body['revision']) is not int or body['operation'] not in ('test','enable','disable','delete'):raise ValueError('Invalid check operation')
    with connect() as c:
        initialize(c);c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM custom_detectors WHERE id=?',(body['id'],)).fetchone()
        if not row or row['revision']!=body['revision']:raise ValueError('Check missing or changed. Reload it')
        spec=json.loads(row['spec']);operation=body['operation'];report=None
        if operation=='test':
            report=test(spec);c.execute('UPDATE custom_detectors SET tested_hash=?,report=? WHERE id=?',(fingerprint(spec) if report['passed'] else None,json.dumps(report),body['id']))
        elif operation=='enable':
            if row['tested_hash']!=fingerprint(spec):raise ValueError('Run passing tests for the saved revision before enabling')
            c.execute('UPDATE custom_detectors SET enabled=1 WHERE id=?',(body['id'],))
        elif operation=='disable':c.execute('UPDATE custom_detectors SET enabled=0 WHERE id=?',(body['id'],))
        else:c.execute('DELETE FROM custom_detectors WHERE id=?',(body['id'],))
        c.execute('INSERT INTO detector_audit(detector_id,revision,event,spec) VALUES(?,?,?,?)',(body['id'],row['revision'],operation,json.dumps(spec)))
    return {'saved':True,'operation':operation,'report':report}

def apply(body,result,connect):
    active=[r for r in listing(connect) if r['enabled'] and (not r['spec']['tracking_ids'] or body['tracking_id'] in r['spec']['tracking_ids'])]
    result['custom_checks']=[]
    result['custom_checks_sha256']=fingerprint([{'spec':r['spec'],'revision':r['revision']} for r in active])
    trace=body['trace'];outputs=body.get('diagnosis',{}).get('outputs',{})
    for index,action in enumerate(trace['actions']):
        for row in active:
            spec=row['spec']
            if spec['tool']!=action['tool']:continue
            after=spec['stage']=='after'
            if after and 'outcome' not in action:
                outcome={'status':'pending','reason':'Requires completed action evidence'}
            elif body['redacted']:
                outcome={'status':'unknown','reason':'Original evidence unavailable in offline event'}
            else:outcome=evaluate(spec,{'action':action,'output':outputs.get(action['id'],{}),'task':trace['task'],'history':trace['actions'][:index]})
            result['custom_checks'].append({'id':spec['id'],'revision':row['revision'],'action_id':action['id'],'stage':spec['stage'],**outcome})
            if outcome['status'] not in ('failed','unknown'):continue
            failure=outcome['status']=='failed'
            finding={'code':'CUSTOM_'+spec['id'].upper().replace('-','_')+('' if failure else '_EVIDENCE'),
                     'category':'custom_check','score':70 if failure else 20,'message':outcome['reason'],
                     'explicit_violation':failure,'evidence_ids':[action['id']],
                     'remediation':{'change':spec['remediation'] if failure else 'Send the required evidence; the custom check could not establish a result.'}}
            target=result['actions'][index];target['findings'].append(finding)
            target['assessment']='violation' if failure else ('review' if target['assessment']=='clear' else target['assessment'])
            target['risk_score']=max(target['risk_score'],finding['score'])
            if failure:target['policy_result']='violation'
    result['finding_count']=sum(len(a['findings']) for a in result['actions'])
    if result['actions']:
        result['assessment']='violation' if any(a['assessment']=='violation' for a in result['actions']) else 'review' if any(a['assessment']=='review' for a in result['actions']) else 'clear'
        result['risk_score']=max(a['risk_score'] for a in result['actions'])
    return result
