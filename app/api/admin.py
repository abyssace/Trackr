from pathlib import Path
from datetime import timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.modelos import Usuario
from app.db.negocio import AuditoriaCambioPrecio, Empleado, Producto
from app.servicios.backup import listar_backups
from app.config import settings
from app.servicios.auth import get_password_hash
from app.servicios.roles import (
    Rol,
    permisos_descriptivos,
    puede_gestionar_personal,
)
from app.servicios.precios import actualizar_precios_producto

router = APIRouter(prefix="/api/admin")


class PersonalCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=200)
    username: str = Field(min_length=1, max_length=100)
    password_temporal: SecretStr = Field(min_length=12, max_length=200)
    rol: Literal["administrador", "vendedor", "almacen", "ensamblador", "solo_lectura"]

    @field_validator("nombre")
    @classmethod
    def limpiar_nombre(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Escribe el nombre del empleado.")
        return value

    @field_validator("username")
    @classmethod
    def normalizar_usuario(cls, value: str) -> str:
        value = value.strip().casefold()
        if not value:
            raise ValueError("Escribe el usuario para iniciar sesión.")
        return value


class PreciosAdminActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    precio_compra: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, ge=0)
    precio_venta: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, ge=0)


def _exigir_admin(usuario: Usuario) -> None:
    if not puede_gestionar_personal(usuario.rol):
        raise HTTPException(status_code=403, detail="Solo administración puede gestionar personal.")


@router.get("/backup")
async def descargar_backup(usuario: Usuario = Depends(get_current_user)):
    if usuario.rol != Rol.ADMINISTRADOR.value:
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


@router.get("/personal")
async def listar_personal(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_admin(usuario)
    usuarios = db.query(Usuario).order_by(Usuario.nombre, Usuario.username).all()
    empleados = (
        db.query(Empleado)
        .filter(Empleado.usuario_id.isnot(None))
        .order_by(Empleado.id)
        .all()
    )
    empleado_por_usuario = {}
    for empleado in empleados:
        empleado_por_usuario.setdefault(empleado.usuario_id, empleado)

    roles = [
        {"rol": rol.value, "permisos": permisos_descriptivos(rol.value)}
        for rol in Rol
    ]
    return {
        "usuarios": [
            {
                "id": user.id,
                "nombre": user.nombre,
                "username": user.username,
                "rol": user.rol,
                "activo": user.activo,
                "debe_cambiar_password": user.debe_cambiar_password,
                "empleado_id": (
                    empleado_por_usuario[user.id].id
                    if user.id in empleado_por_usuario
                    else None
                ),
                "permisos": permisos_descriptivos(user.rol),
            }
            for user in usuarios
        ],
        "roles": roles,
    }


@router.post("/personal", status_code=201)
async def crear_personal(
    payload: PersonalCrear,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_admin(usuario)
    ya_existe = db.query(Usuario.id).filter(func.lower(Usuario.username) == payload.username).first()
    if ya_existe:
        raise HTTPException(status_code=409, detail="Ese usuario ya existe.")

    nuevo = Usuario(
        nombre=payload.nombre,
        username=payload.username,
        password_hash=get_password_hash(payload.password_temporal.get_secret_value()),
        activo=True,
        es_admin=payload.rol == Rol.ADMINISTRADOR.value,
        rol=payload.rol,
        debe_cambiar_password=True,
    )
    db.add(nuevo)
    try:
        db.flush()
        empleado = Empleado(
            nombre=payload.nombre,
            rol=payload.rol,
            usuario_id=nuevo.id,
            activo=True,
        )
        db.add(empleado)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo crear el usuario; revisa que no esté duplicado.")
    db.refresh(nuevo)
    db.refresh(empleado)
    return {
        "usuario": {
            "id": nuevo.id,
            "nombre": nuevo.nombre,
            "username": nuevo.username,
            "rol": nuevo.rol,
            "activo": nuevo.activo,
            "debe_cambiar_password": nuevo.debe_cambiar_password,
            "empleado_id": empleado.id,
            "permisos": permisos_descriptivos(nuevo.rol),
        }
    }


@router.get("/productos-desactivables")
async def productos_desactivables(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_admin(usuario)
    return {
        "productos": [
            {"id": p.id, "nombre": p.nombre, "codigo": p.codigo}
            for p in db.query(Producto)
            .filter(Producto.activo == True)
            .order_by(Producto.nombre)
            .all()
        ]
    }


@router.post("/productos/{producto_id}/desactivar")
async def desactivar_producto_admin(
    producto_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_admin(usuario)
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="No encontramos ese producto.")
    producto.activo = False
    db.commit()
    return {"ok": True, "activo": False, "producto_id": producto.id}


def _dinero(valor: Decimal | None) -> str | None:
    return format(valor.quantize(Decimal("0.01")), ".2f") if valor is not None else None


@router.get("/precios")
async def listar_precios(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_admin(usuario)
    return {
        "productos": [
            {
                "id": producto.id,
                "nombre": producto.nombre,
                "codigo": producto.codigo,
                "activo": producto.activo,
                "precio_compra": _dinero(producto.precio_compra),
                "precio_venta": _dinero(producto.precio_venta),
            }
            for producto in db.query(Producto).order_by(Producto.nombre).all()
        ]
    }


@router.patch("/precios/{producto_id}")
async def actualizar_precios(
    producto_id: int,
    payload: PreciosAdminActualizar,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_admin(usuario)
    cambios = payload.model_fields_set
    if not cambios:
        raise HTTPException(status_code=422, detail="Indica al menos un precio para actualizar.")
    try:
        producto = actualizar_precios_producto(
            db,
            producto_id=producto_id,
            usuario=usuario,
            **payload.model_dump(exclude_unset=True),
        )
        db.commit()
        db.refresh(producto)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "producto": {
            "id": producto.id,
            "nombre": producto.nombre,
            "precio_compra": _dinero(producto.precio_compra),
            "precio_venta": _dinero(producto.precio_venta),
        }
    }


@router.get("/auditoria-precios")
async def listar_auditoria_precios(
    producto_id: int | None = None,
    limite: int = 200,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _exigir_admin(usuario)
    limite = max(1, min(limite, 500))
    query = (
        db.query(AuditoriaCambioPrecio, Usuario)
        .join(Usuario, Usuario.id == AuditoriaCambioPrecio.usuario_id)
    )
    if producto_id is not None:
        query = query.filter(AuditoriaCambioPrecio.producto_id == producto_id)
    filas = query.order_by(AuditoriaCambioPrecio.cambiado_en.desc(), AuditoriaCambioPrecio.id.desc()).limit(limite).all()
    return {
        "cambios": [
            {
                "id": cambio.id,
                "producto_id": cambio.producto_id,
                "producto": cambio.producto_nombre,
                "campo": cambio.campo,
                "valor_anterior": _dinero(cambio.valor_anterior),
                "valor_nuevo": _dinero(cambio.valor_nuevo),
                "usuario_id": cambio.usuario_id,
                "usuario": quien.nombre,
                "cambiado_en": (
                    cambio.cambiado_en.replace(tzinfo=timezone.utc).isoformat()
                    if cambio.cambiado_en.tzinfo is None
                    else cambio.cambiado_en.isoformat()
                ),
            }
            for cambio, quien in filas
        ]
    }
