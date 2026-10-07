import json
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.modelos import Usuario, ComandosLog
from app.agente.agente import run_agent
from app.agente.tools.recordatorios import make_recordatorio_tools

router = APIRouter(prefix="/api")

_rate_limit_store: dict[int, deque] = defaultdict(deque)


class ChatPayload(BaseModel):
    mensaje: str


def _check_rate_limit(user_id: int):
    now = datetime.now(timezone.utc).timestamp()
    window = _rate_limit_store[user_id]
    cutoff = now - 60
    while window and window[0] < cutoff:
        window.popleft()

    if len(window) >= settings.CHAT_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Demasiados mensajes. Espera un minuto.")

    window.append(now)


@router.post("/chat")
async def chat(
    payload: ChatPayload,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _check_rate_limit(usuario.id)

    tools = make_recordatorio_tools(usuario, db)

    try:
        reply, used_tools = await run_agent(payload.mensaje, tools, usuario)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"El agente no respondió: {exc}",
        )

    if used_tools:
        for name, args, result in used_tools:
            db.add(
                ComandosLog(
                    usuario_id=usuario.id,
                    texto_usuario=payload.mensaje,
                    herramienta=name,
                    args=args,
                    resultado=result,
                )
            )
    else:
        db.add(
            ComandosLog(
                usuario_id=usuario.id,
                texto_usuario=payload.mensaje,
                herramienta=None,
                args=None,
                resultado=reply,
            )
        )

    db.commit()
    return {"reply": reply}
