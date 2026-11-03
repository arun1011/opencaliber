"""Paired version evaluation and review-only proposals. Never modifies agents or policies."""
import copy,hashlib,json,math,re,time
from .agent_engine import DEFAULT_CONFIG,evaluate_trace,validate_config
from .privacy import minimize_evidence
from .executability import assess,aggregate

def _text(value,name,maximum=120):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:raise ValueError(name+' must be a bounded nonempty string')
    return value

def _number(value,name):
    if value is not None and (type(value) not in (int,float) or not 0<=value<=1e12 or not math.isfinite(value)):raise ValueError(name+' must be a nonnegative finite number or null')
    return value

def _expected(expected):
    if not isinstance(expected,dict) or set(expected)!={'assessment','required_codes'} or expected['assessment'] not in ('clear','review','violation'):raise ValueError('Invalid expected contract')
    codes=expected['required_codes']
    if not isinstance(codes,list) or len(codes)>100 or any(not isinstance(c,str) or not re.fullmatch('[A-Z][A-Z0-9_]{0,99}',c) for c in codes) or len(set(codes))!=len(codes):raise ValueError('Invalid required finding codes')
    if expected['assessment']=='clear' and codes:raise ValueError('Clear cases cannot require findings')
    return expected

def run_versions(cases,baseline,candidate,*,agent_id,baseline_version,candidate_version,config=None):
    """Execute two application-owned synchronous callbacks on isolated copies of each input.

    Callback returns trace, task_success, cost_usd and cost_source. Application
    code owns credentials, timeouts, side effects and outcome assertions.
    """
    if not callable(baseline) or not callable(candidate):raise ValueError('Provide two application-owned callbacks')
    if not isinstance(cases,list) or not 1<=len(cases)<=100:raise ValueError('Provide 1–100 paired test cases')
    _text(agent_id,'agent_id');_text(baseline_version,'baseline_version',80);_text(candidate_version,'candidate_version',80)
    if baseline_version==candidate_version:raise ValueError('Choose two distinct agent versions')
    cfg=validate_config(DEFAULT_CONFIG if config is None else config)
    seen=set()
    for case in cases:
        if not isinstance(case,dict) or set(case)!={'id','input','expected'}:raise ValueError('Runner cases require id, input and expected')
        ident=_text(case['id'],'case id',80)
        if ident in seen:raise ValueError('Case IDs must be unique')
        seen.add(ident);_expected(case['expected']);json.dumps(case['input'],allow_nan=False)
    rows=[]
    for index,case in enumerate(cases):
        if not isinstance(case,dict) or set(case)!={'id','input','expected'}:raise ValueError('Runner cases require id, input and expected')
        raw=json.dumps(case['input'],sort_keys=True,separators=(',',':'),allow_nan=False)
        row={'id':case['id'],'input_sha256':hashlib.sha256(raw.encode()).hexdigest(),'expected':copy.deepcopy(case['expected'])}
        order=[('baseline',baseline,baseline_version),('candidate',candidate,candidate_version)]
        if index%2:order.reverse()  # Reduce fixed-order bias; not a statistical benchmark.
        for label,callback,version in order:
            started=time.perf_counter()
            try:
                output=callback(copy.deepcopy(case['input']))
            except Exception as exc:
                output={'trace':None,'task_success':False,'cost_usd':None,'cost_source':'not_reported','error_type':type(exc).__name__}
            elapsed=(time.perf_counter()-started)*1000
            if not isinstance(output,dict):raise ValueError('Callback must return a result object')
            result=copy.deepcopy(output)
            if result.get('trace') is not None:
                if not isinstance(result['trace'],dict):raise ValueError('Callback trace must be an object or null')
                result['trace'].setdefault('agent',{'id':agent_id,'version':version})
            result['latency_ms']=round(elapsed,4);result['latency_source']='measured_by_runner'
            row[label]=result
        rows.append(row)
    bundle={'schema_version':1,'agent_id':agent_id,'baseline_version':baseline_version,'candidate_version':candidate_version,
            'config':cfg,'cases':rows}
    compare(bundle)  # Validate exported artifacts before writing them.
    return bundle

