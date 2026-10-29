import json
import time
import uuid
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
    # Esta información la agrega el servidor; no puede elegirla el modelo.
    args["_responsable_usuario_id"] = usuario.id
    args["_idempotency_base"] = f"accion:{pendiente.id}"
    try:
        # Un executor puede generar varios movimientos. El savepoint exterior
        # garantiza que todos se confirman o ninguno.
        with db.begin_nested():
            resultado = await ejecutor(db, args)
            pendiente.estado = "confirmada"
            pendiente.confirmado_por_usuario_id = usuario.id
            db.flush()
    except Exception:
        db.rollback()
        raise
    db.commit()
    return resultado


VENTANA_DUPLICADOS_SEGUNDOS = 60
_ejecuciones_recientes: dict[str, float] = {}


def _clave_duplicado(usuario_id: int, tool: str, args: dict) -> str:
    return f"{usuario_id}:{tool}:{json.dumps(args, sort_keys=True, default=str)}"


def _limpiar_ejecuciones_recientes(ahora: float) -> None:
    for clave, momento in list(_ejecuciones_recientes.items()):
        if ahora - momento > VENTANA_DUPLICADOS_SEGUNDOS:
            del _ejecuciones_recientes[clave]


async def ejecutar_accion_directa(
    db: Session,
    tool: str,
    args: dict,
    usuario: Usuario,
) -> str:
    """Ejecuta una escritura confirmada en la conversación, sin acción pendiente.

    Bloquea repetir la misma acción con los mismos datos durante la ventana de duplicados.
    """
    ejecutor = _ejecutores.get(tool)
    if ejecutor is None:
        raise ValueError(f"No hay ejecutor registrado para '{tool}'.")
    if not puede_usar_tool(usuario.rol, tool):
        raise PermissionError(f"El rol '{usuario.rol}' no puede ejecutar '{tool}'.")

    ahora = time.monotonic()
    _limpiar_ejecuciones_recientes(ahora)
    clave = _clave_duplicado(usuario.id, tool, args)
    if clave in _ejecuciones_recientes:
        return "Esa acción ya se registró hace un momento; no la repetí."

    args = {
        **args,
        "_responsable_usuario_id": usuario.id,
        "_idempotency_base": f"directo:{uuid.uuid4().hex}",
    }
    try:
        with db.begin_nested():
            resultado = await ejecutor(db, args)
            db.flush()
    except Exception:
        db.rollback()
        raise
    db.commit()
    _ejecuciones_recientes[clave] = ahora
    return resultado
