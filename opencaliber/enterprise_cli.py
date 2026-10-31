"""Offline import, profile and coverage commands for application integrations."""
import argparse
import json
from pathlib import Path
from .profiles import available_profiles,load_profile
from .coverage import coverage_report
from .ingestion import normalize_mcp,normalize_databricks

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['profiles','coverage','import-mcp','import-databricks']);p.add_argument('--input');p.add_argument('--context');p.add_argument('--config');p.add_argument('--output');a=p.parse_args()
    if a.command=='profiles':report=available_profiles()
    else:
        if not a.input:p.error('--input is required')
        data=json.loads(Path(a.input).read_text(encoding='utf-8'))
        if a.command=='coverage':
            cfg=json.loads(Path(a.config).read_text(encoding='utf-8')) if a.config else None
            report=coverage_report(data,cfg)
        else:
            if not a.context:p.error('--context is required')
            context=json.loads(Path(a.context).read_text(encoding='utf-8'))
            report=(normalize_mcp if a.command=='import-mcp' else normalize_databricks)(data,**context)
    text=json.dumps(report,indent=2,allow_nan=False)
    if a.output:Path(a.output).write_text(text,encoding='utf-8')
    else:print(text)

if __name__=='__main__':main()
