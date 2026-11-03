"""Allowed database read, wrong objective filter, independently recomputed result."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from opencaliber.diagnosis import diagnose,example
from opencaliber import TrackedExecutor

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--semantic',action='store_true');args=parser.parse_args()
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE tickets(id INTEGER,status TEXT,topic TEXT)')
        db.executemany('INSERT INTO tickets VALUES(?,?,?)',[(1,'resolved','billing'),(2,'resolved','billing'),(3,'unresolved','billing'),(4,'unresolved','billing')])
        setup=example()
        with TrackedExecutor(agent={'id':'connected-support-summary','version':'1'},
            tracking_id='connected-support-summary',task=setup['trace']['task'],diagnosis=True,
            diagnosis_constraints=setup['constraints'],diagnosis_verifications=setup['verifications'],
            capture_output=lambda action,rows:{'statuses':[r[1] for r in rows],'ids':[r[0] for r in rows]}) as agent:
            observed=agent.run(setup['trace']['actions'][0],
                lambda:db.execute('SELECT id,status FROM tickets WHERE status=? AND topic=?',('resolved','billing')).fetchall(),
                success=lambda rows:bool(rows))
        print('Connected run delivery:',agent.tracker.last_status)
        bundle=example();bundle['outputs']['read-tickets']={'statuses':[r[1] for r in observed],'ids':[r[0] for r in observed]}
        def verify(context):
            # Separate developer-owned query encodes the objective, not the agent's chosen filter.
            expected=[r[0] for r in db.execute('SELECT id FROM tickets WHERE status=? AND topic=?',('unresolved','billing'))]
            return context['outputs']['read-tickets']['ids']==expected
        report=diagnose(bundle,use_semantic=args.semantic,verifiers={'independent-ticket-query':verify})
        out=Path('outputs/context-diagnosis');out.mkdir(parents=True,exist_ok=True)
        (out/'evidence.json').write_text(json.dumps(bundle,indent=2),encoding='utf-8')
        (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
if __name__=='__main__':main()
