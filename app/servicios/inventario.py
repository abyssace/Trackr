from decimal import Decimal
import unicodedata

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.db.negocio import (
    Cliente,
    Empleado,
    Pedido,
    PedidoItem,
    Producto,
    MovimientoInventario,
)


def stock_fisico(db: Session, producto_id: int) -> int:
    total = db.query(func.coalesce(func.sum(MovimientoInventario.cantidad), 0)).filter(
        MovimientoInventario.producto_id == producto_id
    ).scalar()
    return int(total)


def stock_reservado(db: Session, producto_id: int) -> int:
    total = (
        db.query(func.coalesce(func.sum(PedidoItem.cantidad), 0))
        .join(Pedido)
        .filter(
            PedidoItem.producto_id == producto_id,
            PedidoItem.activo == True,
            Pedido.estado == "pendiente",
        )
        .scalar()
    )
    return int(total)


def stock_disponible(db: Session, producto_id: int) -> int:
    return stock_fisico(db, producto_id) - stock_reservado(db, producto_id)


def normalizar_busqueda(texto: str | None) -> str:
    """Normaliza acentos y mayúsculas para búsquedas de catálogo."""
    base = unicodedata.normalize("NFD", texto or "")
    return "".join(ch for ch in base if unicodedata.category(ch) != "Mn").casefold().strip()


def unidad_con_cantidad(unidad: str | None, cantidad: int) -> str:
    singular = (unidad or "pieza").strip()
    if cantidad == 1:
        return singular
    plurales = {
        "pieza": "piezas",
        "unidad": "unidades",
        "caja": "cajas",
        "metro": "metros",
        "kilogramo": "kilogramos",
        "litro": "litros",
    }
    return plurales.get(singular.casefold(), singular if singular.endswith("s") else f"{singular}s")


def evaluar_alerta_stock(
    cantidad_fisica: int,
    stock_minimo: int | None,
    *,
    comprometido: int = 0,
    es_terminado: bool = False,
) -> dict[str, int | bool | None]:
    """Regla compartida: rojo por stock físico y ámbar por disponible terminado."""
    disponible = cantidad_fisica - comprometido if es_terminado else cantidad_fisica
    bajo_fisico = stock_minimo is not None and cantidad_fisica <= stock_minimo
    bajo_disponible = (
        es_terminado
        and stock_minimo is not None
        and disponible <= stock_minimo
    )
    return {
        "stock_actual": cantidad_fisica,
        "stock_comprometido": comprometido if es_terminado else 0,
        "stock_disponible": disponible,
        "bajo_minimo": bajo_fisico,
        "disponible_bajo_minimo": bool(bajo_disponible),
    }


def calcular_kpis_inventario(productos) -> dict[str, Decimal | int]:
    """Calcula valores de inventario con Decimal; precios nulos quedan pendientes."""
    costo = Decimal("0.00")
    venta = Decimal("0.00")
    sin_costo = 0
    sin_venta = 0
    for producto, cantidad in productos:
        if producto.precio_compra is None:
            sin_costo += 1
        else:
            costo += Decimal(cantidad) * producto.precio_compra
        if producto.precio_venta is None:
            sin_venta += 1
        else:
            venta += Decimal(cantidad) * producto.precio_venta
    return {
        "valor_costo": costo.quantize(Decimal("0.01")),
        "valor_venta": venta.quantize(Decimal("0.01")),
        "productos_sin_precio_compra": sin_costo,
        "productos_sin_precio_venta": sin_venta,
    }


def buscar_productos(db: Session, texto: str, *, incluir_inactivos: bool = False):
    termino = normalizar_busqueda(texto)
    consulta = db.query(Producto).options(
        selectinload(Producto.categoria), selectinload(Producto.proveedor)
    )
    if not incluir_inactivos:
        consulta = consulta.filter(Producto.activo == True)
    productos = consulta.order_by(Producto.nombre).all()
    if not termino:
        return productos

    def coincide(producto: Producto) -> bool:
        categoria = producto.categoria.nombre if producto.categoria else ""
        searchable = normalizar_busqueda(
            " ".join(
                campo or ""
                for campo in (
                    producto.nombre,
                    producto.descripcion,
                    producto.alias,
                    producto.codigo,
                    categoria,
                )
            )
        )
        if termino in searchable:
            return True

        def variantes(token: str) -> set[str]:
            resultado = {token}
            if len(token) > 5 and token.endswith("es"):
                resultado.add(token[:-2])
            if len(token) > 4 and token.endswith("s"):
                resultado.add(token[:-1])
            return resultado

        return all(
            any(variante in searchable for variante in variantes(token))
            for token in termino.split()
        )

    encontrados = [producto for producto in productos if coincide(producto)]
    # Para escáneres USB, el código exacto debe quedar primero.
    codigo_exacto = [p for p in encontrados if normalizar_busqueda(p.codigo) == termino]
    if codigo_exacto:
        encontrados = codigo_exacto + [p for p in encontrados if p not in codigo_exacto]
    return encontrados


def buscar_clientes(db: Session, texto: str):
    termino = texto.strip().lower()
    return (
        db.query(Cliente)
        .filter(
            or_(
                func.lower(Cliente.nombre).contains(termino),
                func.lower(Cliente.razon_social).contains(termino),
            )
        )
        .all()
    )


def buscar_empleados(db: Session, texto: str):
    termino = texto.strip().lower()
    return (
        db.query(Empleado)
        .filter(
            Empleado.activo == True,
            or_(
                func.lower(Empleado.nombre).contains(termino),
                func.lower(Empleado.rol).contains(termino),
            ),
        )
        .all()
    )


def buscar_pedidos(db: Session, texto: str):
    texto_limpio = texto.strip()
    if texto_limpio.isdigit():
        pedido = db.get(Pedido, int(texto_limpio))
        if pedido:
            return [pedido]

    termino = texto_limpio.lower()
    clientes = buscar_clientes(db, termino)
    if not clientes:
        return []
    cliente_ids = [c.id for c in clientes]
    return (
        db.query(Pedido)
        .filter(Pedido.cliente_id.in_(cliente_ids))
        .order_by(Pedido.fecha_pedido.desc())
        .all()
    )
