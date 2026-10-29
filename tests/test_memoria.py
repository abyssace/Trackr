import pytest

from app.servicios.roles import Rol


@pytest.fixture(autouse=True)
def mock_run_agent(monkeypatch):
    async def fake_run_agent(*args, **kwargs):
        return "Respuesta de prueba", []

    monkeypatch.setattr("app.api.chat.run_agent", fake_run_agent)


def test_historial_isolated_between_users(logged_client, usuario, otro_usuario, db):
    usuario.rol = Rol.VENDEDOR.value
    otro_usuario.rol = Rol.VENDEDOR.value
    db.commit()
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


def test_historial_toma_los_20_mensajes_mas_recientes(usuario, db):
    from datetime import datetime, timedelta

    from app.db.modelos import Mensaje
    from app.servicios.memoria import obtener_historial

    base = datetime(2026, 1, 1)
    for i in range(25):
        db.add(
            Mensaje(
                usuario_id=usuario.id,
                rol="user",
                contenido=f"m{i}",
                creado_en=base + timedelta(minutes=i),
            )
        )
    db.commit()

    contenidos = [m.content for m in obtener_historial(db, usuario.id)]

    assert len(contenidos) == 20
    assert contenidos[0] == "m5"
    assert contenidos[-1] == "m24"


def test_historial_includes_user_and_assistant(logged_client, usuario, db):
    usuario.rol = Rol.VENDEDOR.value
    db.commit()
    r = logged_client.post("/api/chat", json={"mensaje": "mensaje de prueba"})
    assert r.status_code == 200

    hist = logged_client.get("/api/historial")
    assert hist.status_code == 200
    data = hist.json()
    roles = [m["rol"] for m in data]
    assert "user" in roles
    assert "assistant" in roles
