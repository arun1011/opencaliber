"""Run two isolated offline fixture versions and compare their connected outcomes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from opencaliber.tracking import TrackingClient

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True,help='Another extracted copy with your candidate code/config')
    parser.add_argument('--baseline-version',default='1.0')
    parser.add_argument('--candidate-version',default='2.0')
    args=parser.parse_args()
    if args.baseline_version==args.candidate_version:parser.error('Versions must be distinct')
    candidate=args.candidate.resolve()
    if not (candidate/'agent.py').is_file():parser.error('Candidate must be an extracted agent pack')
    client=TrackingClient();headers={}
    if client.token:headers['Authorization']='Bearer '+client.token
    def api(path,body=None):
        request=urllib.request.Request(client.endpoint+'/api/'+path,data=None if body is None else json.dumps(body).encode(),headers={**headers,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
    api('state')  # Require a running collector before dispatching the fixture runs.
    configs=[json.loads((p/'config.json').read_text(encoding='utf-8')) for p in (ROOT,candidate)]
    if configs[0]['agent_id']!=configs[1]['agent_id']:raise ValueError('Compare versions of the same agent_id')
    output=ROOT/'outputs';output.mkdir(exist_ok=True)
    experiment='library-'+uuid.uuid4().hex
    cohorts=[]
    with tempfile.TemporaryDirectory(prefix='comparison-',dir=output) as temp:
        for index,(source,config,version) in enumerate(zip((ROOT,candidate),configs,(args.baseline_version,args.candidate_version))):
            # These are trusted fixture reads by the test harness, not agent operations.
            directory=(source/config['input_dir']).resolve()
            if not directory.is_relative_to(source.resolve()):raise ValueError('Fixture input directory must stay inside the pack')
            files=sorted(p for p in directory.iterdir() if p.is_file())
            if not files or len(files)>100 or any(p.is_symlink() for p in files) or sum(p.stat().st_size for p in files)>1000000:raise ValueError('Use at most 100 fixture files and 1 MB of input')
            digest=hashlib.sha256()
            for p in files:
                digest.update(json.dumps([p.name,p.stat().st_size]).encode());digest.update(p.read_bytes())
            # Computer demo definitions can also depend on these declared inputs.
            for field in ('targets','fields','kind'):
                if field in config:digest.update(json.dumps([field,config[field]],sort_keys=True).encode())
            dest=Path(temp)/str(index)
            shutil.copytree(source,dest,ignore=shutil.ignore_patterns('outputs','.env','.git','__pycache__','.venv'))
            config.update(version=version,diagnosis_enabled=True,trajectory_id=None,parent_span_id=None,
                evaluation={'experiment_id':experiment,'case_id':'shared-fixtures','input_sha256':digest.hexdigest(),
                            'success_criterion':'fixture-assertions-'+hashlib.sha256(json.dumps(config.get('success_checks',{}),sort_keys=True).encode()).hexdigest()[:16],'assignment':'paired'})
            (dest/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
            result=subprocess.run([sys.executable,'agent.py','--demo'],cwd=dest,env={**os.environ,'OPENCALIBER_ENDPOINT':client.endpoint,'OPENCALIBER_TOKEN':client.token,'OPENCALIBER_TRACKING':'on'},timeout=120)
            if result.returncode:raise RuntimeError('Fixture execution failed. Inspect its tracked run before comparing')
            cohorts.append(json.dumps([os.getenv('OPENCALIBER_TRACKING_ID') or config.get('tracking_id',config['agent_id']),version],separators=(',',':')))
        report=api('platform/compare',{'baseline':cohorts[0],'candidate':cohorts[1]})
    (output/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Matched cases:',report['matched']['count'])
    print('Open Compare agent versions in your console. Report: outputs/comparison.json')
    print('This compares demo fixtures and configured assertions; live model/browser quality requires your own cases.')

if __name__=='__main__':main()
