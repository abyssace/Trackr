import json
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.modelos import Usuario, ComandosLog, Mensaje
from app.agente.agente import run_agent
from app.agente.tools.recordatorios import make_recordatorio_tools
from app.agente.tools.negocio import make_negocio_tools
from app.agente.tools.escritura import make_escritura_tools
from app.servicios.memoria import guardar_mensaje, obtener_historial
from app.servicios.roles import Rol, filtrar_tools
from app.servicios.confirmacion import (
    obtener_pendiente,
    puede_confirmar,
    confirmar_pendiente,
    cancelar_pendiente,
)

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


def _exigir_acceso_chat(usuario: Usuario) -> None:
    if usuario.rol == Rol.ADMINISTRADOR.value:
        raise HTTPException(
            status_code=403,
            detail="La cuenta de administración solo gestiona personal y sus excepciones del sistema.",
        )


@router.post("/chat")
async def chat(
    payload: ChatPayload,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_acceso_chat(usuario)
    _check_rate_limit(usuario.id)

    texto = payload.mensaje.strip().lower()

    # Atajos para confirmar/cancelar la acción pendiente del usuario.
    pendiente = obtener_pendiente(db, usuario.id)
    if pendiente and texto in ("confirmar", "sí", "si"):
        return await _confirmar_desde_chat(db, pendiente, usuario, payload.mensaje)
    if pendiente and texto == "cancelar":
        return await _cancelar_desde_chat(db, pendiente, usuario, payload.mensaje)

    # Guardar mensaje del usuario primero para que forme parte del historial.
    guardar_mensaje(db, usuario.id, "user", payload.mensaje)

    tools = (
        make_recordatorio_tools(usuario, db)
        + make_negocio_tools(usuario, db)
        + make_escritura_tools(usuario, db)
    )
    tools = filtrar_tools(usuario.rol, tools)

    historial = obtener_historial(db, usuario.id)
    # El mensaje actual ya está en la BD; lo removemos del historial para no duplicarlo.
    if historial and isinstance(historial[-1].content, str) and historial[-1].content == payload.mensaje:
        historial = historial[:-1]

    try:
        reply, used_tools = await run_agent(payload.mensaje, tools, usuario, historial)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"El agente no respondió: {exc}",
        )

    guardar_mensaje(db, usuario.id, "assistant", reply)

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


async def _confirmar_desde_chat(db, pendiente, usuario, mensaje):
    if not puede_confirmar(pendiente, usuario):
        raise HTTPException(403, "No tienes permiso para confirmar esta acción.")
    try:
        resultado = await confirmar_pendiente(db, pendiente, usuario)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    guardar_mensaje(db, usuario.id, "user", mensaje)
    guardar_mensaje(db, usuario.id, "assistant", resultado)
    db.commit()
    return {"reply": resultado}


async def _cancelar_desde_chat(db, pendiente, usuario, mensaje):
    cancelar_pendiente(db, pendiente)
    reply = "Acción cancelada."
    guardar_mensaje(db, usuario.id, "user", mensaje)
    guardar_mensaje(db, usuario.id, "assistant", reply)
    db.commit()
    return {"reply": reply}


@router.get("/historial")
async def historial(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_acceso_chat(usuario)
    filas = (
        db.query(Mensaje)
        .filter(Mensaje.usuario_id == usuario.id, Mensaje.rol.in_(["user", "assistant"]))
        .order_by(Mensaje.creado_en)
        .limit(settings.MEMORIA_MENSAJES_MAX)
        .all()
    )
    return [
        {"rol": f.rol, "contenido": f.contenido, "creado_en": f.creado_en.isoformat()}
        for f in filas
    ]


@router.get("/pendiente")
async def pendiente(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_acceso_chat(usuario)
    accion = obtener_pendiente(db, usuario.id)
    if accion is None:
        return {"pendiente": False}
    return {
        "pendiente": True,
        "id": accion.id,
        "tool": accion.tool,
        "resumen": accion.resumen,
        "expira_en": accion.expira_en.isoformat(),
    }


@router.post("/confirmar")
async def confirmar(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_acceso_chat(usuario)
    accion = obtener_pendiente(db, usuario.id)
    if accion is None:
        raise HTTPException(404, "No hay acción pendiente.")
    if not puede_confirmar(accion, usuario):
        raise HTTPException(403, "No tienes permiso para confirmar esta acción.")
    try:
        resultado = await confirmar_pendiente(db, accion, usuario)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    db.commit()
    return {"ok": True, "resultado": resultado}


@router.post("/cancelar")
async def cancelar(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_acceso_chat(usuario)
    accion = obtener_pendiente(db, usuario.id)
    if accion is None:
        raise HTTPException(404, "No hay acción pendiente.")
    cancelar_pendiente(db, accion)
    return {"ok": True}
