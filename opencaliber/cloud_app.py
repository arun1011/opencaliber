"""Public product site with an authenticated single-workspace evaluator."""
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import posixpath
import secrets
import sqlite3
from urllib.parse import unquote, urlsplit
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from . import agent_server as store
from .agent_engine import VERSION, evaluate_trace, validate_config
from .adapters import normalize_response
from .privacy import minimize_evidence


@dataclass(frozen=True)
class Settings:
    public_origin: str
    admin_token: str
    data_dir: Path
    require_mount: bool = True

    @classmethod
    def environment(cls):
        return cls(os.getenv('OPENCALIBER_PUBLIC_ORIGIN','').rstrip('/'),
                   os.getenv('OPENCALIBER_ADMIN_TOKEN',''),
                   Path(os.getenv('OPENCALIBER_DATA_DIR','/mnt/opencaliber/data')),
                   os.getenv('OPENCALIBER_STORAGE_MODE','retained')=='retained')

    def validate(self):
        url=urlsplit(self.public_origin)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise RuntimeError('Set OPENCALIBER_PUBLIC_ORIGIN to the HTTPS origin without a path')
        if len(self.admin_token)<32 or ':' in self.admin_token or any(c.isspace() for c in self.admin_token):
            raise RuntimeError('Set OPENCALIBER_ADMIN_TOKEN to a random secret of at least 32 characters')
        if not self.data_dir.is_absolute():raise RuntimeError('OPENCALIBER_DATA_DIR must be absolute')
        if self.require_mount and not os.path.ismount(self.data_dir.parent):
            raise RuntimeError('Retained data volume is not mounted; refusing ephemeral storage fallback')


def authorized(header,token):
    scheme,_,value=(header or '').partition(' ')
    if scheme.lower()=='bearer':return secrets.compare_digest(value.encode(),token.encode())
    if scheme.lower()=='basic':
        try:
            username,password=base64.b64decode(value,validate=True).decode().split(':',1)
            return secrets.compare_digest(username.encode(),b'admin') and secrets.compare_digest(password.encode(),token.encode())
        except (ValueError,UnicodeError):pass
    return False


