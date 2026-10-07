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

    return user
