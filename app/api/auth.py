from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.modelos import Auditoria, Usuario
from app.api.deps import get_current_user
from app.servicios.auth import verify_password
from app.servicios import seguridad

router = APIRouter(prefix="/api")


class LoginPayload(BaseModel):
    username: str
    password: str


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
    return {"ok": True, "usuario": {"id": user.id, "nombre": user.nombre}}


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
async def me(usuario: Usuario = Depends(get_current_user)):
    return {"id": usuario.id, "nombre": usuario.nombre, "username": usuario.username}
