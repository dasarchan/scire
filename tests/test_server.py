from fastapi.testclient import TestClient
from scire.app import create_app


def test_token_host_origin_and_server_lifecycle_routes(tmp_path,monkeypatch):
    monkeypatch.setenv('SCIRE_HOME',str(tmp_path))
    app=create_app('secret')
    with TestClient(app) as client:
        assert client.get('/').status_code==200
        assert client.get('/api/home').status_code==401
        assert client.get('/api/home',headers={'x-scire-token':'secret','origin':'https://evil.example'}).status_code==403
        assert client.get('/api/home',headers={'x-scire-token':'secret','host':'evil.example'}).status_code==403
        assert client.get('/api/status',headers={'x-scire-token':'secret'}).json()['ok']
        assert client.post('/api/setup',headers={'x-scire-token':'secret'},json={'name':'Alex','paths':[]}).status_code==200
        assert client.get('/api/home',headers={'x-scire-token':'secret'}).json()['profile']['name']=='Alex'
