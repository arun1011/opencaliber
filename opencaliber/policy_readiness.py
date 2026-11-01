"""Structural policy coverage of caller-declared scope, never security assurance."""
from .agent_engine import KNOWN_TOOLS,WRITE_TOOLS

def summarize_scope(trace,phase):
    task=trace['task'];rows={}
    for action in trace['actions']:
        tool=action['tool'];row=rows.setdefault(tool,{'tool':tool,'actions':0,'argument_fields':[],'records_missing':False,'command_missing':False,'classification_missing':False})
        row['actions']+=1;args=action.get('arguments',{})
        row['argument_fields']=sorted(set(row['argument_fields'])|set(args))
        row['records_missing']|=tool=='database.read' and 'records' not in args
        row['command_missing']|=tool=='shell.exec' and not args.get('command')
        row['classification_missing']|=tool in ('http.send','email.send') and 'data_class' not in action
    return {'agent_version':trace['agent']['version'],'workflow_id':trace['workflow_id'],'phase':phase,
            'tool_scope_declared':'allowed_tools' in task,'declared_tools':task.get('allowed_tools',[]),
            'resource_scope_declared':'allowed_resources' in task,'resource_count':len(task.get('allowed_resources',[])),
            'read_only':task.get('read_only',False),'observed_tools':list(rows.values())}

def readiness(scope,config,agent_id,cases=()):
    if not scope:return {'status':'waiting_for_scope','gaps':['Run this agent again to report its declared scope.'],'tools':[],'unobserved_tools':[],'agent_case_ids':[]}
    gaps=[];rows=[]
    if not scope['tool_scope_declared']:gaps.append('Declare task.allowed_tools in the wrapper from the authorized agent contract.')
    if not scope['resource_scope_declared']:gaps.append('Resource scope is not declared. Define task.allowed_resources or review resource restrictions for every tool.')
    observed={r['tool']:r for r in scope['observed_tools']}
    declared=set(scope['declared_tools']);tools=sorted(declared|set(observed))
    for tool in tools:
        sample=observed.get(tool);controls=['Declared task tool/resource scope']
        row_gaps=[]
        if tool not in KNOWN_TOOLS:row_gaps.append('No canonical tool semantics: map this operation to a supported tool or implement a reviewed evaluator rule.')
        if sample and scope['tool_scope_declared'] and tool not in declared:row_gaps.append('Observed action is outside the declared tool scope.')
        if scope['read_only'] and tool in WRITE_TOOLS:controls.append('Read-only task forbids this write operation')
        if tool in config['denied_tools']:controls.append('Explicitly denied by this policy')
        if tool.startswith('file.'):controls.append('File-root boundary ('+('configured roots' if config['allowed_file_roots'] else 'no roots approved')+')')
        if tool in ('http.get','http.send','email.send'):controls.append('Destination and transfer checks ('+('approved hosts configured' if config['allowed_hosts'] else 'no hosts approved')+')')
        if tool=='database.read':
            controls.append('Per-resource record budget')
            if sample and sample['records_missing']:row_gaps.append('Some database reads omit arguments.records, so actual read volume is not established.')
        if tool=='shell.exec':
            controls.append('Command patterns and mandatory shell review')
            if sample and sample['command_missing']:row_gaps.append('Some shell operations omit arguments.command.')
        if sample and sample['classification_missing']:row_gaps.append('Outbound actions omit data_class; sensitivity-dependent checks lack declared classification.')
        policy=config['tool_policies'].get(tool,{})
        fields=(['resource'] if 'resource' in policy else [])+['arguments.'+v for v in policy.get('arguments',{})]
        if fields:controls.append('Explicit field constraints: '+', '.join(fields))
        if sample:
            unconstrained=set(sample['argument_fields'])-{'records','command','destination'}-set(policy.get('arguments',{}))
            if unconstrained:row_gaps.append('No explicit argument constraints for: '+', '.join(sorted(unconstrained))+'. Review whether these fields need limits or allowlists.')
        sequences=[r['id'] for r in config['sequence_rules'] if r['tool']==tool]
        if sequences:controls.append('Sequence prerequisites: '+', '.join(sequences))
        elif tool in ('file.delete','database.delete') and tool not in config['denied_tools'] and not scope['read_only']:row_gaps.append('No backup prerequisite configured for this destructive tool; decide whether your workflow requires one.')
        matching=[c['id'] for c in cases if c.get('source')=='workspace' and c['trace'].get('agent',{}).get('id')==agent_id and any(a['tool']==tool for a in c['trace']['actions'])]
        if not matching:row_gaps.append('No workspace contract case is tagged with this agent ID and tool.')
        rows.append({'tool':tool,'supported':tool in KNOWN_TOOLS,'declared':tool in declared,'observed':sample is not None,'controls':controls,'gaps':row_gaps,'agent_case_ids':matching})
        gaps.extend(tool+': '+g for g in row_gaps)
    unobserved=sorted(declared-set(observed))
    if unobserved:gaps.append('Declared tools not exercised in the latest workflow: '+', '.join(unobserved)+'. Run representative and failure-path tests.')
    agent_cases=[c['id'] for c in cases if c.get('source')=='workspace' and c['trace'].get('agent',{}).get('id')==agent_id]
    if not agent_cases:gaps.append('No workspace contract cases identify this agent. Add tests for allowed, denied and prerequisite-failure paths.')
    return {'status':'gaps_to_review' if gaps else 'no_structural_gaps_found','gaps':gaps,'tools':rows,'unobserved_tools':unobserved,'agent_case_ids':agent_cases,
            'limitations':['Scope is supplied by the application, not inferred or verified authorization.','Only the latest online workflow metadata is inspected. Unwrapped code and unobserved branches are not covered.','Matching tests indicate supplied examples, not passing tests, semantic adequacy or a safety guarantee.']}
