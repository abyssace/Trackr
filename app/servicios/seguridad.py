"""Helpers para bloqueo de cuentas tras intentos fallidos de login."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.db.modelos import Usuario


MENSAJE_LOGIN_INVALIDO = "Credenciales inválidas"


def _ahora_utc() -> datetime:
    return datetime.utcnow()


def esta_bloqueado(usuario: Usuario) -> bool:
    if usuario.bloqueado_hasta is None:
        return False
    return usuario.bloqueado_hasta > _ahora_utc()


def registrar_intento_fallido(db: Session, usuario: Usuario) -> None:
    usuario.intentos_fallidos += 1
    if usuario.intentos_fallidos >= settings.MAX_LOGIN_ATTEMPTS:
        usuario.bloqueado_hasta = _ahora_utc() + timedelta(minutes=settings.LOCKOUT_MINUTES)
    db.commit()


def limpiar_intentos(db: Session, usuario: Usuario) -> None:
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    db.commit()
