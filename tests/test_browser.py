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


@pytest.mark.skipif(not os.environ.get("SCIRE_BROWSER"), reason="Set SCIRE_BROWSER to run Chrome checks")
def test_setup_reflects_terminal_connections_without_path_fields(workspace, monkeypatch):
    from scire import operations
    from playwright.sync_api import sync_playwright

    store, repo, root, m, module = workspace
    store.set_repos([])
    store.save_profile({"setup": False, "name": "", "role": "", "model": "test/model", "cheap_model": ""})
    monkeypatch.setattr(operations, "available_models", lambda: ["test/model"])

    class QuietService(Service):
        async def start(self):
            pass

        async def reviews(self, rid):
            return {"items": [], "branches": [], "error": None}

    app = create_app("setup-token", QuietService())
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
            payload = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    payload.append(request.post_data_json) if request.url.endswith("/api/setup") else None
                ),
            )
            page.goto(base + "/#setup-token")
            page.get_by_role("heading", name="A small introduction").wait_for()
            assert page.locator('[name="paths"]').count() == 0
            assert page.get_by_role("button", name="Create workspace →").is_disabled()
            page.get_by_label("Your name", exact=True).fill("Alex")
            page.get_by_label("What do you work on?", exact=True).fill("Learning the request flow")
            page.get_by_role("button", name="Choose in terminal ↗").click()
            page.get_by_role("heading", name="Choose repositories in your terminal.").wait_for()
            page.get_by_role("button", name="Done", exact=True).click()
            # Simulate the CLI committing its selection while this form stays open.
            store.set_repos([root])
            page.locator(".repo-connection b").wait_for()
            assert page.get_by_label("Your name", exact=True).input_value() == "Alex"
            assert (
                page.get_by_label("What do you work on?", exact=True).input_value()
                == "Learning the request flow"
            )
            assert page.get_by_role("button", name="Create workspace →").is_enabled()
            page.get_by_label("Build repository maps in the background").uncheck()
            assert page.evaluate("document.documentElement.scrollWidth") == 390
            page.get_by_role("button", name="Create workspace →").click()
            page.get_by_role("heading", name="Keep the code in mind.").wait_for()
            assert payload and "paths" not in payload[0]
            assert store.profile()["name"] == "Alex" and store.repos()[0]["id"] == repo["id"]
            page.locator('[data-view="settings"]').click()
            page.get_by_role("heading", name="Connected repositories", exact=True).wait_for()
            assert page.locator('[name="paths"]').count() == 0 and not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


@pytest.mark.skipif(not os.environ.get("SCIRE_BROWSER"), reason="Set SCIRE_BROWSER to run Chrome checks")
def test_repo_dropdown_selection_search_and_keyboard(workspace, tmp_path):
    from playwright.sync_api import sync_playwright

    store, repo, root, m, module = workspace
    store.save_profile({"setup": True, "name": "Alex", "model": "test/model"})
    for parent in ["team", "fork"]:
        folder = tmp_path / parent / "flask"
        folder.mkdir(parents=True)
        store.add_repo(str(folder))

    class QuietService(Service):
        async def start(self):
            pass

        async def reviews(self, rid):
            return {"items": [], "branches": [], "error": None}

    app = create_app("dropdown-token", QuietService())
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
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    try:
        with sync_playwright() as p:
            executable = os.environ["SCIRE_BROWSER"]
            browser = p.chromium.launch(
                **({"executable_path": executable} if executable != "chromium" else {})
            )
            page = browser.new_page(viewport={"width": 1440, "height": 980})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/#dropdown-token")
            page.get_by_role("heading", name="Learn", exact=True).wait_for()
            trigger = page.locator("#repo-menu")
            dropdown = page.locator("#repo-dropdown")
            search = page.get_by_role("searchbox", name="Find a repository")
            trigger.click()
            assert trigger.get_attribute("aria-expanded") == "true"
            assert page.get_by_role("option").count() == 4
            assert page.locator("dialog[open]").count() == 0
            assert page.get_by_role("option", selected=True).inner_text().startswith("All repositories")
            # Same-name repos have distinct paths and can be filtered by either.
            search.fill("flask")
            assert page.get_by_role("option").count() == 2
            assert "team/flask" in page.get_by_role("option").first.inner_text()
            search.fill("not-a-repository")
            page.get_by_text("No repositories found.").wait_for()
            search.press("ArrowDown")  # Empty results are safe.
            search.press("Escape")
            assert dropdown.is_hidden() and trigger.evaluate("e => e === document.activeElement")
            trigger.press("ArrowDown")
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            assert dropdown.is_hidden()
            assert page.locator("#repo-label").inner_text() == repo["name"]
            page.reload()
            page.get_by_role("heading", name="Learn", exact=True).wait_for()
            assert page.locator("#repo-label").inner_text() == repo["name"]
            trigger.click()
            assert page.get_by_role("option", selected=True).get_attribute("data-repo") == repo["id"]
            page.screenshot(path="work/repo-dropdown-desktop.png", full_page=True)
            page.locator("main > h1").click()
            assert dropdown.is_hidden()
            page.set_viewport_size({"width": 390, "height": 844})
            trigger.click()
            box, button = dropdown.bounding_box(), trigger.bounding_box()
            assert box["x"] >= 12 and box["x"] + box["width"] <= 378
            assert box["y"] >= button["y"] + button["height"]
            assert page.evaluate("document.documentElement.scrollWidth") == 390
            page.screenshot(path="work/repo-dropdown-mobile.png", full_page=True)
            page.get_by_role("option", name="All repositories").click()
            assert page.locator("#repo-label").inner_text() == "All repositories"
            trigger.click()
            page.get_by_role("button", name="Manage connections").click()
            assert dropdown.is_hidden() and page.locator("dialog[open]").count() == 0
            page.locator("#manage-repos").wait_for()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
