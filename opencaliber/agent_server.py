"""Local-only agent evaluation service. Run python -m opencaliber.agent_server."""
import argparse
import json
import re
import secrets
import sqlite3
from datetime import datetime,timezone
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .agent_engine import DEFAULT_CONFIG,VERSION,evaluate_trace,validate_config
from .privacy import minimize_evidence
from .adapters import normalize_response

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'artifacts/agent-console.sqlite3'


@contextmanager
def connect():
    conn=sqlite3.connect(DB,timeout=15);conn.row_factory=sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:conn.close()


def initialize():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        c.executescript('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, config TEXT NOT NULL); CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, name TEXT NOT NULL, trace TEXT NOT NULL, result TEXT NOT NULL, config TEXT NOT NULL, status TEXT NOT NULL DEFAULT "open", note TEXT NOT NULL DEFAULT ""); CREATE TABLE IF NOT EXISTS benchmarks (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, report TEXT NOT NULL);')
        from .tracking_store import initialize as initialize_tracking
        initialize_tracking(c)
        from .contract_cases import initialize as initialize_cases
        initialize_cases(c)
        from .comparison_store import initialize as initialize_comparisons
        initialize_comparisons(c)
        c.execute('INSERT OR IGNORE INTO settings VALUES(1,?)',(json.dumps(DEFAULT_CONFIG),))


def configuration():
    with connect() as c:return validate_config(json.loads(c.execute('SELECT config FROM settings WHERE id=1').fetchone()[0]))


def cases():
    from .contract_cases import list_cases
    bundle=json.loads((ROOT/'data/agent_cases.json').read_text(encoding='utf-8'))
    custom=[]
    if DB.is_file():
        with connect() as c:has_custom=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='custom_cases'").fetchone()
        if has_custom:custom=list_cases(connect)
    bundle['cases']=[{**case,'source':'included'} for case in bundle['cases']]+custom
    return bundle
def timestamp():return datetime.now(timezone.utc).isoformat()


