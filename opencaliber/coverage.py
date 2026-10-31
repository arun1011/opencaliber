"""Declared evaluation coverage, never a security effectiveness percentage."""
from .agent_engine import KNOWN_TOOLS,evaluate_trace,validate_config,DEFAULT_CONFIG

def coverage_report(trace,config=None,inventory=None):
    cfg=validate_config(DEFAULT_CONFIG if config is None else config)
    result=evaluate_trace(trace,cfg)
    if inventory is not None and (not isinstance(inventory,list) or len(inventory)>1000 or any(not isinstance(t,str) or not t or len(t)>300 for t in inventory)):raise ValueError('Inventory must contain at most 1000 tool names')
    mapped=sorted({a.get('source_tool',a['tool']) for a in trace['actions'] if a['tool'] in KNOWN_TOOLS})
    unmapped=sorted({a.get('source_tool',a['tool']) for a in trace['actions'] if a['tool'] not in KNOWN_TOOLS})
    incomplete=[a['id'] for a in trace['actions'] if a.get('outcome',{}).get('status') not in ('succeeded','failed') or a.get('outcome',{}).get('source')!='application']
    return {'engine_version':result['engine_version'],'action_count':len(trace['actions']),'mapped_tools':mapped,'unmapped_tools':unmapped,
      'inventory_not_observed':sorted(set(inventory or [])-set(mapped)-set(unmapped)),
      'missing_application_outcome_ids':incomplete,'resource_scope_declared':'allowed_resources' in trace['task'],
      'tool_scope_declared':'allowed_tools' in trace['task'],'enabled_checks':{'require_scope':cfg['require_scope'],'untrusted_text':cfg['flag_untrusted_instructions'],'sequence_rule_ids':[r['id'] for r in cfg['sequence_rules']],'tool_policy_fields':{tool: (['resource'] if 'resource' in policy else [])+['arguments.'+key for key in policy.get('arguments',{})] for tool,policy in cfg['tool_policies'].items()},'denied_tools':cfg['denied_tools'],'allowed_hosts':cfg['allowed_hosts'],'allowed_file_roots':cfg['allowed_file_roots'],'max_records':cfg['max_records'],'max_calls':cfg['max_calls']},
      'resources':[{'resource':resource,'tools':sorted({a['tool'] for a in trace['actions'] if a['resource']==resource}),'within_declared_scope':resource in trace['task'].get('allowed_resources',[])} for resource in sorted({a['resource'] for a in trace['actions']})],
      'assessment':result['assessment'],'limitations':['Coverage describes only supplied actions and configured checks, not all possible behavior.','Tool mappings, outcomes, scope and sensitivity labels are caller-supplied.','No live cloud IAM synchronization, MCP datasource inspection, vector quality evaluation, row-level authorization or automatic containment.','Inventory tools not observed have no behavioral evaluation in this trace.']}
