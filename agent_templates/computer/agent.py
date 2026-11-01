"""Bounded workflow runner. Demo is offline; live browser mode requires Playwright.

These are code-driven workflows, not general desktop-control or autonomous LLM agents.
"""
import argparse
import copy
import csv
import io
import json
import os
from pathlib import Path
import re
import queue
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from opencaliber.agent_engine import DEFAULT_CONFIG, evaluate_trace
from opencaliber.tracking import TrackedExecutor
from opencaliber.privacy import minimize_evidence

ROOT = Path(__file__).resolve().parent


def inside(root, value):
    path = (root / value).resolve()
    if path == root.resolve() or not path.is_relative_to(root.resolve()):
        raise ValueError('Path must stay inside its configured directory')
    return path


def policy(config):
    result = copy.deepcopy(DEFAULT_CONFIG)
    result.update(allowed_hosts=config['allowed_hosts'], allowed_file_roots=['/workspace'],
                  max_calls=100, max_records=100,
                  denied_tools=['shell.exec','database.write','database.delete','file.delete','iam.create_key'])
    result['tool_policies'] = {
        'file.read': {'resource': {'path_roots':['/workspace/samples']}},
        'file.write': {'resource': {'path_roots':['/workspace/outputs']}}
    }
    return result


def validate(config):
    if config['kind'] not in ('research','reports','testing','documents'):
        raise ValueError('Unsupported workflow kind')
    for key, maximum in [('max_pages',5),('max_files',20),('max_input_bytes',1_000_000),
                         ('max_text_chars',10000),('timeout_seconds',60),('max_download_bytes',10_000_000)]:
        if type(config[key]) is not int or not 1 <= config[key] <= maximum:
            raise ValueError('Invalid '+key)
    if len(config['targets']) > config['max_pages']:
        raise ValueError('Too many browser targets')
    if type(config['manual_login']) is not bool or type(config['headless']) is not bool:
        raise ValueError('Invalid browser settings')
    if config.get('browser_channel','') not in ('','chrome','msedge'):
        raise ValueError('Use Chromium, chrome or msedge browser_channel')
    if config['manual_login'] and config['headless']:
        raise ValueError('Manual login requires headless false')
    if config['download_extension'] not in ('.csv','.pdf','.xlsx'):
        raise ValueError('Report extension must be csv, pdf or xlsx')
    if config['allowed_methods'] not in (['GET','HEAD'], ['GET','HEAD','POST']):
        raise ValueError('Review allowed_methods; only read requests and optional POST are supported')
    if not isinstance(config['fields'], list) or len(config['fields'])>20 or any(not isinstance(f,str) or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,49}',f) is None for f in config['fields']):
        raise ValueError('Use bounded field identifiers')
    cfg = policy(config)
    # Validates exact hostnames and the engine configuration even in demo mode.
    from opencaliber.agent_engine import validate_config
    validate_config(cfg)
    for target in config['targets']:
        url = target['url']
        if urlsplit(url).scheme != 'https':
            raise ValueError('Live browser targets require HTTPS')
        check = evaluate_trace({'task':{'goal':'Navigate approved target','allowed_tools':['http.get']},
                                'actions':[{'id':'target','tool':'http.get','resource':url}]},cfg)
        if check['assessment'] != 'clear':
            raise ValueError('Target is outside approved hosts or is not a valid URL')
        if not isinstance(target['must_contain'],str) or len(target['must_contain'])>200:
            raise ValueError('Invalid visible-text assertion')
    return config


def manual_checkpoint(page, prompt):
    """Keep browser routing responsive while the operator signs in or reviews."""
    done = queue.Queue()
    def read():
        try:done.put(input(prompt))
        except Exception as exc:done.put(exc)
    threading.Thread(target=read,daemon=True).start()
    deadline = time.monotonic()+300
    while done.empty():
        if time.monotonic()>deadline:
            raise ValueError('Manual approval timed out after five minutes')
        page.wait_for_timeout(100)
    value = done.get()
    if isinstance(value,Exception):raise value


def source_url(url):
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))


def extract_entries(text, suffix, fields):
    if suffix == '.csv':
        rows = list(csv.DictReader(io.StringIO(text)))[:100]
        return [{key: row.get(key,'') for key in fields} for row in rows]
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition(':')
        if sep and key.strip() in fields:
            values[key.strip()] = value.strip()
    return [{key:values.get(key,'') for key in fields}]


