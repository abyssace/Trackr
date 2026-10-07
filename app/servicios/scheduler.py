from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import update

from app.config import settings
from app.db.base import SessionLocal
from app.db.modelos import Recordatorio
from app.servicios import event_queue


_scheduler: Optional[BackgroundScheduler] = None


def _claim_due_reminders(db):
    """Marca atómicamente los recordatorios vencidos y devuelve las filas afectadas."""
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(Recordatorio)
        .where(
            Recordatorio.estado == "pendiente",
            Recordatorio.fecha_hora <= now,
        )
        .values(estado="vencido")
        .returning(Recordatorio.id, Recordatorio.usuario_id, Recordatorio.texto)
    )
    # Consumir antes de commit para evitar "SQL statements in progress" en SQLite.
    rows = result.all()
    db.commit()
    return rows


def _fire_due_reminders(main_loop):
    with SessionLocal() as db:
        rows = _claim_due_reminders(db)

    for row in rows:
        try:
            import asyncio

            asyncio.run_coroutine_threadsafe(
                event_queue.put_event_for_user(
                    row.usuario_id,
                    {"tipo": "recordatorio", "id": row.id, "texto": row.texto},
                ),
                main_loop,
            )
        except Exception:
            # En un worker real esto debería ir a logs/alertas; aquí no fallamos el scheduler.
            pass


def start_scheduler(main_loop):
    global _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        lambda: _fire_due_reminders(main_loop),
        IntervalTrigger(seconds=settings.SCHEDULER_INTERVAL_SECONDS),
        id="recordatorios",
        replace_existing=True,
    )
    _scheduler.start()


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)
