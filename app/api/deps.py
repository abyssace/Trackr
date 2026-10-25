from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.modelos import Usuario


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Usuario:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="No autenticado")

    user = db.get(Usuario, user_id)
    if user is None or not user.activo:
        raise HTTPException(status_code=401, detail="Usuario no válido")
    if user.debe_cambiar_password and request.url.path not in {
        "/api/me",
        "/api/cambiar-password",
        "/api/logout",
    }:
        raise HTTPException(
            status_code=403,
            detail="Cambia tu contraseña temporal antes de continuar.",
        )

    return user
