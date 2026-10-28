from __future__ import annotations
import time
import uuid
from pathlib import Path
from .paths import home, read_json, repo_id, transaction, write_json


class Store:
    def repos(self) -> list[dict]:
        return read_json(home() / "repos.json", [])

    def repo(self, rid: str) -> dict:
        result = next((r for r in self.repos() if r["id"] == rid), None)
        if result is None:
            raise ValueError("Unknown repository")
        return result

    def add_repo(self, path: str) -> dict:
        root = Path(path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Choose a repository directory")
        repo = {"id": repo_id(root), "path": str(root), "name": root.name, "added_at": time.time()}
        with transaction():
            repos = self.repos()
            if not any(r["id"] == repo["id"] for r in repos):
                repos.append(repo)
                write_json(home() / "repos.json", repos)
        self.repo_dir(repo["id"]).mkdir(parents=True, exist_ok=True)
        return self.repo(repo["id"])

    def repo_dir(self, rid: str) -> Path:
        if not rid.isalnum():
            raise ValueError("Invalid repository ID")
        return home() / "repos" / rid

    def profile(self) -> dict:
        return read_json(
            home() / "profile.json", {"name": "", "role": "", "model": "", "cheap_model": "", "setup": False}
        )

    def save_profile(self, profile: dict):
        write_json(home() / "profile.json", profile)

    def sessions(self, rid: str | None = None) -> list[dict]:
        roots = [self.repo_dir(rid)] if rid else [self.repo_dir(r["id"]) for r in self.repos()]
        items = []
        for root in roots:
            for path in (root / "sessions").glob("*/session.json"):
                items.append(read_json(path))
        return sorted(items, key=lambda s: s["updated_at"], reverse=True)

    def new_session(self, rid: str, target: str = "learn", **values) -> dict:
        self.repo(rid)
        now = time.time()
        s = {
            "id": uuid.uuid4().hex[:16],
            "repo": rid,
            "target": target,
            "title": "Learn the codebase",
            "created_at": now,
            "updated_at": now,
            "status": "idle",
            "round": 0,
            "modules": [],
            "answers": {},
            "depths": {},
            "topics": [],
            "activity": [],
            "cost": 0.0,
            "seconds": 0.0,
            "started_learning": False,
            **values,
        }
        self.save_session(s)
        return s

    def session_dir(self, rid: str, sid: str) -> Path:
        if not sid.isalnum():
            raise ValueError("Invalid session ID")
        return self.repo_dir(rid) / "sessions" / sid

    def session(self, rid: str, sid: str) -> dict:
        result = read_json(self.session_dir(rid, sid) / "session.json")
        if result is None:
            raise ValueError("Session not found")
        return result

    def save_session(self, session: dict):
        session["updated_at"] = time.time()
        write_json(self.session_dir(session["repo"], session["id"]) / "session.json", session)

    def event(self, rid: str, kind: str, value: dict):
        path = self.repo_dir(rid) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        with transaction():
            with path.open("a") as stream:
                stream.write(
                    json.dumps({"version": 1, "time": time.time(), "type": kind, "data": value}) + "\n"
                )
            path.chmod(0o600)
