"""Connected monitoring, comparable cohorts and workspace-wide configuration."""
import collections,hashlib,json
from .agent_engine import validate_config,KNOWN_TOOLS
from .run_metrics import validate

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS run_metrics (run_id TEXT PRIMARY KEY, body TEXT NOT NULL)')
    c.execute("CREATE TABLE IF NOT EXISTS platform_settings (id INTEGER PRIMARY KEY, mode TEXT NOT NULL)")
    c.execute("INSERT OR IGNORE INTO platform_settings VALUES(1,'observe')")

def record(c,rid,body):
    initialize(c)
    if 'metrics' in body:
        validate(body['metrics'])
        c.execute('INSERT INTO run_metrics VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET body=excluded.body',(rid,json.dumps(body['metrics'])))

def settings(connect):
    with connect() as c:
        initialize(c)
        return {'mode':c.execute('SELECT mode FROM platform_settings WHERE id=1').fetchone()[0]}

def save_settings(body,connect):
    if not isinstance(body,dict) or set(body)!={'config','mode','replace_overrides'} or body['mode'] not in ('observe','enforce') or type(body['replace_overrides']) is not bool:raise ValueError('Provide config, mode and replace_overrides')
    config=validate_config(body['config'])
    with connect() as c:
        initialize(c);c.execute('BEGIN IMMEDIATE') if not c.in_transaction else None
        c.execute('UPDATE settings SET config=? WHERE id=1',(json.dumps(config),))
        c.execute('UPDATE platform_settings SET mode=? WHERE id=1',(body['mode'],))
        if body['replace_overrides']:c.execute('UPDATE tracking_agents SET policy=NULL,mode=?',(body['mode'],))
        else:c.execute('UPDATE tracking_agents SET mode=? WHERE policy IS NULL',(body['mode'],))
    return {'saved':True}

def collected(connect):
    from .connected_diagnosis import initialize as diagnosis_init
    with connect() as c:
        initialize(c);diagnosis_init(c)
        rows=c.execute('SELECT r.*,m.body AS metrics,d.bundle,d.report AS diagnosis FROM runs r LEFT JOIN run_metrics m ON m.run_id=r.id LEFT JOIN run_diagnosis d ON d.run_id=r.id ORDER BY r.created_at DESC LIMIT 1000').fetchall()
    data=[]
    for row in rows:
        result=json.loads(row['result']);tracking=result.get('tracking')
        if not tracking:continue
        trace=json.loads(row['trace']);metric=json.loads(row['metrics']) if row['metrics'] else {}
        bundle=json.loads(row['bundle']) if row['bundle'] else None
        diagnostic=json.loads(row['diagnosis']) if row['diagnosis'] else None
        findings=[{'code':f['code'],'action_id':a['action_id'],'reason':f['message'],'recommendation':f.get('remediation',{}).get('change','Review the tool call and its permissions.')} for a in result['actions'] for f in a['findings']]
        for attempt in (result.get('reliability') or {}).get('attempts',[]):
            if attempt.get('disposition') in ('policy_blocked','contract_blocked'):
                findings.append({'code':'BLOCKED_ATTEMPT','action_id':attempt['action_id'],'reason':'An attempted action was blocked before dispatch, including attempts followed by recovery.','recommendation':'Inspect run activity for the original policy or contract rejection.'})
        if diagnostic:findings.extend({'code':f['code'],'action_id':', '.join(f.get('action_ids',[])),'reason':f['reason'],'recommendation':f.get('suggested_fix','Review the expected output and correct the action or application logic.')} for f in diagnostic['findings'] if f['layer']!='policy')
        data.append({'id':row['id'],'created_at':row['created_at'],'agent':trace.get('agent'),
          'workflow_id':trace.get('workflow_id'),'tracking_id':tracking['tracking_id'],'phase':tracking['phase'],'connection':tracking.get('connection','wrapper'),'mode':tracking['mode'],
          'assessment':result['assessment'],'findings':findings,'metrics':metric,'reliability':result.get('reliability'),
          'custom_checks':result.get('custom_checks',[]),'custom_checks_sha256':result.get('custom_checks_sha256'),'policy_sha256':result.get('config_sha256'),'context_available':bool(bundle),
          'captured_outputs':len(bundle['outputs']) if bundle else 0,'action_count':len(trace['actions']),
          'diagnosis':diagnostic['assessment'] if diagnostic else 'not_available'})
    return data

