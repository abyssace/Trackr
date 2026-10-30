from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.modelos import Usuario
from app.db.negocio import (
    AuditoriaCambioPrecio,
    Categoria,
    Cliente,
    MovimientoInventario,
    Producto,
    Proveedor,
)
from app.servicios.inventario import (
    buscar_productos,
    calcular_kpis_inventario,
    evaluar_alerta_stock,
    normalizar_busqueda,
    stock_fisico,
    stock_reservado,
)
from app.servicios.roles import (
    puede_desactivar_catalogos,
    puede_desactivar_productos,
    puede_crear_registros,
    puede_editar_productos,
    puede_registrar_movimientos,
    puede_ver_historial_inventario,
    puede_ver_catalogo_inventario,
    puede_ver_precio_compra,
    puede_ver_precio_venta,
)
from app.servicios.movimientos import registrar_movimiento
from app.servicios.precios import actualizar_precios_producto

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


class CategoriaCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str | None = Field(default=None, max_length=4000)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Escribe el nombre de la categoría.")
        return value


class CategoriaActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    descripcion: str | None = Field(default=None, max_length=4000)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Escribe el nombre de la categoría.")
        return value


class ProveedorCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=150)
    contacto: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=120)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Escribe el nombre del proveedor.")
        return value


class ProveedorActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    contacto: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=120)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Escribe el nombre del proveedor.")
        return value


class ClienteCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=150)
    razon_social: str | None = Field(default=None, max_length=150)
    rfc: str | None = Field(default=None, max_length=13)
    direccion: str | None = Field(default=None, max_length=255)
    telefono: str | None = Field(default=None, max_length=15)
    correo: str | None = Field(default=None, max_length=100)
    contacto: str | None = Field(default=None, max_length=100)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Escribe el nombre del cliente.")
        return value

    @field_validator("razon_social", "direccion", "telefono", "contacto")
    @classmethod
    def texto_opcional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("rfc")
    @classmethod
    def validar_rfc(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value:
            return None
        if len(value) not in (12, 13) or not value.isalnum():
            raise ValueError("El RFC debe tener 12 o 13 letras y números.")
        return value

    @field_validator("correo")
    @classmethod
    def validar_correo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Escribe un correo válido.")
        return value


class PreciosActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    precio_compra: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, ge=0)
    precio_venta: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, ge=0)


class PrecioVentaActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    precio_venta: Decimal | None = Field(max_digits=12, decimal_places=2, ge=0)


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
    if not puede_ver_catalogo_inventario(usuario.rol):
        raise HTTPException(status_code=403, detail="La cuenta de administración gestiona personal.")
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
    if not puede_ver_catalogo_inventario(usuario.rol):
        raise HTTPException(status_code=403, detail="La cuenta de administración gestiona personal.")
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


@router.get("/catalogos/gestion")
async def listar_catalogos_gestion(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_editar_productos(usuario.rol):
        raise HTTPException(status_code=403, detail="Solo almacén puede gestionar catálogos.")
    incluir_inactivos = puede_desactivar_productos(usuario.rol)
    categorias = db.query(Categoria)
    proveedores = db.query(Proveedor)
    if not incluir_inactivos:
        categorias = categorias.filter(Categoria.activo == True)
        proveedores = proveedores.filter(Proveedor.activo == True)
    return {
        "categorias": [
            {"id": c.id, "nombre": c.nombre, "descripcion": c.descripcion, "activo": c.activo}
            for c in categorias.order_by(Categoria.nombre).all()
        ],
        "proveedores": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "contacto": p.contacto,
                "telefono": p.telefono,
                "correo": p.correo,
                "activo": p.activo,
            }
            for p in proveedores.order_by(Proveedor.nombre).all()
        ],
    }


def _validar_nombre_catalogo(db: Session, modelo, nombre: str, excluir_id: int | None = None):
    normalizado = " ".join(normalizar_busqueda(nombre).split())
    for existente in db.query(modelo).all():
        existente_normalizado = " ".join(normalizar_busqueda(existente.nombre).split())
        if existente.id != excluir_id and existente_normalizado == normalizado:
            raise HTTPException(status_code=409, detail="Ya existe un registro con ese nombre.")


