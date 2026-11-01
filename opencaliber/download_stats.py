"""Read aggregate GitHub release-asset counts; no browser tracking or visitor data."""
from datetime import datetime,timezone
import json,os,re,threading,time,urllib.request,urllib.error
_CACHE={};_LOCK=threading.Lock()

def repository():
    repo=os.getenv('OPENCALIBER_GITHUB_REPOSITORY','arun1011/opencaliber')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}/[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',repo):raise ValueError('Invalid GitHub repository')
    return repo

def fetch(path):
    request=urllib.request.Request('https://api.github.com/'+path,headers={'Accept':'application/vnd.github+json','User-Agent':'OpenCaliber-download-report','X-GitHub-Api-Version':'2026-03-10'})
    with urllib.request.urlopen(request,timeout=8) as response:raw=response.read(8_000_001)
    if len(raw)>8_000_000:raise ValueError('GitHub response exceeds report limit')
    return json.loads(raw)

def summarize(releases,repo,catalog):
    if not isinstance(releases,list):raise ValueError('Invalid GitHub release response')
    known={'opencaliber.zip':'OpenCaliber console',**{a['id']+'.zip':a['title'] for a in catalog}}
    packages={};versions=[]
    for release in releases:
        if release.get('draft'):continue
        total=0;found=False
        for asset in release.get('assets',[]):
            name=asset.get('name');count=asset.get('download_count')
            if name not in known or type(count) is not int or count<0:continue
            found=True;total+=count
            row=packages.setdefault(name,{'asset':name,'title':known[name],'downloads':0});row['downloads']+=count
        if found:versions.append({'tag':release['tag_name'],'downloads':total,'published_at':release.get('published_at')})
    rows=sorted(packages.values(),key=lambda a:(-a['downloads'],a['asset']))
    return {'status':'available' if rows else 'setup_required','source':'GitHub release asset download_count','repository':repo,'checked_at':datetime.now(timezone.utc).isoformat(),'total_downloads':sum(a['downloads'] for a in rows) if rows else None,'console_downloads':packages.get('opencaliber.zip',{}).get('downloads',0) if rows else None,'agent_downloads':sum(a['downloads'] for a in rows if a['asset']!='opencaliber.zip') if rows else None,'packages':rows,'releases':versions,'scope':'Up to the latest 100 published releases. Includes direct GitHub and site-linked downloads, repeat downloads and automation; not unique users, completed installs, or site-only attribution. Static Pages, clone/source archives and internal-server downloads are excluded.'}

def snapshot_report(snapshot,repo):
    from .download_ledger import merge
    merge(snapshot,[],repo,[])  # Validate stored counter identities before display.
    packages={};versions={}
    for a in snapshot['assets'].values():
        row=packages.setdefault(a['asset'],{'asset':a['asset'],'title':a['title'],'downloads':0});row['downloads']+=a['downloads']
        versions[a['release']]=versions.get(a['release'],0)+a['downloads']
    rows=sorted(packages.values(),key=lambda a:(-a['downloads'],a['asset']))
    return {'status':'available' if rows else 'setup_required','source':'Persistent GitHub release-asset ledger','repository':repo,'checked_at':snapshot['updated_at'],'persisted':True,'total_downloads':snapshot['total_downloads'] if rows else None,'console_downloads':snapshot['console_downloads'] if rows else None,'agent_downloads':snapshot['agent_downloads'] if rows else None,'packages':rows,'releases':[{'tag':tag,'downloads':count} for tag,count in sorted(versions.items())],'daily_totals':snapshot['daily_totals'],'scope':'Cumulative maximum observed counts per GitHub asset ID, retained in download-metrics/download-counts.json. Includes site-linked and direct GitHub downloads, repeats and automation; not unique users, completed installs, or site-only attribution. Earlier static Pages downloads are unknown. Deleted assets retain their last observed counts.'}

def read_snapshot(repo):
    req=urllib.request.Request(f'https://raw.githubusercontent.com/{repo}/download-metrics/download-counts.json',headers={'User-Agent':'OpenCaliber-download-report'})
    with urllib.request.urlopen(req,timeout=8) as response:raw=response.read(8_000_001)
    if len(raw)>8_000_000:raise ValueError('Snapshot exceeds report limit')
    return json.loads(raw)

def report(catalog):
    repo=repository()
    with _LOCK:
        cached=_CACHE.get(repo)
        if cached and time.monotonic()-cached[0]<300:return cached[1]
        try:
            result=snapshot_report(read_snapshot(repo),repo)
        except urllib.error.HTTPError as exc:
            if exc.code==404:
                try:
                    result=summarize(fetch(f'repos/{repo}/releases?per_page=100'),repo,catalog)
                    result['persisted']=False
                except Exception:result={'status':'unavailable','repository':repo,'error':'Cannot read GitHub counts. Check connectivity or retry later.','total_downloads':None,'packages':[],'releases':[]}
            else:result={'status':'unavailable','repository':repo,'error':'Stored count file is unavailable. Existing counts have not been reset.','packages':[],'releases':[]}
        except Exception:
            if cached:return {**cached[1],'stale':True,'error':'Count file unavailable; showing the previous report.'}
            result={'status':'unavailable','repository':repo,'error':'Cannot read or validate the stored counts. Counts have not been reset.','total_downloads':None,'packages':[],'releases':[]}
        _CACHE[repo]=(time.monotonic(),result)
        return result
