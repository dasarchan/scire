import pytest
from scire.store import Store
from scire.paths import write_json


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "core.py").write_text("def dispatch(value):\n    return value + 1\n")
    store = Store()
    repo = store.add_repo(str(root))
    anchor = {
        "id": "dispatch",
        "path": "core.py",
        "symbol": "dispatch",
        "key_lines": [2],
        "look_for": ["value"],
    }
    m = {
        "status": "ready",
        "source": str(root),
        "areas": [
            {
                "id": "request",
                "name": "Requests",
                "parent": None,
                "importance": 1,
                "summary": "Follow an input",
                "paths": ["core.py"],
            }
        ],
        "concepts": [
            {
                "id": "dispatch",
                "name": "Dispatch",
                "parent": "request",
                "importance": 1,
                "aliases": [],
                "related": [],
                "anchors": [anchor],
            }
        ],
    }
    write_json(store.repo_dir(repo["id"]) / "map.json", m)
    module = {
        "id": "boundary",
        "title": "One request boundary",
        "summary": "A value is transformed once.",
        "concepts": ["dispatch"],
        "new_concepts": [],
        "why": "The boundary converts an input into a result.",
        "flow": ["Pass a number into dispatch.", "Return the number plus one."],
        "key_code": "Look at the return expression.",
        "pitfalls": ["The caller must supply a number."],
        "anchors": [anchor],
        "diagram": None,
        "questions": [
            {
                "key": "boundary-q1",
                "concept": "dispatch",
                "question": "What does dispatch(2) return?",
                "options": [{"key": k, "text": t} for k, t in zip("abcd", ["1", "2", "3", "4"])],
                "correct": "c",
                "explanation": "Adding one to two returns three.",
                "misconception": "The return value is unchanged.",
                "ref": "dispatch",
            }
        ],
        "findings": [],
    }
    return store, repo, root, m, module
