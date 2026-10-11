from sqlalchemy import func, or_
from sqlalchemy.orm import Session

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
            Pedido.estado == "pendiente",
        )
        .scalar()
    )
    return int(total)


def stock_disponible(db: Session, producto_id: int) -> int:
    return stock_fisico(db, producto_id) - stock_reservado(db, producto_id)


def buscar_productos(db: Session, texto: str):
    termino = texto.strip().lower()
    return (
        db.query(Producto)
        .filter(
            Producto.activo == True,
            or_(
                func.lower(Producto.nombre).contains(termino),
                func.lower(Producto.descripcion).contains(termino),
                func.lower(Producto.alias).contains(termino),
            ),
        )
        .all()
    )


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
