from fastapi.testclient import TestClient
from scire.app import create_app


def test_token_host_origin_and_server_lifecycle_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIRE_HOME", str(tmp_path))
    app = create_app("secret")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/home").status_code == 401
        assert (
            client.get(
                "/api/home", headers={"x-scire-token": "secret", "origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert (
            client.get("/api/home", headers={"x-scire-token": "secret", "host": "evil.example"}).status_code
            == 403
        )
        assert client.get("/api/status", headers={"x-scire-token": "secret"}).json()["ok"]
        assert (
            client.post(
                "/api/setup", headers={"x-scire-token": "secret"}, json={"name": "Alex", "paths": []}
            ).status_code
            == 200
        )
        assert (
            client.get("/api/home", headers={"x-scire-token": "secret"}).json()["profile"]["name"] == "Alex"
        )


def test_web_setup_only_uses_cli_connected_repositories(tmp_path, monkeypatch):
    from scire.store import Store

    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    store = Store()
    repo = store.add_repo(str(root))
    app = create_app("secret")
    with TestClient(app, base_url="http://127.0.0.1", headers={"x-scire-token": "secret"}) as client:
        response = client.post("/api/setup", json={"name": "Alex", "paths": [str(root / "unselected")]})
        assert response.status_code == 400
        assert store.profile()["setup"] is False
        response = client.post("/api/setup", json={"name": "Alex", "model": "test/model", "map_now": False})
        assert response.status_code == 200 and store.profile()["setup"]
        assert client.post("/api/repos/sync", json={}).json()["repos"] == [repo]
        assert client.get("/api/home").json()["repos"][0]["id"] == repo["id"]


def test_auto_maps_wait_until_profile_setup_is_finished(tmp_path, monkeypatch):
    from scire.service import Service
    from scire.store import Store

    monkeypatch.setenv("SCIRE_HOME", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    store = Store()
    repo = store.add_repo(str(root))
    service = Service()
    queued = []
    monkeypatch.setattr(service, "queue_map", lambda rid, force=False: queued.append(rid))
    store.save_profile({"setup": False, "model": "test/model"})
    service.sync_repos()
    assert queued == []
    store.save_profile({"setup": True, "model": "test/model"})
    service.sync_repos()
    assert queued == [repo["id"]]
