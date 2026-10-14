"""Backups online de SQLite usando la API nativa de sqlite3."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine

from app.config import settings

logger = logging.getLogger(__name__)


def _backup_filename() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"trackr_backup_{ts}.db"


def backup_online(db_url: str, backup_dir: str) -> Path:
    """Crea un backup online de la base de datos SQLite en db_url."""
    dest_dir = Path(backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / _backup_filename()

    source_engine = create_engine(db_url)
    with source_engine.begin() as conn:
        source_conn = conn.connection.connection
        dest_conn = sqlite3.connect(str(dest_path))
        try:
            with dest_conn:
                source_conn.backup(dest_conn)
        finally:
            dest_conn.close()

    logger.info("Backup creado: %s", dest_path)
    return dest_path


def listar_backups(backup_dir: str) -> list[Path]:
    """Devuelve los backups ordenados del más reciente al más antiguo."""
    path = Path(backup_dir)
    if not path.exists():
        return []
    backups = sorted(path.glob("trackr_backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return backups


def limpiar_backups(backup_dir: str, retention_days: int) -> list[Path]:
    """Elimina backups más antiguos que retention_days. Devuelve los eliminados."""
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    eliminados = []
    for f in Path(backup_dir).glob("trackr_backup_*.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            eliminados.append(f)
            logger.info("Backup antiguo eliminado: %s", f)
    return eliminados


def ejecutar_backup_diario() -> Path | None:
    """Función que ejecuta el scheduler para el backup diario."""
    try:
        path = backup_online(settings.DATABASE_URL, settings.BACKUP_DIR)
        limpiar_backups(settings.BACKUP_DIR, settings.BACKUP_RETENTION_DAYS)
        return path
    except Exception:
        logger.exception("Error al crear backup diario")
        return None
