import pytest
from pathlib import Path

from app.servicios.backup import backup_online


def test_admin_backup_requiere_login(client):
    r = client.get("/api/admin/backup")
    assert r.status_code == 401


def test_admin_backup_solo_admin(logged_client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.BACKUP_DIR", str(tmp_path / "backups"))
    backup_online("sqlite:///:memory:", str(tmp_path / "backups"))

    r = logged_client.get("/api/admin/backup")
    assert r.status_code == 200
    assert "trackr_backup_" in r.headers["content-disposition"]


def test_admin_backup_rechaza_no_admin(client, db, monkeypatch):
    from app.servicios.auth import get_password_hash
    from app.servicios.roles import Rol
    from app.db.modelos import Usuario

    user = Usuario(
        nombre="Vendedor",
        username="vendedor",
        password_hash=get_password_hash("secret"),
        activo=True,
        rol=Rol.VENDEDOR.value,
    )
    db.add(user)
    db.commit()

    r = client.post("/api/login", json={"username": "vendedor", "password": "secret"})
    assert r.status_code == 200

    r = client.get("/api/admin/backup")
    assert r.status_code == 403
