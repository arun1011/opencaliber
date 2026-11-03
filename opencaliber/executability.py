"""Executability under explicit flat tool contracts and application-reported state.

This checks emitted wrapper calls:
including rejections, count once; planner drafts and lifecycle events do not.
Unknown evidence is never silently promoted to valid or invalid.
"""
import copy,hashlib,json,math,re
TYPES={'string':lambda v:type(v) is str,'integer':lambda v:type(v) is int,'number':lambda v:type(v) in (int,float) and math.isfinite(v),'boolean':lambda v:type(v) is bool}

def scalar(v):return v is None or type(v) in (str,bool) or type(v) in (int,float) and abs(v)<=1e12 and math.isfinite(v)
def label(v):return isinstance(v,str) and 0<len(v)<=1000
def identifier(v):return isinstance(v,str) and re.fullmatch('[A-Za-z0-9_.:-]{1,120}',v) is not None

def validate_contracts(contracts):
    if not isinstance(contracts,dict) or len(contracts)>100:raise ValueError('Provide at most 100 tool contracts')
    for tool,c in contracts.items():
        if not label(tool) or not isinstance(c,dict) or set(c)-{'available','arguments','required','outputs','preconditions','effects','consumes'}:raise ValueError('Invalid tool contract')
        if 'available' in c and type(c['available']) is not bool:raise ValueError('available must be boolean')
        for field in ('arguments','outputs'):
            types=c.get(field,{})
            if not isinstance(types,dict) or len(types)>50 or any(not identifier(k) or not isinstance(t,str) or t not in TYPES for k,t in types.items()):raise ValueError('Contract fields require flat scalar types')
        required=c.get('required',[])
        if not isinstance(required,list) or len(required)>50 or any(k not in c.get('arguments',{}) for k in required) or len(set(required))!=len(required):raise ValueError('Invalid required argument names')
        for field in ('preconditions','effects'):
            values=c.get(field,{})
            if not isinstance(values,dict) or len(values)>50 or any(not identifier(k) or not scalar(v) or isinstance(v,str) and len(v)>300 for k,v in values.items()):raise ValueError('State predicates must be bounded scalar equalities')
        consumes=c.get('consumes',[])
        if not isinstance(consumes,list) or len(consumes)>50 or any(k not in c.get('arguments',{}) for k in consumes):raise ValueError('consumes must identify declared arguments')
    if len(json.dumps(contracts,allow_nan=False).encode())>100000:raise ValueError('Contracts exceed 100 KB')
    return copy.deepcopy(contracts)

