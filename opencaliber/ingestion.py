"""Offline MCP execution-log and Databricks audit-export adapters. No remote access."""
import copy
from datetime import datetime
from .adapters import validate_policy,select
from .agent_engine import validate_trace

def _action(call_id,name,args,policy):
    if not isinstance(args,dict) or not isinstance(name,str) or not name or len(name)>300:raise ValueError('Invalid tool event')
    spec=policy['tools'].get(name)
    if spec is None:return {'id':call_id,'tool':'unmapped.tool','source_tool':name,'resource':'[unmapped-resource]'}
    return {'id':call_id,'tool':spec['tool'],'source_tool':name,'resource':spec['resource'] if 'resource' in spec else select(args,spec['resource_from']),
      'arguments':{key:select(args,path) for key,path in spec.get('arguments',{}).items()},'data_class':spec['data_class']}

def _trace(actions,agent,task,workflow_id,name):
    trace={'name':name,'agent':copy.deepcopy(agent),'task':copy.deepcopy(task),'workflow_id':workflow_id,'actions':actions}
    validate_trace(trace);return trace

def normalize_mcp(events,*,policy,agent,task,workflow_id,success_selectors=None):
    """Events are application-recorded completed tools/call results in execution order."""
    policy=validate_policy(policy);selectors={} if success_selectors is None else success_selectors
    if not isinstance(selectors,dict) or any(k not in policy['tools'] or not isinstance(v,str) or not v or len(v)>300 for k,v in selectors.items()):raise ValueError('Invalid application success selectors')
    if not isinstance(events,list) or not 1<=len(events)<=200:raise ValueError('Provide 1–200 MCP execution events')
    actions=[]
    for event in events:
        if not isinstance(event,dict) or set(event)-{'id','name','arguments','result','resource_version'} or not {'id','name','arguments','result'}<=set(event):raise ValueError('MCP event requires id, name, arguments and result')
        result=event['result']
        if not isinstance(result,dict) or 'isError' in result and type(result['isError']) is not bool:raise ValueError('Invalid MCP tool result')
        action=_action(event['id'],event['name'],event['arguments'],policy)
        status='failed' if result.get('isError') is True else 'unknown'
        if status!='failed' and event['name'] in selectors:
            try:success=select(result,selectors[event['name']])
            except ValueError:success=None
            if type(success) is bool:status='succeeded' if success else 'failed'
        action['outcome']={'status':status,'source':'application'}
        if 'resource_version' in event:action['resource_version']=event['resource_version']
        actions.append(action)
    return _trace(actions,agent,task,workflow_id,'MCP execution audit')

def normalize_databricks(rows,*,policy,agent,task,workflow_id):
    """Map selected exported columns; audit HTTP 200 never proves business success."""
    policy=validate_policy(policy)
    if not isinstance(rows,list) or not 1<=len(rows)<=200:raise ValueError('Provide 1–200 exported audit rows')
    actions=[];previous=None
    for row in rows:
        if not isinstance(row,dict) or not {'request_id','event_time','service_name','action_name','request_params','response'}<=set(row):raise ValueError('Missing required Databricks audit columns')
        if not isinstance(row['event_time'],str):raise ValueError('event_time must be ISO datetime')
        stamp=datetime.fromisoformat(row['event_time'].replace('Z','+00:00'))
        if stamp.tzinfo is None or previous is not None and stamp<=previous:raise ValueError('Export must have strictly increasing timezone-aware event_time; do not infer ordering for ties')
        previous=stamp
        if any(not isinstance(row[k],str) or not row[k] for k in ('service_name','action_name')):raise ValueError('Invalid audit operation')
        name=row['service_name']+'.'+row['action_name'];params=row['request_params'];response=row['response']
        if not isinstance(params,dict) or not isinstance(response,dict):raise ValueError('Decode request_params and response to objects before importing')
        action=_action(row['request_id'],name,params,policy)
        code=response.get('status_code');failed=type(code) is int and code>=400
        action['outcome']={'status':'failed' if failed else 'unknown','source':'application'}
        actions.append(action)
    return _trace(actions,agent,task,workflow_id,'Databricks audit export')
