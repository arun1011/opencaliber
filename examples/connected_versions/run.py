"""Connected paired versions: real SQLite calls, graph spans and business assertions."""
import hashlib,json,sqlite3,sys,uuid,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from opencaliber import TrackedExecutor
from opencaliber.trajectory import Trajectory
from opencaliber.agent_engine import DEFAULT_CONFIG

def main():
    experiment='ticket-eval-'+uuid.uuid4().hex[:8]
    contracts={'database.read':{'arguments':{'records':'integer','status_filter':'string'},'required':['records','status_filter'],'outputs':{'count':'integer'}}}
    for index,topic in enumerate(['billing','login','shipping']):
        payload={'topic':topic};fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        for version in (['v1','v2'] if index%2==0 else ['v2','v1']):
            graph=Trajectory(experiment+'-'+topic+'-'+version,endpoint=os.getenv('OPENCALIBER_ENDPOINT','http://127.0.0.1:8787'),token=os.getenv('OPENCALIBER_TOKEN'))
            with sqlite3.connect(':memory:') as db:
                db.execute('CREATE TABLE tickets(id INTEGER,status TEXT,topic TEXT)')
                db.executemany('INSERT INTO tickets VALUES(?,?,?)',[(1,'resolved',topic),(2,'unresolved',topic)])
                with graph.span('Coordinate lookup','coordinator',kind='agent') as root:
                    with graph.span('Delegate lookup','coordinator',kind='handoff',parent_id=root['id']) as handoff:
                        with graph.span('Find ticket','ticket-agent',kind='agent',parent_id=handoff['id']) as worker:
                            with TrackedExecutor(agent={'id':'ticket-agent','version':version},tracking_id='ticket-agent-'+version,
                              task={'goal':'Find the unresolved '+topic+' ticket','allowed_tools':['database.read'],'allowed_resources':['tickets']},
                              config=DEFAULT_CONFIG,tool_contracts=contracts,contract_mode='enforce',
                              trajectory_id=graph.id,evaluation={'experiment_id':experiment,'case_id':topic,'input_sha256':fingerprint,'success_criterion':'unresolved-ticket-id-v1','assignment':'paired'},
                              diagnosis=True,capture_output=lambda action,rows:{'ids':[r[0] for r in rows],'statuses':[r[1] for r in rows]},
                              diagnosis_constraints=['Return unresolved tickets only'],diagnosis_verifications=[{'id':'ticket-id','action_id':'lookup','path':['ids'],'expected':[2],'source':'Independent synthetic fixture'}]) as agent:
                                status='resolved' if version=='v1' else 'unresolved'
                                with graph.span('Query tickets','ticket-agent',parent_id=worker['id'],work_key='lookup-'+topic):
                                    rows=agent.run({'id':'lookup','tool':'database.read','resource':'tickets','arguments':{'records':1,'status_filter':status}},
                                      lambda:db.execute('SELECT id,status FROM tickets WHERE topic=? AND status=? LIMIT 1',(topic,status)).fetchall(),
                                      success=lambda value:bool(value),extract_outputs=lambda value:{'count':len(value)})
                                expected=[r[0] for r in db.execute('SELECT id FROM tickets WHERE topic=? AND status=?',(topic,'unresolved'))]
                                agent.record_outcome([r[0] for r in rows]==expected,cost_usd=0,cost_source='estimated')
                            if agent.tracker.last_status!='delivered':raise RuntimeError('Run delivery incomplete; start the console and rerun')
                if graph.delivery_errors:raise RuntimeError('Trajectory delivery incomplete')
    print('Connected experiment complete:',experiment)
    print('Open Agents Dashboard, then Compare agent versions: ticket-agent-v1 versus ticket-agent-v2.')

if __name__=='__main__':main()
