"""Offline evaluation reports for CI; no traces or raw tool payloads in artifacts."""
import argparse
import json
from pathlib import Path
import re
from .agent_engine import evaluate_trace,DEFAULT_CONFIG,validate_config

def run_checks(suite,config=None):
    cfg=validate_config(DEFAULT_CONFIG if config is None else config)
    if not isinstance(suite,dict) or set(suite)!={'version','cases'} or not isinstance(suite['version'],str) or not suite['version'] or not isinstance(suite['cases'],list) or not 1<=len(suite['cases'])<=1000:raise ValueError('Invalid CI trace suite')
    seen=set();rows=[]
    for case in suite['cases']:
        if not isinstance(case,dict) or set(case)!={'id','trace','expected_assessment','required_codes'}:raise ValueError('Invalid CI case')
        cid=case['id']
        if not isinstance(cid,str) or re.fullmatch('[A-Za-z0-9_-]{1,100}',cid) is None or cid in seen:raise ValueError('CI case IDs must be unique bounded identifiers')
        if case['expected_assessment'] not in ('clear','review','violation') or not isinstance(case['required_codes'],list) or any(not isinstance(c,str) for c in case['required_codes']):raise ValueError('Invalid CI expectations')
        seen.add(cid);result=evaluate_trace(case['trace'],cfg)
        findings=[{'action_id':a['action_id'],'code':f['code'],'evidence_ids':f['evidence_ids']} for a in result['actions'] for f in a['findings']]
        codes={f['code'] for f in findings}
        rows.append({'id':cid,'actual':result['assessment'],'expected':case['expected_assessment'],'passed':result['assessment']==case['expected_assessment'] and set(case['required_codes'])<=codes,'findings':findings})
    return {'suite_version':suite['version'],'engine_version':result['engine_version'],'config_sha256':result['config_sha256'],'total':len(rows),'passed':sum(r['passed'] for r in rows),'failed':sum(not r['passed'] for r in rows),'cases':rows,'limitations':'Synthetic regression results, not independent safety evidence. No source traces included; IDs may still be sensitive.'}

def markdown(report):
    def safe(v):return str(v).replace('\n',' ').replace('|','/').replace('`','')
    lines=['# OpenCaliber evaluation report','',f"Matched {report['passed']} of {report['total']} cases.",'','| Case | Expected | Actual | Match | Findings |','|---|---|---|---|---|']
    for row in report['cases']:lines.append('| '+' | '.join(map(safe,[row['id'],row['expected'],row['actual'],row['passed'],', '.join(sorted({f['code'] for f in row['findings']}))]))+' |')
    return '\n'.join(lines)+'\n'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--suite',required=True);parser.add_argument('--config');parser.add_argument('--output-dir',default='artifacts/ci');parser.add_argument('--fail-on',choices=['mismatch','violation','review'],default='mismatch');args=parser.parse_args()
    report=run_checks(json.loads(Path(args.suite).read_text(encoding='utf-8')),json.loads(Path(args.config).read_text(encoding='utf-8')) if args.config else None)
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');(out/'report.md').write_text(markdown(report),encoding='utf-8')
    print(f"Matched {report['passed']}/{report['total']}; reports: {out}")
    failed=report['failed'] or args.fail_on=='violation' and any(c['actual']=='violation' for c in report['cases']) or args.fail_on=='review' and any(c['actual']!='clear' for c in report['cases'])
    return 1 if failed else 0

if __name__=='__main__':raise SystemExit(main())
