"""Resolve a complete latest release before switching website download links."""
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def ready_tag(release,catalog):
    tag=release.get('tag_name','')
    if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?',tag):return ''
    required={'opencaliber.zip','SHA256SUMS.txt'}|{a['id']+'.zip' for a in catalog}
    uploaded={a.get('name') for a in release.get('assets',[]) if a.get('state')=='uploaded' and a.get('size',0)>0}
    return tag if required<=uploaded else ''
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('release_json');a=p.parse_args()
    print(ready_tag(json.loads(Path(a.release_json).read_text()),json.loads((ROOT/'web/agents.json').read_text())))
