"""Build a root-level EB source bundle without private state or training dependencies."""
import argparse
import io
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from opencaliber.local_package import build_package

DEPLOY_FILES=('application.py','Procfile','requirements.txt','opencaliber/cloud_app.py',
 'opencaliber/local_package.py','LOCAL_TOOL.md','web/index.html','web/marketing.js',
 '.ebextensions/01_runtime.config','.ebextensions/02_bootstrap.config',
 '.platform/nginx/conf.d/opencaliber.conf','.platform/confighooks/predeploy/01_storage.sh','deploy/bootstrap.py','deploy/bootstrap.sh',
 'deploy/elasticbeanstalk.json','deploy/build_bundle.py','deploy/aws_deploy.py',
 'docs/elastic-beanstalk.md','tools/check_deployment.py',
 'web/media/opencaliber-walkthrough.mp4','web/media/opencaliber-walkthrough.vtt',
 'web/media/opencaliber-poster.jpg','web/media/black-t-photo.jpeg','web/media/opencaliber-chapters.json','web/media/opencaliber-transcript.txt')


def build(destination=None):
    destination=destination or ROOT/'dist/opencaliber-elasticbeanstalk.zip'
    with zipfile.ZipFile(io.BytesIO(build_package())) as runtime:
        names=set(runtime.namelist())|set(DEPLOY_FILES)
        destination.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as output:
            for name in sorted(names):
                path=ROOT/name
                if not path.is_file() or path.is_symlink():raise ValueError('Required source missing: '+name)
                if name.endswith('.sh'):
                    item=zipfile.ZipInfo(name);item.external_attr=0o100755<<16
                    output.writestr(item,path.read_bytes().replace(b'\r\n',b'\n'))
                else:output.write(path,name)
    if destination.stat().st_size>=500*1024*1024:raise ValueError('Bundle exceeds the EB size limit')
    return destination


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);a=p.parse_args()
    print(build(a.output))
