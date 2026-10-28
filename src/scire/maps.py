from __future__ import annotations
import fnmatch
import hashlib
import time
from pathlib import Path
from .models import RepoMap
from .source import resolve_anchor
from .paths import read_json
from .knowledge import current
from .store import Store


def validate_map(root: Path, value: dict, skeleton: dict) -> dict:
    model = RepoMap.model_validate(value)
    areas = {a.id: a for a in model.areas}
    concepts = {c.id: c for c in model.concepts}
    if len(areas) != len(model.areas) or len(concepts) != len(model.concepts):
        raise ValueError("Area and concept IDs must be unique")
    for area in model.areas:
        seen = {area.id}
        cursor = area.parent
        while cursor:
            if cursor in seen or cursor not in areas:
                raise ValueError("Area tree contains a cycle or missing parent")
            seen.add(cursor)
            cursor = areas[cursor].parent
    for c in model.concepts:
        if c.parent not in areas or any(r not in concepts or r == c.id for r in c.related):
            raise ValueError("Concept parent or relationship is invalid")
        for anchor in c.anchors:
            resolve_anchor(root, anchor)
    if len(concepts) > 1:
        edges = {key: set(c.related) for key, c in concepts.items()}
        for key, values in list(edges.items()):
            for target in values:
                edges[target].add(key)
        seen, pending = set(), [next(iter(concepts))]
        while pending:
            key = pending.pop()
            if key not in seen:
                seen.add(key)
                pending.extend(edges[key] - seen)
        if seen != set(concepts):
            raise ValueError("Concept graph must be connected; explain relationships")
    files = [u["path"] for u in skeleton["units"]]
    patterns = [p for a in model.areas for p in a.paths]
    omitted = [o.get("path", "") for o in model.omitted if o.get("reason")]
    for area in model.areas:
        if not any(any(fnmatch.fnmatch(f, p) for p in area.paths) for f in files):
            raise ValueError(f"Area {area.id} covers no real source files")
    uncovered = [f for f in files if not any(fnmatch.fnmatch(f, p) for p in patterns + omitted)]
    if len(uncovered) > max(1, len(files) * 0.1):
        raise ValueError("Map leaves more than 10% of files unaccounted for: " + ", ".join(uncovered[:12]))
    result = model.model_dump()
    result["coverage"] = round(1 - len(uncovered) / max(1, len(files)), 3)
    return result


def merge_map(old: dict | None, new: dict) -> dict:
    old = old or {}
    names = {}
    for c in old.get("concepts", []):
        for name in [c["id"], c["name"], *c.get("aliases", [])]:
            names[name.lower()] = c["id"]
    renames = {}
    for c in new["concepts"]:
        match = next(
            (names[n.lower()] for n in [c["id"], c["name"], *c.get("aliases", [])] if n.lower() in names),
            None,
        )
        if match:
            renames[c["id"]] = match
    for c in new["concepts"]:
        c["id"] = renames.get(c["id"], c["id"])
        c["related"] = list(dict.fromkeys(renames.get(x, x) for x in c.get("related", [])))
    if len({c["id"] for c in new["concepts"]}) != len(new["concepts"]):
        raise ValueError("Map aliases collapse distinct concepts; use stable IDs")
    ids = {c["id"] for c in new["concepts"]}
    areas = {a["id"] for a in new["areas"]}
    for c in old.get("concepts", []):
        if c.get("pending") and c["id"] not in ids and c["parent"] in areas:
            new["concepts"].append(c)
    # Learner evidence is stored independently by stable concept ID, never reset here.
    new["updated_at"] = time.time()
    return new


def concept_fingerprint(root: Path, concept: dict) -> str:
    try:
        values = [resolve_anchor(root, a)["fingerprint"] for a in concept["anchors"]]
        return hashlib.sha256("".join(values).encode()).hexdigest()
    except (ValueError, OSError):
        return "changed-or-missing"


def public_map(store: Store, rid: str) -> dict:
    value = read_json(store.repo_dir(rid) / "map.json", {"status": "missing", "areas": [], "concepts": []})
    source = Path(value.get("source", store.repo(rid)["path"]))
    learner = read_json(store.repo_dir(rid) / "learner.json", {})
    concepts = []
    for c in value.get("concepts", []):
        if c.get("pending"):
            try:
                for a in c["anchors"]:
                    resolve_anchor(source, a)
            except (ValueError, OSError):
                continue
        fp = concept_fingerprint(source, c)
        state = current(learner.get(c["id"]), fp)
        concepts.append(
            {
                **c,
                "mastery": state["mastery"],
                "confidence": state["confidence"],
                "attempts": state["attempts"],
                "misconceptions": state["misconceptions"],
                "fingerprint": fp,
            }
        )
    areas = []
    by_id = {a["id"]: a for a in value.get("areas", [])}

    def belongs(c, aid):
        parent = c["parent"]
        seen = set()
        while parent and parent not in seen:
            if parent == aid:
                return True
            seen.add(parent)
            parent = by_id.get(parent, {}).get("parent")
        return False

    for area in value.get("areas", []):
        children = [c for c in concepts if belongs(c, area["id"])]
        weight = sum(c.get("importance", 0.5) for c in children)
        mastery = sum(c["mastery"] * c.get("importance", 0.5) for c in children) / weight if weight else 0.2
        areas.append({**area, "mastery": mastery, "concept_count": len(children)})
    return {
        **{k: v for k, v in value.items() if k not in {"areas", "concepts"}},
        "areas": areas,
        "concepts": concepts,
    }
