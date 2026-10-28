from __future__ import annotations
import argparse
import os
import secrets
import socket
import sys
import time
import webbrowser
from pathlib import Path
import httpx
import uvicorn
from . import __version__
from .app import create_app
from .build import build_id
from .paths import home,read_json,write_json,transaction
from .store import Store


def running():
    state=read_json(home()/'server.json',{})
    if not state: return None
    try:
        response=httpx.get(f'http://127.0.0.1:{state["port"]}/api/status',headers={'x-scire-token':state['token']},timeout=1)
        if response.status_code==200 and response.json().get('build')==state.get('build'): return state
    except (httpx.HTTPError,KeyError): pass
    return None


def serve(no_open=False):
    state=running()
    if state and state['build']==build_id():
        url=f'http://127.0.0.1:{state["port"]}/#{state["token"]}'
        if not no_open:webbrowser.open(url)
        print(url)
        return
    if state:
        httpx.post(f'http://127.0.0.1:{state["port"]}/api/quit',headers={'x-scire-token':state['token']},timeout=2)
        for _ in range(30):
            if not running():break
            time.sleep(.1)
        else:raise SystemExit('Old server did not stop; use scire quit before upgrading.')
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
    token=secrets.token_urlsafe(32)
    app=create_app(token)
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
    app.state.quit=lambda:setattr(server,'should_exit',True)
    state={'port':sock.getsockname()[1],'token':token,'pid':os.getpid(),'build':build_id(),'started_at':time.time()}
    write_json(home()/'server.json',state)
    url=f'http://127.0.0.1:{state["port"]}/#{token}'
    print(f'\nScire · {url}\nPress Ctrl-C to stop.\n',flush=True)
    if not no_open:
        import threading
        threading.Timer(.6,lambda:webbrowser.open(url)).start()
    try:server.run(sockets=[sock])
    finally:
        if read_json(home()/'server.json',{}).get('token')==token:(home()/'server.json').unlink(missing_ok=True)
        sock.close()


def main(argv=None):
    parser=argparse.ArgumentParser(prog='scire',description='Keep your understanding of a codebase current')
    parser.add_argument('--version',action='version',version=__version__)
    parser.add_argument('--no-open',action='store_true')
    commands=parser.add_subparsers(dest='command')
    setup=commands.add_parser('setup');setup.add_argument('repos',nargs='*');setup.add_argument('--no-open',action='store_true')
    commands.add_parser('status');commands.add_parser('open');commands.add_parser('quit')
    args=parser.parse_args(argv)
    if args.command in {'status','open','quit'}:
        state=running()
        if not state:
            print('Scire is not running.');return
        if args.command=='status':print(f'Running on 127.0.0.1:{state["port"]} · {state["build"]}');return
        if args.command=='open':webbrowser.open(f'http://127.0.0.1:{state["port"]}/#{state["token"]}');return
        httpx.post(f'http://127.0.0.1:{state["port"]}/api/quit',headers={'x-scire-token':state['token']},timeout=3);print('Stopping Scire.');return
    if args.command=='setup':
        for path in args.repos:Store().add_repo(path)
    serve(args.no_open)
