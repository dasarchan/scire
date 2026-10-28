from pathlib import Path
import subprocess

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from scire import discovery
from scire.discovery import BROWSE, discover_repos, repository_prompt
from scire.paths import read_json, write_json
from scire.store import Store


def repository(path):
    (path / ".git").mkdir(parents=True)
    (path / ".git/HEAD").write_text("ref: refs/heads/main\n")
    return path.resolve()


def test_scan_finds_repos_skips_dependencies_and_does_not_follow_symlinks(tmp_path):
    first = repository(tmp_path / "Projects" / "one")
    second = repository(tmp_path / "Desktop" / "two")
    repository(first / "nested")
    repository(tmp_path / "node_modules" / "dependency")
    repository(tmp_path / ".scire" / "internal")
    repository(tmp_path / "Library" / "cache")
    outside = repository(tmp_path.parent / (tmp_path.name + "-outside"))
    (tmp_path / "alias").symlink_to(outside, target_is_directory=True)
    result = discover_repos([tmp_path, tmp_path / "Projects"])
    assert set(result.repos) == {first, second}
    assert not result.limited
    assert (first / ".git/HEAD").read_text() == "ref: refs/heads/main\n"


def test_linked_worktree_discovery_leaves_git_metadata_unchanged(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
        ).stdout

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (root / "core.py").write_text("value=1\n")
    git("add", ".")
    git("commit", "-m", "Initial")
    worktree = tmp_path / "worktree"
    git("worktree", "add", "--detach", str(worktree), "HEAD")
    before = {str(p.relative_to(root)): p.read_bytes() for p in (root / ".git").rglob("*") if p.is_file()}
    assert set(discover_repos([tmp_path]).repos) == {root, worktree}
    assert {
        str(p.relative_to(root)): p.read_bytes() for p in (root / ".git").rglob("*") if p.is_file()
    } == before


def test_scan_is_bounded_and_handles_inaccessible_folders(tmp_path, monkeypatch):
    denied = tmp_path / "denied"
    denied.mkdir()
    expected = repository(tmp_path / "visible")
    scan = discovery.os.scandir

    def guarded(path):
        if Path(path) == denied:
            raise PermissionError("not readable")
        return scan(path)

    monkeypatch.setattr(discovery.os, "scandir", guarded)
    result = discover_repos([tmp_path])
    assert result.repos == (expected,) and result.skipped == 1
    assert discover_repos([tmp_path], max_directories=1).limited
    assert discover_repos([tmp_path], max_depth=0).limited
    assert discover_repos([tmp_path], max_seconds=0).limited


def test_picker_search_select_and_enter_keep_existing_connections(tmp_path):
    alpha = repository(tmp_path / "alpha")
    beta = repository(tmp_path / "beta")
    with create_pipe_input() as keys:
        prompt = repository_prompt([alpha, beta], {alpha}, input=keys, output=DummyOutput())
        keys.send_text("BeTa \r")
        selected = prompt.unsafe_ask()
    assert set(selected) == {str(alpha), str(beta)}


def test_picker_cancel_does_not_change_connected_repositories(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    alpha = repository(tmp_path / "alpha")
    store = Store()
    store.add_repo(str(alpha))
    original = store.repos()
    monkeypatch.setattr(discovery, "default_roots", lambda: [tmp_path])
    with create_pipe_input() as keys:
        builder = discovery.repository_prompt
        monkeypatch.setattr(
            discovery,
            "repository_prompt",
            lambda paths, selected: builder(paths, selected, input=keys, output=DummyOutput()),
        )
        keys.send_text("\x03")
        with pytest.raises(KeyboardInterrupt):
            discovery.connect_repositories(store)
    assert store.repos() == original


def test_folder_browsing_keeps_selection_until_final_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    alpha = repository(tmp_path / "normal" / "alpha")
    beta = repository(tmp_path / "elsewhere" / "beta")
    monkeypatch.setattr(discovery, "default_roots", lambda: [tmp_path / "normal"])
    answers = iter([[str(alpha), BROWSE], [str(alpha), str(beta)]])

    class Prompt:
        def unsafe_ask(self, **kwargs):
            return next(answers)

    monkeypatch.setattr(discovery, "repository_prompt", lambda *args: Prompt())
    monkeypatch.setattr(discovery, "browse_folder", lambda: tmp_path / "elsewhere")
    repos = discovery.connect_repositories()
    assert {r["path"] for r in repos} == {str(alpha), str(beta)}


def test_disconnecting_keeps_learning_history(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    alpha = repository(tmp_path / "alpha")
    beta = repository(tmp_path / "beta")
    store = Store()
    old = store.add_repo(str(alpha))
    store.add_repo(str(beta))
    learner = store.repo_dir(old["id"]) / "learner.json"
    write_json(learner, {"concept": {"attempts": 3}})
    store.set_repos([beta])
    assert [r["path"] for r in store.repos()] == [str(beta)]
    assert read_json(learner) == {"concept": {"attempts": 3}}
    assert store.set_repos([alpha, beta])[0]["id"] == old["id"]
    assert read_json(learner)["concept"]["attempts"] == 3


def test_setup_uses_the_picker_before_opening_the_app(tmp_path, monkeypatch):
    from scire import cli, operations

    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    repo = repository(tmp_path / "repo")
    events = []
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(operations, "check_updates", lambda: None)

    def pick():
        events.append("picker")
        return Store().set_repos([repo])

    monkeypatch.setattr(discovery, "connect_repositories", pick)
    monkeypatch.setattr(cli, "serve", lambda no_open: events.append(("serve", no_open)))
    cli.main(["setup", "--model", "test/model", "--no-open"])
    assert events == ["picker", ("serve", True)]
    assert Store().repos()[0]["path"] == str(repo)
    assert Store().profile()["model"] == "test/model"


def test_scire_first_launch_uses_the_picker(tmp_path, monkeypatch):
    from scire import cli, operations

    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    Store().save_profile({"setup": False, "model": "test/model"})
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(operations, "check_updates", lambda: None)
    events = []
    monkeypatch.setattr(discovery, "connect_repositories", lambda: events.append("picker"))
    monkeypatch.setattr(cli, "serve", lambda no_open: events.append("serve"))
    cli.main(["--no-open"])
    assert events == ["picker", "serve"]


def test_empty_result_can_open_folder_browser():
    with create_pipe_input() as keys:
        prompt = repository_prompt([], set(), input=keys, output=DummyOutput())
        keys.send_text(" \r")
        assert prompt.unsafe_ask() == [BROWSE]


def test_folder_browser_can_enter_folders_excluded_from_automatic_scan(tmp_path, monkeypatch):
    library = tmp_path / "Library"
    library.mkdir()
    replies = iter([("open", library), ("search", library)])
    options = []

    class Prompt:
        def unsafe_ask(self, **kwargs):
            return next(replies)

    def select(message, choices, **kwargs):
        options.append([choice.value for choice in choices])
        return Prompt()

    monkeypatch.setattr(discovery.questionary, "select", select)
    assert discovery.browse_folder(tmp_path) == library
    assert ("open", library) in options[0]


def test_commands_offer_connected_repositories_instead_of_requiring_paths(tmp_path, monkeypatch):
    from scire import cli, git

    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    one = repository(tmp_path / "one")
    two = repository(tmp_path / "two")
    repos = Store().set_repos([one, two])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(git, "git", lambda *a: (_ for _ in ()).throw(ValueError("Not a repository")))
    monkeypatch.setattr(discovery, "choose_connected_repo", lambda options: options[1])
    assert cli.choose_repo() == repos[1]
