"""Run with SCIRE_BROWSER=chromium (or a Chrome executable path)."""

import os
import socket
import threading
import time
import pytest
import uvicorn
from scire.app import create_app
from scire.models import validate_module
from scire.service import Service


@pytest.mark.skipif(not os.environ.get("SCIRE_BROWSER"), reason="Set SCIRE_BROWSER to run Chrome checks")
def test_workspace_navigation_responsiveness_and_findings(workspace, tmp_path):
    from playwright.sync_api import sync_playwright

    store, repo, root, m, module = workspace
    store.save_profile(
        {"setup": True, "name": "Alex", "role": "Engineer", "model": "test/model", "cheap_model": ""}
    )
    module["findings"] = [
        {
            "key": "input",
            "title": "A string input fails",
            "scenario": "A caller sends a string to dispatch.",
            "evidence": "An integer is added to the input.",
            "impact": "The caller receives a TypeError.",
            "ref": "dispatch",
            "severity": "low",
            "draft": "Consider validating a numeric input.",
        }
    ]
    validated = validate_module(root, module, m, True)
    validated.update(status="ready", round=1, index=0)
    review = {"kind": "branch", "head": "a" * 40, "title": "feature", "diff": "", "source": str(root)}
    s = store.new_session(
        repo["id"],
        "feature",
        source=str(root),
        round=1,
        status="ready",
        started_learning=True,
        modules=[validated],
        review=review,
    )

    class QuietService(Service):
        async def start(self):
            pass

        async def reviews(self, rid):
            return {"items": [], "branches": [], "error": None}

        async def ask(self, rid, question, sid=None):
            topic = {
                "question": question,
                "concepts": ["dispatch"],
                "route": "quick",
                "answer": "It adds one to the supplied number.",
                "refs": module["anchors"],
            }
            session = store.new_session(rid, source=str(root), topics=[topic])
            return {"session": session["id"], "topic": topic}

    service = QuietService()
    service.make_orders(s, validated)
    app = create_app("browser-token", service)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    try:
        with sync_playwright() as p:
            executable = os.environ["SCIRE_BROWSER"]
            browser = p.chromium.launch(
                **({"executable_path": executable} if executable != "chromium" else {})
            )
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/?view=knowledge#browser-token")
            page.get_by_role("heading", name="What you know, and what to revisit.").wait_for()
            page.locator(".knowledge-tree details").first.wait_for()
            assert page.evaluate("document.documentElement.scrollWidth") == 390
            page.locator(".knowledge-tree summary").first.click()
            page.get_by_role("button", name="Learn this →").wait_for()
            page.goto(base + f"/w/{repo['id']}/{s['id']}/")
            page.locator(".findings-lock").wait_for()
            assert page.locator(".finding").count() == 0
            assert page.locator(".feedback").count() == 0
            page.get_by_role("button", name="I don’t know yet").click()
            page.locator(".feedback").wait_for()
            page.get_by_role("heading", name="A string input fails").wait_for()
            page.get_by_role("button", name="Preview exact comment →").click()
            page.get_by_role("heading", name="Review the exact comment.").wait_for()
            assert page.get_by_role("button", name="Post exact comment to GitHub").is_disabled()
            page.goto(base + "/")
            page.get_by_role("textbox", name="Ask about the codebase").fill("What does dispatch do?")
            page.get_by_role("button", name="Explore question →").click()
            page.get_by_role("heading", name="What does dispatch do?").wait_for()
            assert page.url == base + "/"
            page.get_by_role("button", name="core.py ↗").click()
            page.locator(".source-preview").wait_for()
            assert "return value + 1" in page.locator(".source-preview").inner_text()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
