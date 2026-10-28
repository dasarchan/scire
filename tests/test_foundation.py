import time
import pytest
from scire.source import resolve_anchor
from scire.paths import safe_source
from scire.skeleton import build_skeleton
from scire.knowledge import current, observe


def test_anchors_are_literal_unique_and_listings_exact(tmp_path):
    (tmp_path / "core.py").write_text(
        "class Queue:\n    def take(self):\n        return 1\n\nvalue = 1\nvalue = 1\n"
    )
    result = resolve_anchor(
        tmp_path, {"id": "take", "path": "core.py", "symbol": "Queue.take", "key_lines": [3]}
    )
    assert result["start_line"] == 2 and result["end_line"] == 3
    with pytest.raises(ValueError, match="occurs 2"):
        resolve_anchor(tmp_path, {"id": "v", "path": "core.py", "literal": "value = 1"})
    assert (
        resolve_anchor(tmp_path, {"id": "v", "path": "core.py", "literal": "value = 1", "occurrence": 2})[
            "start_line"
        ]
        == 6
    )
    with pytest.raises(ValueError, match="line by line"):
        resolve_anchor(
            tmp_path,
            {
                "id": "q",
                "path": "core.py",
                "start_line": 1,
                "end_line": 3,
                "listing": "class Queue:\n    def take(self):\n        return 2",
            },
        )


def test_source_excludes_secrets_and_escapes(tmp_path):
    (tmp_path / ".env").write_text("private")
    (tmp_path / "env.storage.prod").write_text("private")
    (tmp_path / "ok.py").write_text("print(1)")
    (tmp_path / "link").symlink_to("/etc/passwd")
    for name in (".env", "env.storage.prod", "../outside", "/etc/passwd", "link"):
        with pytest.raises((ValueError, FileNotFoundError)):
            safe_source(tmp_path, name)
    assert safe_source(tmp_path, "ok.py").name == "ok.py"


def test_static_skeleton_extracts_imports_definitions_and_headings(tmp_path):
    (tmp_path / "main.py").write_text("from core import Queue\nq=Queue()\n")
    (tmp_path / "core.py").write_text("class Queue:\n    def take(self): return 1\n")
    (tmp_path / "README.md").write_text("# A queue\n## Usage\n")
    skeleton = build_skeleton(tmp_path)
    assert skeleton["file_count"] == 3
    assert any(x["name"] == "Queue" for x in skeleton["central_definitions"])
    assert skeleton["imports"][0]["root"] == "core"
    assert "main.py" in skeleton["entry_points"]


def test_bkt_guessing_forgetting_and_code_drift():
    now = time.time()
    known = observe(None, "a", True, fingerprint="a", now=now)
    assert known["mastery"] < 0.6
    unknown = observe(known, "unknown", False, now=now)
    assert unknown["mastery"] < known["mastery"]
    learned = known
    for _ in range(6):
        learned = observe(learned, "a", True, fingerprint="a", now=now)
    assert learned["mastery"] > 0.9
    assert current(learned, now=now + 90 * 86400)["mastery"] < learned["mastery"]
    assert current(learned, "b", now)["mastery"] < learned["mastery"]
