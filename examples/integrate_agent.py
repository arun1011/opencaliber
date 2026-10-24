"""Evaluate a proposed action; no agent tool is executed by this example."""
import json
import sys
from pathlib import Path

# For another project, add the extracted package directory to PYTHONPATH.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from opencaliber import evaluate_trace

trace=json.loads((Path(__file__).parent/'agent_trace.json').read_text(encoding='utf-8'))
result=evaluate_trace(trace)
print(json.dumps(result,indent=2))
if result['assessment']!='clear':
    print('Application should route this action for review; no tool executed.',file=sys.stderr)
# Your application owns execution and authorization, including what to do with clear.
