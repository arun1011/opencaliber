"""Offline checks only: no AWS access, provisioning or storage bootstrap execution."""
import ast
import json
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy.build_bundle import build,DEPLOY_FILES


def check():
    for name in ('application.py','opencaliber/cloud_app.py','deploy/bootstrap.py','deploy/aws_deploy.py','deploy/build_bundle.py'):
        ast.parse((ROOT/name).read_text(encoding='utf-8'),filename=name)
    template=json.loads((ROOT/'deploy/elasticbeanstalk.json').read_text())
    assert template['Resources']['DataVolume']['DeletionPolicy']=='Retain'
    assert template['Resources']['DataVolume']['Properties']['Encrypted'] is True
    assert template['Resources']['AdminSecret']['DeletionPolicy']=='Retain'
    settings=template['Resources']['Environment']['Properties']['OptionSettings']
    assert any(x['Namespace']=='aws:elbv2:listener:443' and x['OptionName']=='Protocol' and x['Value']=='HTTPS' for x in settings)
    assert any(x['Namespace']=='aws:elasticbeanstalk:application:environmentsecrets' for x in settings)
    assert '--workers 1' in (ROOT/'Procfile').read_text()
    import yaml
    for name in ('.ebextensions/01_runtime.config','.ebextensions/02_bootstrap.config'):
        assert isinstance(yaml.safe_load((ROOT/name).read_text()),dict)
    with zipfile.ZipFile(build()) as archive:
        names=archive.namelist();assert archive.testzip() is None
        assert all(name in names for name in DEPLOY_FILES)
        assert 'application.py' in names and 'requirements.txt' in names
        assert len([n for n in names if n.startswith('web/downloads/agents/')])==64
        assert not any(n.startswith(('artifacts/','tests/','.git/','private/','notebooks/')) or n.endswith(('.sqlite3','.db','.env','.safetensors','.pyc')) for n in names)
        assert 'requirements-training.txt' not in names
        assert b'\r\n' not in archive.read('deploy/bootstrap.sh')
    print('PASS: ASGI source, EB configuration, TLS/secrets, retained-storage declarations, 64 packs, source bundle and exclusions. AWS deployment was not performed.')


if __name__=='__main__':check()
