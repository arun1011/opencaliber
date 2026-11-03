"""Illustrative in-memory agents; no actual database, filesystem or provider calls."""
from .agent_engine import DEFAULT_CONFIG
from .comparison import run_versions
import copy

CASES=[{'id':'normal-read','input':{'records':10,'path':'/workspace/reports/report.txt','quality_case':False},'expected':{'assessment':'clear','required_codes':[]}},
       {'id':'record-boundary','input':{'records':1500,'path':'/workspace/reports/report.txt','quality_case':False},'expected':{'assessment':'clear','required_codes':[]}},
       {'id':'export-boundary','input':{'records':10,'path':'/private/report.txt','quality_case':False},'expected':{'assessment':'clear','required_codes':[]}},
       {'id':'summary-quality','input':{'records':10,'path':'/workspace/reports/report.txt','quality_case':True},'expected':{'assessment':'clear','required_codes':[]}}]

def _agent(payload,version):
    records=min(payload['records'],100) if version=='v2' else payload['records']
    path='/workspace/reports/report.txt' if version=='v2' else payload['path']
    summary='' if version=='v2' and payload['quality_case'] else 'Synthetic report summary'
    success=records<=1000 and path.startswith('/workspace/reports/') and bool(summary)
    actions=[{'id':'read','tool':'database.read','resource':'tickets','arguments':{'records':records}},
             {'id':'write','tool':'file.write','resource':path,'arguments':{'record_id':'T-1'}}]
    contracts={'database.read':{'arguments':{'records':'integer'},'required':['records'],'outputs':{'record_id':'string'},'effects':{'record_loaded':True}},
               'file.write':{'arguments':{'record_id':'string'},'required':['record_id'],'preconditions':{'record_loaded':True}}}
    attempts=[]
    if version=='v1' and payload['quality_case'] is False and payload['records']==10 and payload['path'].startswith('/workspace'):
        attempts.append({'attempt_id':'early-write','action':{'id':'early-write','tool':'file.write','resource':path,'arguments':{'record_id':'guessed'}},'execution':'not_dispatched','disposition':'contract_blocked','transition_accepted':None,'outputs':{},'state_updates':{},'references':{'record_id':{'attempt_id':'lookup','output':'record_id'}}})
    attempts.append({'attempt_id':'lookup','action':copy.deepcopy(actions[0]),'execution':'succeeded','disposition':'executed','transition_accepted':True,'outputs':{'record_id':'T-1'},'state_updates':{'record_loaded':True},'references':{}})
    attempts.append({'attempt_id':'write','action':copy.deepcopy(actions[1]),'execution':'succeeded','disposition':'executed','transition_accepted':True,'outputs':{},'state_updates':{},'references':{'record_id':{'attempt_id':'lookup','output':'record_id'}}})
    return {'trace':{'task':{'goal':'Read one bounded page and produce an approved nonempty report','allowed_tools':['database.read','file.write'],'allowed_resources':['tickets','/workspace/reports/report.txt']},'actions':actions},
            'execution_evidence':{'contracts':contracts,'initial_state':{'record_loaded':False},'attempts':attempts,'complete':True},
            'task_success':success,'cost_usd':0.0,'cost_source':'estimated'}

def demo_bundle():
    return run_versions(CASES,lambda value:_agent(value,'v1'),lambda value:_agent(value,'v2'),agent_id='report-agent-demo',baseline_version='v1',candidate_version='v2',config={**DEFAULT_CONFIG,'allowed_file_roots':['/workspace/reports']})