def _validate(evidence):
    if not isinstance(evidence,dict) or not {'contracts','initial_state','attempts','complete'}<=set(evidence) or set(evidence)-{'contracts','initial_state','attempts','complete','no_tool_completion_allowed'}:raise ValueError('Evidence requires contracts, initial_state, attempts and complete')
    validate_contracts(evidence['contracts'])
    if type(evidence['complete']) is not bool:raise ValueError('complete must be boolean')
    state=evidence['initial_state']
    if not isinstance(state,dict) or len(state)>100 or any(not identifier(k) or not scalar(v) or isinstance(v,str) and len(v)>300 for k,v in state.items()):raise ValueError('Invalid initial state facts')
    if 'no_tool_completion_allowed' in evidence and type(evidence['no_tool_completion_allowed']) is not bool:raise ValueError('No-tool completion permission must be explicit boolean')
    attempts=evidence['attempts']
    if not isinstance(attempts,list) or len(attempts)>200:raise ValueError('At most 200 attempts per workflow')
    seen=set()
    for a in attempts:
        if not isinstance(a,dict) or not {'attempt_id','action','execution','disposition','transition_accepted','outputs','state_updates','references'}<=set(a) or set(a)-{'attempt_id','action','execution','disposition','transition_accepted','outputs','state_updates','references','error_type'}:raise ValueError('Invalid attempt fields')
        if not identifier(a['attempt_id']) or a['attempt_id'] in seen:raise ValueError('Attempt IDs must be unique bounded identifiers')
        seen.add(a['attempt_id'])
        action=a['action']
        if not isinstance(action,dict) or not {'id','tool','resource'}<=set(action) or not label(action['id']) or not label(action['tool']) or not isinstance(action['resource'],str) or len(action['resource'])>8000:raise ValueError('Invalid attempt action')
        args=action.get('arguments',{})
        if not isinstance(args,dict) or len(args)>50 or any(not identifier(k) or not scalar(v) or isinstance(v,str) and len(v)>8000 for k,v in args.items()):raise ValueError('Attempt arguments must be flat scalar metadata')
        if a['execution'] not in ('not_dispatched','succeeded','failed','unknown') or a['disposition'] not in ('proposed','executed','policy_blocked','contract_blocked','evaluation_unavailable'):raise ValueError('Invalid attempt disposition or outcome')
        if a['transition_accepted'] is not None and type(a['transition_accepted']) is not bool:raise ValueError('Transition acceptance must be true, false or null')
        if a['execution']!='succeeded' and a['transition_accepted'] is True:raise ValueError('Only successful execution may assert an accepted transition')
        for field in ('outputs','state_updates'):
            values=a[field]
            if not isinstance(values,dict) or len(values)>50 or any(not identifier(k) or not scalar(v) or isinstance(v,str) and len(v)>8000 for k,v in values.items()):raise ValueError('Invalid bounded attempt evidence')
        refs=a['references']
        if not isinstance(refs,dict) or len(refs)>50:raise ValueError('Invalid argument references')
        for key,ref in refs.items():
            if not identifier(key) or not isinstance(ref,dict) or set(ref)!={'attempt_id','output'} or not identifier(ref['attempt_id']) or not identifier(ref['output']):raise ValueError('References require prior attempt_id and output field')
    if len(json.dumps(evidence,allow_nan=False).encode())>500000:raise ValueError('Executability evidence exceeds 500 KB')

