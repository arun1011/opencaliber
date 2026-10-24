"""Evaluate your completed response JSON. Does not call a provider or execute tools."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from opencaliber.sdk import Client

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--provider',required=True,choices=['openai-responses','openai-chat','anthropic'])
    p.add_argument('--response',required=True,help='Completed response model_dump JSON')
    p.add_argument('--context',required=True,help='Application-owned policy, task, agent, session_id and optional workflow_id JSON')
    a=p.parse_args()
    response=json.loads(Path(a.response).read_text(encoding='utf-8'))
    context=json.loads(Path(a.context).read_text(encoding='utf-8'))
    print(json.dumps(Client(failure_mode='raise').observe_response(a.provider,response,**context),indent=2))
