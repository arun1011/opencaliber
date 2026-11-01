"""Build versioned public release assets for counted GitHub downloads."""
import hashlib,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.build_agent_library import main as agents
from opencaliber.local_package import build_package

def build():
    agents();out=ROOT/'dist/release';out.mkdir(parents=True,exist_ok=True)
    (out/'opencaliber.zip').write_bytes(build_package())
    catalog=json.loads((ROOT/'web/agents.json').read_text(encoding='utf-8'))
    for agent in catalog:(out/(agent['id']+'.zip')).write_bytes((ROOT/'web'/agent['download']).read_bytes())
    names=['opencaliber.zip']+[a['id']+'.zip' for a in catalog]
    (out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256((out/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in sorted(names)),encoding='utf-8')
    print('Built',len(names),'versioned package assets and checksums')
if __name__=='__main__':build()
