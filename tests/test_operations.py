import sys
import json
from pathlib import Path
import subprocess
from fastapi.testclient import TestClient
from scire.app import create_app
from scire.git import pinned_worktree, filtered_diff
from scire.operations import install_skill, newest_tag
from scire.store import Store


def test_worktrees_never_modify_source_git(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
        ).stdout

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (root / "core.py").write_text("value=1\n")
    git("add", ".")
    git("commit", "-m", "Initial")
    (root / "core.py").write_text("value=2\n")
    before = {str(p.relative_to(root)): p.read_bytes() for p in (root / ".git").rglob("*") if p.is_file()}
    repo = Store().add_repo(str(root))
    path, sha = pinned_worktree(repo)
    assert (path / "core.py").read_text() == "value=1\n"
    assert (root / "core.py").read_text() == "value=2\n"
    assert {
        str(p.relative_to(root)): p.read_bytes() for p in (root / ".git").rglob("*") if p.is_file()
    } == before


def test_diff_filters_private_paths():
    patch = "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -0,0 +1 @@\n+{value}\n"
        for p, value in [
            ("core.py", "return 1"),
            (".env", "SECRET=x"),
            ("env.storage.prod", "private"),
            ("keys.py", "sk-" + "a" * 30),
        ]
    )
    filtered = filtered_diff(patch)
    assert (
        "return 1" in filtered
        and "SECRET" not in filtered
        and "private" not in filtered
        and "sk-" not in filtered
    )


def test_no_post_without_explicit_action_and_markdown_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIRE_HOME", str(tmp_path))
    app = create_app("secret")
    with TestClient(app, base_url="http://127.0.0.1", headers={"x-scire-token": "secret"}) as client:
        result = client.post("/api/sessions/a/b/finding/c/d/post", json={"confirmation": "hash"})
        assert result.status_code == 400
        rendered = client.post(
            "/api/render",
            json={"text": "| Key | Value |\n| --- | --- |\n| A | B |\n\n<script>alert(1)</script>"},
        ).json()["html"]
        assert "<table>" in rendered and "<script>" not in rendered


def test_skill_can_install_and_release_tags_sort_numerically(tmp_path, monkeypatch):
    install_skill(tmp_path / "skill")
    assert (tmp_path / "skill/SKILL.md").read_text().startswith("---\nname: scire")

    class Result:
        returncode = 0
        stdout = "sha\trefs/tags/v0.1.9\nsha\trefs/tags/v0.1.10\nsha\trefs/tags/v0.2.0-rc1\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    assert newest_tag("https://example.test/repo.git") == (0, 1, 10)


def test_native_provider_login_and_model_choice_stay_in_opencode(tmp_path, monkeypatch):
    from scire import operations

    monkeypatch.setenv("SCIRE_HOME", str(tmp_path))
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(operations, "opencode_binary", lambda: "/bin/opencode")
    monkeypatch.setattr(operations.subprocess, "run", lambda args, **kwargs: calls.append(args) or Result())
    monkeypatch.setattr(operations, "available_models", lambda: ["custom/my-model", "openai/another"])
    operations.connect("custom/my-model")
    assert calls == [["/bin/opencode", "auth", "login", "--pure"]]
    assert Store().profile()["model"] == "custom/my-model"


def test_uv_directory_receipt_resolves_its_git_source(tmp_path, monkeypatch):
    from scire import operations

    root = tmp_path / "tool"
    root.mkdir()
    (root / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{name="scire-local",directory="' + str(tmp_path) + '"}]\n'
    )
    monkeypatch.setattr(operations.sys, "prefix", str(root))
    monkeypatch.setattr(operations.shutil, "which", lambda name: None)
    monkeypatch.setattr(operations, "git", lambda *args: "https://github.com/example/scire.git\n")
    assert operations.receipt_source() == str(tmp_path)
    assert operations.update_source() == "https://github.com/example/scire.git"


def test_waiting_reviews_are_first_and_not_duplicated(monkeypatch):
    from scire import review

    replies = iter(
        ['[{"number":2,"title":"Waiting"}]', '[{"number":1,"title":"Recent"},{"number":2,"title":"Waiting"}]']
    )
    monkeypatch.setattr(review, "gh", lambda *args: next(replies))
    items = review.waiting_reviews({"path": "."})
    assert [(p["number"], p["waiting"]) for p in items] == [(2, True), (1, False)]


def test_server_build_is_captured_at_start(tmp_path, monkeypatch):
    from scire import app as module

    monkeypatch.setenv("SCIRE_HOME", str(tmp_path))
    monkeypatch.setattr(module, "build_id", lambda: "before")
    app = module.create_app("secret")
    monkeypatch.setattr(module, "build_id", lambda: "after")
    with TestClient(app, base_url="http://127.0.0.1", headers={"x-scire-token": "secret"}) as client:
        assert client.get("/api/status").json()["build"] == "before"


def test_concurrent_cli_launches_share_one_server(tmp_path):
    import os, time
    import httpx
    import scire.cli

    env = {**os.environ, "SCIRE_HOME": str(tmp_path), "PYTHONPATH": str(Path(scire.cli.__file__).parents[1])}
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "scire", "--no-open"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    state = None
    try:
        for _ in range(150):
            try:
                state = json.loads((tmp_path / "server.json").read_text())
                response = httpx.get(
                    f"http://127.0.0.1:{state['port']}/api/status",
                    headers={"x-scire-token": state["token"]},
                    timeout=0.2,
                )
                if response.status_code == 200 and any(p.poll() == 0 for p in processes):
                    break
            except (OSError, ValueError, httpx.HTTPError):
                pass
            time.sleep(0.05)
        assert state and sum(p.poll() is None for p in processes) == 1
        assert (tmp_path / "server.json").stat().st_mode & 0o777 == 0o600
        httpx.post(
            f"http://127.0.0.1:{state['port']}/api/quit", headers={"x-scire-token": state["token"]}, timeout=2
        )
        for p in processes:
            p.wait(timeout=5)
        assert all(p.returncode == 0 for p in processes)
        assert not (tmp_path / "server.json").exists()
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=5)


async def test_agent_shutdown_terminates_its_process_group():
    import asyncio
    from scire.agent import AgentRunner

    runner = AgentRunner()
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)", start_new_session=True
    )
    runner.processes.add(process)
    await asyncio.wait_for(runner.close(), 4)
    assert process.returncode is not None


def test_weekly_schedule_configuration_without_installing_a_job(tmp_path, monkeypatch):
    import plistlib
    from scire import operations

    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(operations.sys, "platform", "darwin")
    monkeypatch.setattr(operations.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(operations.shutil, "which", lambda name: "/usr/local/bin/scire")
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(operations.subprocess, "run", lambda args, **kwargs: calls.append(args) or Result())
    operations.schedule_digest()
    file = tmp_path / "Library/LaunchAgents/ai.scire.digest.plist"
    value = plistlib.loads(file.read_bytes())
    assert value["ProgramArguments"] == ["/usr/local/bin/scire", "digest", "--no-open"]
    assert value["StartCalendarInterval"] == {"Weekday": 1, "Hour": 9, "Minute": 0}
    assert file.stat().st_mode & 0o777 == 0o600
    assert calls[-1][:2] == ["launchctl", "bootstrap"]


def test_branch_head_checks_resolve_triple_dot_ranges(monkeypatch):
    from scire import review

    refs = []
    monkeypatch.setattr(review, "revision", lambda root, ref: refs.append(ref) or "new")
    assert review.head_moved({"path": "."}, {"kind": "branch", "title": "main...feature", "head": "old"})
    assert refs == ["feature"]
