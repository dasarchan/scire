from __future__ import annotations
import math
import time
from .paths import read_json, transaction, write_json
from .store import Store

PRIOR, LEARN, GUESS, SLIP = 0.20, 0.12, 0.25, 0.10
HALF_LIFE_DAYS = 45


def current(state: dict | None, fingerprint: str | None = None, now: float | None = None) -> dict:
    now = now or time.time()
    state = dict(
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
    state["confidence"] = 1 - math.exp(-state["attempts"] / 5)
    return state


def observe(
    state: dict | None,
    answer: str,
    correct: bool,
    misconception: str = "",
    fingerprint: str = "",
    now: float | None = None,
) -> dict:
    now = now or time.time()
    result = current(state, fingerprint, now)
    p = result["mastery"]
    if answer == "unknown":
        guess, slip = 0.05, 0.05
        posterior = p * slip / max(1e-9, p * slip + (1 - p) * (1 - guess))
    elif correct:
        posterior = p * (1 - SLIP) / max(1e-9, p * (1 - SLIP) + (1 - p) * GUESS)
    else:
        posterior = p * SLIP / max(1e-9, p * SLIP + (1 - p) * (1 - GUESS))
    result["mastery"] = min(0.98, posterior + (1 - posterior) * LEARN)
    result["attempts"] += 1
    result["correct"] += int(correct)
    result["updated_at"] = now
    result["fingerprint"] = fingerprint
    result["confidence"] = 1 - math.exp(-result["attempts"] / 5)
    result["observations"] = (
        result.get("observations", []) + [{"at": now, "correct": correct, "unknown": answer == "unknown"}]
    )[-100:]
    if not correct and misconception:
        result["misconceptions"] = (result["misconceptions"] + [misconception])[-8:]
    return result


class Knowledge:
    def __init__(self, store: Store, rid: str):
        self.store, self.rid = store, rid
        self.path = store.repo_dir(rid) / "learner.json"

    def states(self, fingerprints: dict | None = None) -> dict:
        values = read_json(self.path, {})
        return {key: current(value, (fingerprints or {}).get(key)) for key, value in values.items()}

    def record(
        self, concept: str, event_key: str, answer: str, correct: bool, misconception: str, fingerprint: str
    ) -> tuple[dict, dict]:
        with transaction():
            values = read_json(self.path, {})
            prior = values.get(concept)
            if event_key in (prior or {}).get("event_keys", []):
                return prior, prior
            before = current(prior, fingerprint)
            after = observe(prior, answer, correct, misconception, fingerprint)
            after["event_keys"] = ((prior or {}).get("event_keys", []) + [event_key])[-500:]
            values[concept] = after
            write_json(self.path, values)
            self.store.event(
                self.rid,
                "assessment",
                {"concept": concept, "key": event_key, "answer": answer, "before": before, "after": after},
            )
            return before, after
