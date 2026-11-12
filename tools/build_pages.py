"""Build a public static site, including downloadable console and agent packages."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.build_agent_library import main as build_agents
from opencaliber.local_package import build_package


def build(destination,base_path='',release_tag='',release_repository='arun1011/opencaliber',metrics_file=''):
    if release_tag and not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?',release_tag):raise ValueError('Invalid release tag')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}/[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',release_repository):raise ValueError('Invalid release repository')
    release_base=f'https://github.com/{release_repository}/releases/download/{release_tag}/' if release_tag else ''
    base_path=base_path.rstrip('/')
    if base_path and not re.fullmatch(r'/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',base_path):
        raise ValueError('Invalid Pages base path')
    destination=Path(destination).resolve()
    if not destination.is_relative_to(ROOT/'dist') or destination==ROOT/'dist':
        raise ValueError('Output must be a subdirectory of dist')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Choose an empty output directory')
    from tools.build_public_guide import build as build_guide
    build_guide()
    from tools.manage_releases import render as render_releases,catalog as release_catalog
    render_releases()
    if release_tag!='v'+release_catalog()[0]['version']:release_base='' # Never redirect current downloads to an older GitHub release.
    build_agents()
    destination.mkdir(parents=True,exist_ok=True)
    prefix=base_path+'/'
    def write(name,data):
        p=destination/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data if isinstance(data,bytes) else data.encode('utf-8'))
    def url(value):
        if value.startswith(('#','https://','http://','mailto:','data:')):return value
        if release_base and value=='/api/package':return release_base+'opencaliber.zip'
        parsed=urlsplit(value)
        routes={'/':'','/agents':'agents/','/console':'console/','/guide':'guide/','/releases':'releases/','/api/package':'downloads/opencaliber.zip'}
        path=routes.get(parsed.path,parsed.path.lstrip('/'))
        return prefix+path+('?' + parsed.query if parsed.query else '')+('#'+parsed.fragment if parsed.fragment else '')
    def page(text):
        return re.sub(r'\b(href|src|poster)="([^"]+)"',lambda m:m[1]+'="'+url(m[2])+'"',text)
    for name in ('styles.css','marketing.js','assets/favicon.svg','assets/logo.svg',
                 'media/opencaliber-walkthrough.mp4','media/opencaliber-walkthrough.vtt','media/opencaliber-poster.jpg',
                 'media/black-t-photo.jpeg'):
        write(name,(ROOT/'web'/name).read_bytes())
    for name in ('LICENSE','NOTICE','LICENSING.md'):write(name,(ROOT/name).read_bytes())
    write('.nojekyll','')
    if metrics_file:
        from opencaliber.download_stats import snapshot_report
        snapshot=json.loads(Path(metrics_file).read_text(encoding='utf-8'))
        snapshot_report(snapshot,release_repository)
        write('download-counts.json',json.dumps(snapshot,indent=2))
    home=(ROOT/'web/index.html').read_text(encoding='utf-8').replace('Open the console →','Console setup →').replace('Open console ↗','Console setup ↗').replace('Compare agent versions →','Set up version comparisons →')
    write('index.html',page(home))
    library=(ROOT/'web/agents.html').read_text(encoding='utf-8').replace('Open console ↗','Console setup ↗')
    write('agents/index.html',page(library))
    write('releases/index.html',page((ROOT/'web/releases.html').read_text(encoding='utf-8')))
    write('releases.json',(ROOT/'web/releases.json').read_bytes())
    for release in release_catalog():
        write(release['download'],(ROOT/'web'/release['download']).read_bytes())
    write('guide/index.html',page((ROOT/'web/guide.html').read_text(encoding='utf-8')))
    for asset in (ROOT/'web/assets/guide').glob('*.png'):
        write('assets/guide/'+asset.name,asset.read_bytes())
    script=(ROOT/'web/agents.js').read_text(encoding='utf-8').replace("fetch('agents.json'","fetch("+json.dumps(prefix+'agents.json'))
    write('agents.js',script)
    catalog=json.loads((ROOT/'web/agents.json').read_text(encoding='utf-8'))
    for entry in catalog:
        path=entry['download'];write(path,(ROOT/'web'/path).read_bytes());entry['download']=release_base+entry['id']+'.zip' if release_base else prefix+path
    write('agents.json',json.dumps(catalog,indent=2))
    write('downloads/opencaliber.zip',(ROOT/'web'/release_catalog()[0]['download']).read_bytes())
    write('console/index.html',page((ROOT/'web/pages-console.html').read_text(encoding='utf-8')))
    for old,target in [('agents.html','agents/'),('console.html','console/'),('guide.html','guide/'),('releases.html','releases/')]:
        write(old,'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='+prefix+target+'"><title>OpenCaliber</title></head><body><a href="'+prefix+target+'">Continue to OpenCaliber</a></body></html>')
    write('404.html',page('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Page not found</title></head><body><h1>Page not found</h1><p><a href="/">OpenCaliber home</a></p></body></html>'))
    print('Static site:',destination,'base path:',base_path or '/')
    return destination

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/pages')
    parser.add_argument('--base-path',default='')
    parser.add_argument('--release-tag',default='')
    parser.add_argument('--release-repository',default='arun1011/opencaliber')
    parser.add_argument('--metrics-file',default='')
    args=parser.parse_args();build(args.output,args.base_path,args.release_tag,args.release_repository,args.metrics_file)