def dashboard(connect,config,cases):
    from .tracking_store import agents
    from .trajectory import report
    registered=agents(connect,config,cases);runs=collected(connect);graphs={}
    for tid in {r['metrics'].get('trajectory_id') for r in runs}-{None}:
        graphs[tid]=report(tid,connect)
        graphs[tid]['graph_only_agents']=sorted({n['agent_id'] for n in graphs[tid]['nodes']}-{a['agent_id'] for a in registered})
    for a in registered:
        history=[r for r in runs if r['tracking_id']==a['tracking_id']];latest=history[0] if history else None
        gaps=list(a.get('readiness',{}).get('gaps',[]))
        if a['policy']:gaps.append('Legacy agent override is active; platform defaults do not replace it until explicitly reset.')
        if latest:
            if not latest['context_available']:gaps.append('Objective/output diagnosis context is not captured. Enable diagnosis and select safe output fields.')
            elif latest['captured_outputs']<latest['action_count']:gaps.append('Some tool outputs are missing; output-aware diagnosis is incomplete.')
            reliability=latest.get('reliability')
            if not reliability or reliability.get('unknown_attempts',0):gaps.append('Tool-step evidence is missing or unknown; supply per-tool contracts and outcome evidence.')
            if latest['metrics'].get('task_success') is None:gaps.append('Task-success assertion is missing. Workflow completion alone is not task success.')
            if not latest['metrics'].get('evaluation'):gaps.append('Experiment/case fingerprints are missing; version comparisons are observational only.')
            tid=latest['metrics'].get('trajectory_id')
            if tid and not graphs[tid]['nodes']:gaps.append('A trajectory ID was supplied, but no graph spans were received.')
            if not tid:gaps.append('No trajectory link. Required for reconstructing multi-agent jobs; optional for a single-agent run.')
        else:gaps.append('No run in the latest 1,000 saved records. Run the agent to refresh its evidence.')
        from .check_gaps import enrich
        a['runs']=history;a['gaps']=gaps
        enrich(a,latest,connect)
    return {'agents':registered,'runs':runs,'graphs':graphs,'supported_tools':sorted(KNOWN_TOOLS),
            'settings':settings(connect),'config':config,'limits':'Shows all registered agents and the latest 1,000 saved records. Gaps are structural signals, not a completeness guarantee.'}

def cohort_key(r):return json.dumps([r['tracking_id'],r['agent']['version']],separators=(',',':'))

