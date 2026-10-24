from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.modelos import Usuario
from app.db.negocio import Categoria, Producto, Proveedor
from app.servicios.inventario import (
    buscar_productos,
    calcular_kpis_inventario,
    evaluar_alerta_stock,
    stock_fisico,
    stock_reservado,
)
from app.servicios.roles import (
    puede_ver_precio_compra,
    puede_ver_precio_venta,
)

router = APIRouter(prefix="/api/inventario", tags=["inventario"])


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
    return {
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