def benchmark(cfg,selected=None):
    fixtures=cases()['cases']
    if selected is not None:
        if not isinstance(selected,list) or not selected or any(not isinstance(x,str) for x in selected) or not set(selected)<={c['id'] for c in fixtures}:raise ValueError('Invalid case selection')
        fixtures=[c for c in fixtures if c['id'] in selected]
    rows=[]
    for case in fixtures:
        effective={**cfg,**case['config_patch']};result=evaluate_trace(case['trace'],effective)
        codes={f['code'] for a in result['actions'] for f in a['findings']}
        passed=result['assessment']==case['expected']['assessment'] and set(case['expected']['required_codes'])<=codes
        rows.append({'id':case['id'],'name':case['name'],'expected':case['expected'],'actual':result['assessment'],'codes':sorted(codes),'passed':passed,'config_patch':case['config_patch']})
    return {'engine_version':VERSION,'total':len(rows),'passed':sum(r['passed'] for r in rows),'failed':sum(not r['passed'] for r in rows),'config':cfg,'cases':rows,'disclaimer':'Synthetic contract suite, not an independent measure of safety or real-world detection quality.'}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'web'),**kwargs)
    def trusted(self):
        port=self.server.server_address[1];origins={f'http://localhost:{port}',f'http://127.0.0.1:{port}'}
        return self.headers.get('Host') in {f'localhost:{port}',f'127.0.0.1:{port}'} and (self.headers.get('Origin') is None or self.headers.get('Origin') in origins) and self.headers.get('Sec-Fetch-Site') not in ('cross-site',)
    def json(self,value,status=200):
        raw=json.dumps(value,allow_nan=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()
    def do_GET(self):
        if not self.trusted():return self.json({'error':'Untrusted host or origin'},403)
        # This is a local development server: never reuse stale UI/media after updates.
        for header in ('If-Modified-Since','If-None-Match'):
            if header in self.headers:del self.headers[header]
        path=urlsplit(self.path).path
        aliases={'/index.html':'/','/agents.html':'/agents','/console.html':'/console','/agents/':'/agents','/console/':'/console','/guide.html':'/guide','/guide/':'/guide','/releases.html':'/releases','/releases/':'/releases'}
        if path in aliases:
            query=urlsplit(self.path).query
            self.send_response(308);self.send_header('Location',aliases[path]+('?' + query if query else ''));self.send_header('Content-Length','0');self.end_headers();return
        if path in ('/agents','/console','/guide','/releases'):
            self.path=path+'.html'
        elif path=='/' and not (ROOT/'web/index.html').exists():
            self.path='/console.html'
        if path=='/media/opencaliber-walkthrough.mp4':
            video=ROOT/'web/media/opencaliber-walkthrough.mp4'
            if not video.exists():return self.json({'error':'Video not found'},404)
            size=video.stat().st_size;start=0;end=size-1;status=200
            requested=self.headers.get('Range')
            if requested:
                match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
                if not match or not any(match.groups()):return self.json({'error':'A single byte range is required'},400)
                first,last=match.groups()
                if first:start=int(first);end=min(int(last),size-1) if last else size-1
                else:start=max(0,size-int(last))
                if start>=size or end<start:
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
                status=206
            length=end-start+1;self.send_response(status);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(length))
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with video.open('rb') as source:
                    source.seek(start)
                    while length>0:
                        chunk=source.read(min(length,65536))
                        if not chunk:break
                        self.wfile.write(chunk);length-=len(chunk)
            except (BrokenPipeError,ConnectionResetError):pass
            return
        if path=='/api/package':
            from .local_package import build_package
            try:raw=build_package()
            except (ValueError,OSError):return self.json({'error':'Local package source is incomplete'},503)
            self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Disposition','attachment; filename="opencaliber-local.zip"');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw);return
        if path=='/api/checks':
            from .custom_checks import listing
            return self.json(listing(connect))
        if path=='/api/check-model':
            from .check_models import status
            return self.json(status(connect))
        if path=='/api/platform/dashboard':
            from .connected_platform import dashboard
            return self.json(dashboard(connect,configuration(),cases()['cases']))
        if path=='/api/diagnosis/runs':
            from .connected_diagnosis import runs
            return self.json(runs(connect))
        if path=='/api/diagnosis/status':
            from .diagnosis import model_status
            return self.json(model_status())
        if path=='/api/diagnosis/example':
            from .diagnosis import example
            return self.json(example())
        if path=='/api/cases':return self.json(cases())
        if path=='/api/comparisons/example':
            from .comparison_demo import demo_bundle
            return self.json(demo_bundle())
        if path=='/api/comparisons':
            from .comparison_store import list_reports
            return self.json(list_reports(connect))
        if path.startswith('/api/comparisons/'):
            from .comparison_store import get_report
            try:report=get_report(path.rsplit('/',1)[-1],connect)
            except ValueError:return self.json({'error':'Invalid comparison ID'},400)
            return self.json(report) if report else self.json({'error':'Comparison not found'},404)

        if path=='/api/downloads':
            from .download_stats import report
            return self.json(report(json.loads((ROOT/'web/agents.json').read_text(encoding='utf-8'))))

        if path=='/api/adoption/profiles':
            from .profiles import available_profiles
            return self.json(available_profiles())
        if path=='/api/adoption/examples':
            from .adoption_api import examples
            return self.json(examples())
        if path=='/api/integration-examples':
            return self.json(json.loads((ROOT/'examples/adoption/bundle.json').read_text(encoding='utf-8')))
        if path=='/api/trajectories':
            from .trajectory import listing
            return self.json(listing(connect))
        if path.startswith('/api/trajectories/'):
            from .trajectory import report
            try:return self.json(report(path.rsplit('/',1)[-1],connect))
            except ValueError:return self.json({'error':'Invalid trajectory ID'},400)
        if path=='/api/tracking/agents':
            from .tracking_store import agents
            return self.json(agents(connect,configuration(),cases()['cases']))
        if path.startswith('/api/tracking/events/'):
            from .tracking_store import events
            try:return self.json(events(path.rsplit('/',1)[-1],connect))
            except ValueError:return self.json({'error':'Invalid workflow ID'},400)
        if path=='/api/state':
            with connect() as c:
                rows=c.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT 100').fetchall();last=c.execute('SELECT report,created_at FROM benchmarks ORDER BY created_at DESC LIMIT 1').fetchone()
            findings=[{'run_id':r['id'],'run_name':r['name'],'agent':json.loads(r['trace']).get('agent'),'workflow_id':json.loads(r['trace']).get('workflow_id'),'context':json.loads(r['trace']).get('context'),'status':r['status'],'created_at':r['created_at'],'action_id':a['action_id'],**f} for r in rows for a in json.loads(r['result'])['actions'] for f in a['findings']]
            return self.json({'engine_version':VERSION,'config':configuration(),'findings':findings,'runs':[{'id':r['id'],'created_at':r['created_at'],'name':r['name'],'agent':json.loads(r['trace']).get('agent'),'workflow_id':json.loads(r['trace']).get('workflow_id'),'context':json.loads(r['trace']).get('context'),'status':r['status'],'note':r['note'],'tracking':json.loads(r['result']).get('tracking'),**{k:json.loads(r['result'])[k] for k in ('assessment','risk_score','action_count','finding_count')}} for r in rows],'benchmark':{**json.loads(last['report']),'created_at':last['created_at']} if last else None})
        if path.startswith('/api/runs/'):
            with connect() as c:r=c.execute('SELECT * FROM runs WHERE id=?',(path.split('/')[-1],)).fetchone()
            if not r:return self.json({'error':'Run not found'},404)
            return self.json({**dict(r),'trace':json.loads(r['trace']),'result':json.loads(r['result']),'config':json.loads(r['config'])})
        if path.startswith('/api/'):return self.json({'error':'Not found'},404)
        return super().do_GET()
    def do_POST(self):
        if not self.trusted():return self.json({'error':'Untrusted host or origin'},403)
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.json({'error':'JSON required'},415)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=1048576:return self.json({'error':'Body must be 1 byte to 1 MiB'},413)
            body=json.loads(self.rfile.read(length));path=urlsplit(self.path).path
            if not isinstance(body,dict):raise ValueError('Expected a JSON object')
            if path.startswith('/api/checks/') or path.startswith('/api/check-model/'):
                from .check_api import handle
                return self.json(handle(path[5:],body,connect))
            if path=='/api/platform/settings':
                from .connected_platform import save_settings
                return self.json(save_settings(body,connect))
            if path=='/api/platform/compare':
                from .connected_platform import compare
                return self.json(compare(body,connect))
            if path=='/api/platform/contracts':
                from .connected_platform import contract_from_run
                return self.json(contract_from_run(body,connect,configuration(),cases()['cases'],timestamp))
            if path=='/api/diagnosis/run':
                from .connected_diagnosis import run_report
                if set(body)!={'run_id','use_semantic'} or type(body['use_semantic']) is not bool:raise ValueError('Provide run_id and use_semantic boolean')
                return self.json(run_report(body['run_id'],connect,body['use_semantic']))
            if path=='/api/diagnosis':
                from .diagnosis import diagnose
                if set(body)!={'bundle','use_semantic'} or type(body['use_semantic']) is not bool:raise ValueError('Provide bundle and use_semantic boolean')
                return self.json(diagnose(body['bundle'],use_semantic=body['use_semantic']))
            if path=='/api/trajectories/spans':
                from .trajectory import save
                return self.json(save(body,connect,timestamp))
            if path=='/api/tracking/events':
                from .tracking_store import ingest
                return self.json(ingest(body,connect,timestamp,configuration()))
            if path=='/api/tracking/policy':
                from .tracking_store import save_policy
                return self.json(save_policy(body,connect))
            if path in ('/api/cases/custom','/api/cases/preview'):
                from .contract_cases import preview,save
                if set(body)!={'case'}:raise ValueError('Provide a case object')
                if path.endswith('/preview'):return self.json(preview(body['case'],configuration()))
                builtin=json.loads((ROOT/'data/agent_cases.json').read_text(encoding='utf-8'))['cases']
                return self.json(save(body['case'],connect,{c['id'] for c in builtin},configuration(),timestamp),201)
            if path=='/api/comparisons':
                from .comparison_store import save
                if set(body)!={'comparison'}:raise ValueError('Provide a comparison bundle')
                return self.json(save(body['comparison'],connect,timestamp),201)
            if path=='/api/normalize':
                if set(body)!={'provider','response','context'} or not isinstance(body['context'],dict):raise ValueError('Provide provider, response and context')
                if set(body['context'])-{'policy','agent','task','session_id','workflow_id'} or not {'policy','agent','task','session_id'}<=set(body['context']):raise ValueError('Invalid integration context fields')
                return self.json({'trace':normalize_response(body['provider'],body['response'],**body['context'])})
            if path.startswith('/api/adoption/'):
                from .adoption_api import handle
                return self.json(handle(path.rsplit('/',1)[-1],body,configuration()))
            if path=='/api/config':
                cfg=validate_config(body)
                with connect() as c:c.execute('UPDATE settings SET config=? WHERE id=1',(json.dumps(cfg),))
                return self.json({'config':cfg})
            if path=='/api/evaluate':
                if set(body)-{'trace','storage'} or 'trace' not in body:raise ValueError('Provide trace and optional storage')
                storage=body.get('storage','raw')
                if storage not in ('raw','redacted'):raise ValueError('storage must be raw or redacted')
                cfg=configuration();trace=body['trace'];result=evaluate_trace(trace,cfg);rid=secrets.token_hex(8)
                result['storage_mode']=storage;result['replayable']=storage=='raw'
                if storage=='redacted':trace,result=minimize_evidence(trace,result)
                with connect() as c:c.execute('INSERT INTO runs(id,created_at,name,trace,result,config) VALUES(?,?,?,?,?,?)',(rid,timestamp(),trace.get('name','Imported trace'),json.dumps(trace),json.dumps(result),json.dumps(cfg)))
                return self.json({'id':rid,'result':result},201)
            if path=='/api/benchmark':
                if set(body)-{'case_ids'}:raise ValueError('Unsupported benchmark option')
                report=benchmark(configuration(),body.get('case_ids'));rid=secrets.token_hex(8)
                with connect() as c:c.execute('INSERT INTO benchmarks VALUES(?,?,?)',(rid,timestamp(),json.dumps(report)))
                return self.json({'id':rid,**report})
            if path=='/api/review':
                if set(body)!={'id','status','note'} or body['status'] not in ('open','reviewed','dismissed') or not isinstance(body['note'],str) or len(body['note'])>2000 or not isinstance(body['id'],str):raise ValueError('Invalid review record')
                with connect() as c:
                    cur=c.execute('UPDATE runs SET status=?,note=? WHERE id=?',(body['status'],body['note'],body['id']))
                    if not cur.rowcount:return self.json({'error':'Run not found'},404)
                return self.json({'saved':True})
            return self.json({'error':'Not found'},404)
        except (ValueError,KeyError,TypeError,UnicodeDecodeError) as exc:return self.json({'error':str(exc)},400)
        except sqlite3.Error:return self.json({'error':'Local database unavailable'},503)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8787);a=p.parse_args();initialize()
    print(f'OpenCaliber: http://127.0.0.1:{a.port}/ · Console: /console',flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
