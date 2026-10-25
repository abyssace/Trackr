from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.modelos import Auditoria, Usuario
from app.api.deps import get_current_user
from app.servicios.auth import get_password_hash, verify_password
from app.servicios import seguridad

router = APIRouter(prefix="/api")


class LoginPayload(BaseModel):
    username: str
    password: str


class CambiarPasswordPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password_actual: str
    password_nueva: str = Field(min_length=12, max_length=200)
    confirmar_password: str = Field(min_length=12, max_length=200)

    @model_validator(mode="after")
    def validar_confirmacion(self):
        if self.password_nueva != self.confirmar_password:
            raise ValueError("Las contraseñas nuevas no coinciden.")
        return self


def _ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/login")
async def login(
    payload: LoginPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = _ip(request)
    user = db.query(Usuario).filter(Usuario.username == payload.username).first()

    if user is None:
        db.add(
            Auditoria(
                username=payload.username,
                ip=ip,
                exito=False,
                razon="usuario_desconocido",
            )
        )
        db.commit()
        raise HTTPException(status_code=401, detail=seguridad.MENSAJE_LOGIN_INVALIDO)

    if seguridad.esta_bloqueado(user):
        db.add(
            Auditoria(
                username=user.username,
                ip=ip,
                exito=False,
                razon="bloqueado",
            )
        )
        db.commit()
        raise HTTPException(status_code=401, detail=seguridad.MENSAJE_LOGIN_INVALIDO)

    if not verify_password(payload.password, user.password_hash):
        seguridad.registrar_intento_fallido(db, user)
        db.add(
            Auditoria(
                username=user.username,
                ip=ip,
                exito=False,
                razon="clave_incorrecta",
            )
        )
        db.commit()
        raise HTTPException(status_code=401, detail=seguridad.MENSAJE_LOGIN_INVALIDO)

    seguridad.limpiar_intentos(db, user)
    db.add(
        Auditoria(
            username=user.username,
            ip=ip,
            exito=True,
            razon="ok",
        )
    )
    db.commit()

    request.session["user_id"] = user.id
    return {
        "ok": True,
        "usuario": {
            "id": user.id,
            "nombre": user.nombre,
            "rol": user.rol,
            "debe_cambiar_password": user.debe_cambiar_password,
        },
    }


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
async def me(usuario: Usuario = Depends(get_current_user)):
    return {
        "id": usuario.id,
        "nombre": usuario.nombre,
        "username": usuario.username,
        "rol": usuario.rol,
        "debe_cambiar_password": usuario.debe_cambiar_password,
    }


@router.post("/cambiar-password")
async def cambiar_password(
    payload: CambiarPasswordPayload,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not verify_password(payload.password_actual, usuario.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta.")
    if verify_password(payload.password_nueva, usuario.password_hash):
        raise HTTPException(status_code=400, detail="Elige una contraseña distinta a la temporal.")

    usuario.password_hash = get_password_hash(payload.password_nueva)
    usuario.debe_cambiar_password = False
    db.commit()
    return {"ok": True, "mensaje": "Contraseña actualizada."}
