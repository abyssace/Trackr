import pytest


@pytest.fixture(autouse=True)
def mock_run_agent(monkeypatch):
    async def fake_run_agent(*args, **kwargs):
        return "Respuesta de prueba", []

    monkeypatch.setattr("app.api.chat.run_agent", fake_run_agent)


def test_historial_isolated_between_users(logged_client, otro_usuario, db):
    # User A sends a message
    r = logged_client.post("/api/chat", json={"mensaje": "hola soy A"})
    assert r.status_code == 200

    # User B logs in on a new client
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.base import get_db

    app.dependency_overrides[get_db] = lambda: db
    client_b = TestClient(app)
    login = client_b.post("/api/login", json={"username": "otro", "password": "secret"})
    assert login.status_code == 200

    hist = client_b.get("/api/historial")
    assert hist.status_code == 200
    contenidos = [m["contenido"] for m in hist.json()]
    assert "hola soy A" not in contenidos

    app.dependency_overrides.clear()


def test_historial_includes_user_and_assistant(logged_client):
    r = logged_client.post("/api/chat", json={"mensaje": "mensaje de prueba"})
    assert r.status_code == 200

    hist = logged_client.get("/api/historial")
    assert hist.status_code == 200
    data = hist.json()
    roles = [m["rol"] for m in data]
    assert "user" in roles
    assert "assistant" in roles
