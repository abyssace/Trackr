from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    activo: Mapped[bool] = mapped_column(default=True)


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
