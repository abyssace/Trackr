import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.modelos import Usuario, Recordatorio
from app.servicios.event_queue import get_or_create_queue, drop_queue

router = APIRouter(prefix="/api")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def event_stream(usuario: Usuario, db: Session):
    user_id = usuario.id
    queue = get_or_create_queue(user_id)

    try:
        # Entregar recordatorios que vencieron mientras el cliente estaba offline.
        vencidos = db.scalars(
            select(Recordatorio)
            .where(
                Recordatorio.usuario_id == user_id,
                Recordatorio.estado == "vencido",
            )
            .order_by(Recordatorio.fecha_hora)
        ).all()

        for recordatorio in vencidos:
            recordatorio.estado = "visto"
            recordatorio.visto_en = datetime.now(timezone.utc)
            yield _sse(
                {
                    "tipo": "recordatorio",
                    "id": recordatorio.id,
                    "texto": recordatorio.texto,
                }
            )
        db.commit()

        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield _sse({"tipo": "ping"})
                continue

            recordatorio_id = payload.get("id")
            if recordatorio_id:
                rec = db.get(Recordatorio, recordatorio_id)
                if rec:
                    rec.estado = "visto"
                    rec.visto_en = datetime.now(timezone.utc)
                    db.commit()

            yield _sse(payload)
    finally:
        drop_queue(user_id)


@router.get("/eventos")
async def eventos(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    return StreamingResponse(
        event_stream(usuario, db),
        media_type="text/event-stream",
    )
