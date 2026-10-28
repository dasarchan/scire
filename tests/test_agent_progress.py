from fnmatch import fnmatch
import copy
from scire.agent import job_permissions, snapshot
from scire.progress import AgentOutput, MapActivity
from scire.paths import read_json, write_json
from scire.service import Service


def test_output_permissions_match_opencode_relative_and_absolute_paths(tmp_path):
    permissions = job_permissions(tmp_path)

    def allowed(kind, path):
        result = "deny"
        for pattern, action in permissions[kind].items():
            if fnmatch(path, pattern):
                result = action
        return result == "allow"

    for name in ["output/round.json", "output/modules/01/module.json"]:
        assert allowed("edit", name)
        assert allowed("edit", str(tmp_path / name))
    for name in ["source/core.py", ".git/config", "config/opencode.json", "../other.json"]:
        assert not allowed("edit", name)
        assert not allowed("edit", str(tmp_path / name))
    assert allowed("read", "source/core.py")
    assert permissions["*"] == permissions["external_directory"] == "deny"


def test_agent_streams_partial_public_text_and_tool_titles_only():
    events = []
    relay = AgentOutput(events.append)

    def send(kind, **properties):
        relay.accept({"type": kind, "properties": properties})

    send("message.updated", info={"id": "m", "role": "assistant"})
    send("message.part.delta", messageID="m", partID="p", field="text", delta="I’m reading")
    assert not events  # Don't expose unknown part types, which may be reasoning.
    send("message.part.updated", part={"id": "p", "messageID": "m", "type": "text", "text": ""})
    assert events[-1]["text"] == "I’m reading"
    send("message.part.delta", messageID="m", partID="p", field="text", delta=" the entry point.")
    assert events[-1]["text"] == "I’m reading the entry point."
    send(
        "message.part.updated",
        part={"id": "r", "messageID": "m", "type": "reasoning", "text": "private reasoning"},
    )
    send("message.part.delta", messageID="m", partID="r", field="text", delta="more private reasoning")
    send(
        "message.part.updated",
        part={
            "id": "t",
            "messageID": "m",
            "type": "tool",
            "tool": "read",
            "state": {"title": "Reading core.py", "status": "completed", "output": "SECRET TOOL BODY"},
        },
    )
    assert events[-1] == {"id": "t", "kind": "tool", "text": "Reading core.py", "status": "completed"}
    assert "private" not in str(events) and "SECRET" not in str(events)
    send("message.updated", info={"id": "u", "role": "user"})
    before = len(events)
    send("message.part.updated", part={"id": "up", "messageID": "u", "type": "text", "text": "system prompt"})
    assert len(events) == before


def test_transcript_replaces_partial_parts_bounds_size_and_flushes_tail():
    saved = []
    activity = MapActivity(lambda events, last: saved.append(copy.deepcopy(events)))
    activity.emit({"id": "a", "kind": "text", "text": "first"})
    activity.emit({"id": "a", "kind": "text", "text": "first and second"})
    activity.flush()
    assert len(saved[-1]) == 1 and saved[-1][0]["text"] == "first and second"
    for index in range(250):
        activity.emit({"id": str(index), "kind": "text", "text": "x" * 1000})
    activity.flush()
    assert len(saved[-1]) <= 200
    assert sum(len(e["text"]) for e in saved[-1]) <= 160000
    assert saved[-1][-1]["id"] == "249"


async def test_map_keeps_stream_and_timings_after_validation(workspace, monkeypatch):
    import scire.service as module

    store, repo, source, mapped, lesson = workspace
    monkeypatch.setattr(module, "default_ref", lambda p: "main")
    monkeypatch.setattr(module, "revision", lambda *args: "a" * 40)
    monkeypatch.setattr(module, "pinned_worktree", lambda *args: (source, "a" * 40))

    class Runner:
        async def run(self, kind, source, payload, folder, model, validate, progress, **kwargs):
            progress("Starting OpenCode")
            kwargs["output_event"]({"id": "n", "kind": "text", "text": "Following the request boundary."})
            output = folder / "output"
            output.mkdir(parents=True)
            write_json(output / "map.json", mapped)
            return {"value": validate(output), "metrics": {"seconds": 1.0, "cost": 0}}

    service = Service(Runner())
    await service.build_map(repo["id"], True)
    result = read_json(store.repo_dir(repo["id"]) / "map.json")
    assert result["status"] == "ready", result.get("error")
    assert result["events"][-1]["text"] == "Following the request boundary."
    assert result["finished_at"] >= result["started_at"]


async def test_missing_round_manifest_has_actionable_error(workspace):
    store, repo, root, mapped, lesson = workspace

    class EmptyRunner:
        async def run(self, kind, source, payload, folder, model, validate, *args, **kwargs):
            folder.mkdir(parents=True)
            validate(folder / "output")

    service = Service(EmptyRunner())
    session = store.new_session(
        repo["id"], source=str(root), round=1, status="working", started_learning=True
    )
    await service.generate(session)
    result = store.session(repo["id"], session["id"])
    assert result["status"] == "error"
    assert "did not create output/round.json" in result["error"]
    assert "Field required" not in result["error"]


def test_retry_empty_failed_calibration_remains_first_round(workspace, monkeypatch):
    store, repo, root, mapped, lesson = workspace
    service = Service()
    session = store.new_session(
        repo["id"], source=str(root), round=1, status="error", started_learning=True, error="No files"
    )
    monkeypatch.setattr(service, "spawn", lambda key, coroutine: coroutine.close())
    service.start_round(repo["id"], session["id"])
    result = store.session(repo["id"], session["id"])
    assert result["round"] == 1 and result["status"] == "queued" and result["error"] is None


def test_retry_refreshes_read_only_job_snapshot_without_touching_source(tmp_path):
    source, destination = tmp_path / "repo", tmp_path / "job/source"
    source.mkdir()
    path = source / "core.py"
    path.write_text("value = 1\n")
    snapshot(source, destination)
    snapshot(source, destination)
    path.write_text("value = 2\n")
    snapshot(source, destination)
    assert (destination / "core.py").read_text() == path.read_text() == "value = 2\n"
    assert (destination / "core.py").stat().st_mode & 0o777 == 0o400
    assert path.stat().st_mode & 0o200