@router.post("/categorias", status_code=201)
async def crear_categoria(
    payload: CategoriaCrear,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_editar_productos(usuario.rol):
        raise HTTPException(status_code=403, detail="No tienes permiso para crear categorías.")
    _validar_nombre_catalogo(db, Categoria, payload.nombre)
    categoria = Categoria(nombre=payload.nombre, descripcion=payload.descripcion, activo=True)
    db.add(categoria)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
    db.refresh(categoria)
    return {"categoria": {"id": categoria.id, "nombre": categoria.nombre, "activo": categoria.activo}}


@router.patch("/categorias/{categoria_id}")
async def actualizar_categoria(
    categoria_id: int,
    payload: CategoriaActualizar,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_editar_productos(usuario.rol):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar categorías.")
    categoria = db.get(Categoria, categoria_id)
    if categoria is None:
        raise HTTPException(status_code=404, detail="No encontramos esa categoría.")
    datos = payload.model_dump(exclude_unset=True)
    if "nombre" in datos and datos["nombre"] is not None:
        _validar_nombre_catalogo(db, Categoria, datos["nombre"], excluir_id=categoria_id)
    for campo, valor in datos.items():
        setattr(categoria, campo, valor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
    db.refresh(categoria)
    return {"categoria": {"id": categoria.id, "nombre": categoria.nombre, "activo": categoria.activo}}


@router.post("/categorias/{categoria_id}/desactivar")
async def desactivar_categoria(
    categoria_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_desactivar_catalogos(usuario.rol):
        raise HTTPException(status_code=403, detail="Solo almacén puede desactivar categorías.")
    categoria = db.get(Categoria, categoria_id)
    if categoria is None:
        raise HTTPException(status_code=404, detail="No encontramos esa categoría.")
    productos_activos = db.query(Producto.id).filter(
        Producto.categoria_id == categoria.id,
        Producto.activo == True,
    ).count()
    if productos_activos:
        raise HTTPException(
            status_code=409,
            detail="Primero cambia la categoría o desactiva los productos que la usan.",
        )
    categoria.activo = False
    db.commit()
    return {"ok": True, "activo": False, "categoria_id": categoria.id}


@router.post("/proveedores", status_code=201)
async def crear_proveedor(
    payload: ProveedorCrear,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_crear_registros(usuario.rol):
        raise HTTPException(status_code=403, detail="No tienes permiso para crear proveedores.")
    _validar_nombre_catalogo(db, Proveedor, payload.nombre)
    proveedor = Proveedor(**payload.model_dump(), activo=True)
    db.add(proveedor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un proveedor con ese nombre.")
    db.refresh(proveedor)
    return {"proveedor": {"id": proveedor.id, "nombre": proveedor.nombre, "activo": proveedor.activo}}


@router.patch("/proveedores/{proveedor_id}")
async def actualizar_proveedor(
    proveedor_id: int,
    payload: ProveedorActualizar,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_editar_productos(usuario.rol):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar proveedores.")
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise HTTPException(status_code=404, detail="No encontramos ese proveedor.")
    datos = payload.model_dump(exclude_unset=True)
    if "nombre" in datos and datos["nombre"] is not None:
        _validar_nombre_catalogo(db, Proveedor, datos["nombre"], excluir_id=proveedor_id)
    for campo, valor in datos.items():
        setattr(proveedor, campo, valor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un proveedor con ese nombre.")
    db.refresh(proveedor)
    return {"proveedor": {"id": proveedor.id, "nombre": proveedor.nombre, "activo": proveedor.activo}}


@router.post("/proveedores/{proveedor_id}/desactivar")
async def desactivar_proveedor(
    proveedor_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_desactivar_catalogos(usuario.rol):
        raise HTTPException(status_code=403, detail="Solo almacén puede desactivar proveedores.")
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise HTTPException(status_code=404, detail="No encontramos ese proveedor.")
    productos_activos = db.query(Producto.id).filter(
        Producto.proveedor_id == proveedor.id,
        Producto.activo == True,
    ).count()
    if productos_activos:
        raise HTTPException(
            status_code=409,
            detail="Primero cambia el proveedor o desactiva los productos que lo usan.",
        )
    proveedor.activo = False
    db.commit()
    return {"ok": True, "activo": False, "proveedor_id": proveedor.id}


@router.post("/clientes", status_code=201)
async def crear_cliente(
    payload: ClienteCrear,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_crear_registros(usuario.rol):
        raise HTTPException(status_code=403, detail="No tienes permiso para crear clientes.")
    existente = (
        db.query(Cliente)
        .filter(func.lower(Cliente.nombre) == payload.nombre.lower())
        .first()
    )
    if existente is not None:
        raise HTTPException(status_code=409, detail="Ya existe un cliente con ese nombre.")
    cliente = Cliente(**payload.model_dump())
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return {"cliente": {"id": cliente.id, "nombre": cliente.nombre}}


@router.get("/resumen")
async def resumen_inventario(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not puede_ver_catalogo_inventario(usuario.rol):
        raise HTTPException(status_code=403, detail="La cuenta de administración gestiona personal.")
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
    if not puede_crear_registros(usuario.rol):
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


@router.patch("/productos/{producto_id}/precio-venta")
async def actualizar_precio_venta_vendedor(
    producto_id: int,
    payload: PrecioVentaActualizar,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if usuario.rol != "vendedor":
        raise HTTPException(status_code=403, detail="Esta pantalla solo permite al vendedor cambiar el precio de venta.")
    try:
        producto = actualizar_precios_producto(
            db,
            producto_id=producto_id,
            usuario=usuario,
            precio_venta=payload.precio_venta,
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
    return {"ok": True, "producto_id": producto.id, "precio_venta": _dinero(producto.precio_venta) if producto.precio_venta is not None else None}


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
