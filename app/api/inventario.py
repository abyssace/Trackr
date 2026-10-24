from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.modelos import Usuario
from app.db.negocio import (
    Categoria,
    MovimientoInventario,
    Producto,
    Proveedor,
)
from app.servicios.inventario import (
    buscar_productos,
    calcular_kpis_inventario,
    evaluar_alerta_stock,
    stock_fisico,
    stock_reservado,
)
from app.servicios.roles import (
    puede_desactivar_productos,
    puede_editar_productos,
    puede_registrar_movimientos,
    puede_ver_historial_inventario,
    puede_ver_precio_compra,
    puede_ver_precio_venta,
)
from app.servicios.movimientos import registrar_movimiento

router = APIRouter(prefix="/api/inventario", tags=["inventario"])


class ProductoCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=100)
    tipo: Literal["componente", "terminado"]
    descripcion: str | None = Field(default=None, max_length=4000)
    unidad_medida: str | None = Field(default=None, max_length=20)
    codigo: str | None = Field(default=None, max_length=80)
    categoria_id: int | None = Field(default=None, ge=1)
    proveedor_id: int | None = Field(default=None, ge=1)
    stock_minimo: int | None = Field(default=None, ge=0)
    precio_compra: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, ge=0)
    precio_venta: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, ge=0)
    alias: str | None = Field(default=None, max_length=255)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Escribe el nombre del producto.")
        return value

    @field_validator("codigo")
    @classmethod
    def normalizar_codigo(cls, value: str | None) -> str | None:
        value = value.strip().upper() if value else None
        return value or None


class ProductoActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    tipo: Literal["componente", "terminado"] | None = None
    descripcion: str | None = Field(default=None, max_length=4000)
    unidad_medida: str | None = Field(default=None, max_length=20)
    codigo: str | None = Field(default=None, max_length=80)
    categoria_id: int | None = Field(default=None, ge=1)
    proveedor_id: int | None = Field(default=None, ge=1)
    stock_minimo: int | None = Field(default=None, ge=0)
    precio_compra: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, ge=0)
    precio_venta: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, ge=0)
    alias: str | None = Field(default=None, max_length=255)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Escribe el nombre del producto.")
        return value

    @field_validator("codigo")
    @classmethod
    def normalizar_codigo(cls, value: str | None) -> str | None:
        value = value.strip().upper() if value else None
        return value or None


class MovimientoCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    producto_id: int = Field(ge=1)
    tipo_movimiento: Literal[
        "compra", "reabastecimiento", "venta_mostrador", "merma", "ajuste"
    ]
    cantidad: StrictInt = Field(gt=0)
    direccion: Literal["entrada", "salida"] | None = None
    referencia: str | None = Field(default=None, max_length=100)
    observaciones: str | None = Field(default=None, max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validar_direccion(self):
        if self.tipo_movimiento == "ajuste" and self.direccion is None:
            raise ValueError("Para un ajuste indica si aumenta o disminuye el stock.")
        if self.tipo_movimiento != "ajuste" and self.direccion is not None:
            raise ValueError("La dirección solo se usa en ajustes.")
        return self


def _dinero(valor: Decimal) -> str:
    return format(valor.quantize(Decimal("0.01")), ".2f")


def _producto_json(db: Session, producto: Producto, usuario: Usuario) -> dict:
    fisico = stock_fisico(db, producto.id)
    es_terminado = producto.tipo == "terminado"
    comprometido = stock_reservado(db, producto.id) if es_terminado else 0
    alerta = evaluar_alerta_stock(
        fisico,
        producto.stock_minimo,
        comprometido=comprometido,
        es_terminado=es_terminado,
    )
    resultado = {
        "id": producto.id,
        "nombre": producto.nombre,
        "descripcion": producto.descripcion,
        "tipo": producto.tipo,
        "unidad_medida": producto.unidad_medida,
        "codigo": producto.codigo,
        "categoria": producto.categoria.nombre if producto.categoria else None,
        "proveedor": producto.proveedor.nombre if producto.proveedor else None,
        "stock_minimo": producto.stock_minimo,
        "activo": producto.activo,
        **alerta,
    }
    if puede_ver_precio_compra(usuario.rol):
        resultado["precio_compra"] = (
            _dinero(producto.precio_compra)
            if producto.precio_compra is not None
            else None
        )
    if puede_ver_precio_venta(usuario.rol):
        resultado["precio_venta"] = (
            _dinero(producto.precio_venta)
            if producto.precio_venta is not None
            else None
        )
    return resultado


@router.get("/productos")
async def listar_productos(
    q: str = Query(default="", max_length=120),
    incluir_inactivos: bool = False,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if incluir_inactivos and not puede_ver_precio_compra(usuario.rol):
        raise HTTPException(status_code=403, detail="Solo administración puede ver productos inactivos.")

    productos = buscar_productos(
        db,
        q,
        incluir_inactivos=incluir_inactivos,
    )
    return {"productos": [_producto_json(db, producto, usuario) for producto in productos]}


@router.get("/catalogos")
async def catalogos(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    resultado = {
        "categorias": [
            {"id": c.id, "nombre": c.nombre}
            for c in db.query(Categoria)
            .filter(Categoria.activo == True)
            .order_by(Categoria.nombre)
            .all()
        ],
        "proveedores": [
            {"id": p.id, "nombre": p.nombre}
            for p in db.query(Proveedor)
            .filter(Proveedor.activo == True)
            .order_by(Proveedor.nombre)
            .all()
        ],
    }
    if puede_ver_historial_inventario(usuario.rol):
        resultado["usuarios"] = [
            {"id": u.id, "nombre": u.nombre, "activo": u.activo}
            for u in db.query(Usuario)
            .order_by(Usuario.nombre)
            .all()
        ]
    return resultado


@router.get("/resumen")
async def resumen_inventario(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    productos = buscar_productos(db, "")
    stock_por_producto = [(producto, stock_fisico(db, producto.id)) for producto in productos]
    kpis = calcular_kpis_inventario(stock_por_producto)

    por_categoria: dict[str, int] = {}
    bajo_minimo = 0
    for producto, cantidad in stock_por_producto:
        categoria = producto.categoria.nombre if producto.categoria else "Sin categoría"
        por_categoria[categoria] = por_categoria.get(categoria, 0) + cantidad
        reservado = stock_reservado(db, producto.id) if producto.tipo == "terminado" else 0
        alerta = evaluar_alerta_stock(
            cantidad,
            producto.stock_minimo,
            comprometido=reservado,
            es_terminado=producto.tipo == "terminado",
        )
        if alerta["bajo_minimo"]:
            bajo_minimo += 1

    resultado = {
        "total_productos": len(productos),
        "productos_bajo_minimo": bajo_minimo,
        "stock_por_categoria": [
            {"categoria": nombre, "cantidad": cantidad}
            for nombre, cantidad in sorted(por_categoria.items())
        ],
    }

    # No incluir importes ni metadatos de precios en respuestas sin permiso.
    if puede_ver_precio_compra(usuario.rol):
        resultado["valor_inventario_costo_mxn"] = _dinero(kpis["valor_costo"])
        resultado["productos_sin_precio_compra"] = kpis["productos_sin_precio_compra"]
    if puede_ver_precio_venta(usuario.rol):
        resultado["valor_inventario_venta_mxn"] = _dinero(kpis["valor_venta"])
        resultado["productos_sin_precio_venta"] = kpis["productos_sin_precio_venta"]

    return resultado


def _validar_referencias_producto(db: Session, datos: dict) -> None:
    categoria_id = datos.get("categoria_id")
    proveedor_id = datos.get("proveedor_id")
    if categoria_id is not None:
        categoria = db.get(Categoria, categoria_id)
        if categoria is None or not categoria.activo:
            raise HTTPException(status_code=422, detail="Elige una categoría disponible.")
    if proveedor_id is not None:
        proveedor = db.get(Proveedor, proveedor_id)
        if proveedor is None or not proveedor.activo:
            raise HTTPException(status_code=422, detail="Elige un proveedor disponible.")


def _validar_campos_precio(usuario: Usuario, datos: dict) -> None:
    if usuario.rol != "administrador" and {
        "precio_compra",
        "precio_venta",
    }.intersection(datos):
        raise HTTPException(
            status_code=403,
            detail="Solo administración puede ver o cambiar precios desde el almacén.",
        )


@router.post("/productos", status_code=201)
async def crear_producto(
    payload: ProductoCrear,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_editar_productos(usuario.rol):
        raise HTTPException(status_code=403, detail="No tienes permiso para crear productos.")
    datos = payload.model_dump()
    _validar_campos_precio(usuario, payload.model_fields_set)
    _validar_referencias_producto(db, datos)
    producto = Producto(**datos, activo=True)
    db.add(producto)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese código ya está registrado.")
    db.refresh(producto)
    return {"producto": _producto_json(db, producto, usuario)}


@router.patch("/productos/{producto_id}")
async def actualizar_producto(
    producto_id: int,
    payload: ProductoActualizar,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_editar_productos(usuario.rol):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar productos.")
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="No encontramos ese producto.")
    datos = payload.model_dump(exclude_unset=True)
    _validar_campos_precio(usuario, payload.model_fields_set)
    if any(datos.get(campo) is None for campo in ("nombre", "tipo") if campo in datos):
        raise HTTPException(status_code=422, detail="El nombre y tipo del producto son obligatorios.")
    _validar_referencias_producto(db, datos)
    for campo, valor in datos.items():
        setattr(producto, campo, valor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese código ya está registrado.")
    db.refresh(producto)
    return {"producto": _producto_json(db, producto, usuario)}


@router.post("/productos/{producto_id}/desactivar")
async def desactivar_producto(
    producto_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_desactivar_productos(usuario.rol):
        raise HTTPException(status_code=403, detail="Solo administración puede desactivar productos.")
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="No encontramos ese producto.")
    producto.activo = False
    db.commit()
    return {"ok": True, "activo": False, "producto_id": producto.id}


@router.post("/movimientos", status_code=201)
async def crear_movimiento(
    payload: MovimientoCrear,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_registrar_movimientos(usuario.rol):
        raise HTTPException(status_code=403, detail="No tienes permiso para registrar movimientos.")
    producto = db.get(Producto, payload.producto_id)
    if producto is None or not producto.activo:
        raise HTTPException(status_code=404, detail="El producto no existe o está inactivo.")

    try:
        resultado = registrar_movimiento(
            db,
            producto_id=producto.id,
            tipo_movimiento=payload.tipo_movimiento,
            cantidad=payload.cantidad,
            direccion=payload.direccion,
            usuario_id=usuario.id,
            # La clave la envía la interfaz; el usuario responsable no.
            idempotency_key=payload.idempotency_key,
            referencia=payload.referencia,
            observaciones=payload.observaciones,
        )
        db.commit()
        db.refresh(resultado.movimiento)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="El movimiento ya fue registrado.")

    movimiento = resultado.movimiento
    return {
        "ok": True,
        "duplicado": resultado.duplicado,
        "movimiento": {
            "id": movimiento.id,
            "producto_id": movimiento.producto_id,
            "tipo_movimiento": movimiento.tipo_movimiento,
            "cantidad": movimiento.cantidad,
            "creado_en": movimiento.creado_en.isoformat() if movimiento.creado_en else None,
        },
        "stock_antes": resultado.stock_antes,
        "stock_actual": resultado.stock_despues,
        "advertencias": list(resultado.advertencias),
    }


@router.get("/movimientos")
async def listar_movimientos(
    producto_id: int | None = Query(default=None, ge=1),
    tipo: str | None = Query(default=None, max_length=40),
    usuario_id: int | None = Query(default=None, ge=1),
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limite: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_ver_historial_inventario(usuario.rol):
        raise HTTPException(status_code=403, detail="El historial es solo para administración y almacén.")
    if desde and desde.tzinfo is None:
        raise HTTPException(status_code=422, detail="La fecha inicial debe incluir zona horaria.")
    if hasta and hasta.tzinfo is None:
        raise HTTPException(status_code=422, detail="La fecha final debe incluir zona horaria.")

    consulta = (
        db.query(MovimientoInventario, Producto, Usuario)
        .join(Producto, Producto.id == MovimientoInventario.producto_id)
        .outerjoin(Usuario, Usuario.id == MovimientoInventario.usuario_id)
    )
    if producto_id is not None:
        consulta = consulta.filter(MovimientoInventario.producto_id == producto_id)
    if tipo:
        consulta = consulta.filter(MovimientoInventario.tipo_movimiento == tipo)
    if usuario_id is not None:
        consulta = consulta.filter(MovimientoInventario.usuario_id == usuario_id)
    if desde is not None:
        consulta = consulta.filter(
            MovimientoInventario.creado_en >= desde.astimezone(timezone.utc).replace(tzinfo=None)
        )
    if hasta is not None:
        consulta = consulta.filter(
            MovimientoInventario.creado_en <= hasta.astimezone(timezone.utc).replace(tzinfo=None)
        )

    filas = (
        consulta.order_by(MovimientoInventario.creado_en.desc(), MovimientoInventario.id.desc())
        .limit(limite)
        .all()
    )
    return {
        "movimientos": [
            {
                "id": movimiento.id,
                "producto_id": movimiento.producto_id,
                "producto": producto.nombre,
                "tipo_movimiento": movimiento.tipo_movimiento,
                "cantidad": movimiento.cantidad,
                "responsable_usuario_id": movimiento.usuario_id,
                "responsable": responsable.nombre if responsable else "Registro histórico",
                "referencia": movimiento.referencia,
                "observaciones": movimiento.observaciones,
                "creado_en": (
                    movimiento.creado_en.replace(tzinfo=timezone.utc).isoformat()
                    if movimiento.creado_en and movimiento.creado_en.tzinfo is None
                    else movimiento.creado_en.isoformat() if movimiento.creado_en else None
                ),
            }
            for movimiento, producto, responsable in filas
        ]
    }
