"""Working dry-run integration; callbacks touch no filesystem or provider."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from opencaliber.execution import GuardedExecutor,ActionBlocked
trace=json.loads((ROOT/'examples/sequence_trace.json').read_text())
cfg=json.loads((ROOT/'examples/sequence_config.json').read_text())
executor=GuardedExecutor(agent=trace['agent'],task=trace['task'],workflow_id=trace['workflow_id'],config=cfg,mode='enforce')
backup,delete=trace['actions'];backup.pop('outcome')
try:
    executor.run(delete,lambda:print('This must never run'),success=lambda value:True)
except ActionBlocked:print('Blocked delete before backup; no callback dispatched.')
executor.run(backup,lambda:{'backup_verified':True},success=lambda value:value.get('backup_verified') is True)
executor.run(delete,lambda:{'deleted':True},success=lambda value:value.get('deleted') is True)
print('Allowed dry-run delete after the verified backup callback. No real files changed.')
