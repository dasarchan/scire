from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel, Field
from .knowledge import response_likelihoods
from .source import Anchor, resolve_anchor

ID = r"^[a-z0-9][a-z0-9_-]{0,79}$"


class Area(BaseModel):
    id: str = Field(pattern=ID)
    name: str = Field(max_length=80)
    parent: str | None = None
    importance: float = Field(ge=0, le=1)
    summary: str = Field(max_length=350)
    paths: list[str] = Field(min_length=1)


class Concept(BaseModel):
    id: str = Field(pattern=ID)
    name: str = Field(max_length=80)
    parent: str
    importance: float = Field(ge=0, le=1)
    aliases: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    anchors: list[Anchor] = Field(min_length=1, max_length=8)
    pending: bool = False


class RepoMap(BaseModel):
    areas: list[Area] = Field(min_length=1, max_length=24)
    concepts: list[Concept] = Field(min_length=1, max_length=100)
    omitted: list[dict[str, str]] = Field(default_factory=list)


class Option(BaseModel):
    key: str = Field(pattern=r"^[a-d]$")
    text: str = Field(min_length=1, max_length=450)


class ResponseLikelihood(BaseModel):
    known: float = Field(gt=0, lt=1)
    unknown: float = Field(gt=0, lt=1)


class Question(BaseModel):
    key: str = Field(pattern=ID)
    concept: str
    question: str = Field(min_length=1, max_length=700)
    options: list[Option] = Field(min_length=4, max_length=4)
    correct: str = Field(pattern=r"^[a-d]$")
    explanation: str = Field(min_length=1, max_length=650)
    misconception: str = Field(max_length=400)
    ref: str
    likelihoods: dict[str, ResponseLikelihood] | None = None
    after: str = Field(default="flow", pattern=r"^(why|flow|key_code|pitfalls)$")


class Finding(BaseModel):
    key: str = Field(pattern=ID)
    title: str = Field(max_length=150)
    scenario: str = Field(min_length=12, max_length=900)
    evidence: str = Field(min_length=12, max_length=1000)
    impact: str = Field(min_length=8, max_length=600)
    ref: str
    severity: str = Field(pattern=r"^(low|medium|high)$")
    draft: str = Field(min_length=1, max_length=2000)


class Diagram(BaseModel):
    nodes: list[dict[str, str]] = Field(max_length=7)
    edges: list[dict[str, str]] = Field(max_length=12)


class Module(BaseModel):
    id: str = Field(pattern=ID)
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=300)
    concepts: list[str] = Field(min_length=1, max_length=5)
    new_concepts: list[Concept] = Field(default_factory=list, max_length=5)
    why: str = Field(min_length=1, max_length=800)
    flow: list[str] = Field(min_length=2, max_length=5)
    key_code: str = Field(min_length=1, max_length=700)
    pitfalls: list[str] = Field(min_length=1, max_length=3)
    anchors: list[Anchor] = Field(min_length=1, max_length=8)
    diagram: Diagram | None = None
    questions: list[Question] = Field(min_length=1, max_length=4)
    findings: list[Finding] = Field(default_factory=list, max_length=5)


class Preview(BaseModel):
    id: str = Field(pattern=ID)
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=300)
    concepts: list[str] = Field(max_length=5)
    index: int = Field(ge=0, le=20)


class RoundManifest(BaseModel):
    title: str = Field(max_length=150)
    modules: list[str] = Field(min_length=1, max_length=12)
    next: list[str] = Field(max_length=5)


class Triage(BaseModel):
    route: str = Field(pattern=r"^(quick|focused|broad)$")
    answer: str = Field(default="", max_length=2400)
    concepts: list[str] = Field(default_factory=list, max_length=8)
    refs: list[Anchor] = Field(default_factory=list, max_length=6)


def validate_module(root: Path, value: dict, repo_map: dict, review=False) -> dict:
    module = Module.model_validate(value)
    anchors = {a.id: a for a in module.anchors}
    if len(anchors) != len(module.anchors):
        raise ValueError("Duplicate anchor IDs")
    resolved = {key: resolve_anchor(root, anchor) for key, anchor in anchors.items()}
    known = {c["id"] for c in repo_map.get("concepts", [])}
    areas = {a["id"] for a in repo_map.get("areas", [])}
    for concept in module.new_concepts:
        if concept.parent not in areas:
            raise ValueError("Every new concept must name a mapped parent area")
        for anchor in concept.anchors:
            resolve_anchor(root, anchor)
        known.add(concept.id)
    if any(c not in known for c in module.concepts):
        raise ValueError("Module references an unknown concept")
    keys = set()
    for q in module.questions:
        if q.key in keys or q.concept not in module.concepts or q.ref not in anchors:
            raise ValueError("Question keys, assessed concepts and code refs must be valid")
        if q.likelihoods is None:
            q.likelihoods = {k: ResponseLikelihood(**v) for k, v in response_likelihoods(q.correct).items()}
        if set(q.likelihoods) != {"a", "b", "c", "d", "unknown"}:
            raise ValueError("Question likelihoods must cover a, b, c, d and unknown")
        if any(
            abs(sum(getattr(v, field) for v in q.likelihoods.values()) - 1) > 0.005
            for field in ("known", "unknown")
        ):
            raise ValueError("Question response likelihoods must sum to 1 for known and unknown learners")
        keys.add(q.key)
        if {o.key for o in q.options} != {"a", "b", "c", "d"} or len(
            {o.text.strip().lower() for o in q.options}
        ) != 4:
            raise ValueError("Questions need four distinct plausible choices")
    if module.findings and not review:
        raise ValueError("Findings belong only in PR review modules")
    for finding in module.findings:
        if finding.ref not in anchors:
            raise ValueError("Every finding needs anchored evidence")
    if len({f.key for f in module.findings}) != len(module.findings):
        raise ValueError("Duplicate finding keys")
    if module.diagram:
        ids = [n.get("id") for n in module.diagram.nodes]
        if len(set(ids)) != len(ids) or any(not x for x in ids):
            raise ValueError("Invalid diagram node IDs")
        if any(e.get("from") not in ids or e.get("to") not in ids for e in module.diagram.edges):
            raise ValueError("Diagram edge references an unknown node")
    prose = " ".join([module.summary, module.why, *module.flow, module.key_code, *module.pitfalls])
    if len(prose.split()) > 420:
        raise ValueError("Module exceeds 420 visible words; teach less and use shorter examples")
    return {**module.model_dump(), "resolved": resolved}


class RepositoryDigest(BaseModel):
    repo: str
    changed: list[str] = Field(max_length=20)
    revisit: list[str] = Field(max_length=20)
    notes: str = Field(max_length=5000)


class Digest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    summary: str = Field(min_length=1, max_length=5000)
    repos: list[RepositoryDigest] = Field(min_length=1)
