"""Update download-metrics/download-counts.json using the workflow token."""
import base64,json,os,sys,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from opencaliber.download_stats import repository
from opencaliber.download_ledger import empty,merge

def main():
    repo=os.environ.get('GITHUB_REPOSITORY') or repository();token=os.environ['GH_TOKEN']
    def api(path,body=None,method=None):
        req=urllib.request.Request('https://api.github.com/repos/'+repo+'/'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'OpenCaliber-count-snapshot','X-GitHub-Api-Version':'2026-03-10'})
        with urllib.request.urlopen(req,timeout=30) as res:return json.load(res)
    try:api('git/ref/heads/download-metrics')
    except urllib.error.HTTPError as exc:
        if exc.code!=404:raise
        api('git/refs',{'ref':'refs/heads/download-metrics','sha':api('git/ref/heads/main')['object']['sha']})
    try:
        existing=api('contents/download-counts.json?ref=download-metrics');sha=existing['sha']
        blob=existing if existing.get('encoding')=='base64' else api('git/blobs/'+sha)
        prior=json.loads(base64.b64decode(blob['content']))
    except urllib.error.HTTPError as exc:
        if exc.code!=404:raise
        if api('commits?sha=download-metrics&path=download-counts.json&per_page=1'):
            raise RuntimeError('Counter file was removed but its history exists. Restore the previous file on download-metrics; refusing a reset.')
        prior=empty(repo);sha=None
    releases=api('releases?per_page=100')
    catalog=json.loads((ROOT/'web/agents.json').read_text(encoding='utf-8'))
    result=merge(prior,releases,repo,catalog)
    if result==prior:print('Counts unchanged; existing snapshot retained');return
    payload={'message':'Update cumulative package download counts','branch':'download-metrics','content':base64.b64encode((json.dumps(result,indent=2)+'\n').encode()).decode()}
    if sha:payload['sha']=sha
    api('contents/download-counts.json',payload,method='PUT')
    print('Recorded',result['total_downloads'],'package downloads; historical asset counters preserved')
if __name__=='__main__':main()
