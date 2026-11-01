"""Monotonic, versioned package download snapshots independent of site deployments."""
import copy
from datetime import datetime,timezone
import re

def empty(repo):return {'version':1,'repository':repo,'updated_at':None,'legacy_pages_downloads':None,'assets':{},'daily_totals':[],'total_downloads':0,'console_downloads':0,'agent_downloads':0}

def merge(previous,releases,repo,catalog,now=None):
    if not isinstance(previous,dict) or previous.get('version')!=1 or previous.get('repository')!=repo or not isinstance(previous.get('assets'),dict):raise ValueError('Invalid previous download snapshot; refusing to reset counts')
    for key,a in previous['assets'].items():
        if not re.fullmatch('[0-9]+',key) or not isinstance(a,dict) or type(a.get('downloads')) is not int or a['downloads']<0 or not {'asset','title','release'}<=set(a):raise ValueError('Invalid stored asset counter')
    if previous.get('total_downloads')!=sum(a['downloads'] for a in previous['assets'].values()):raise ValueError('Stored total does not match asset counters; refusing to reset')
    console=sum(a['downloads'] for a in previous['assets'].values() if a['asset']=='opencaliber.zip')
    if previous.get('console_downloads')!=console or previous.get('agent_downloads')!=previous['total_downloads']-console:raise ValueError('Stored package totals are inconsistent')
    history=previous.get('daily_totals')
    if not isinstance(history,list):raise ValueError('Invalid count history')
    last_day='';last_total=0
    for point in history:
        if (not isinstance(point,dict) or not isinstance(point.get('date'),str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',point['date']) or
            point['date']<=last_day or any(type(point.get(k)) is not int or point[k]<0 for k in ('total_downloads','console_downloads','agent_downloads')) or
            point['total_downloads']<last_total or point['total_downloads']!=point['console_downloads']+point['agent_downloads']):raise ValueError('Invalid count history; refusing reset')
        last_day=point['date'];last_total=point['total_downloads']
    if previous['total_downloads']<last_total:raise ValueError('Stored total is below historical observations; refusing reset')
    result=copy.deepcopy(previous)
    now=now or datetime.now(timezone.utc).isoformat();known={'opencaliber.zip':'OpenCaliber console',**{a['id']+'.zip':a['title'] for a in catalog}}
    if not isinstance(releases,list):raise ValueError('Invalid GitHub release response')
    changed=False
    for release in releases:
        if release.get('draft'):continue
        for a in release.get('assets',[]):
            name=a.get('name');count=a.get('download_count');ident=a.get('id')
            if name not in known or type(count) is not int or count<0 or type(ident) is not int or ident<=0:continue
            key=str(ident);old=result['assets'].get(key)
            if old and (old['asset']!=name or old['release']!=release['tag_name']):raise ValueError('Asset identity changed; refusing ambiguous merge')
            if old is None or count>old['downloads']:
                result['assets'][key]={'asset':name,'title':known[name],'release':release['tag_name'],'downloads':max(count,old['downloads'] if old else 0),'updated_at':now};changed=True
    result['total_downloads']=sum(a['downloads'] for a in result['assets'].values())
    result['console_downloads']=sum(a['downloads'] for a in result['assets'].values() if a['asset']=='opencaliber.zip')
    result['agent_downloads']=result['total_downloads']-result['console_downloads']
    day=now[:10];history=result.setdefault('daily_totals',[])
    point={'date':day,'total_downloads':result['total_downloads'],'console_downloads':result['console_downloads'],'agent_downloads':result['agent_downloads']}
    if not history or history[-1]!=point:
        if history and history[-1]['date']==day:history[-1]=point
        else:history.append(point)
        changed=True
    if changed:result['updated_at']=now
    return result
