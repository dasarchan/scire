from __future__ import annotations
import copy
import json
import math
import time
from functools import lru_cache
from pathlib import Path
from .paths import read_json, transaction, write_json
from .store import Store

PRIOR, LEARN = 0.20, 0.12
HALF_LIFE_DAYS = 45


def response_likelihoods(correct: str) -> dict:
    return {
        key: {
            "known": 0.86 if key == correct else 0.02 if key == "unknown" else 0.04,
            "unknown": 0.25 if key == correct else 0.12 if key == "unknown" else 0.21,
        }
        for key in ["a", "b", "c", "d", "unknown"]
    }


def current(state: dict | None, fingerprint: str | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    state = copy.deepcopy(
        state
        or {
            "mastery": PRIOR,
            "attempts": 0,
            "correct": 0,
            "misconceptions": [],
            "updated_at": now,
            "fingerprint": fingerprint,
            "observations": [],
        }
    )
    elapsed = max(0, now - state["updated_at"]) / 86400
    state["mastery"] = PRIOR + (state["mastery"] - PRIOR) * math.exp(-math.log(2) * elapsed / HALF_LIFE_DAYS)
    if fingerprint and state.get("fingerprint") and fingerprint != state["fingerprint"]:
        state["mastery"] = PRIOR + (state["mastery"] - PRIOR) * 0.55
        state["code_changed"] = True
    state["code_changed"] = bool(
        fingerprint and state.get("fingerprint") and fingerprint != state["fingerprint"]
    )
    state["confidence"] = 1 - math.exp(-state["attempts"] / 5)
    return state


def observe(state, answer, correct, misconception="", fingerprint="", now=None, likelihoods=None):
    now = time.time() if now is None else now
    result = current(state, fingerprint, now)
    p = result["mastery"]
    # A choice has P(response | knows) and P(response | does not know).
    # This distinguishes diagnostic distractors from ambiguous wrong answers.
    likelihood = (
        likelihoods or response_likelihoods(answer if correct else ("b" if answer == "a" else "a"))
    )[answer]
    known, unknown = likelihood["known"], likelihood["unknown"]
    posterior = p * known / max(1e-12, p * known + (1 - p) * unknown)
    result["mastery"] = min(0.98, posterior + (1 - posterior) * LEARN)
    result["attempts"] += 1
    result["correct"] += int(correct)
    result["updated_at"], result["fingerprint"] = now, fingerprint
    result["code_changed"] = False
    result["confidence"] = 1 - math.exp(-result["attempts"] / 5)
    result["observations"] = (
        result.get("observations", [])
        + [
            {
                "at": now,
                "correct": correct,
                "unknown": answer == "unknown",
                "answer": answer,
                "likelihood": likelihood,
                "posterior_before_feedback": posterior,
            }
        ]
    )[-100:]
    if not correct and answer != "unknown" and misconception:
        result["misconceptions"] = list(dict.fromkeys(result["misconceptions"] + [misconception]))[-8:]
    return result


def replay(events: list[dict]) -> tuple[dict, set]:
    values, seen = {}, set()
    for event in sorted(events, key=lambda e: e.get("time", 0)):
        data = event.get("data", {})
        if event.get("type") == "learner_import":
            for concept, state in data.get("states", {}).items():
                values.setdefault(concept, copy.deepcopy(state))
        if event.get("type") != "assessment" or data.get("key") in seen:
            continue
        key, concept = data["key"], data["concept"]
        seen.add(key)
        if data.get("format") == 2:
            values[concept] = observe(
                values.get(concept),
                data["answer"],
                data["correct"],
                data.get("misconception", ""),
                data.get("fingerprint", ""),
                data.get("observed_at", event["time"]),
                data["likelihoods"],
            )
        else:
            # Earlier releases logged complete before/after states. Preserve that
            # historical evidence exactly, then replay new observations above it.
            after = data["after"]
            observation = after.get("observations", [{}])[-1]
            correct = observation.get(
                "correct", after.get("correct", 0) > data.get("before", {}).get("correct", 0)
            )
            likelihood = {
                data["answer"]: {
                    "known": 0.05 if data["answer"] == "unknown" else 0.9 if correct else 0.1,
                    "unknown": 0.95 if data["answer"] == "unknown" else 0.25 if correct else 0.75,
                }
            }
            if concept not in values and data.get("before", {}).get("attempts", 0):
                values[concept] = copy.deepcopy(data["before"])
            values[concept] = observe(
                values.get(concept),
                data["answer"],
                correct,
                (after.get("misconceptions") or [""])[-1],
                after.get("fingerprint", ""),
                observation.get("at", event["time"]),
                likelihood,
            )
    return values, seen


@lru_cache(maxsize=32)
def replay_log(path: str, modified: int, size: int):
    # Cache only deterministic replay, keyed by the append-only log's identity.
    # All callers receive copies; learner.json is never an authority for replay.
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    return replay(events)


class Knowledge:
    def __init__(self, store: Store, rid: str):
        self.store, self.rid = store, rid
        self.path = store.repo_dir(rid) / "learner.json"
        self.log = store.repo_dir(rid) / "events.jsonl"

    def history(self):
        if self.log.exists():
            stamp = self.log.stat()
            values, seen = copy.deepcopy(replay_log(str(self.log), stamp.st_mtime_ns, stamp.st_size))
        else:
            values, seen = {}, set()
        # Import only pre-event-log evidence, once. Cache edits cannot alter any
        # concept already represented by assessment/import events.
        legacy = {k: v for k, v in read_json(self.path, {}).items() if k not in values}
        if legacy:
            self.store.event(self.rid, "learner_import", {"states": legacy})
            values.update(legacy)
        return values, seen

    def states(self, fingerprints=None, now=None):
        with transaction():
            values, _ = self.history()
        at = time.time() if now is None else now
        return {
            key: {**current(value, (fingerprints or {}).get(key), at), "updated_at": at}
            for key, value in values.items()
        }

    def record(self, concept, event_key, answer, correct, misconception, fingerprint, likelihoods=None):
        with transaction():
            values, seen = self.history()
            prior = values.get(concept)
            if event_key in seen:
                return current(prior, fingerprint), current(prior, fingerprint)
            now = time.time()
            before = current(prior, fingerprint, now)
            likelihoods = likelihoods or response_likelihoods(
                answer if correct else ("b" if answer == "a" else "a")
            )
            after = observe(prior, answer, correct, misconception, fingerprint, now, likelihoods)
            # Append evidence first. learner.json is a disposable compatibility cache.
            self.store.event(
                self.rid,
                "assessment",
                {
                    "format": 2,
                    "concept": concept,
                    "key": event_key,
                    "answer": answer,
                    "correct": correct,
                    "misconception": misconception,
                    "fingerprint": fingerprint,
                    "observed_at": now,
                    "likelihoods": likelihoods,
                },
            )
            values[concept] = after
            write_json(self.path, values)
            return before, after

    def summary(self, repo_map, fingerprints=None, now=None):
        states = self.states(fingerprints, now)
        concepts = [
            {
                "id": c["id"],
                "name": c["name"],
                "parent": c["parent"],
                "importance": c.get("importance", 0.5),
                **states.get(c["id"], current(None, now=now)),
            }
            for c in repo_map["concepts"]
        ]

        def concise(c):
            return {
                "id": c["id"],
                "name": c["name"],
                "mastery": round(c["mastery"], 2),
                "answers": c["attempts"],
                "code_changed": c.get("code_changed", False),
            }

        assessed = [c for c in concepts if c["attempts"]]
        return {
            "areas": [
                {k: a[k] for k in ("id", "name", "mastery", "assessed_count", "concept_count")}
                for a in rollup_areas(repo_map["areas"], concepts)[:8]
            ],
            "assessed": len(assessed),
            "total": len(concepts),
            "weakest": [concise(c) for c in sorted(concepts, key=lambda c: c["mastery"])[:6]],
            "strengths": [concise(c) for c in sorted(assessed, key=lambda c: -c["mastery"])[:3]],
            "misconceptions": [
                {"concept": c["id"], "belief": belief}
                for c in assessed
                for belief in c["misconceptions"][-2:]
            ][:6],
            "guidance": "Untested is uncertain, not a demonstrated weakness. Compress strengths; test misconceptions with fresh scenarios.",
        }


def rollup_areas(areas, concepts):
    by_id = {a["id"]: a for a in areas}

    def belongs(concept, area):
        parent, visited = concept["parent"], set()
        while parent and parent not in visited:
            if parent == area:
                return True
            visited.add(parent)
            parent = by_id.get(parent, {}).get("parent")
        return False

    result = []
    for area in areas:
        children = [c for c in concepts if belongs(c, area["id"])]
        weight = sum(c.get("importance", 0.5) for c in children)
        mastery = sum(c["mastery"] * c.get("importance", 0.5) for c in children) / weight if weight else PRIOR
        result.append(
            {
                **area,
                "mastery": mastery,
                "concept_count": len(children),
                "assessed_count": sum(c["attempts"] > 0 for c in children),
                "observations": sum(c["attempts"] for c in children),
            }
        )
    return result
