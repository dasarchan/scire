from fastapi.testclient import TestClient
from scire.app import create_app
from scire.models import validate_module
from scire.review import diff_hunks
from scire.service import Service

PATCH = "diff --git a/core.py b/core.py\n--- a/core.py\n+++ b/core.py\n@@ -1,2 +1,2 @@\n def dispatch(value):\n-    return value\n+    return value + 1\n"


def test_pinned_diff_hunks_preserve_line_coordinates_and_filter_secrets():
    private = "diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-old\n+secret\n"
    files = diff_hunks(PATCH + private)
    assert len(files) == 1 and files[0]["path"] == "core.py"
    assert files[0]["additions"] == files[0]["deletions"] == 1
    assert files[0]["hunks"][0]["lines"] == [
        {"kind": "context", "old": 1, "new": 1, "text": "def dispatch(value):"},
        {"kind": "remove", "old": 2, "new": None, "text": "    return value"},
        {"kind": "add", "old": None, "new": 2, "text": "    return value + 1"},
    ]
    deleted = PATCH.replace("+++ b/core.py", "+++ /dev/null")
    assert diff_hunks(deleted)[0]["path"] == "core.py"


def test_changes_endpoint_uses_pinned_patch_and_preserves_quiz_secrecy(workspace):
    store, repo, root, mapped, module = workspace
    validated = validate_module(root, module, mapped)
    validated.update(status="ready", round=1, index=0)
    session = store.new_session(
        repo["id"],
        "feature",
        source=str(root),
        modules=[validated],
        round=1,
        status="ready",
        review={"kind": "branch", "head": "a" * 40, "base": "b" * 40, "diff": PATCH},
    )
    app = create_app("token", Service())
    with TestClient(app, base_url="http://127.0.0.1", headers={"x-scire-token": "token"}) as client:
        response = client.get(f"/api/sessions/{repo['id']}/{session['id']}/changes")
        assert response.status_code == 200 and response.json()["head"] == "a" * 40
        assert response.json()["files"][0]["hunks"][0]["lines"][-1]["new"] == 2
        public = client.get(f"/api/sessions/{repo['id']}/{session['id']}").json()
        assert "likelihoods" not in public["modules"][0]["questions"][0]
        assert "correct" not in public["modules"][0]["questions"][0]
        assert (
            client.post(f"/api/repos/{repo['id']}/onboarding", json={"calibration": "skipped"}).status_code
            == 200
        )
        assert client.get("/api/home").json()["repos"][0]["onboarding"]["calibration"] == "skipped"


def test_hunk_content_that_looks_like_file_headers_stays_content():
    patch = PATCH.replace("-    return value", "--- old SQL comment").replace(
        "+    return value + 1", "+++ new expression"
    )
    file = diff_hunks(patch)[0]
    assert file["path"] == "core.py"
    assert file["hunks"][0]["lines"][1]["text"] == "-- old SQL comment"
    assert file["additions"] == file["deletions"] == 1
