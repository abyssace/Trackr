from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.modelos import Usuario
from app.api.deps import get_current_user

router = APIRouter(prefix="/api")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class LoginPayload(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(
    payload: LoginPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = db.query(Usuario).filter(Usuario.username == payload.username).first()
    if user is None or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    request.session["user_id"] = user.id
    return {"ok": True, "usuario": {"id": user.id, "nombre": user.nombre}}


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
async def me(usuario: Usuario = Depends(get_current_user)):
    return {"id": usuario.id, "nombre": usuario.nombre, "username": usuario.username}
