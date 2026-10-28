from __future__ import annotations
import argparse
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
import httpx
import uvicorn
from . import __version__
from .app import create_app
from .build import build_id
from .paths import home, read_json, write_json
from .store import Store


def running():
    state = read_json(home() / "server.json", {})
    if not state:
        return None
    try:
        response = httpx.get(
            f"http://127.0.0.1:{state['port']}/api/status",
            headers={"x-scire-token": state["token"]},
            timeout=0.6,
        )
        if response.status_code == 200 and response.json().get("build") == state.get("build"):
            return state
    except (httpx.HTTPError, KeyError):
        pass
    return None


def api(state, path, value=None):
    url = f"http://127.0.0.1:{state['port']}/api/{path}"
    headers = {"x-scire-token": state["token"]}
    response = (
        httpx.get(url, headers=headers, timeout=45)
        if value is None
        else httpx.post(url, headers=headers, json=value, timeout=120)
    )
    if not response.is_success:
        raise ValueError(response.json().get("error", "Scire request failed"))
    return response.json()


def serve(no_open=False):
    import fcntl

    lock = (home() / "launch.lock").open("a+")
    os.chmod(home() / "launch.lock", 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    active_build = build_id()
    state = running()
    pending = read_json(home() / "server.json", {})
    if not state and pending and time.time() - pending.get("started_at", 0) < 10:
        for _ in range(50):
            time.sleep(0.1)
            state = running()
            if state:
                break
    if state and state["build"] == active_build:
        lock.close()
        url = f"http://127.0.0.1:{state['port']}/#{state['token']}"
        if not no_open:
            webbrowser.open(url)
        print(url)
        return
    if state:
        api(state, "quit", {})
        for _ in range(50):
            if not running():
                break
            time.sleep(0.1)
        else:
            raise ValueError("Old server did not stop. Run scire quit and retry.")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    token = secrets.token_urlsafe(32)
    from .service import Service

    app = create_app(token, Service())
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    app.state.quit = lambda: setattr(server, "should_exit", True)
    state = {
        "port": sock.getsockname()[1],
        "token": token,
        "pid": os.getpid(),
        "build": active_build,
        "started_at": time.time(),
    }
    write_json(home() / "server.json", state)
    lock.close()
    url = f"http://127.0.0.1:{state['port']}/#{token}"
    print(f"\nScire · {url}\nPress Ctrl-C to stop.\n", flush=True)
    if not no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.run(sockets=[sock])
    finally:
        if read_json(home() / "server.json", {}).get("token") == token:
            (home() / "server.json").unlink(missing_ok=True)
        sock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="scire", description="Keep your understanding of a codebase current"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--no-open", action="store_true")
    commands = parser.add_subparsers(dest="command")
    setup = commands.add_parser("setup", aliases=["init"])
    setup.add_argument("repos", nargs="*")
    setup.add_argument("--connect", action="store_true")
    setup.add_argument("--model")
    setup.add_argument("--no-open", action="store_true", default=argparse.SUPPRESS)
    for name in ("status", "open", "quit", "doctor"):
        commands.add_parser(name)
    args = parser.parse_args(argv)
    from .operations import connect, doctor

    try:
        if args.command == "doctor":
            doctor()
            return
        if args.command in {"status", "open", "quit"}:
            state = running()
            if not state:
                print("Scire is not running.")
                return
            if args.command == "status":
                print(f"Running on 127.0.0.1:{state['port']}")
                return
            if args.command == "open":
                webbrowser.open(f"http://127.0.0.1:{state['port']}/#{state['token']}")
                return
            api(state, "quit", {})
            print("Stopping Scire.")
            return
        if args.command in {"setup", "init"}:
            for path in args.repos:
                Store().add_repo(path)
            if args.connect:
                connect(args.model)
            elif args.model:
                profile = Store().profile()
                profile["model"] = args.model
                Store().save_profile(profile)
        serve(args.no_open)
    except ValueError as exc:
        print("Scire: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