def assess(evidence,*,preflight_last=False):
    _validate(evidence);contracts=evidence['contracts'];state=copy.deepcopy(evidence['initial_state']);available={};rows=[];prior_rows={}
    for index,a in enumerate(evidence['attempts'],1):
        action=a['action'];tool=action['tool'];args=action.get('arguments',{});c=contracts.get(tool);invalid=[];unknown=[]
        def fail(category,code):invalid.append((category,code))
        if c is None:unknown.append(('schema','CONTRACT_NOT_REGISTERED'))
        else:
            if c.get('available',True) is False:fail('schema','TOOL_UNAVAILABLE')
            if any(k not in args for k in c.get('required',[])):fail('schema','REQUIRED_ARGUMENT_MISSING')
            if any(k not in c.get('arguments',{}) for k in args):fail('schema','UNDECLARED_ARGUMENT')
            if any(k in args and not TYPES[t](args[k]) for k,t in c.get('arguments',{}).items()):fail('schema','ARGUMENT_TYPE_MISMATCH')
            for key,ref in a['references'].items():
                produced=available.get((ref['attempt_id'],ref['output']))
                if produced is None:
                    if prior_rows.get(ref['attempt_id'],{}).get('validity')=='unknown':unknown.append(('dependency','REFERENCE_NOT_CONFIRMED'))
                    else:fail('dependency','REFERENCE_UNAVAILABLE')
                elif key not in args or args[key]!=produced[0] or key in c.get('arguments',{}) and not TYPES[c['arguments'][key]](produced[0]):fail('dependency','REFERENCE_VALUE_MISMATCH')
            for key,expected in c.get('preconditions',{}).items():
                if key not in state:unknown.append(('precondition','STATE_NOT_OBSERVED'))
                elif type(state[key]) is not type(expected) or state[key]!=expected:fail('precondition','PRECONDITION_FALSE')
            if a['transition_accepted'] is False:fail('state','TRANSITION_REJECTED')
            if a['execution']=='succeeded':
                for key,t in c.get('outputs',{}).items():
                    if key not in a['outputs']:unknown.append(('dependency','OUTPUT_NOT_OBSERVED'))
                    elif not TYPES[t](a['outputs'][key]):fail('schema','OUTPUT_TYPE_MISMATCH')
                for key,value in c.get('effects',{}).items():
                    if key not in a['state_updates']:unknown.append(('state','EFFECT_NOT_OBSERVED'))
                    elif type(a['state_updates'][key]) is not type(value) or a['state_updates'][key]!=value:fail('state','STATE_EFFECT_MISMATCH')
            if not (preflight_last and index==len(evidence['attempts'])) and (a['execution']!='succeeded' or a['transition_accepted'] is None):unknown.append(('state','TRANSITION_NOT_CONFIRMED'))
        if invalid:status='invalid';category,code=invalid[0]
        elif unknown:status='unknown';category,code=unknown[0]
        else:status='valid';category,code='none','CONTRACT_AND_TRANSITION_CONFIRMED'
        rows.append({'depth':index,'attempt_id':a['attempt_id'],'action_id':action['id'],'tool':tool,'execution':a['execution'],'disposition':a['disposition'],'validity':status,'category':category,'code':code})
        prior_rows[a['attempt_id']]=rows[-1]
        # Only confirmed successful effects advance the recorded state. Never
        # invent outputs after a rejected call or use an uncertain producer.
        if status!='valid' and c and a['disposition']=='executed' and a['transition_accepted'] is not False:
            for key in c.get('effects',{}):state.pop(key,None)
        if status=='valid' and a['execution']=='succeeded' and a['transition_accepted'] is True:
            for key in c.get('outputs',{}):available[(a['attempt_id'],key)]=(copy.deepcopy(a['outputs'][key]),c['outputs'][key])
            state.update({key:copy.deepcopy(a['state_updates'][key]) for key in c.get('effects',{})})
            for key in c.get('consumes',[]):
                ref=a['references'].get(key)
                if ref:available.pop((ref['attempt_id'],ref['output']),None)
    if not rows:
        allowed=evidence.get('no_tool_completion_allowed') if evidence['complete'] else None
        rows=[{'depth':1,'attempt_id':'terminal-no-tool','action_id':'terminal-no-tool','tool':'terminal.no_tool','execution':'not_dispatched','disposition':'proposed','validity':'unknown' if allowed is None else 'valid' if allowed else 'invalid','category':'information','code':'NO_TOOL_EVIDENCE' if allowed is None else 'NO_TOOL_COMPLETION_ALLOWED' if allowed else 'TOOL_ACTION_REQUIRED'}]
    return _summarize(rows,evidence['complete'],len(evidence['attempts']),hashlib.sha256(json.dumps(contracts,sort_keys=True,separators=(',',':')).encode()).hexdigest(),hashlib.sha256(json.dumps(evidence['initial_state'],sort_keys=True,separators=(',',':')).encode()).hexdigest())

def _summarize(rows,complete,attempt_count,contract_hash,state_hash):
    first_invalid=next((r['depth'] for r in rows if r['validity']=='invalid'),None);unknown_before=any(r['validity']=='unknown' for r in rows[:first_invalid-1 if first_invalid else len(rows)])
    fed=first_invalid if first_invalid and not unknown_before else len(rows)+1 if complete and all(r['validity']=='valid' for r in rows) else None
    ter=False if first_invalid else True if complete and all(r['validity']=='valid' for r in rows) else None
    prefixes=[];prior='valid'
    for r in rows:
        prior='invalid' if prior=='invalid' or r['validity']=='invalid' else 'unknown' if prior=='unknown' or r['validity']=='unknown' else 'valid';prefixes.append(prior)
    return {'schema_version':1,'scope':'emitted_wrapper_attempts','complete':complete,'contract_sha256':contract_hash,'initial_state_sha256':state_hash,
            'attempt_count':attempt_count,'horizon':len(rows),'first_invalid_step':fed,'first_observed_invalid_step':first_invalid,'all_calls_valid':ter,
            'validated_progress':(fed-1)/len(rows) if fed is not None and complete else None,'unknown_attempts':sum(r['validity']=='unknown' for r in rows),'attempts':rows,'step_status':prefixes,
            'limits':['Application-reported tool contracts, state, outputs and acceptance; not independent environment replay.','Policy rejection alone does not prove a tool cannot run. Unknown transitions do not pass.','Emitted calls include rejections; planning drafts are excluded.']}

