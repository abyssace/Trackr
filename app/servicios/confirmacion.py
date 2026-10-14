import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.modelos import AccionPendiente, Usuario
from app.servicios.roles import puede_usar_tool


TTL_MINUTOS = 5

_ejecutores: dict[str, Callable[[Session, dict], Awaitable[str]]] = {}


def registrar_ejecutor(nombre_tool: str):
    """Decorador para registrar la función que ejecuta realmente una tool de escritura."""

    def decorador(func: Callable[[Session, dict], Awaitable[str]]):
        _ejecutores[nombre_tool] = func
        return func

    return decorador


def _limpiar_expiradas(db: Session, usuario_id: int):
    db.query(AccionPendiente).filter(
        AccionPendiente.usuario_id == usuario_id,
        AccionPendiente.estado == "pendiente",
        AccionPendiente.expira_en < datetime.now(timezone.utc),
    ).update({AccionPendiente.estado: "expirada"}, synchronize_session=False)
    db.commit()


def crear_pendiente(
    db: Session,
    usuario_id: int,
    tool: str,
    args: dict,
    resumen: str,
) -> AccionPendiente:
    # Una sola acción pendiente por usuario; una nueva cancela la anterior.
    db.query(AccionPendiente).filter(
        AccionPendiente.usuario_id == usuario_id,
        AccionPendiente.estado == "pendiente",
    ).update({AccionPendiente.estado: "cancelada"}, synchronize_session=False)

    pendiente = AccionPendiente(
        usuario_id=usuario_id,
        tool=tool,
        args=json.dumps(args, ensure_ascii=False),
        resumen=resumen,
        expira_en=datetime.now(timezone.utc) + timedelta(minutes=TTL_MINUTOS),
    )
    db.add(pendiente)
    db.commit()
    db.refresh(pendiente)
    return pendiente


def obtener_pendiente(db: Session, usuario_id: int) -> AccionPendiente | None:
    _limpiar_expiradas(db, usuario_id)
    pendiente = db.scalar(
        select(AccionPendiente)
        .where(
            AccionPendiente.usuario_id == usuario_id,
            AccionPendiente.estado == "pendiente",
        )
        .order_by(AccionPendiente.creado_en.desc())
    )
    return pendiente


def puede_confirmar(pendiente: AccionPendiente, usuario: Usuario) -> bool:
    """Cada usuario solo confirma sus propias acciones, incluidos los administradores."""
    return pendiente.usuario_id == usuario.id


def cancelar_pendiente(db: Session, pendiente: AccionPendiente) -> None:
    pendiente.estado = "cancelada"
    db.commit()


async def confirmar_pendiente(
    db: Session,
    pendiente: AccionPendiente,
    usuario: Usuario,
) -> str:
    if pendiente.estado != "pendiente":
        raise ValueError(f"La acción ya está {pendiente.estado}.")

    ejecutor = _ejecutores.get(pendiente.tool)
    if ejecutor is None:
        raise ValueError(f"No hay ejecutor registrado para '{pendiente.tool}'.")

    if not puede_usar_tool(usuario.rol, pendiente.tool):
        raise PermissionError(
            f"El rol '{usuario.rol}' no puede ejecutar '{pendiente.tool}'."
        )

    args = json.loads(pendiente.args)
    resultado = await ejecutor(db, args)

    pendiente.estado = "confirmada"
    pendiente.confirmado_por_usuario_id = usuario.id
    db.commit()
    return resultado
