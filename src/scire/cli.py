from __future__ import annotations
import argparse
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
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


def ensure_server():
    state = running()
    if state and state["build"] == build_id():
        return state
    log = (home() / "server.log").open("a")
    os.chmod(home() / "server.log", 0o600)
    subprocess.Popen(
        [sys.executable, "-m", "scire", "--no-open"], stdout=log, stderr=log, start_new_session=True
    )
    log.close()
    for _ in range(100):
        time.sleep(0.1)
        state = running()
        if state and state["build"] == build_id():
            return state
    raise ValueError("Scire could not start. See " + str(home() / "server.log"))


def choose_repo(path=None):
    store = Store()
    if path:
        return store.add_repo(path)
    cwd = Path.cwd().resolve()
    candidates = [r for r in store.repos() if cwd.is_relative_to(Path(r["path"]))]
    if candidates:
        return max(candidates, key=lambda r: len(r["path"]))
    if len(store.repos()) == 1:
        return store.repos()[0]
    try:
        from .git import git

        root = git(cwd, "rev-parse", "--show-toplevel").strip()
        return store.add_repo(root)
    except ValueError:
        raise ValueError("Choose a repository with --repo /path/to/repo")


def show(state, path="/", no_open=False):
    url = f"http://127.0.0.1:{state['port']}{path}#{state['token']}"
    print(url)
    if not no_open:
        webbrowser.open(url)


def wait_map(state, rid, force=False, wait=True):
    current = api(state, "maps/" + rid)
    if force or current.get("status") != "ready":
        api(state, "maps/" + rid + "/build", {})
    if not wait:
        return
    last = None
    started = time.monotonic()
    while time.monotonic() - started < 360:
        value = api(state, "maps/" + rid)
        if value["status"] == "ready" and (not force or time.monotonic() - started > 1):
            return value
        if value.get("status") == "error":
            raise ValueError(value.get("error", "Map failed"))
        message = value.get("activity", "Preparing map…")
        if message != last:
            print(message, flush=True)
            last = message
        time.sleep(1)
    raise ValueError("Map is still running; open Scire to follow its progress")


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
    for name in ("learn", "map", "review", "ask"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--repo")
        cmd.add_argument("--no-open", action="store_true", default=argparse.SUPPRESS)
        if name == "review":
            cmd.add_argument("target")
        if name == "ask":
            cmd.add_argument("question")
        if name == "learn":
            cmd.add_argument("--focus")
        if name == "map":
            cmd.add_argument("--force", action="store_true")
            cmd.add_argument("--no-wait", action="store_true")
    for name in ("status", "open", "quit", "doctor", "update", "prefetch"):
        commands.add_parser(name)
    skill = commands.add_parser("install-skill")
    skill.add_argument("--path")
    digest = commands.add_parser("digest")
    digest.add_argument("--schedule", action="store_true")
    digest.add_argument("--no-open", action="store_true", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    from . import operations

    if args.command not in {"update", "doctor", "quit", "status"}:
        threading.Thread(target=operations.check_updates, daemon=True).start()
    try:
        if args.command == "doctor":
            if not operations.doctor():
                raise SystemExit(1)
            return
        if args.command == "update":
            operations.update()
            return
        if args.command == "install-skill":
            operations.install_skill(args.path)
            return
        if args.command in {"status", "open", "quit"}:
            state = running()
            if not state:
                print("Scire is not running.")
                return
            if args.command == "status":
                print(f"Running on 127.0.0.1:{state['port']} · {state['build']}")
                return
            if args.command == "open":
                show(state)
                return
            api(state, "quit", {})
            print("Stopping Scire and its agents.")
            return
        if args.command in {"setup", "init"}:
            for path in args.repos:
                Store().add_repo(path)
            if args.connect:
                operations.connect(args.model)
            elif not Store().profile().get("model") and sys.stdin.isatty() and not args.model:
                print("Use an existing OpenCode login, or connect a provider.")
                if input("Connect a provider now? [y/N] ").strip().lower() in {"y", "yes"}:
                    operations.connect()
                else:
                    operations.select_model()
            elif args.model:
                profile = Store().profile()
                profile["model"] = args.model
                Store().save_profile(profile)
            serve(args.no_open)
            return
        if args.command in {"learn", "map", "review", "ask"}:
            repo = choose_repo(args.repo)
            state = ensure_server()
            value = wait_map(
                state, repo["id"], getattr(args, "force", False), not getattr(args, "no_wait", False)
            )
            if args.command == "map":
                if value:
                    print(f"Mapped {len(value['areas'])} areas and {len(value['concepts'])} concepts.")
                    return
                print("Mapping in the background.")
                return
            if args.command == "ask":
                result = api(state, "ask", {"repo": repo["id"], "question": args.question})
                show(state, f"/w/{repo['id']}/{result['session']}/", args.no_open)
                return
            result = api(
                state,
                "sessions",
                {
                    "repo": repo["id"],
                    "target": args.target if args.command == "review" else "learn",
                    "focus": getattr(args, "focus", None),
                },
            )
            show(state, result["url"], args.no_open)
            return
        if args.command == "prefetch":
            state = ensure_server()
            count = 0
            for repo in Store().repos():
                try:
                    wait_map(state, repo["id"])
                except ValueError as exc:
                    print(repo["name"] + ": " + str(exc), file=sys.stderr)
                    continue
                for pr in api(state, "reviews/" + repo["id"])["items"]:
                    if not pr["waiting"]:
                        continue
                    existing = any(
                        s.get("review", {}).get("head") == pr["headRefOid"]
                        and s.get("review", {}).get("number") == pr["number"]
                        and s["status"] not in {"error", "cancelled", "interrupted"}
                        for s in Store().sessions(repo["id"])
                    )
                    if existing:
                        continue
                    result = api(state, "sessions", {"repo": repo["id"], "target": str(pr["number"])})
                    api(state, f"sessions/{repo['id']}/{result['id']}/start", {})
                    count += 1
            print(f"Queued {count} waiting reviews. Open Scire to follow progress.")
            return
        if args.command == "digest":
            if args.schedule:
                operations.schedule_digest()
                return
            state = ensure_server()
            api(state, "digest", {})
            while True:
                value = api(state, "digest")
                if not value["running"]:
                    break
                time.sleep(1)
            result = value["value"]
            if result.get("error"):
                raise ValueError(result["error"])
            print(result.get("title", "Weekly digest") + "\n\n" + result.get("summary", ""))
            for item in result.get("repos", []):
                print("\n" + item["repo"] + "\n" + item.get("notes", ""))
            print("\nSaved: " + result.get("path", ""))
            return
        if not Store().profile().get("model") and sys.stdin.isatty():
            print("Welcome to Scire. Inference runs through your OpenCode provider login.")
            if input("Connect a provider now? [y/N] ").strip().lower() in {"y", "yes"}:
                operations.connect()
            else:
                operations.select_model()
        serve(args.no_open)
    except (ValueError, OSError, httpx.HTTPError, subprocess.SubprocessError) as exc:
        print("Scire: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