def create_app(settings=None):
    config=settings

    @asynccontextmanager
    async def lifespan(app):
        cfg=config or Settings.environment();cfg.validate();app.state.config=cfg
        previous=store.DB;store.DB=cfg.data_dir/'agent-console.sqlite3'
        try:
            store.initialize()
            yield
        finally:store.DB=previous

    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def boundary(request,call_next):
        path='/'+posixpath.normpath(unquote(request.url.path)).lstrip('/')
        private=path in ('/console','/console.html') or path.startswith('/api/') and path!='/api/package'
        if private:
            cfg=request.app.state.config
            if request.url.scheme!='https':return JSONResponse({'error':'HTTPS is required for the workspace'},403)
            if request.headers.get('host','').lower()!=urlsplit(cfg.public_origin).netloc.lower():
                return JSONResponse({'error':'Untrusted host'},403)
            if request.headers.get('origin') not in (None,cfg.public_origin) or request.headers.get('sec-fetch-site')=='cross-site':
                return JSONResponse({'error':'Untrusted origin'},403)
            if not authorized(request.headers.get('authorization'),cfg.admin_token):
                return JSONResponse({'error':'Workspace authentication required'},401,headers={'WWW-Authenticate':'Basic realm="OpenCaliber", charset="UTF-8"','Cache-Control':'no-store'})
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.scheme=='https':response.headers['Strict-Transport-Security']='max-age=31536000'
        if private:response.headers['Cache-Control']='no-store'
        return response

    @app.get('/api/adoption/profiles')
    def profiles():
        from .profiles import available_profiles
        return available_profiles()

    @app.get('/api/adoption/examples')
    def adoption_examples():
        from .adoption_api import examples
        return examples()

    @app.get('/health/live')
    def live():return {'status':'alive'}

    @app.get('/health/ready')
    def ready():
        try:
            with store.connect() as c:
                c.execute('SELECT config FROM settings WHERE id=1').fetchone()
                c.execute('BEGIN IMMEDIATE');c.rollback()
            return {'status':'ready'}
        except sqlite3.Error:return JSONResponse({'status':'unavailable'},503)

    @app.get('/api/package')
    def package():
        # The source builder excludes cloud configuration, credentials and saved history.
        from fastapi.responses import Response
        from .local_package import build_package
        return Response(build_package(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="opencaliber.zip"'})

    @app.get('/api/cases')
    def cases():return store.cases()

    @app.get('/api/integration-examples')
    def examples():return json.loads((store.ROOT/'examples/adoption/bundle.json').read_text(encoding='utf-8'))

    @app.get('/api/state')
    def state():
        with store.connect() as c:
            rows=c.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT 100').fetchall()
            last=c.execute('SELECT * FROM benchmarks ORDER BY created_at DESC LIMIT 1').fetchone()
        runs=[];findings=[]
        for r in rows:
            trace,result=json.loads(r['trace']),json.loads(r['result'])
            identity={k:trace.get(k) for k in ('agent','workflow_id','context')}
            runs.append({'id':r['id'],'created_at':r['created_at'],'name':r['name'],'status':r['status'],'note':r['note'],**identity,
                         **{k:result[k] for k in ('assessment','risk_score','action_count','finding_count')}})
            for action in result['actions']:
                for finding in action['findings']:
                    findings.append({'run_id':r['id'],'run_name':r['name'],'status':r['status'],'created_at':r['created_at'],'action_id':action['action_id'],**identity,**finding})
        return {'engine_version':VERSION,'config':store.configuration(),'runs':runs,'findings':findings,
                'benchmark':{**json.loads(last['report']),'created_at':last['created_at']} if last else None}

    @app.get('/api/runs/{run_id}')
    def run(run_id:str):
        with store.connect() as c:r=c.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
        if not r:return JSONResponse({'error':'Run not found'},404)
        return {**dict(r),**{k:json.loads(r[k]) for k in ('trace','result','config')}}

    @app.post('/api/{operation:path}')
    async def mutate(operation:str,request:Request):
        if request.headers.get('content-type','').split(';')[0]!='application/json':return JSONResponse({'error':'JSON required'},415)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>1048576:return JSONResponse({'error':'Body exceeds 1 MiB'},413)
        try:
            body=json.loads(raw)
            if not isinstance(body,dict):raise ValueError('Expected a JSON object')
            if operation=='normalize':
                if set(body)!={'provider','response','context'} or not isinstance(body['context'],dict) or set(body['context'])-{'policy','agent','task','session_id','workflow_id'} or not {'policy','agent','task','session_id'}<=set(body['context']):raise ValueError('Invalid normalization request')
                return {'trace':normalize_response(body['provider'],body['response'],**body['context'])}
            if operation.startswith('adoption/'):
                from .adoption_api import handle
                return handle(operation.split('/',1)[1],body,store.configuration())
            if operation=='config':
                cfg=validate_config(body)
                with store.connect() as c:c.execute('UPDATE settings SET config=? WHERE id=1',(json.dumps(cfg),))
                return {'config':cfg}
            if operation=='evaluate':
                if set(body)-{'trace','storage'} or 'trace' not in body:raise ValueError('Provide trace and optional storage')
                mode=body.get('storage','redacted')
                if mode not in ('raw','redacted'):raise ValueError('Invalid storage mode')
                cfg=store.configuration();trace=body['trace'];result=evaluate_trace(trace,cfg)
                result.update(storage_mode=mode,replayable=mode=='raw')
                if mode=='redacted':trace,result=minimize_evidence(trace,result)
                rid=secrets.token_hex(8)
                with store.connect() as c:c.execute('INSERT INTO runs(id,created_at,name,trace,result,config) VALUES(?,?,?,?,?,?)',(rid,store.timestamp(),trace.get('name','Imported trace'),json.dumps(trace),json.dumps(result),json.dumps(cfg)))
                return JSONResponse({'id':rid,'result':result},201)
            if operation=='benchmark':
                if set(body)-{'case_ids'}:raise ValueError('Unsupported benchmark option')
                report=store.benchmark(store.configuration(),body.get('case_ids'));rid=secrets.token_hex(8)
                with store.connect() as c:c.execute('INSERT INTO benchmarks VALUES(?,?,?)',(rid,store.timestamp(),json.dumps(report)))
                return {'id':rid,**report}
            if operation=='review':
                if set(body)!={'id','status','note'} or body['status'] not in ('open','reviewed','dismissed') or not isinstance(body['id'],str) or not isinstance(body['note'],str) or len(body['note'])>2000:raise ValueError('Invalid review')
                with store.connect() as c:found=c.execute('UPDATE runs SET status=?,note=? WHERE id=?',(body['status'],body['note'],body['id'])).rowcount
                return {'saved':True} if found else JSONResponse({'error':'Run not found'},404)
            return JSONResponse({'error':'Not found'},404)
        except (ValueError,TypeError,KeyError,UnicodeError):return JSONResponse({'error':'Invalid request; check the supported schema'},400)
        except sqlite3.Error:return JSONResponse({'error':'Storage unavailable'},503)

    @app.get('/index.html')
    @app.get('/agents.html')
    @app.get('/console.html')
    @app.get('/agents/')
    @app.get('/console/')
    def page_alias(request: Request):
        target={'/index.html':'/','/agents.html':'/agents','/console.html':'/console','/agents/':'/agents','/console/':'/console'}[request.url.path]
        return RedirectResponse(target+('?' + request.url.query if request.url.query else ''),status_code=308)

    @app.get('/agents')
    @app.get('/console')
    def page(request: Request):
        return FileResponse(store.ROOT/'web'/ (request.url.path.lstrip('/')+'.html'))

    app.mount('/',StaticFiles(directory=store.ROOT/'web',html=True),name='site')
    return app
