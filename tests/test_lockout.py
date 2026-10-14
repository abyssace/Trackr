import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.db.modelos import Usuario, Auditoria
from app.servicios import seguridad


@pytest.fixture
def usuario_no_admin(db):
    from app.servicios.auth import get_password_hash
    from app.servicios.roles import Rol

    user = Usuario(
        nombre="Vendedor",
        username="vendedor",
        password_hash=get_password_hash("secret"),
        activo=True,
        es_admin=False,
        rol=Rol.VENDEDOR.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def client_user(client, usuario_no_admin):
    return client, usuario_no_admin


def test_login_exitoso_limpia_intentos(client_user):
    client, user = client_user
    for _ in range(3):
        r = client.post("/api/login", json={"username": "vendedor", "password": "mal"})
        assert r.status_code == 401
        assert r.json()["detail"] == seguridad.MENSAJE_LOGIN_INVALIDO

    r = client.post("/api/login", json={"username": "vendedor", "password": "secret"})
    assert r.status_code == 200
    assert user.intentos_fallidos == 0
    assert user.bloqueado_hasta is None


def test_bloqueo_despues_de_intentos_fallidos(client_user):
    client, user = client_user
    for i in range(5):
        r = client.post("/api/login", json={"username": "vendedor", "password": "mal"})
        assert r.status_code == 401
        assert r.json()["detail"] == seguridad.MENSAJE_LOGIN_INVALIDO

    assert user.intentos_fallidos == 5
    assert user.bloqueado_hasta is not None
    assert user.bloqueado_hasta > datetime.utcnow()

    # Mismo mensaje aun estando bloqueado
    r = client.post("/api/login", json={"username": "vendedor", "password": "secret"})
    assert r.status_code == 401
    assert r.json()["detail"] == seguridad.MENSAJE_LOGIN_INVALIDO


def test_usuario_desconocido_recibe_mismo_error(client):
    r = client.post("/api/login", json={"username": "noexiste", "password": "secret"})
    assert r.status_code == 401
    assert r.json()["detail"] == seguridad.MENSAJE_LOGIN_INVALIDO


def test_auditoria_registra_intentos(client_user):
    client, user = client_user
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        client.post("/api/login", json={"username": "vendedor", "password": "mal"})
        client.post("/api/login", json={"username": "vendedor", "password": "secret"})

        registros = db.query(Auditoria).filter(Auditoria.username == "vendedor").all()
        assert len(registros) == 2
        assert sum(1 for r in registros if not r.exito) == 1
        assert sum(1 for r in registros if r.exito) == 1
    finally:
        db.close()


def test_auditoria_registra_desconocido(client):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        client.post("/api/login", json={"username": "desconocido", "password": "x"})
        registro = db.query(Auditoria).filter(Auditoria.username == "desconocido").first()
        assert registro is not None
        assert registro.exito is False
        assert registro.razon == "usuario_desconocido"
    finally:
        db.close()