def make_guard(config):
    return TrackedExecutor(root=ROOT,tracking_id=config.get('tracking_id',config['agent_id']),agent={'id':config['agent_id'],'version':'0.2.0'},
        task={'goal':config['title'],'allowed_tools':['http.get','http.send','file.read','file.write']},
        workflow_id=config['agent_id']+'-workflow',config=policy(config),mode='enforce')


def guarded(guard, tool, resource, callback):
    action = {'id':'step-'+str(len(guard.trace['actions'])+1),'tool':tool,'resource':resource}
    return guard.run(action,callback,success=lambda value: True)


def document_workflow(config, guard):
    inputs = inside(ROOT, config['input_dir'])
    files = sorted(p for p in inputs.iterdir() if p.suffix.lower() in ('.txt','.md','.csv'))
    if not files or len(files)>config['max_files']:
        raise ValueError('Provide a bounded set of text, Markdown or CSV inputs')
    total = 0; entries = []
    for file in files:
        if file.is_symlink() or not file.resolve().is_relative_to(inputs):
            raise ValueError('Input escapes its configured directory')
        total += file.stat().st_size
        if total>config['max_input_bytes']:
            raise ValueError('Input exceeds byte budget')
        def read():
            with file.open('r',encoding='utf-8') as source:
                data = source.read(config['max_input_bytes']+1)
            if len(data.encode('utf-8'))>config['max_input_bytes']:
                raise ValueError('Input grew past the byte budget')
            return data
        text = guarded(guard,'file.read','/workspace/samples/'+file.name,read)
        for entry in extract_entries(text,file.suffix.lower(),config['fields']):
            entries.append({'source':file.name,'fields':entry,
                            'missing_fields':[key for key,value in entry.items() if not value]})
            if len(entries)>100:
                raise ValueError('Document workflow allows at most 100 draft entries')
    return {'entries':entries,'review_required':True,'external_submission':False}


def demo(config, guard):
    if config['kind']=='documents':
        return document_workflow(config,guard)
    # Fixture reading is a real file action; demo never pretends a browser call ran.
    sample = inside(ROOT,'samples/pages.json')
    pages = guarded(guard,'file.read','/workspace/samples/pages.json',
                    lambda:json.loads(sample.read_text(encoding='utf-8')))
    if config['kind']=='research':
        return {'sources':pages,'comparison_draft':[p['excerpt'] for p in pages],
                'review_questions':['Verify freshness and source context.'],'review_required':True}
    if config['kind']=='reports':
        return {'report':'Synthetic report: 12 resolved tickets, 3 pending.',
                'source':'Offline sample','download_performed':False,'review_required':True}
    return {'assertions':[{'url':p['url'],'expected':'Example','passed':'Example' in p['title']}
                          for p in pages],'screenshots':[],'browser_executed':False}


