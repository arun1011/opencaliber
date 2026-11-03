"""Real synthetic lookup and file write, with a rejected early call and recovery."""
import json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from opencaliber import TrackedExecutor
from opencaliber.agent_engine import DEFAULT_CONFIG
from opencaliber.execution import ActionBlocked
from opencaliber.comparison import run_versions,compare

CONTRACTS={
 'database.read':{'arguments':{'records':'integer'},'required':['records'],'outputs':{'record_id':'string'},'effects':{'record_loaded':True}},
 'file.write':{'arguments':{'record_id':'string'},'required':['record_id'],'preconditions':{'record_loaded':True}}
}

def version(payload,release):
    folder=Path(payload['output']).resolve()/release;folder.mkdir(parents=True,exist_ok=True);target=folder/'report.txt'
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE tickets (id TEXT, topic TEXT)');db.execute('INSERT INTO tickets VALUES (?,?)',('T-1','Synthetic invoice'))
    try:
        with TrackedExecutor(agent={'id':'lookup-report','version':release},tracking_id='lookup-report-'+release,
          task={'goal':'Look up a ticket then write its report','allowed_tools':['database.read','file.write'],'allowed_resources':['tickets','/workspace/reports/report.txt']},
          config={**DEFAULT_CONFIG,'allowed_file_roots':['/workspace/reports']},tool_contracts=CONTRACTS,initial_state={'record_loaded':False},contract_mode='enforce') as agent:
            if release=='v1':
                try:
                    agent.run({'id':'early-write','tool':'file.write','resource':'/workspace/reports/report.txt','arguments':{'record_id':'guessed'}},
                              lambda:target.write_text('This callback must never run'),success=lambda _:True,
                              references={'record_id':{'attempt_id':'attempt-2','output':'record_id'}})
                except ActionBlocked:pass  # Explicit recovery; the rejected call stays in the ledger.
            row=agent.run({'id':'lookup','tool':'database.read','resource':'tickets','arguments':{'records':1}},
                          lambda:db.execute('SELECT id,topic FROM tickets LIMIT 1').fetchone(),success=lambda value:value is not None,
                          extract_outputs=lambda value:{'record_id':value[0]},state_updates=lambda value:{'record_loaded':True})
            producer=agent.attempts[-1]['attempt_id']
            agent.run({'id':'write','tool':'file.write','resource':'/workspace/reports/report.txt','arguments':{'record_id':row[0]}},
                      lambda:target.write_text(row[1],encoding='utf-8'),success=lambda value:value>0,
                      references={'record_id':{'attempt_id':producer,'output':'record_id'}})
        return {'trace':agent.trace,'execution_evidence':agent.execution_evidence(),'task_success':target.read_text(encoding='utf-8')=='Synthetic invoice','cost_usd':0,'cost_source':'estimated'}
    finally:db.close()

if __name__=='__main__':
    out=Path(sys.argv[1]) if len(sys.argv)>1 else Path('outputs/step-checks');out.mkdir(parents=True,exist_ok=True)
    cases=[{'id':'lookup-before-write','input':{'output':str(out)},'expected':{'assessment':'clear','required_codes':[]}}]
    bundle=run_versions(cases,lambda p:version(p,'v1'),lambda p:version(p,'v2'),agent_id='lookup-report',baseline_version='v1',candidate_version='v2',config={**DEFAULT_CONFIG,'allowed_file_roots':['/workspace/reports']})
    (out/'comparison-input.json').write_text(json.dumps(bundle,indent=2),encoding='utf-8')
    (out/'comparison-report.json').write_text(json.dumps(compare(bundle),indent=2),encoding='utf-8')
    print('Import',out/'comparison-input.json','into Compare agent versions.')
