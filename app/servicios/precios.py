"""Price updates whose SQLite trigger records the authenticated user."""

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.db.modelos import Usuario
from app.db.negocio import ContextoAuditoriaPrecio, Producto
from app.servicios.roles import puede_editar_precio_compra, puede_editar_precio_venta

_SIN_CAMBIO = object()


def actualizar_precios_producto(
    db: Session,
    *,
    producto_id: int,
    usuario: Usuario,
    precio_compra: Decimal | None | Any = _SIN_CAMBIO,
    precio_venta: Decimal | None | Any = _SIN_CAMBIO,
) -> Producto:
    """Actualiza los campos permitidos y deja que el trigger escriba la auditoría.

    ``usuario`` debe provenir de la sesión autenticada. El contexto SQLite y los
    cambios de precio comparten una transacción; el actor se limpia antes de
    confirmar para que no se atribuya a otra solicitud del pool.
    """
    if precio_compra is _SIN_CAMBIO and precio_venta is _SIN_CAMBIO:
        raise ValueError("Indica al menos un precio para actualizar.")
    if precio_compra is not _SIN_CAMBIO and not puede_editar_precio_compra(usuario.rol):
        raise PermissionError("Tu rol no puede cambiar el precio de compra.")
    if precio_venta is not _SIN_CAMBIO and not puede_editar_precio_venta(usuario.rol):
        raise PermissionError("Tu rol no puede cambiar el precio de venta.")

    for valor in (precio_compra, precio_venta):
        if valor is _SIN_CAMBIO or valor is None:
            continue
        if not isinstance(valor, Decimal) or not valor.is_finite() or valor < 0:
            raise ValueError("El precio debe ser un importe válido, cero o mayor.")
        if max(0, -valor.as_tuple().exponent) > 2:
            raise ValueError("El precio admite como máximo dos decimales.")

    if not usuario.activo:
        raise PermissionError("La cuenta del usuario está inactiva.")

    with db.begin_nested():
        producto = db.get(Producto, producto_id)
        if producto is None or not producto.activo:
            raise ValueError("El producto no existe o está inactivo.")
        contexto = db.get(ContextoAuditoriaPrecio, 1)
        if contexto is None:
            raise RuntimeError("Falta aplicar la migración de auditoría de precios.")

        contexto.usuario_id = usuario.id
        db.flush()
        if precio_compra is not _SIN_CAMBIO:
            producto.precio_compra = precio_compra
        if precio_venta is not _SIN_CAMBIO:
            producto.precio_venta = precio_venta
        db.flush()  # El trigger guarda actor, campo, valores anteriores/nuevos y fecha/hora.
        contexto.usuario_id = None
        db.flush()

    return producto