def _result(value,agent_id,version,config,expected):
    required={'trace','task_success','cost_usd','cost_source','latency_ms','latency_source'}
    if not isinstance(value,dict) or not required<=set(value) or set(value)-required-{'error_type','execution_evidence'}:raise ValueError('Invalid version result fields')
    success=value['task_success']
    if success is not None and type(success) is not bool:raise ValueError('task_success must be true, false or null')
    cost=_number(value['cost_usd'],'cost_usd');latency=_number(value['latency_ms'],'latency_ms')
    if value['cost_source'] not in ('provider_reported','estimated','not_reported') or (cost is None)!=(value['cost_source']=='not_reported'):raise ValueError('Supply cost provenance or mark cost not_reported')
    if value['latency_source'] not in ('measured_by_runner','reported','not_reported') or (latency is None)!=(value['latency_source']=='not_reported'):raise ValueError('Supply latency provenance or mark latency not_reported')
    error=value.get('error_type')
    if error is not None and (not isinstance(error,str) or not re.fullmatch('[A-Za-z0-9_]{1,80}',error)):raise ValueError('Provide error type only, not exception text')
    trace=value['trace'];assessment='unavailable';codes=[];findings=[];contract_passed=False
    if trace is not None:
        if not isinstance(trace,dict) or trace.get('agent')!={'id':agent_id,'version':version}:raise ValueError('Trace agent identity must match its version label')
        evaluated=evaluate_trace(trace,config);assessment=evaluated['assessment']
        _,minimal=minimize_evidence(trace,evaluated)
        findings=[{'action_id':a['action_id'],'tool':a['tool'],'code':f['code'],'message':f['message'],
                   'change':f.get('remediation',{}).get('change','Review the action and policy.')} for a in minimal['actions'] for f in a['findings']]
        codes=sorted({f['code'] for f in findings})
        contract_passed=assessment==expected['assessment'] and set(expected['required_codes'])<=set(codes)
    elif not error:raise ValueError('A missing trace requires an error_type')
    evidence=value.get('execution_evidence')
    executable=assess(evidence if evidence is not None else {'contracts':{},'initial_state':{},'attempts':[],'complete':False})
    if evidence is not None and trace is not None:
        executed=[a['action'] for a in evidence['attempts'] if a['disposition']=='executed']
        if len(executed)!=len(trace['actions']) or any(any(a.get(k,{})!=b.get(k,{}) for k in ('id','tool','resource','arguments')) for a,b in zip(executed,trace['actions'])):raise ValueError('Executed attempt evidence must match the policy trace in order')
    return {'step_checks':executable,'execution_evidence_reported':evidence is not None,'task_success':success,'assessment':assessment,'codes':codes,'contract_passed':contract_passed,'cost_usd':cost,
            'cost_source':value['cost_source'],'latency_ms':latency,'latency_source':value['latency_source'],'error_type':error,'findings':findings}

def _metrics(rows,label):
    values=[r[label] for r in rows];n=len(values);known=[r for r in values if r['task_success'] is not None]
    costs=[r['cost_usd'] for r in values if r['cost_usd'] is not None];latencies=[r['latency_ms'] for r in values if r['latency_ms'] is not None]
    evaluated=[r for r in values if r['assessment']!='unavailable']
    return {'step_checks':aggregate([(v['step_checks'],v['task_success']) for v in values],max_depth=max(row[side]['step_checks']['horizon'] for row in rows for side in ('baseline','candidate'))),'execution_evidence_cases':sum(v['execution_evidence_reported'] for v in values),'cases':n,'task_successes':sum(r['task_success'] is True for r in values),'task_outcomes_reported':len(known),
            'task_success_rate':sum(r['task_success'] is True for r in known)/n if len(known)==n else None,
            'contract_passes':sum(r['contract_passed'] for r in values),'policy_violations':sum(r['assessment']=='violation' for r in values),
            'evaluated_traces':len(evaluated),'execution_errors':sum(r['error_type'] is not None for r in values),
            'total_cost_usd':sum(costs) if len(costs)==n else None,'reported_cost_usd':sum(costs),'cost_cases_reported':len(costs),
            'mean_latency_ms':sum(latencies)/n if len(latencies)==n else None,'latency_cases_reported':len(latencies),
            'cost_sources':sorted({r['cost_source'] for r in values}),'latency_sources':sorted({r['latency_source'] for r in values})}

