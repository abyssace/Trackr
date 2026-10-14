import json


def test_manifest_served(client):
    r = client.get("/manifest.json")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Trackr"
    assert data["start_url"] == "/"
    assert any(icon["src"] == "/icons/icon.svg" for icon in data["icons"])


def test_service_worker_served(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    body = r.text
    assert "self.addEventListener('install'" in body
    assert "self.addEventListener('fetch'" in body
    assert "/api/" in body


def test_icon_served(client):
    r = client.get("/icons/icon.svg")
    assert r.status_code == 200
    assert "<svg" in r.text
