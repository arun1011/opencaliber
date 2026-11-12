"""Create immutable runtime snapshots and validate versioned core changes."""
import argparse
from datetime import date
import hashlib
import html
import json
import io
import zipfile
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'0|[1-9]\d*',value.split('.')[0]) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',value):raise ValueError('Use a semantic version such as 0.6.0')
    return tuple(map(int,value.split('.')))

def core_hash(root=ROOT):
    paths=[]
    for folder in ('opencaliber','sdk','agent_templates','profiles'):
        paths.extend(p for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.mjs','.mts'))
    paths.extend(p for p in (root/'web').glob('*.js') if p.name not in ('marketing.js','developer-guide.js','agents.js'))
    paths.append(root/'data/agent_cases.json')
    digest=hashlib.sha256()
    for p in sorted(paths):
        digest.update(p.relative_to(root).as_posix().encode()+b'\0')
        digest.update(p.read_bytes().replace(b'\r\n',b'\n')+b'\0')
    return digest.hexdigest()

def catalog(root=ROOT):
    path=root/'web/releases.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

def validate(root=ROOT,check_core=True):
    rows=catalog(root);seen=set();previous=None
    if not rows:raise ValueError('Create an initial release with tools/manage_releases.py create')
    for row in rows:
        number=version_tuple(row['version'])
        if row['version'] in seen or previous is not None and number>=previous:raise ValueError('Releases must be unique and newest first')
        seen.add(row['version']);previous=number;date.fromisoformat(row['date'])
        if not row['title'].strip() or not row['changes'] or any(not isinstance(c,str) or not c.strip() for c in row['changes']):raise ValueError('Each release needs a title and change notes')
        expected=f"downloads/releases/v{row['version']}/opencaliber-{row['version']}.zip"
        if row['download']!=expected:raise ValueError('Invalid release download path')
        archive=root/'web'/expected
        if not archive.is_file() or archive.stat().st_size!=row['bytes'] or hashlib.sha256(archive.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Release archive missing or modified: '+row['version'])
    if (root/'VERSION').read_text().strip()!=rows[0]['version']:raise ValueError('VERSION must match latest release')
    if check_core and rows[0]['core_sha256']!=core_hash(root):raise ValueError('Core functionality changed. Create a new release with change notes before publishing.')
    return rows

def create(version,title,changes,released=None,root=ROOT):
    version_tuple(version);rows=catalog(root)
    if rows:
        validate(root,check_core=False)
        if version_tuple(version)<=version_tuple(rows[0]['version']):raise ValueError('Use a newer version; existing releases cannot be replaced')
    if not title.strip() or not changes or any(not c.strip() for c in changes):raise ValueError('Provide a title and at least one change')
    released=released or date.today().isoformat();date.fromisoformat(released)
    destination=root/f'web/downloads/releases/v{version}/opencaliber-{version}.zip'
    if destination.exists():raise ValueError('Archive already exists; choose a new version')
    from tools.build_agent_library import main as build_agents
    from opencaliber.local_package import build_package
    from tools.build_public_guide import build as build_guide
    build_guide();build_agents()
    version_file=root/'VERSION';old=version_file.read_bytes() if version_file.exists() else None
    version_file.write_text(version+'\n',encoding='utf-8')
    try:
        stream=io.BytesIO(build_package())
        with zipfile.ZipFile(stream,'a',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('RELEASE_NOTES.md',f'# OpenCaliber {version}\n\n{released} - {title.strip()}\n\n'+'\n'.join('- '+c.strip() for c in changes)+'\n')
        raw=stream.getvalue()
    except BaseException:
        if old is None:version_file.unlink()
        else:version_file.write_bytes(old)
        raise
    row={'version':version,'date':released,'title':title.strip(),'changes':[c.strip() for c in changes],
         'download':destination.relative_to(root/'web').as_posix(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'core_sha256':core_hash(root)}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb') as stream:stream.write(raw)
    (root/'web/releases.json').write_text(json.dumps([row,*rows],indent=2)+'\n',encoding='utf-8')
    render(root)
    return row

def render(root=ROOT):
    rows=validate(root,check_core=False);esc=html.escape
    cards=[]
    for i,row in enumerate(rows):
        cards.append(f'<article class="panel panel-content release-card"><p class="eyebrow">{"LATEST RELEASE" if i==0 else "PREVIOUS RELEASE"} · {esc(row["date"])}</p><h2>v{esc(row["version"])} · {esc(row["title"])}</h2><ul>'+''.join('<li>'+esc(c)+'</li>' for c in row['changes'])+f'</ul><a class="btn primary" href="/{esc(row["download"])}" download="opencaliber-{esc(row["version"])}.zip">Download v{esc(row["version"])}</a><p>{row["bytes"]/1024/1024:.1f} MB · Console, evaluation backend and agent packs</p><details><summary>SHA256 checksum</summary><code class="release-checksum">{row["sha256"]}</code></details></article>')
    page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Releases | OpenCaliber</title><meta name="description" content="Download versioned OpenCaliber packages and read what changed in each release."><link rel="icon" href="/assets/favicon.svg"><link rel="stylesheet" href="/styles.css"></head><body class="marketing"><header class="site-nav"><a class="logo" href="/"><img src="/assets/logo.svg" width="29" height="29" alt="">OpenCaliber</a><nav class="site-links"><a href="/agents">Agents Library</a><a href="/guide">Developer Guide</a><a href="/releases" aria-current="page">Releases</a><a class="btn" href="/console">Console</a></nav></header><main class="public-guide"><div class="page-heading"><div><h1>Releases</h1><p>Choose a version, see what changed and download its original package.</p></div></div>'''+''.join(cards)+'''<p>Versioned downloads start with v'''+esc(rows[-1]['version'])+'''. Earlier development builds were not archived here. Back up your console database before upgrading; old packages do not include your saved data.</p></main></body></html>'''
    (root/'web/releases.html').write_text(page,encoding='utf-8')

def main():
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    create_args=commands.add_parser('create');group=create_args.add_mutually_exclusive_group(required=True);group.add_argument('--version');group.add_argument('--bump',choices=['patch','minor','major'])
    create_args.add_argument('--title',required=True);create_args.add_argument('--change',action='append',required=True);create_args.add_argument('--date')
    commands.add_parser('check');commands.add_parser('render');args=p.parse_args()
    if args.command=='check':validate();print('Release archives, version and core fingerprint verified')
    elif args.command=='render':render()
    else:
        version=args.version
        if args.bump:
            numbers=list(version_tuple(catalog()[0]['version']));index={'major':0,'minor':1,'patch':2}[args.bump];numbers[index]+=1
            for i in range(index+1,3):numbers[i]=0
            version='.'.join(map(str,numbers))
        row=create(version,args.title,args.change,args.date);print('Created immutable release v'+row['version'])

if __name__=='__main__':main()