def aggregate(items,*,max_depth=None):
    n=len(items)
    if not n:return {'trajectories':0,'valid_run_rate':None,'validated_progress':None,'recovery_success_rate':None,'recovery_cases':0,'step_curve':[]}
    valid=sum(r['all_calls_valid'] is True for r,_ in items);failed=sum(r['all_calls_valid'] is False for r,_ in items);unknown=n-valid-failed
    areas=[r['validated_progress'] for r,_ in items];eligible=[(r,y) for r,y in items if r['all_calls_valid'] is False];recovered_tasks=sum(y is True for _,y in eligible)
    pec=[]
    for k in range(1,max(max(r['horizon'] for r,_ in items),max_depth or 0)+1):
        states=[r['step_status'][k-1] if k<=r['horizon'] else 'invalid' if r['complete'] or r['first_observed_invalid_step'] else 'unknown' for r,_ in items]
        lo=sum(s=='valid' for s in states)/n;hi=lo+sum(s=='unknown' for s in states)/n;eligible_n=sum(k<=r['horizon'] for r,_ in items)
        eligible_states=[r['step_status'][k-1] for r,_ in items if k<=r['horizon']]
        pec.append({'depth':k,'value':lo if lo==hi else None,'lower':lo,'upper':hi,'active_runs':eligible_n,'active_value':sum(s=='valid' for s in eligible_states)/eligible_n if eligible_n and 'unknown' not in eligible_states else None})
    return {'trajectories':n,'valid_run_rate':valid/n if unknown==0 else None,'valid_run_lower':valid/n,'valid_run_upper':(valid+unknown)/n,'unknown_runs':unknown,'validated_progress':sum(areas)/n if all(v is not None for v in areas) else None,
            'recovery_cases':len(eligible),'recovered_tasks':recovered_tasks,'recovery_success_rate':recovered_tasks/len(eligible) if eligible and unknown==0 and all(y is not None for _,y in eligible) else None,'step_curve':pec}

def validate_report(report):
    fields={'schema_version','scope','complete','contract_sha256','initial_state_sha256','attempt_count','horizon','first_invalid_step','first_observed_invalid_step','all_calls_valid','validated_progress','unknown_attempts','attempts','step_status','limits'}
    if not isinstance(report,dict) or set(report)!=fields or report['schema_version']!=1 or report['scope']!='emitted_wrapper_attempts' or type(report['complete']) is not bool:raise ValueError('Invalid reliability summary')
    for k in ('contract_sha256','initial_state_sha256'):
        if not isinstance(report[k],str) or re.fullmatch('[0-9a-f]{64}',report[k]) is None:raise ValueError('Invalid evidence fingerprint')
    rows=report['attempts']
    if not isinstance(rows,list) or not 1<=len(rows)<=200 or type(report['attempt_count']) is not int or report['attempt_count'] not in (0,len(rows)):raise ValueError('Invalid attempt count')
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict) or set(row)!={'depth','attempt_id','action_id','tool','execution','disposition','validity','category','code'} or row['depth']!=i:raise ValueError('Invalid attempt summary')
        if not identifier(row['attempt_id']) or any(not label(row[k]) for k in ('action_id','tool')) or not isinstance(row['code'],str) or not re.fullmatch('[A-Z_]{1,80}',row['code']):raise ValueError('Invalid attempt identity or code')
        if row['validity'] not in ('valid','invalid','unknown') or row['category'] not in ('schema','dependency','precondition','state','information','none') or row['execution'] not in ('not_dispatched','succeeded','failed','unknown') or row['disposition'] not in ('proposed','executed','policy_blocked','contract_blocked','evaluation_unavailable'):raise ValueError('Invalid attempt status')
    derived=_summarize(copy.deepcopy(rows),report['complete'],report['attempt_count'],report['contract_sha256'],report['initial_state_sha256'])
    if any(report[k]!=derived[k] for k in fields-{'limits'}):raise ValueError('Reliability summary metrics do not match its attempt ledger')
    return derived
