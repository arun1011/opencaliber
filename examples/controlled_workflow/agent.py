"""Synthetic SQLite -> report -> verified backup -> optional guarded deletion."""
import argparse,hashlib,json,shutil,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from opencaliber import TrackedExecutor
from opencaliber.execution import ActionBlocked,EvaluationFailed
ROOT=Path(__file__).resolve().parent

def run(output,delete=False,skip_backup=False,fail_backup=False):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    report=output/'summary.txt';backup=output/'summary.bak'
    config=json.loads((ROOT/'policy.json').read_text(encoding='utf-8'))
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE tickets (id INTEGER, subject TEXT)')
    db.executemany('INSERT INTO tickets VALUES(?,?)',[(1,'invoice export failed'),(2,'invoice receipt request'),(3,'password reset')])
    try:
        with TrackedExecutor(agent={'id':'controlled-report','version':'1.0'},tracking_id='controlled-report-dev',
             task={'goal':'Read synthetic tickets and maintain an approved report','allowed_tools':['database.read','file.write','file.backup','file.delete'],
                   'allowed_resources':['tickets','/workspace/reports/summary.txt','/workspace/reports/summary.bak'],
                   'approved_action_ids':['delete-report'] if delete else []},config=config) as agent:
            print('Central policy assignment:',json.dumps(agent.policy_status))
            rows=agent.run({'id':'read-tickets','tool':'database.read','resource':'tickets','arguments':{'records':100}},
                          lambda:db.execute('SELECT id,subject FROM tickets WHERE subject LIKE ? LIMIT ? ',('%invoice%',100)).fetchall(),success=lambda value:isinstance(value,list))
            # In-memory formatting is not an external tool operation. No model call.
            text='Synthetic invoice tickets: '+str(len(rows))+'\n'
            version=hashlib.sha256(text.encode()).hexdigest()
            written=agent.run({'id':'write-report','tool':'file.write','resource':'/workspace/reports/summary.txt','resource_version':version},
                             lambda:report.write_text(text,encoding='utf-8',newline='\n'),success=lambda n:n==len(text))
            if written!=len(text):raise RuntimeError('Report write did not complete')
            if not skip_backup:
                def copy_report():
                    if fail_backup:raise OSError('Synthetic backup failure')
                    shutil.copy2(report,backup);return backup
                copied=agent.run({'id':'backup-report','tool':'file.backup','resource':'/workspace/reports/summary.txt','resource_version':version,
                                  'arguments':{'backup_path':'/workspace/reports/summary.bak'}},copy_report,
                                 success=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()==version)
                if hashlib.sha256(copied.read_bytes()).hexdigest()!=version:raise RuntimeError('Backup verification failed')
            if delete:
                agent.run({'id':'delete-report','tool':'file.delete','resource':'/workspace/reports/summary.txt','resource_version':version},
                          lambda:report.unlink(),success=lambda _:not report.exists())
            return {'rows':len(rows),'report_exists':report.exists(),'backup_exists':backup.exists(),'workflow_id':agent.trace['workflow_id']}
    finally:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=Path('outputs/controlled-workflow'))
    p.add_argument('--delete-after-backup',action='store_true');p.add_argument('--skip-backup',action='store_true');p.add_argument('--fail-backup',action='store_true');a=p.parse_args()
    try:print(json.dumps(run(a.output,a.delete_after_backup,a.skip_backup,a.fail_backup),indent=2))
    except ActionBlocked as exc:print('Blocked before execution:',exc,file=sys.stderr);sys.exit(2)
    except EvaluationFailed as exc:print('Evaluation unavailable; callback not dispatched:',exc,file=sys.stderr);sys.exit(3)
    except Exception as exc:print('Workflow failed:',type(exc).__name__,file=sys.stderr);sys.exit(4)
