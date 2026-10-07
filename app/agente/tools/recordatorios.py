from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.config import settings
from app.db.modelos import Usuario, Recordatorio


def parse_fecha_hora(fecha_hora: str) -> datetime:
    """Parsea ISO 8601 con zona horaria y devuelve UTC."""
    if not fecha_hora:
        raise ValueError("La fecha/hora es requerida.")

    s = fecha_hora.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"No entendí la fecha: {exc}")

    if dt.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria (ej. -06:00).")

    dt_utc = dt.astimezone(timezone.utc)
    if dt_utc <= datetime.now(timezone.utc):
        raise ValueError("La fecha/hora debe ser futura.")

    return dt_utc


def formatear_fecha_local(dt: datetime) -> str:
    tz = ZoneInfo(settings.TIMEZONE)
    return dt.astimezone(tz).strftime("%A %d %b, %I:%M %p").lower()


def _crear_recordatorio(
    db: Session,
    usuario: Usuario,
    texto: str,
    fecha_hora: str,
) -> str:
    try:
        dt = parse_fecha_hora(fecha_hora)
    except ValueError as exc:
        return f"No pude crear el recordatorio: {exc}"

    recordatorio = Recordatorio(
        usuario_id=usuario.id,
        texto=texto,
        fecha_hora=dt,
    )
    db.add(recordatorio)
    db.commit()

    return (
        f"Listo, guardé el recordatorio: '{texto}' "
        f"para {formatear_fecha_local(dt)}."
    )


def _listar_recordatorios(db: Session, usuario: Usuario) -> str:
    pendientes = (
        db.query(Recordatorio)
        .filter(Recordatorio.usuario_id == usuario.id, Recordatorio.estado == "pendiente")
        .order_by(Recordatorio.fecha_hora)
        .all()
    )

    if not pendientes:
        return "No tienes recordatorios pendientes."

    lineas = [
        f"- {r.id}: {r.texto} ({formatear_fecha_local(r.fecha_hora)})"
        for r in pendientes
    ]
    return "Tus recordatorios pendientes:\n" + "\n".join(lineas)


class CrearRecordatorioInput(BaseModel):
    texto: str = Field(description="Texto del recordatorio")
    fecha_hora: str = Field(
        description="Fecha y hora en ISO 8601 con zona horaria (ej. 2026-10-08T17:00:00-06:00)"
    )


def make_recordatorio_tools(usuario: Usuario, db: Session):
    @tool(args_schema=CrearRecordatorioInput)
    def crear_recordatorio(texto: str, fecha_hora: str) -> str:
        """Crea un recordatorio para el usuario con la fecha/hora indicada."""
        return _crear_recordatorio(db, usuario, texto, fecha_hora)

    @tool
    def listar_recordatorios() -> str:
        """Lista los recordatorios pendientes del usuario."""
        return _listar_recordatorios(db, usuario)

    return [crear_recordatorio, listar_recordatorios]