def browser_workflow(config, guard, output):
    from playwright.sync_api import sync_playwright
    checks = []; sources = []; assertions = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=config['headless'],
                                    **({'channel':config['browser_channel']} if config.get('browser_channel') else {}))
        context = browser.new_context(accept_downloads=True,service_workers='block')
        try:
            # All contexts are ephemeral; cookies and passwords are not exported.
            def route_request(route):
                request = route.request
                if request.method not in config['allowed_methods'] or urlsplit(request.url).scheme!='https':
                    checks.append({'host':urlsplit(request.url).hostname,'allowed':False})
                    return route.abort()
                tool = 'http.get' if request.method in ('GET','HEAD') else 'http.send'
                action = {'id':'network','tool':tool,'resource':request.url,
                          'arguments':{'destination':request.url},'data_class':config['data_class']}
                result = evaluate_trace({'task':{'goal':'Browser request','allowed_tools':['http.get','http.send']},
                                         'actions':[action]},policy(config))
                allowed = result['assessment']=='clear'
                checks.append({'host':urlsplit(request.url).hostname,'allowed':allowed})
                if allowed:return route.continue_()
                return route.abort()
            context.route('**/*',route_request)
            page = context.new_page()
            page.set_default_timeout(config['timeout_seconds']*1000)
            page.on('dialog',lambda dialog:dialog.dismiss())
            for index,target in enumerate(config['targets']):
                def navigate():
                    response = page.goto(target['url'],wait_until='domcontentloaded')
                    if response is None or response.status>=400:
                        raise ValueError('Target returned an unsuccessful response')
                    return response.status
                guarded(guard,'http.get',target['url'],navigate)
                if config['manual_login']:
                    manual_checkpoint(page,'Sign in manually in this browser, then press Enter here to continue: ')
                if config['kind']=='reports':
                    manual_checkpoint(page,'Review the report and configured download control. Press Enter to collect it, or Ctrl+C to stop: ')
                    destination = inside(output,'report-'+str(index+1)+config['download_extension'])
                    def download():
                        with page.expect_download() as info:
                            page.locator(config['download_selector']).click()
                        item = info.value
                        temp = item.path()
                        if Path(item.suggested_filename).suffix.lower()!=config['download_extension']:
                            raise ValueError('Report extension differs from reviewed configuration')
                        if temp is None or Path(temp).stat().st_size>config['max_download_bytes']:
                            raise ValueError('Downloaded file exceeds save limit or failed')
                        item.save_as(str(destination))
                        return destination.name
                    saved = guarded(guard,'file.write','/workspace/outputs/'+destination.name,download)
                    sources.append({'url':source_url(page.url),'saved_file':saved})
                else:
                    text = page.locator('body').inner_text()[:config['max_text_chars']]
                    sources.append({'url':source_url(page.url),'title':page.title(),'excerpt':text})
                    if config['kind']=='testing':
                        expected = target['must_contain']
                        assertions.append({'url':source_url(page.url),'expected':expected,'passed':expected in text})
                        image = inside(output,'page-'+str(index+1)+'.png')
                        guarded(guard,'file.write','/workspace/outputs/'+image.name,
                                lambda:page.screenshot(path=str(image),full_page=False))
        finally:
            context.close();browser.close()
    return {'sources':sources,'assertions':assertions,'network_checks':checks,
            'comparison_draft':[{'source':s['url'],'excerpt':s.get('excerpt','')} for s in sources],
            'review_required':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo',action='store_true');mode.add_argument('--run',action='store_true')
    parser.add_argument('--approve-config',action='store_true',help='Confirm review of live targets, permissions and output location')
    parser.add_argument('--overwrite',action='store_true')
    args = parser.parse_args()
    envfile=ROOT/'.env'
    if envfile.exists():
        for line in envfile.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key,value=line.split('=',1);os.environ.setdefault(key.strip(),value.strip().strip(chr(34)).strip(chr(39)))
    config = validate(json.loads((ROOT/'config.json').read_text(encoding='utf-8')))
    if args.run and not args.approve_config:
        raise ValueError('Review config.json and pass --approve-config before live execution')
    output = inside(ROOT,config['output_dir'])
    names = ['draft.txt','result.json','evaluation.json']
    names += ['report-'+str(i+1)+config['download_extension'] for i in range(config['max_pages'])]
    names += ['page-'+str(i+1)+'.png' for i in range(config['max_pages'])]
    for name in names:
        path = inside(output,name)
        if path.exists() and not args.overwrite:
            raise ValueError('Output exists; use --overwrite after review')
    output.mkdir(parents=True,exist_ok=True)
    guard = make_guard(config)
    result = None
    completed = False
    try:
        result = demo(config,guard) if args.demo else document_workflow(config,guard) if config['kind']=='documents' else browser_workflow(config,guard,output)
        prefix = 'DEMO — offline fixtures; no browser or external request executed.\n' if args.demo else 'Workflow results — review before use.\n'
        guarded(guard,'file.write','/workspace/outputs/result.json',lambda:(output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8'))
        guarded(guard,'file.write','/workspace/outputs/draft.txt',lambda:(output/'draft.txt').write_text(prefix+json.dumps(result,indent=2),encoding='utf-8'))
        completed = not any(not a['passed'] for a in result.get('assertions',[]))
    finally:
        guard.finish('completed' if completed else 'failed')
        if guard.trace['actions']:
            report = evaluate_trace(guard.trace,policy(config))
            trace, report = minimize_evidence(guard.trace,report)
            last = minimize_evidence(guard.trace,guard.last_evaluation)[1] if guard.last_evaluation else None
            (output/'evaluation.json').write_text(json.dumps({'trace':trace,**report,
                'workflow_status':'completed' if completed else 'stopped',
                'last_pre_dispatch_evaluation':last},indent=2),encoding='utf-8')
    if result and any(not a['passed'] for a in result.get('assertions',[])):
        raise ValueError('One or more UI assertions failed; inspect result.json')
    print('Results and evaluation saved in outputs. Review the generated files.')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Workflow stopped: '+type(exc).__name__+': '+str(exc),file=sys.stderr)
        sys.exit(1)
