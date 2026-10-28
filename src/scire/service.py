from __future__ import annotations
import asyncio
import copy
import hashlib
import json
import random
import time
import uuid
from pathlib import Path
from .agent import AgentRunner
from .git import default_ref, git, pinned_worktree, revision
from .knowledge import Knowledge
from .maps import validate_map, merge_map, public_map, concept_fingerprint
from .models import Module, Preview, RoundManifest, Triage, validate_module
from .paths import read_json, transaction, write_json
from .review import resolve_review, waiting_reviews, head_moved, post_comment, changed_line
from .skeleton import build_skeleton
from .source import resolve_anchor
from .store import Store


class Service:
    def __init__(self, runner=None):
        self.store = Store()
        self.runner = runner or AgentRunner()
        self.jobs = {}
        self.map_slots = asyncio.Semaphore(2)
        self.repo_locks = {}
        self.review_cache = {}
        self.maintenance = None

    async def start(self):
        # Interrupted runs are resumable, not silently labelled as still working.
        for s in self.store.sessions():
            if s["status"] in {"working", "queued"}:
                s["status"] = "interrupted"
                self.store.save_session(s)
        for repo in self.store.repos():
            self.queue_map(repo["id"])
        self.maintenance = asyncio.create_task(self.maintain())

    async def close(self):
        if self.maintenance:
            self.maintenance.cancel()
        for task in list(self.jobs.values()):
            task.cancel()
        await self.runner.close()
        await asyncio.gather(*list(self.jobs.values()), return_exceptions=True)
        if self.maintenance:
            await asyncio.gather(self.maintenance, return_exceptions=True)

    def spawn(self, key, coroutine):
        if key in self.jobs:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self.jobs[key] = task

        def finished(t):
            self.jobs.pop(key, None)
            try:
                t.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass  # Every worker stores a concrete error on its resource.

        task.add_done_callback(finished)

    def save_worker(self, s):
        disk = self.store.session(s["repo"], s["id"])
        for key in ("answers", "drafts", "posted", "topics", "depths"):
            if key in disk:
                s[key] = disk[key]
        self.store.save_session(s)

    def activity(self, s, message):
        if not message:
            return
        s["activity"] = (s["activity"] + [{"at": time.time(), "text": message}])[-60:]
        self.save_worker(s)

    async def maintain(self):
        while True:
            await asyncio.sleep(60)
            for repo in self.store.repos():
                self.queue_map(repo["id"])

    def queue_map(self, rid, force=False):
        key = "map:" + rid
        self.spawn(key, self.build_map(rid, force))

    async def build_map(self, rid, force=False):
        repo = self.store.repo(rid)
        path = self.store.repo_dir(rid) / "map.json"
        old = read_json(path, {})
        try:
            async with self.map_slots:
                ref = await asyncio.to_thread(default_ref, Path(repo["path"]))
                sha = await asyncio.to_thread(revision, Path(repo["path"]), ref)
                if not force and old.get("status") == "ready" and old.get("sha") == sha:
                    return
                if (
                    not force
                    and old.get("status") == "error"
                    and old.get("attempt_sha") == sha
                    and time.time() - old.get("failed_at", 0) < 86400
                ):
                    return
                write_json(
                    path,
                    {
                        **old,
                        "status": "working",
                        "error": None,
                        "activity": "Preparing the default-branch snapshot",
                        "attempt_sha": sha,
                    },
                )
                lock = self.repo_locks.setdefault(rid, asyncio.Lock())
                async with lock:
                    source, sha = await asyncio.to_thread(pinned_worktree, repo)
                skeleton = await asyncio.to_thread(build_skeleton, source)
                write_json(self.store.repo_dir(rid) / "skeleton.json", skeleton)
                profile = self.store.profile()
                job = self.store.repo_dir(rid) / "jobs" / uuid.uuid4().hex

                def progress(message):
                    current_map = read_json(path, {})
                    write_json(path, {**current_map, "activity": message, "last_activity": time.time()})

                result = await self.runner.run(
                    "map",
                    source,
                    {"skeleton": self.context_skeleton(skeleton), "existing_map": old},
                    job,
                    profile["model"],
                    lambda output: validate_map(source, read_json(output / "map.json", {}), skeleton),
                    progress,
                    timeout=330,
                    budget=3,
                )
                value = merge_map(read_json(path, old), result["value"])
                value.update(
                    status="ready",
                    source=str(source),
                    sha=sha,
                    fingerprint=skeleton["fingerprint"],
                    metrics=result["metrics"],
                    error=None,
                )
                write_json(path, value)
                self.store.event(rid, "map_built", {"sha": sha, "metrics": result["metrics"]})
        except asyncio.CancelledError:
            write_json(path, {**read_json(path, old), "status": "interrupted"})
            raise
        except Exception as exc:
            write_json(
                path,
                {
                    **read_json(path, old),
                    "status": "error",
                    "error": str(exc),
                    "last_activity": time.time(),
                    "failed_at": time.time(),
                },
            )

    def context_skeleton(self, value):
        return {k: v[:1000] if isinstance(v, list) else v for k, v in value.items() if k != "fingerprints"}

    async def new_session(self, rid, target="learn", focus=None, topic=None):
        repo = self.store.repo(rid)
        values = {}
        if target != "learn":
            review = await asyncio.to_thread(resolve_review, repo, target)
            values = {
                "review": review,
                "source": review["source"],
                "title": review["title"],
                "head_moved": False,
            }
        else:
            lock = self.repo_locks.setdefault(rid, asyncio.Lock())
            async with lock:
                source, sha = await asyncio.to_thread(pinned_worktree, repo)
            values = {"source": str(source), "sha": sha}
        s = self.store.new_session(rid, target, focus=focus, **values)
        if topic:
            s["topics"].append({"question": topic, "concepts": [focus] if focus else [], "at": time.time()})
        self.store.save_session(s)
        return s

    def map_for(self, rid):
        value = read_json(self.store.repo_dir(rid) / "map.json", {})
        if not value.get("areas") or not value.get("concepts"):
            raise ValueError("Wait for the repository map, or retry its build first")
        return value

    def start_round(self, rid, sid, depths=None, focus=None, allow_incomplete=False):
        key = "round:" + sid
        if key in self.jobs:
            raise ValueError("This session already has a round running")
        s = self.store.session(rid, sid)
        m = self.map_for(rid)
        if depths is not None:
            known = {a["id"] for a in m["areas"]}
            if any(
                k not in known or v not in {"skip", "skim", "standard", "deep"} for k, v in depths.items()
            ):
                raise ValueError("Invalid area depth")
            if not any(v != "skip" for v in depths.values()):
                raise ValueError("Choose at least one area to learn")
            s["depths"] = depths
        if not s.get("depths"):
            s["depths"] = {a["id"]: "standard" for a in m["areas"]}
        if s["round"] and s["status"] == "ready" and not allow_incomplete and not self.round_complete(s):
            raise ValueError("Answer this round’s questions before continuing")
        s["round"] += 1
        s["status"] = "queued"
        s["error"] = None
        s["started_learning"] = True
        s["round_started_at"] = time.time()
        s["next"] = []
        self.store.save_session(s)
        self.spawn(key, self.generate(s, focus))
        return s

    def round_complete(self, s):
        modules = [m for m in s["modules"] if m.get("round") == s["round"] and m.get("status") == "ready"]
        return (
            bool(modules)
            and all(q["key"] in s["answers"] for m in modules for q in m["questions"])
            and s["status"] != "working"
        )

    def make_orders(self, s, module):
        path = self.store.session_dir(s["repo"], s["id"]) / "orders.json"
        orders = read_json(path, {})
        counts = [0, 0, 0, 0]
        previous = {
            q["key"]: q for m in s["modules"] if m.get("status") == "ready" for q in m.get("questions", [])
        }
        for key, order in orders.items():
            if key in previous:
                counts[order.index(previous[key]["correct"])] += 1
        for q in module["questions"]:
            if q["key"] not in orders:
                target = min(range(4), key=lambda n: (counts[n], random.random()))
                remaining = [o["key"] for o in q["options"] if o["key"] != q["correct"]]
                random.shuffle(remaining)
                order = remaining[:]
                order.insert(target, q["correct"])
                orders[q["key"]] = order
                counts[target] += 1
        write_json(path, orders)

    async def generate(self, s, focus=None):
        rid = s["repo"]
        m = self.map_for(rid)
        source = Path(s["source"])
        round_no = s["round"]
        folder = self.store.session_dir(rid, s["id"]) / "rounds" / str(round_no)
        published = {}
        preview_ids = set()
        try:
            s["status"] = "working"
            self.activity(s, "Mapping this round to your current understanding")
            skeleton = await asyncio.to_thread(build_skeleton, source)
            profile = self.store.profile()
            kind = (
                "review"
                if s.get("review")
                else "concept"
                if focus
                else "calibrate"
                if round_no == 1
                else "learn"
            )
            payload = {
                "skeleton": self.context_skeleton(skeleton),
                "map": m if s.get("review") else {**m, "concepts": public_map(self.store, rid)["concepts"]},
                "learner": Knowledge(self.store, rid).states(
                    {c["id"]: concept_fingerprint(source, c) for c in m["concepts"]}
                ),
                "previous_modules": [old["id"] for old in s["modules"]],
                "profile": {"role": profile.get("role", "")},
                "depths": s["depths"],
                "round": round_no,
                "focus": focus or s.get("focus"),
                "topics": s["topics"],
                "review": s.get("review"),
                "previous_questions": [
                    q
                    for old in s["modules"]
                    if old.get("status") == "ready"
                    for q in old.get("questions", [])
                ],
                "answers": s["answers"],
            }

            def stream(output):
                for preview_path in sorted(output.glob("modules/*/preview.json")):
                    try:
                        preview = Preview.model_validate(read_json(preview_path)).model_dump()
                        mid = preview["id"]
                        if any(old["id"] == mid and old.get("round") != round_no for old in s["modules"]):
                            raise ValueError("Module ID was reused from an earlier round")
                        if mid not in preview_ids and mid not in published:
                            preview_ids.add(mid)
                            s["modules"].append({**preview, "round": round_no, "status": "preview"})
                            self.save_worker(s)
                        module_path = preview_path.parent / "module.json"
                        if module_path.exists() and mid not in published:
                            module = validate_module(source, read_json(module_path), m, bool(s.get("review")))
                            if module["id"] != mid:
                                raise ValueError("Preview ID and module ID differ")
                            prior_keys = {
                                q["key"]
                                for old in s["modules"]
                                if old.get("status") == "ready"
                                for q in old["questions"]
                            }
                            if any(q["key"] in prior_keys for q in module["questions"]):
                                raise ValueError("Question key was reused from an earlier module")
                            module.update(round=round_no, status="ready", index=preview["index"])
                            self.make_orders(s, module)
                            s["modules"] = [
                                old
                                for old in s["modules"]
                                if not (old["id"] == mid and old.get("round") == round_no)
                            ] + [module]
                            published[mid] = copy.deepcopy(module)
                            self.register_concepts(rid, module)
                            self.activity(s, "Ready to read · " + module["title"])
                    except (ValueError, OSError, json.JSONDecodeError):
                        continue

            def validate(output):
                manifest = RoundManifest.model_validate(read_json(output / "round.json", {}))
                modules = []
                seen = set()
                all_questions = set()
                for relative in manifest.modules:
                    path = (output / relative).resolve()
                    if not path.is_relative_to(output.resolve()) or path.suffix != ".json":
                        raise ValueError("Module path escapes output directory")
                    if path.name != "module.json" or path.parent.parent != output.resolve() / "modules":
                        raise ValueError("Use modules/<name>/module.json paths")
                    module = validate_module(source, read_json(path), m, bool(s.get("review")))
                    if any(
                        old["id"] == module["id"] and old.get("round") != round_no for old in s["modules"]
                    ):
                        raise ValueError("Module ID was reused from an earlier round; choose a new ID")
                    if module["id"] in seen:
                        raise ValueError("Round repeats a module")
                    seen.add(module["id"])
                    if module["id"] in published:
                        for key in Module.model_fields:
                            if module[key] != published[module["id"]][key]:
                                raise ValueError(
                                    "A published module was changed; restore its original content"
                                )
                    for q in module["questions"]:
                        if q["key"] in all_questions:
                            raise ValueError("Round repeats a question key")
                        all_questions.add(q["key"])
                    preview = Preview.model_validate(read_json(path.parent / "preview.json", {}))
                    if preview.id != module["id"]:
                        raise ValueError("Preview ID and module ID differ")
                    prior_keys = {
                        q["key"]
                        for old in s["modules"]
                        if old.get("round") != round_no and old.get("status") == "ready"
                        for q in old["questions"]
                    }
                    if any(q["key"] in prior_keys for q in module["questions"]):
                        raise ValueError("Question key was reused from an earlier round")
                    modules.append(module)
                if set(published) - seen:
                    raise ValueError("Round dropped a published module")
                return manifest.model_dump()

            result = await self.runner.run(
                kind,
                source,
                payload,
                folder,
                profile["model"],
                validate,
                lambda text: self.activity(s, text),
                stream,
                timeout=330,
                budget=3,
            )
            stream(folder / "output")
            manifest = result["value"]
            if len(published) != len(manifest["modules"]):
                raise ValueError("A module could not be published; check stable IDs and previews")
            s["status"] = "ready"
            s["next"] = manifest["next"]
            s["cost"] += result["metrics"]["cost"]
            s["seconds"] += result["metrics"]["seconds"]
            if s["target"] == "learn":
                s["title"] = manifest["title"]
            self.store.event(
                rid, "round_ready", {"session": s["id"], "round": round_no, "metrics": result["metrics"]}
            )
            self.activity(s, "This round is ready. Modules already read remain available.")
        except asyncio.CancelledError:
            s["status"] = "cancelled"
            self.save_worker(s)
            raise
        except Exception as exc:
            s["status"] = "error"
            s["error"] = str(exc)
            self.save_worker(s)
            metrics = read_json(folder / "metrics.json", {})
            if metrics:
                s["cost"] += metrics.get("cost", 0)
                s["seconds"] += metrics.get("seconds", 0)
                self.save_worker(s)

    def register_concepts(self, rid, module):
        if not module["new_concepts"]:
            return
        path = self.store.repo_dir(rid) / "map.json"
        with transaction():
            m = read_json(path, {})
            source = Path(m.get("source", self.store.repo(rid)["path"]))
            known = {c["id"] for c in m.get("concepts", [])}
            for c in module["new_concepts"]:
                if c["id"] in known:
                    continue
                try:
                    for a in c["anchors"]:
                        resolve_anchor(source, a)
                    c["pending"] = False
                except (ValueError, OSError):
                    c["pending"] = True
                m["concepts"].append(c)
                known.add(c["id"])
            write_json(path, m)

    def public_session(self, rid, sid):
        s = copy.deepcopy(self.store.session(rid, sid))
        orders = read_json(self.store.session_dir(rid, sid) / "orders.json", {})
        for module in s["modules"]:
            if module.get("status") != "ready":
                continue
            all_answered = all(q["key"] in s["answers"] for q in module["questions"])
            for q in module["questions"]:
                by_key = {o["key"]: o for o in q["options"]}
                q["options"] = [by_key[key] for key in orders.get(q["key"], list(by_key))]
                q["options"].append({"key": "unknown", "text": "I don’t know yet"})
                if q["key"] not in s["answers"]:
                    for key in ("correct", "explanation", "misconception"):
                        q.pop(key, None)
            if not all_answered:
                module["findings"] = []
            module["findings_unlocked"] = all_answered
        if s.get("review"):
            s["review"] = {k: v for k, v in s["review"].items() if k not in {"diff", "source"}}
        s["complete"] = self.round_complete(s)
        s["map"] = public_map(self.store, rid)
        return s

    def answer(self, rid, sid, key, choice):
        with transaction():
            s = self.store.session(rid, sid)
            if key in s["answers"]:
                return s["answers"][key]
            module = next(
                (
                    m
                    for m in s["modules"]
                    if m.get("status") == "ready" and any(q["key"] == key for q in m["questions"])
                ),
                None,
            )
            if not module:
                raise ValueError("Question is not ready")
            q = next(q for q in module["questions"] if q["key"] == key)
            if choice not in {o["key"] for o in q["options"]} | {"unknown"}:
                raise ValueError("Invalid choice")
            correct = choice == q["correct"]
            anchor = module["resolved"][q["ref"]]
            concept = next((c for c in self.map_for(rid)["concepts"] if c["id"] == q["concept"]), None)
            fingerprint = (
                concept_fingerprint(Path(s["source"]), concept) if concept else anchor["fingerprint"]
            )
            before, after = Knowledge(self.store, rid).record(
                q["concept"], f"{sid}:{key}", choice, correct, q["misconception"], fingerprint
            )
            result = {
                "choice": choice,
                "correct": correct,
                "correct_option": q["correct"],
                "explanation": q["explanation"],
                "at": time.time(),
            }
            s["answers"][key] = result
            self.store.save_session(s)
            self.store.event(
                rid,
                "question_answered",
                {
                    "session": sid,
                    "round": module["round"],
                    "question": q,
                    "response": result,
                    "explanation_shown": {k: module[k] for k in ("why", "flow", "key_code", "pitfalls")},
                    "learner_before": before,
                    "learner_after": after,
                },
            )
            return result

    def what_next(self, rid, sid):
        s = self.store.session(rid, sid)
        if not self.round_complete(s):
            raise ValueError("Complete this round first")
        m = public_map(self.store, rid)
        areas = sorted(m["areas"], key=lambda a: (a["mastery"], -a["importance"]))
        concepts = sorted(m["concepts"], key=lambda c: (c["mastery"], -c["importance"]))
        return {"areas": areas[:4], "concepts": concepts[:6], "suggestions": s.get("next", [])}

    async def ask(self, rid, question, sid=None):
        question = question.strip()
        if not question or len(question) > 2000:
            raise ValueError("Ask a question of 1–2000 characters")
        m = self.map_for(rid)
        profile = self.store.profile()
        repo = self.store.repo(rid)
        if sid:
            if "round:" + sid in self.jobs:
                raise ValueError("Wait for this round to finish before adding a topic")
            s = self.store.session(rid, sid)
            source = Path(s["source"])
        else:
            lock = self.repo_locks.setdefault(rid, asyncio.Lock())
            async with lock:
                source, _ = await asyncio.to_thread(pinned_worktree, repo)
            s = None
        folder = self.store.repo_dir(rid) / "topics" / uuid.uuid4().hex

        def validate(output):
            value = Triage.model_validate(read_json(output / "triage.json", {}))
            known = {c["id"] for c in m["concepts"]}
            if any(c not in known for c in value.concepts):
                raise ValueError("Topic references an unknown concept")
            if value.route == "quick" and not value.refs:
                raise ValueError("A quick answer needs code evidence")
            for a in value.refs:
                resolve_anchor(source, a)
            return value.model_dump()

        result = await self.runner.run(
            "triage",
            source,
            {"question": question, "map": m},
            folder,
            profile.get("cheap_model") or profile["model"],
            validate,
            lambda text: None,
            timeout=90,
            budget=0.35,
        )
        topic = {
            "question": question,
            "concepts": result["value"]["concepts"],
            "at": time.time(),
            "route": result["value"]["route"],
            "answer": result["value"]["answer"],
            "refs": result["value"]["refs"],
            "metrics": result["metrics"],
        }
        if s is None:
            s = await self.new_session(rid, topic=question)
        else:
            s["topics"].append(topic)
        if not any(t.get("question") == question and t.get("route") for t in s["topics"]):
            s["topics"] = [t for t in s["topics"] if t.get("question") != question] + [topic]
        s["cost"] += result["metrics"]["cost"]
        s["seconds"] += result["metrics"]["seconds"]
        self.store.save_session(s)
        if topic["route"] != "quick":
            focus = topic["concepts"][0] if topic["route"] == "focused" and topic["concepts"] else None
            if s.get("started_learning"):
                self.start_round(rid, s["id"], focus=focus, allow_incomplete=True)
            else:
                s["pending_focus"] = focus
                self.store.save_session(s)
        return {"session": s["id"], "topic": topic}

    async def reviews(self, rid):
        cached = self.review_cache.get(rid)
        if cached and time.time() - cached["at"] < 60:
            return cached
        repo = self.store.repo(rid)
        try:
            result = {
                "items": await asyncio.to_thread(waiting_reviews, repo),
                "error": None,
                "at": time.time(),
            }
        except ValueError as exc:
            result = {"items": [], "error": str(exc), "at": time.time()}
        try:
            result["branches"] = git(
                Path(repo["path"]), "for-each-ref", "--format=%(refname:short)", "refs/heads"
            ).splitlines()
        except ValueError:
            result["branches"] = []
        self.review_cache[rid] = result
        return result

    async def check_head(self, rid, sid):
        s = self.store.session(rid, sid)
        if not s.get("review"):
            return {"moved": False}
        moved = await asyncio.to_thread(head_moved, self.store.repo(rid), s["review"])
        s = self.store.session(rid, sid)
        s["head_moved"] = moved
        self.store.save_session(s)
        return {"moved": moved}

    def finding_draft(self, rid, sid, mid, fid, stance, body):
        if stance not in {"agree", "unsure", "disagree"}:
            raise ValueError("Choose agree, unsure or disagree")
        s = self.store.session(rid, sid)
        module = next((m for m in s["modules"] if m["id"] == mid and m.get("status") == "ready"), None)
        if not module or not all(q["key"] in s["answers"] for q in module["questions"]):
            raise ValueError("Answer the module’s questions before viewing findings")
        f = next((f for f in module["findings"] if f["key"] == fid), None)
        if not f:
            raise ValueError("Unknown finding")
        if len(body) > 10000:
            raise ValueError("Comment exceeds 10,000 characters")
        s.setdefault("drafts", {})[fid] = {"stance": stance, "body": body}
        self.store.save_session(s)
        return s["drafts"][fid]

    def comment_preview(self, rid, sid, mid, fid):
        s = self.store.session(rid, sid)
        module = next((m for m in s["modules"] if m["id"] == mid and m.get("status") == "ready"), None)
        if not module or not all(q["key"] in s["answers"] for q in module["questions"]):
            raise ValueError("Finding is locked")
        finding = next((f for f in module["findings"] if f["key"] == fid), None)
        if not finding:
            raise ValueError("Unknown finding")
        anchor = module["resolved"][finding["ref"]]
        draft = s.get("drafts", {}).get(fid, {"body": finding["draft"], "stance": "unsure"})
        value = {
            "finding": fid,
            "module": mid,
            "body": draft["body"],
            "path": anchor["path"],
            "line": anchor["key_lines"][0] if anchor["key_lines"] else anchor["start_line"],
            "head": s["review"]["head"],
        }
        lines = [
            line
            for line in range(anchor["start_line"], anchor["end_line"] + 1)
            if changed_line(s["review"]["diff"], anchor["path"], line)
        ]
        if lines:
            value["line"] = next((line for line in anchor["key_lines"] if line in lines), lines[0])
        value["postable"] = s["review"]["kind"] == "pr" and bool(lines)
        value["confirmation"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        return value

    async def publish_comment(self, rid, sid, mid, fid, confirmation):
        value = self.comment_preview(rid, sid, mid, fid)
        if confirmation != value["confirmation"]:
            raise ValueError("Comment changed. Preview the exact text and lines again before posting.")
        s = self.store.session(rid, sid)
        if fid in s.get("posted", {}):
            return {"url": s["posted"][fid]}
        url = await asyncio.to_thread(
            post_comment, self.store.repo(rid), s["review"], value["path"], value["line"], value["body"]
        )
        s.setdefault("posted", {})[fid] = url
        self.store.save_session(s)
        return {"url": url}