def compare(body,connect):
    if not isinstance(body,dict) or set(body)!={'baseline','candidate'} or not all(isinstance(body[k],str) for k in body) or body['baseline']==body['candidate']:raise ValueError('Choose two distinct tracked agent/version cohorts')
    from .trajectory import report
    runs=collected(connect)
    cohorts={k:[r for r in runs if cohort_key(r)==body[k] and r['phase'] in ('completed','workflow_failed')] for k in ('baseline','candidate')}
    if not all(cohorts.values()):raise ValueError('Each cohort needs completed connected runs')
    def match(r):
        e=r['metrics'].get('evaluation');rel=r.get('reliability') or {}
        if not e or not r['policy_sha256']:return None
        return (e['experiment_id'],e['case_id'],e['input_sha256'],e['success_criterion'],r['policy_sha256'],r.get('custom_checks_sha256'),rel.get('contract_sha256'),rel.get('initial_state_sha256'))
    indices={k:{} for k in cohorts}
    for k,rows in cohorts.items():
        for r in rows:
            key=match(r)
            if key:indices[k].setdefault(key,r)  # latest repeated case; disclosed below
    common=set(indices['baseline'])&set(indices['candidate'])
    pairs=[(indices['baseline'][key],indices['candidate'][key]) for key in sorted(common)]
    graph_cache={}
    def summarize(rows):
        known=[r['metrics']['task_success'] for r in rows if r['metrics'].get('task_success') is not None]
        costs=[r['metrics']['cost_usd'] for r in rows if r['metrics'].get('cost_usd') is not None]
        latency=[r['metrics']['latency_ms'] for r in rows if r['metrics'].get('latency_ms') is not None]
        rel=[r['reliability']['all_calls_valid'] for r in rows if r.get('reliability') and r['reliability'].get('all_calls_valid') is not None]
        graph_ids={r['metrics'].get('trajectory_id') for r in rows}-{None};counts=collections.Counter()
        for tid in graph_ids:
            if tid not in graph_cache:graph_cache[tid]=report(tid,connect)
            counts.update(f['code'] for f in graph_cache[tid]['findings'])
        return {'runs':len(rows),'success_reported':len(known),'success_rate':sum(known)/len(known) if known else None,
                'policy_violations':sum(r['assessment']=='violation' for r in rows),'diagnosis_failures':sum(r['diagnosis']=='failure_detected' for r in rows),
                'tool_validity_reported':len(rel),'valid_run_rate':sum(rel)/len(rel) if rel else None,
                'cost_reported':len(costs),'mean_cost':sum(costs)/len(costs) if costs else None,'cost_sources':sorted({r['metrics'].get('cost_source') for r in rows if r['metrics'].get('cost_usd') is not None}),
                'latency_reported':len(latency),'mean_latency_ms':sum(latency)/len(latency) if latency else None,
                'linked_trajectories':len(graph_ids),'trajectory_findings':dict(counts)}
    a=summarize([p[0] for p in pairs]);b=summarize([p[1] for p in pairs]);delta=None
    if pairs and a['success_reported']==b['success_reported']==len(pairs):delta=b['success_rate']-a['success_rate']
    designs=sorted({r['metrics']['evaluation']['assignment'] for pair in pairs for r in pair})
    note='No matched cases. Compare descriptive metrics only; collect common case IDs, input fingerprints, success criteria and policy snapshots.'
    if pairs:note=('Candidate completed more matched cases.' if delta is not None and delta>0 else 'Baseline completed more matched cases.' if delta is not None and delta<0 else 'No task-success preference is established on the matched cases.')+' Review policy, output and trajectory failures before promotion.'
    return {'baseline':summarize(cohorts['baseline']),'candidate':summarize(cohorts['candidate']),
            'matched':{'count':len(pairs),'baseline':a,'candidate':b,'success_rate_delta':delta,'assignment_labels':designs},
            'recommendation':note,'failures':[{'id':r['id'],'agent':r['agent'],'phase':r['phase'],'findings':r['findings']} for rows in cohorts.values() for r in rows if r['findings'] or r['metrics'].get('task_success') is False][:30],
            'limits':['Observed outcomes, not causal or statistical significance. Randomized assignment labels are application-reported, not independently verified.',
                      'Matching requires the same experiment, case, input hash, success criterion, policy, custom checks, tool contracts and initial state. Only the latest run per repeated case in each cohort is paired.',
                      'Rates use reported denominators. Missing success, cost, latency or trajectory evidence remains unknown. Costs may mix estimates and provider values; inspect provenance.',
                      'Trajectory findings describe the linked whole job, not attribution of blame to one agent. Different unreported environments may confound comparisons.']}

def contract_from_run(body,connect,config,cases,timestamp):
    from .contract_cases import preview,save
    if not isinstance(body,dict) or set(body)!={'run_id','id','name','assessment','required_codes','save'} or type(body['save']) is not bool:raise ValueError('Invalid contract request')
    with connect() as c:
        row=c.execute('SELECT bundle FROM run_diagnosis WHERE run_id=?',(body['run_id'],)).fetchone()
    if not row or not row['bundle']:raise ValueError('This run lacks original context. Enable diagnosis capture and run the agent again; redacted traces cannot become reliable regression cases.')
    bundle=json.loads(row['bundle']);case={'id':body['id'],'name':body['name'],'trace':bundle['trace'],'expected':{'assessment':body['assessment'],'required_codes':body['required_codes']},'config_patch':{}}
    if body['save']:return save(case,connect,{c['id'] for c in cases if c.get('source')!='workspace'},config,timestamp)
    return preview(case,config)
