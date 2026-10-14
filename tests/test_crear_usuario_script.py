import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.modelos import Usuario
from app.servicios.roles import Rol


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_crear_usuario.db"
    return f"sqlite:///{db_path}"


def _run_script(temp_db, *extra_args):
    env = {**dict(subprocess.os.environ), "DATABASE_URL": temp_db}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.crear_usuario", *extra_args],
        env=env,
        capture_output=True,
        text=True,
    )
    return result


def _user_rol(temp_db, username):
    engine = create_engine(temp_db)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter_by(username=username).first()
        return user.rol if user else None
    finally:
        db.close()


@pytest.mark.parametrize("rol", [r.value for r in Rol])
def test_crear_usuario_con_cada_rol(temp_db, rol):
    result = _run_script(
        temp_db,
        "--username", f"user_{rol}",
        "--password", "ClaveSegura123",
        "--nombre", "Test",
        "--rol", rol,
    )
    assert result.returncode == 0, result.stderr
    assert _user_rol(temp_db, f"user_{rol}") == rol


def test_crear_usuario_rol_invalido(temp_db):
    result = _run_script(
        temp_db,
        "--username", "bad_user",
        "--password", "ClaveSegura123",
        "--nombre", "Test",
        "--rol", "superuser",
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr.lower()
    assert "solo_lectura" in result.stderr
    assert "administrador" in result.stderr


def test_crear_usuario_sin_rol_requerido(temp_db):
    result = _run_script(
        temp_db,
        "--username", "no_role",
        "--password", "ClaveSegura123",
        "--nombre", "Test",
    )
    assert result.returncode == 2
    assert "--rol" in result.stderr
