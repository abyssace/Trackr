import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.servicios.backup import backup_online, listar_backups, limpiar_backups


def test_backup_online_crea_copia(tmp_path):
    db_path = tmp_path / "origen.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (x INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO t (x) VALUES (1)"))

    backup_dir = tmp_path / "backups"
    backup_path = backup_online(f"sqlite:///{db_path}", str(backup_dir))

    assert backup_path.exists()
    backup_engine = create_engine(f"sqlite:///{backup_path}")
    with backup_engine.begin() as conn:
        result = conn.execute(text("SELECT x FROM t")).scalar()
        assert result == 1


def test_limpiar_backups_elimina_antiguos(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old = backup_dir / "trackr_backup_20000101_000000.db"
    new = backup_dir / "trackr_backup_20990101_000000.db"
    old.write_text("old")
    new.write_text("new")

    # Forzar timestamps
    now = datetime.now(timezone.utc).timestamp()
    old.touch(exist_ok=True)
    new.touch(exist_ok=True)
    # Ajustar mtime manualmente
    import os
    os.utime(str(old), (now - 10 * 86400, now - 10 * 86400))
    os.utime(str(new), (now, now))

    eliminados = limpiar_backups(str(backup_dir), retention_days=7)
    assert old in eliminados
    assert new not in eliminados
    assert not old.exists()
    assert new.exists()


def test_listar_backups_ordenados(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    p1 = backup_dir / "trackr_backup_20260101_000000.db"
    p2 = backup_dir / "trackr_backup_20260102_000000.db"
    p1.write_text("a")
    p2.write_text("b")
    time.sleep(0.1)
    p2.touch()

    backups = listar_backups(str(backup_dir))
    assert backups == [p2, p1]
