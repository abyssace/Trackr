from datetime import datetime, timedelta, timezone

import pytest

from app.agente.tools.recordatorios import (
    parse_fecha_hora,
    _crear_recordatorio,
    _listar_recordatorios,
)
from app.db.modelos import Recordatorio
from app.servicios.scheduler import _claim_due_reminders


def test_parse_rejects_missing_timezone():
    mañana = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    with pytest.raises(ValueError, match="zona horaria"):
        parse_fecha_hora(mañana)


def test_parse_rejects_past_date():
    ayer = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="futura"):
        parse_fecha_hora(ayer)


def test_parse_converts_to_utc():
    dt = parse_fecha_hora("2030-01-01T12:00:00-06:00")
    assert dt.tzinfo is not None
    assert dt.hour == 18  # 12:00 Monterrey -> 18:00 UTC


def test_crear_recordatorio_persists(db, usuario):
    futuro = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    msg = _crear_recordatorio(db, usuario, "Llamar al proveedor", futuro)
    assert "guardé" in msg

    rec = db.query(Recordatorio).filter(Recordatorio.usuario_id == usuario.id).first()
    assert rec is not None
    assert rec.texto == "Llamar al proveedor"
    assert rec.estado == "pendiente"


def test_listar_recordatorios_only_own(db, usuario, otro_usuario):
    futuro = datetime.now(timezone.utc) + timedelta(hours=5)
    _crear_recordatorio(db, usuario, "Mío", futuro.isoformat())
    _crear_recordatorio(db, otro_usuario, "Suyo", futuro.isoformat())

    texto = _listar_recordatorios(db, usuario)
    assert "Mío" in texto
    assert "Suyo" not in texto


def test_claim_due_reminders_is_atomic(db, usuario):
    pasado = datetime.now(timezone.utc) - timedelta(minutes=5)
    rec = Recordatorio(usuario_id=usuario.id, texto="Vencido", fecha_hora=pasado)
    db.add(rec)
    db.commit()

    # Primera llamada debe reclamarlo.
    rows1 = _claim_due_reminders(db)
    assert len(rows1) == 1
    db.refresh(rec)
    assert rec.estado == "vencido"

    # Segunda llamada no debe volver a reclamar el mismo recordatorio.
    rows2 = _claim_due_reminders(db)
    assert len(rows2) == 0
