import argparse
import json
import sys
from pathlib import Path
from .agent_engine import DEFAULT_CONFIG,evaluate_trace
from .agent_server import benchmark
from .regression import run_suite

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Local, advisory agent-action evaluation')
    p.add_argument('command',choices=['evaluate','benchmark','regression']);p.add_argument('--input');p.add_argument('--config');p.add_argument('--output');p.add_argument('--fail-on',choices=['none','violation','review'],default='none');a=p.parse_args()
    cfg=json.loads(Path(a.config).read_text(encoding='utf-8')) if a.config else DEFAULT_CONFIG
    if a.command=='evaluate':
        if not a.input:p.error('--input trace.json is required')
        report=evaluate_trace(json.loads(Path(a.input).read_text(encoding='utf-8')),cfg)
    elif a.command=='regression':
        if not a.input:p.error('--input suite.json is required')
        report=run_suite(json.loads(Path(a.input).read_text(encoding='utf-8')),cfg)
    else:report=benchmark(cfg)
    text=json.dumps(report,indent=2,allow_nan=False)
    if a.output:Path(a.output).write_text(text,encoding='utf-8')
    else:print(text)
    if a.command in ('regression','benchmark') and report['failed']:sys.exit(1)
    if a.command=='evaluate' and (a.fail_on=='violation' and report['assessment']=='violation' or a.fail_on=='review' and report['assessment']!='clear'):sys.exit(1)