def compare(bundle):
    if not isinstance(bundle,dict) or set(bundle)!={'schema_version','agent_id','baseline_version','candidate_version','config','cases'} or type(bundle['schema_version']) is not int or bundle['schema_version']!=1:raise ValueError('Invalid comparison bundle schema')
    agent=_text(bundle['agent_id'],'agent_id');a=_text(bundle['baseline_version'],'baseline_version',80);b=_text(bundle['candidate_version'],'candidate_version',80)
    if a==b:raise ValueError('Choose two distinct agent versions')
    cfg=validate_config(bundle['config']);cases=bundle['cases']
    if not isinstance(cases,list) or not 1<=len(cases)<=100:raise ValueError('Provide 1–100 paired cases')
    if len(json.dumps(bundle,allow_nan=False).encode())>950_000:raise ValueError('Comparison bundle exceeds 950 KB; split the suite')
    seen=set();rows=[]
    for case in cases:
        if not isinstance(case,dict) or set(case)!={'id','input_sha256','expected','baseline','candidate'}:raise ValueError('Both versions must share each case ID, input fingerprint and expectation')
        ident=_text(case['id'],'case id',80)
        if ident in seen:raise ValueError('Case IDs must be unique')
        seen.add(ident)
        if not isinstance(case['input_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',case['input_sha256']):raise ValueError('Supply a SHA-256 input fingerprint for each paired case')
        expected=_expected(case['expected'])
        rows.append({'id':ident,'input_sha256':case['input_sha256'],'expected':copy.deepcopy(expected),
                     'baseline':_result(case['baseline'],agent,a,cfg,expected),'candidate':_result(case['candidate'],agent,b,cfg,expected)})
    baseline=_metrics(rows,'baseline');candidate=_metrics(rows,'candidate')
    def delta(key):return candidate[key]-baseline[key] if candidate[key] is not None and baseline[key] is not None else None
    changes={k:delta(k) for k in ('task_success_rate','policy_violations','contract_passes','total_cost_usd','mean_latency_ms','execution_errors')}
    if baseline['evaluated_traces']!=len(rows) or candidate['evaluated_traces']!=len(rows):changes['policy_violations']=None
    comparable_contracts=all(r['baseline']['execution_evidence_reported'] and r['candidate']['execution_evidence_reported'] and r['baseline']['step_checks']['contract_sha256']==r['candidate']['step_checks']['contract_sha256'] and r['baseline']['step_checks']['initial_state_sha256']==r['candidate']['step_checks']['initial_state_sha256'] for r in rows)
    changes['valid_run_rate']=candidate['step_checks']['valid_run_rate']-baseline['step_checks']['valid_run_rate'] if comparable_contracts and candidate['step_checks']['valid_run_rate'] is not None and baseline['step_checks']['valid_run_rate'] is not None else None
    failures=[r for r in rows if r['candidate']['task_success'] is False or r['candidate']['error_type'] or not r['candidate']['contract_passed'] or r['candidate']['assessment']=='violation' or r['candidate']['step_checks']['all_calls_valid'] is False]
    proposals=[]
    def propose(kind,title,reason,evidence,change):
        proposals.append({'id':'PROPOSAL-'+str(len(proposals)+1),'type':kind,'title':title,'reason':reason,'case_ids':evidence,'proposed_change':change,'review_required':True,'applied':False,'basis':'Deterministic comparison evidence; not a trained model diagnosis'})
    code_cases={}
    for row in failures:
        for code in row['candidate']['codes']:code_cases.setdefault(code,[]).append(row['id'])
    for code,ids in sorted(code_cases.items()):
        guidance='Add an allowed case and a denied/boundary variant for '+code+'. Review the corresponding tool arguments or application behavior; do not relax the policy solely to pass.'
        if code.startswith('SEQUENCE_'):guidance='Test successful, failed and invalidated prerequisites on the same resource/version. Review execution order and business-success reporting.'
        if code=='UNKNOWN_TOOL':guidance='Review the operation mapping or add reviewed evaluator logic. Test its actual semantics before relying on enforcement.'
        propose('test','Add coverage around '+code,'Candidate traces triggered this finding.',ids,guidance)
    regressions=[r['id'] for r in rows if r['baseline']['task_success'] is True and r['candidate']['task_success'] is False]
    if regressions:propose('improvement','Investigate task-success regressions','Previously successful cases now fail the application outcome check.',regressions,'Inspect candidate prompt/tool changes and failure evidence. Reproduce with independent outcome assertions and a held-out test set before promotion.')
    errors=[r['id'] for r in rows if r['candidate']['error_type']]
    if errors:propose('test','Exercise exception and recovery paths','Candidate callbacks reported exceptions.',errors,'Add timeout, partial-effect and idempotency tests. Reconcile external state before retrying.')
    if changes['total_cost_usd'] is not None and changes['total_cost_usd']>0:propose('improvement','Review the measured cost trade-off','Complete reported candidate costs are higher for this paired suite.',[r['id'] for r in rows if r['candidate']['cost_usd']>r['baseline']['cost_usd']],'Check provider usage, redundant calls and token volume; repeat on representative inputs before concluding costs increased generally.')
    if changes['mean_latency_ms'] is not None and changes['mean_latency_ms']>max(10,baseline['mean_latency_ms']*.1):propose('test','Repeat the latency comparison','Candidate mean latency is higher in this run.',[r['id'] for r in rows if r['candidate']['latency_ms']>r['baseline']['latency_ms']],'Repeat with warm-up and controlled concurrency. One paired run is not a statistically established performance regression.')
    if any(candidate[k]<len(rows) for k in ('task_outcomes_reported','cost_cases_reported','latency_cases_reported')):propose('measurement','Complete the missing measurements','Some task outcomes, costs or latencies were not reported.',[r['id'] for r in rows if any(r['candidate'][k] is None for k in ('task_success','cost_usd','latency_ms'))],'Add application-owned success assertions, cost provenance and latency measurement. Unknown values are not zero.')
    step_failures=[r for r in rows if r['candidate']['step_checks']['first_observed_invalid_step']]
    if step_failures:propose('test','Test the first invalid tool call','An emitted call failed its declared schema, dependency or state contract.',[r['id'] for r in step_failures],'Add failure and recovery variants around the first invalid attempt. Keep the original attempt ledger; a later successful retry must not erase it.')
    if candidate['execution_evidence_cases']<len(rows) or candidate['step_checks']['unknown_runs']:
        propose('measurement','Complete tool contracts and outcome evidence','Some candidate calls lack sufficient validation evidence.',[r['id'] for r in rows if r['candidate']['step_checks']['all_calls_valid'] is None],'Register explicit tool schemas and initial state, record typed outputs and accepted transitions, and export complete attempt ledgers. Policy clearance alone is not executable proof.')
    if not proposals:propose('test','Challenge the apparent improvement','No proposal-triggering failures or increases were found in this submitted suite.',[r['id'] for r in rows],'Add held-out, adversarial and failure-path cases. Passing the submitted suite does not establish complete reliability.')
    return {'schema_version':1,'agent_id':agent,'baseline_version':a,'candidate_version':b,'suite_sha256':hashlib.sha256(json.dumps([{'id':r['id'],'input_sha256':r['input_sha256'],'expected':r['expected']} for r in rows],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'config_sha256':hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'step_contracts_comparable':comparable_contracts,'baseline':baseline,'candidate':candidate,'deltas':changes,'cases':rows,'failure_example_count':len(failures),'failure_examples':[{'id':r['id'],'baseline':r['baseline'],'candidate':r['candidate']} for r in failures[:20]],'proposals':proposals,
            'limitations':['Success assertions, input fingerprints and cost provenance are supplied by the application, not independently verified by the console.','Contract pass means expected assessment plus required codes; an expected violation can pass its contract while still being a policy violation.','A fixed policy snapshot is applied to both versions. Missing metrics remain unknown. Imported pairs may not have been run under controlled conditions.','Runner inputs are deep-copied and run in alternating order; callbacks own timeouts, side effects and credentials. No sandbox is provided.','Input copies do not isolate databases, provider sessions, files, caches or randomness. Reset fixtures and isolate external effects in callbacks.','One run per version/case is exploratory, not a causal or statistical claim. Repeat on held-out inputs.','Proposals require developer review. No policy, prompt, code or deployed agent is modified. Raw inputs and traces are not stored in this report; protect finding text and case identifiers.']}
