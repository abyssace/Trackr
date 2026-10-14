from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.db.modelos import Usuario
from app.servicios.backup import listar_backups
from app.config import settings
from app.servicios.roles import Rol

router = APIRouter(prefix="/api/admin")


@router.get("/backup")
async def descargar_backup(usuario: Usuario = Depends(get_current_user)):
    if not usuario.es_admin and usuario.rol != Rol.ADMINISTRADOR.value:
        raise HTTPException(status_code=403, detail="Se requiere rol administrador")

    backups = listar_backups(settings.BACKUP_DIR)
    if not backups:
        raise HTTPException(status_code=404, detail="No hay backups disponibles")

    ultimo = backups[0]
    return FileResponse(
        ultimo,
        filename=ultimo.name,
        media_type="application/octet-stream",
    )
