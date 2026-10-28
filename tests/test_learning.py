import asyncio
import copy
import pytest
from scire.maps import merge_map, validate_map
from scire.models import validate_module
from scire.paths import read_json, write_json
from scire.service import Service


class StreamingRunner:
    def __init__(self, module):
        self.module = module
        self.ready = asyncio.Event()
        self.release = asyncio.Event()

    async def close(self):
        pass

    async def run(self, kind, source, payload, folder, model, validate, progress, stream, **kwargs):
        output = folder / "output"
        directory = output / "modules/01"
        directory.mkdir(parents=True)
        write_json(
            directory / "preview.json",
            {
                "id": self.module["id"],
                "index": 0,
                "title": self.module["title"],
                "summary": self.module["summary"],
                "concepts": self.module["concepts"],
            },
        )
        stream(output)
        write_json(directory / "module.json", self.module)
        stream(output)
        self.ready.set()
        await self.release.wait()
        progress("Validated the final module.")
        write_json(
            output / "round.json",
            {"title": "A boundary", "modules": ["modules/01/module.json"], "next": ["Follow the caller."]},
        )
        return {"value": validate(output), "metrics": {"cost": 0.01, "seconds": 1.0}}


async def test_streamed_answers_survive_worker_updates_and_are_idempotent(workspace):
    store, repo, root, m, module = workspace
    runner = StreamingRunner(module)
    service = Service(runner)
    session = store.new_session(
        repo["id"], source=str(root), round=1, status="working", started_learning=True
    )
    task = asyncio.create_task(service.generate(session))
    await asyncio.wait_for(runner.ready.wait(), 2)
    public = service.public_session(repo["id"], session["id"])
    assert public["status"] == "working" and public["modules"][0]["status"] == "ready"
    assert "correct" not in public["modules"][0]["questions"][0]
    assert public["modules"][0]["questions"][0]["options"][-1]["key"] == "unknown"
    answer = service.answer(repo["id"], session["id"], "boundary-q1", "unknown")
    assert not answer["correct"] and answer["correct_option"] == "c"
    assert service.answer(repo["id"], session["id"], "boundary-q1", "c") == answer
    runner.release.set()
    await asyncio.wait_for(task, 2)
    final = service.public_session(repo["id"], session["id"])
    assert final["answers"]["boundary-q1"]["choice"] == "unknown" and final["complete"]
    learner = read_json(store.repo_dir(repo["id"]) / "learner.json")
    assert learner["dispatch"]["attempts"] == 1
    assert service.what_next(repo["id"], session["id"])["areas"][0]["id"] == "request"


def test_findings_unlock_only_after_answers_and_require_exact_preview(workspace):
    store, repo, root, m, module = workspace
    module["findings"] = [
        {
            "key": "bad-input",
            "title": "Text input raises",
            "scenario": "A caller supplies a string instead of a number.",
            "evidence": "The function adds an integer to the supplied value.",
            "impact": "The request raises a TypeError.",
            "ref": "dispatch",
            "severity": "low",
            "draft": "Consider validating the number before adding one.",
        }
    ]
    service = Service()
    validated = validate_module(root, module, m, True)
    validated.update(status="ready", round=1)
    review = {
        "kind": "pr",
        "head": "a" * 40,
        "diff": "diff --git a/core.py b/core.py\n--- a/core.py\n+++ b/core.py\n@@ -1 +1,2 @@\n def dispatch(value):\n+    return value + 1\n",
    }
    session = store.new_session(
        repo["id"], "1", source=str(root), round=1, status="ready", modules=[validated], review=review
    )
    service.make_orders(session, validated)
    assert service.public_session(repo["id"], session["id"])["modules"][0]["findings"] == []
    with pytest.raises(ValueError, match="locked"):
        service.comment_preview(repo["id"], session["id"], "boundary", "bad-input")
    service.answer(repo["id"], session["id"], "boundary-q1", "c")
    assert (
        service.public_session(repo["id"], session["id"])["modules"][0]["findings"][0]["key"] == "bad-input"
    )
    preview = service.comment_preview(repo["id"], session["id"], "boundary", "bad-input")
    assert preview["line"] == 2 and preview["postable"]
    service.finding_draft(
        repo["id"], session["id"], "boundary", "bad-input", "disagree", "I could not reproduce this."
    )
    assert (
        service.comment_preview(repo["id"], session["id"], "boundary", "bad-input")["confirmation"]
        != preview["confirmation"]
    )


def test_orders_balance_and_persist(workspace):
    store, repo, root, m, module = workspace
    service = Service()
    s = store.new_session(repo["id"])
    for i in range(12):
        item = copy.deepcopy(module)
        item["questions"][0]["key"] = f"q{i}"
        item["status"] = "ready"
        service.make_orders(s, item)
        s["modules"].append(item)
    orders = read_json(store.session_dir(repo["id"], s["id"]) / "orders.json")
    assert [sum(order.index("c") == i for order in orders.values()) for i in range(4)] == [3, 3, 3, 3]
    service.make_orders(s, s["modules"][0])
    assert read_json(store.session_dir(repo["id"], s["id"]) / "orders.json") == orders


def test_map_merge_preserves_alias_identity_and_pending_concepts(workspace):
    store, repo, root, m, module = workspace
    pending = copy.deepcopy(m["concepts"][0])
    pending.update(id="pending", name="New feature", pending=True)
    m["concepts"].append(pending)
    new = copy.deepcopy(m)
    new["concepts"] = new["concepts"][:1]
    new["concepts"][0].update(id="renamed", aliases=["Dispatch"])
    merged = merge_map(m, new)
    assert {c["id"] for c in merged["concepts"]} == {"dispatch", "pending"}
    invalid = copy.deepcopy(m)
    invalid["concepts"][0]["related"] = ["absent"]
    with pytest.raises(ValueError, match="relationship"):
        validate_map(root, invalid, {"units": [{"path": "core.py"}]})
