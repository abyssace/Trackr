from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    """Endpoint de salud sin autenticación para Railway/Docker."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "trackr"}
