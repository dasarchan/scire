from __future__ import annotations
import asyncio
import hmac
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .build import build_id
from .paths import write_json, read_json, home
from .store import Store
from .maps import public_map
from .source import resolve_anchor
from .paths import safe_source
from markdown_it import MarkdownIt

STATIC = Path(__file__).parent / "static"


def create_app(token=None, service=None):
    token = token or secrets.token_urlsafe(32)
    active_build = build_id()
    store = Store()

    @asynccontextmanager
    async def lifespan(app):
        if service:
            await service.start()
        yield
        if service:
            await service.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.token = token
    app.state.quit = lambda: None
    app.state.service = service
    renderer = MarkdownIt("commonmark", {"html": False}).enable("table")
    renderer.disable("image")

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1"}:
            return JSONResponse({"error": "Loopback host required"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"http://{request.headers.get('host')}":
            return JSONResponse({"error": "Cross-origin request denied"}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-scire-token") or request.query_params.get("token", "")
            if not hmac.compare_digest(supplied, token):
                return JSONResponse({"error": "Session token required"}, status_code=401)
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing_field(request, exc):
        return JSONResponse({"error": "Missing required field"}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        return JSONResponse({"error": "Source or session not found"}, status_code=404)

    @app.get("/api/status")
    async def status():
        return {
            "ok": True,
            "build": active_build,
            "repos": len(store.repos()),
            "running": len(service.jobs) if service else 0,
        }

    @app.get("/api/home")
    async def home_state():
        repos = [
            {
                **r,
                "map": public_map(store, r["id"]),
                "onboarding": read_json(store.repo_dir(r["id"]) / "onboarding.json", {}),
            }
            for r in store.repos()
        ]
        return {
            "profile": store.profile(),
            "repos": repos,
            "sessions": [
                {
                    **{
                        k: s[k]
                        for k in (
                            "id",
                            "repo",
                            "title",
                            "target",
                            "status",
                            "round",
                            "created_at",
                            "updated_at",
                            "cost",
                            "seconds",
                        )
                    },
                    "calibration": s.get("calibration", False),
                    "complete": service.round_complete(s) if service else False,
                    "answered_count": len(s["answers"]),
                    "question_count": sum(
                        len(m.get("questions", [])) for m in s["modules"] if m.get("status") == "ready"
                    ),
                }
                for s in store.sessions()
            ],
            "build": active_build,
        }

    @app.post("/api/setup")
    async def setup(request: Request):
        value = await request.json()
        if value.get("paths"):
            raise ValueError("Connect repositories in your terminal with scire setup")
        if any(
            not isinstance(value[k], str) or len(value[k]) > 2000
            for k in ("name", "role", "model", "cheap_model")
            if k in value
        ):
            raise ValueError("Profile fields must be text")
        profile = {
            **store.profile(),
            **{k: value[k] for k in ("name", "role", "model", "cheap_model") if k in value},
            "setup": True,
        }
        prior = store.profile()
        store.save_profile(profile)
        if service and value.get("map_now", True) and profile.get("model"):
            for repo in store.repos():
                service.queue_map(repo["id"], profile.get("model") != prior.get("model"))
        return {"ok": True}

    @app.post("/api/repos/sync")
    async def sync_repos():
        if service:
            service.sync_repos(retry_errors=True)
        return {"repos": store.repos()}

    @app.post("/api/repos/{rid}/onboarding")
    async def repository_onboarding(rid: str, request: Request):
        store.repo(rid)
        value = await request.json()
        if value.get("calibration") not in {"skipped", "offered"}:
            raise ValueError("Invalid calibration preference")
        write_json(store.repo_dir(rid) / "onboarding.json", {"calibration": value["calibration"]})
        return {"ok": True}

    @app.get("/api/models")
    async def models():
        from .operations import available_models

        return {"models": await asyncio.to_thread(available_models)}

    @app.post("/api/open")
    async def open_app():
        import webbrowser

        state = read_json(home() / "server.json", {})
        webbrowser.open(f"http://127.0.0.1:{state.get('port')}/#{token}")
        return {"ok": True}

    @app.post("/api/quit")
    async def quit_app():
        asyncio.get_running_loop().call_later(0.2, app.state.quit)
        return {"ok": True}

    @app.get("/api/maps/{rid}")
    async def map_state(rid: str):
        store.repo(rid)
        return public_map(store, rid)

    @app.post("/api/maps/{rid}/build")
    async def build_map(rid: str):
        store.repo(rid)
        if not service:
            raise ValueError("Learning service is unavailable")
        service.queue_map(rid, True)
        return {"ok": True}

    @app.post("/api/digest")
    async def digest():
        service.spawn("digest", service.digest())
        return {"ok": True}

    @app.get("/api/digest")
    async def digest_status():
        return {"running": "digest" in service.jobs, "value": read_json(home() / "digest.json", {})}

    @app.get("/api/reviews/{rid}")
    async def review_list(rid: str):
        return await service.reviews(rid)

    @app.post("/api/sessions")
    async def new_session(request: Request):
        value = await request.json()
        s = await service.new_session(
            value["repo"],
            value.get("target", "learn"),
            value.get("focus"),
            minutes=value.get("minutes", 5),
            calibration=value.get("calibration", False),
        )
        return {"id": s["id"], "repo": s["repo"], "url": f"/w/{s['repo']}/{s['id']}/"}

    @app.get("/api/sessions/{rid}/{sid}")
    async def session(rid: str, sid: str):
        return service.public_session(rid, sid)

    @app.get("/api/sessions/{rid}/{sid}/changes")
    async def review_changes(rid: str, sid: str):
        from .review import diff_hunks

        value = store.session(rid, sid)
        review = value.get("review")
        if not review:
            raise ValueError("This session is not a change review")
        return {
            "head": review["head"],
            "base": review.get("base", ""),
            "files": diff_hunks(review.get("diff", "")),
        }

    @app.post("/api/sessions/{rid}/{sid}/start")
    async def start_round(rid: str, sid: str, request: Request):
        value = await request.json()
        service.start_round(
            rid,
            sid,
            value.get("depths"),
            value.get("focus"),
            minutes=value.get("minutes"),
            calibration=value.get("calibration"),
        )
        return {"ok": True}

    @app.post("/api/sessions/{rid}/{sid}/answer")
    async def answer(rid: str, sid: str, request: Request):
        value = await request.json()
        return service.answer(rid, sid, value["key"], value["choice"])

    @app.post("/api/sessions/{rid}/{sid}/cancel")
    async def cancel(rid: str, sid: str):
        s = store.session(rid, sid)
        task = service.jobs.get("round:" + sid)
        if task:
            task.cancel()
            s["status"] = "cancelled"
            store.save_session(s)
        return {"ok": True}

    @app.get("/api/sessions/{rid}/{sid}/next")
    async def what_next(rid: str, sid: str):
        return service.what_next(rid, sid)

    @app.get("/api/sessions/{rid}/{sid}/head")
    async def check_head(rid: str, sid: str):
        return await service.check_head(rid, sid)

    @app.get("/api/sessions/{rid}/{sid}/topics/{index}/source/{ref}")
    async def topic_source(rid: str, sid: str, index: int, ref: int):
        s = store.session(rid, sid)
        if index < 0 or index >= len(s["topics"]) or ref < 0 or ref >= len(s["topics"][index]["refs"]):
            raise ValueError("Unknown topic anchor")
        return resolve_anchor(Path(s["source"]), s["topics"][index]["refs"][ref])

    @app.get("/api/sessions/{rid}/{sid}/source/{mid}/{aid}")
    async def source(rid: str, sid: str, mid: str, aid: str):
        s = store.session(rid, sid)
        module = next((m for m in s["modules"] if m["id"] == mid and m.get("status") == "ready"), None)
        if not module or aid not in module["resolved"]:
            raise ValueError("Unknown code anchor")
        return resolve_anchor(Path(s["source"]), module["resolved"][aid])

    @app.get("/api/source/{rid}")
    async def source_file(rid: str, path: str):
        root = Path(store.repo(rid)["path"])
        target = safe_source(root, path)
        return {"path": path, "text": target.read_text()}

    @app.post("/api/ask")
    async def ask(request: Request):
        value = await request.json()
        return await service.ask(value["repo"], value["question"], value.get("session"))

    @app.post("/api/sessions/{rid}/{sid}/finding/{mid}/{fid}")
    async def save_finding(rid: str, sid: str, mid: str, fid: str, request: Request):
        value = await request.json()
        return service.finding_draft(rid, sid, mid, fid, value["stance"], value["body"])

    @app.get("/api/sessions/{rid}/{sid}/finding/{mid}/{fid}/preview")
    async def preview_comment(rid: str, sid: str, mid: str, fid: str):
        return service.comment_preview(rid, sid, mid, fid)

    @app.post("/api/sessions/{rid}/{sid}/finding/{mid}/{fid}/post")
    async def post_finding(rid: str, sid: str, mid: str, fid: str, request: Request):
        value = await request.json()
        if value.get("explicit_action") is not True:
            raise ValueError("An explicit post action is required")
        return await service.publish_comment(rid, sid, mid, fid, value["confirmation"])

    @app.post("/api/render")
    async def render_markdown(request: Request):
        value = await request.json()
        text = value.get("text", "")
        if len(text) > 30000:
            raise ValueError("Markdown is too long")
        return {"html": renderer.render(text)}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/{path:path}")
    async def index(path: str):
        return HTMLResponse((STATIC / "index.html").read_text())

    return app
