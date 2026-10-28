from __future__ import annotations
import asyncio
import hmac
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .build import build_id
from .paths import read_json, home
from .store import Store
from .maps import public_map
from .source import resolve_anchor
from .paths import safe_source
from markdown_it import MarkdownIt

STATIC=Path(__file__).parent/'static'


def create_app(token=None, service=None):
    token=token or secrets.token_urlsafe(32)
    store=Store()
    @asynccontextmanager
    async def lifespan(app):
        if service: await service.start()
        yield
        if service: await service.close()
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.token=token
    app.state.quit=lambda:None
    app.state.service=service
    renderer=MarkdownIt('commonmark',{'html':False}).enable('table')
    renderer.disable('image')
    @app.middleware('http')
    async def local_access(request: Request, call_next):
        host=request.headers.get('host','').split(':')[0]
        if host not in {'127.0.0.1','testserver'}:
            return JSONResponse({'error':'Loopback host required'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin!=f'http://{request.headers.get("host")}':
            return JSONResponse({'error':'Cross-origin request denied'},status_code=403)
        if request.url.path.startswith('/api/'):
            supplied=request.headers.get('x-scire-token') or request.query_params.get('token','')
            if not hmac.compare_digest(supplied,token):
                return JSONResponse({'error':'Session token required'},status_code=401)
        response=await call_next(request)
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    @app.exception_handler(ValueError)
    async def invalid(request,exc): return JSONResponse({'error':str(exc)},status_code=400)
    @app.exception_handler(FileNotFoundError)
    async def missing(request,exc): return JSONResponse({'error':'Source or session not found'},status_code=404)
    @app.get('/api/status')
    async def status(): return {'ok':True,'build':build_id(),'repos':len(store.repos()),'running':len(service.jobs) if service else 0}
    @app.get('/api/home')
    async def home_state():
        repos=[{**r,'map':public_map(store,r['id'])} for r in store.repos()]
        return {'profile':store.profile(),'repos':repos,'sessions':[{k:s[k] for k in ('id','repo','title','target','status','round','created_at','updated_at','cost','seconds')} for s in store.sessions()], 'build':build_id()}
    @app.post('/api/setup')
    async def setup(request:Request):
        value=await request.json()
        profile={**store.profile(),**{k:value[k] for k in ('name','role','model','cheap_model') if k in value},'setup':True}
        prior=store.profile();store.save_profile(profile)
        if service and profile.get('model')!=prior.get('model'):
            for repo in store.repos():service.queue_map(repo['id'],True)
        for path in value.get('paths',[]):
            repo=store.add_repo(path)
            if service: service.queue_map(repo['id'])
        return {'ok':True}
    @app.post('/api/open')
    async def open_app():
        import webbrowser
        state=read_json(home()/'server.json',{})
        webbrowser.open(f'http://127.0.0.1:{state.get("port")}/#{token}')
        return {'ok':True}
    @app.post('/api/quit')
    async def quit_app():
        asyncio.get_running_loop().call_later(.2,app.state.quit)
        return {'ok':True}
    @app.get('/api/maps/{rid}')
    async def map_state(rid:str):
        store.repo(rid)
        return public_map(store,rid)
    app.mount('/static',StaticFiles(directory=STATIC),name='static')
    @app.get('/{path:path}')
    async def index(path:str): return HTMLResponse((STATIC/'index.html').read_text())
    return app
