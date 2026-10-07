from sqlalchemy import select
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage, AIMessage

from app.config import settings
from app.db.modelos import Mensaje


def guardar_mensaje(db: Session, usuario_id: int, rol: str, contenido: str) -> Mensaje:
    mensaje = Mensaje(usuario_id=usuario_id, rol=rol, contenido=contenido)
    db.add(mensaje)
    db.commit()
    return mensaje


def obtener_historial(db: Session, usuario_id: int, limite: int | None = None):
    if limite is None:
        limite = settings.MEMORIA_MENSAJES_MAX

    filas = db.scalars(
        select(Mensaje)
        .where(Mensaje.usuario_id == usuario_id, Mensaje.rol.in_(["user", "assistant"]))
        .order_by(Mensaje.creado_en)
        .limit(limite)
    ).all()

    mensajes = []
    for fila in filas:
        if fila.rol == "user":
            mensajes.append(HumanMessage(content=fila.contenido))
        elif fila.rol == "assistant":
            mensajes.append(AIMessage(content=fila.contenido))
    return mensajes
