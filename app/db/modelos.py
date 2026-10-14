from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.servicios.roles import Rol


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    activo: Mapped[bool] = mapped_column(default=True)
    es_admin: Mapped[bool] = mapped_column(default=False)
    rol: Mapped[str] = mapped_column(String(30), default=Rol.SOLO_LECTURA.value)
    intentos_fallidos: Mapped[int] = mapped_column(default=0)
    bloqueado_hasta: Mapped[Optional[datetime]] = mapped_column(default=None)


class Recordatorio(Base):
    __tablename__ = "recordatorios"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    texto: Mapped[str] = mapped_column(String(1000))
    fecha_hora: Mapped[datetime]
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    creado_en: Mapped[datetime] = mapped_column(default=utc_now)
    visto_en: Mapped[Optional[datetime]] = mapped_column(default=None)


class ComandosLog(Base):
    __tablename__ = "comandos_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    texto_usuario: Mapped[str] = mapped_column(String(2000))
    herramienta: Mapped[Optional[str]] = mapped_column(String(100))
    args: Mapped[Optional[str]] = mapped_column(String(2000))
    resultado: Mapped[Optional[str]] = mapped_column(String(2000))
    creado_en: Mapped[datetime] = mapped_column(default=utc_now)


class Mensaje(Base):
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    rol: Mapped[str] = mapped_column(String(20))
    contenido: Mapped[str] = mapped_column(String(4000))
    creado_en: Mapped[datetime] = mapped_column(default=utc_now)


class AccionPendiente(Base):
    __tablename__ = "acciones_pendientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    tool: Mapped[str] = mapped_column(String(100))
    args: Mapped[str] = mapped_column(Text)
    resumen: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    expira_en: Mapped[datetime]
    confirmado_por_usuario_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(default=utc_now)


class Auditoria(Base):
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    exito: Mapped[bool]
    razon: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(default=utc_now)
