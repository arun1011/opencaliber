"""Minimal, allowlisted console runtime distribution."""
import io
import json
import re
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def build_package():
    files=['LICENSE','NOTICE','LICENSING.md','opencaliber/__init__.py','opencaliber/agent_engine.py','opencaliber/agent_server.py','opencaliber/agent_cli.py','opencaliber/adapters.py','opencaliber/sdk.py','opencaliber/privacy.py','opencaliber/regression.py',
           'data/agent_cases.json','web/console.html','web/console.js','web/agents.html','web/agents.js','web/agents.json','web/integration.js','web/styles.css','web/assets/favicon.svg','web/assets/logo.svg',
           'examples/agent_trace.json','examples/integrate_agent.py','ADOPTION.md','sdk/typescript/opencaliber.mjs','sdk/typescript/opencaliber.d.mts','examples/adoption/bundle.json','examples/adoption/context.json','examples/adoption/provider_demo.py','examples/adoption/provider_demo.mjs','examples/adoption/live_response.py','examples/adoption/live_agent.py','examples/adoption/regression-suite.json']
    catalog=json.loads((ROOT/'web/agents.json').read_text(encoding='utf-8'))
    for entry in catalog:
        if re.fullmatch('[a-z0-9-]+',entry['id']) is None:raise ValueError('Invalid catalog ID')
        files.append('web/downloads/agents/'+entry['id']+'.zip')
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            path=(ROOT/name).resolve()
            if not path.is_relative_to(ROOT.resolve()) or not path.is_file():raise ValueError('Required package file is missing: '+name)
            if path.suffix=='.zip':
                archive.write(path,name);continue
            text=path.read_text(encoding='utf-8')
            if name in ('web/console.html','web/agents.html'):
                text=text.replace('href="/"','href="/console#docs"').replace('About OpenCaliber','Developer guide')
            elif name=='web/console.js':
                text=re.sub(r'<a class="btn primary" href="/#walkthrough">.*?</a>','',text)
                text=text.replace('python -m unittest discover -s tests -v','')
            elif name=='opencaliber/agent_server.py':
                start=text.index("        if path=='/media/opencaliber-walkthrough.mp4':")
                end=text.index("        if path=='/api/cases':",start)
                text=text[:start]+text[end:]
            archive.writestr(name,text)
        docs=(ROOT/'LOCAL_TOOL.md').read_text(encoding='utf-8')
        start=docs.index('## Narrated user walkthrough')
        end=docs.index('## Integrate with an agent',start)
        docs=docs[:start]+docs[end:]
        docs=docs.replace('The home page is http://127.0.0.1:8787/ .','The root URL also opens the console.').replace('python -m unittest discover -s tests -v','')
        docs+='\nLicensed under Apache-2.0. See LICENSE, NOTICE and LICENSING.md.\n'
        docs+='\nThis runtime package contains only the console, evaluation backend, built-in cases, launchers and integration examples. Marketing pages, videos, model training code, development tests and local evaluation history are excluded.\n'
        archive.writestr('README.md',docs)
        archive.writestr('run.py',"from opencaliber.agent_server import initialize, Handler\nfrom http.server import ThreadingHTTPServer\nif __name__ == '__main__':\n    initialize()\n    print('OpenCaliber: http://127.0.0.1:8787/console', flush=True)\n    ThreadingHTTPServer(('127.0.0.1',8787),Handler).serve_forever()\n")
        archive.writestr('start-windows.cmd','@echo off\r\ncd /d "%~dp0"\r\npython run.py\r\npause\r\n')
        archive.writestr('start-macos-linux.sh','#!/bin/sh\ncd "$(dirname "$0")" || exit 1\nexec python3 run.py\n')
    return stream.getvalue()

if __name__=='__main__':
    destination=ROOT/'artifacts/opencaliber-local.zip';destination.parent.mkdir(exist_ok=True)
    destination.write_bytes(build_package());print(destination)
