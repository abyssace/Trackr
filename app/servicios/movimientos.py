"""Registro transaccional e idempotente de movimientos de inventario."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.modelos import Usuario
from app.db.negocio import MovimientoInventario, Producto
from app.servicios.inventario import stock_fisico, stock_reservado


_ENTRADAS = {"compra", "reabastecimiento", "entrada", "produccion_entrada"}
_SALIDAS = {
    "venta_mostrador",
    "venta",
    "merma",
    "salida",
    "produccion_salida",
}


@dataclass(frozen=True)
class ResultadoMovimiento:
    movimiento: MovimientoInventario
    stock_antes: int
    stock_despues: int
    advertencias: tuple[str, ...] = ()
    duplicado: bool = False


def _cantidad_firmada(tipo: str, cantidad: int, direccion: str | None) -> int:
    if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad <= 0:
        raise ValueError("La cantidad debe ser un entero mayor que cero.")

    if tipo in _ENTRADAS:
        if direccion is not None:
            raise ValueError("Este tipo de movimiento no necesita indicar dirección.")
        return cantidad
    if tipo in _SALIDAS:
        if direccion is not None:
            raise ValueError("Este tipo de movimiento no necesita indicar dirección.")
        return -cantidad
    if tipo == "ajuste":
        if direccion == "entrada":
            return cantidad
        if direccion == "salida":
            return -cantidad
        raise ValueError("Para un ajuste indica si aumenta o disminuye el stock.")
    raise ValueError(f"Tipo de movimiento no permitido: {tipo}.")


def registrar_movimiento(
    db: Session,
    *,
    producto_id: int,
    tipo_movimiento: str,
    cantidad: int,
    usuario_id: int,
    idempotency_key: str,
    direccion: str | None = None,
    pedido_id: int | None = None,
    empleado_id: int | None = None,
    empleado_entrega_id: int | None = None,
    referencia: str | None = None,
    observaciones: str | None = None,
) -> ResultadoMovimiento:
    """Valida stock e inserta exactamente un movimiento en la transacción activa.

    No hace commit: la ruta HTTP o el dispatcher del agente confirma la transacción
    completa. Los movimientos de venta ligados a pedidos deben proporcionar
    ``pedido_id``; las ventas de mostrador nunca se ligan a un pedido.
    """
    if not idempotency_key or len(idempotency_key) > 120:
        raise ValueError("Falta una clave válida para evitar registrar el movimiento dos veces.")
    if tipo_movimiento == "venta" and pedido_id is None:
        raise ValueError("Una venta ligada a pedido requiere el pedido correspondiente.")
    if tipo_movimiento == "venta_mostrador" and pedido_id is not None:
        raise ValueError("La venta de mostrador no puede ligarse a un pedido.")

    delta = _cantidad_firmada(tipo_movimiento, cantidad, direccion)

    with db.begin_nested():
        movimiento_existente = (
            db.query(MovimientoInventario)
            .filter(MovimientoInventario.idempotency_key == idempotency_key)
            .first()
        )
        if movimiento_existente:
            mismo = (
                movimiento_existente.producto_id == producto_id
                and movimiento_existente.tipo_movimiento == tipo_movimiento
                and movimiento_existente.cantidad == delta
                and movimiento_existente.pedido_id == pedido_id
                and movimiento_existente.usuario_id == usuario_id
            )
            if not mismo:
                raise ValueError("La clave de movimiento ya fue usada para otra operación.")
            stock_actual = stock_fisico(db, producto_id)
            return ResultadoMovimiento(
                movimiento=movimiento_existente,
                stock_antes=stock_actual - movimiento_existente.cantidad,
                stock_despues=stock_actual,
                duplicado=True,
            )

        usuario = db.get(Usuario, usuario_id)
        if usuario is None or not usuario.activo:
            raise ValueError("No se pudo validar al usuario responsable del movimiento.")
        producto = db.get(Producto, producto_id)
        if producto is None:
            raise ValueError("El producto no existe.")

        fisico_antes = stock_fisico(db, producto_id)
        if delta < 0 and -delta > fisico_antes:
            raise ValueError(
                f"Existencia insuficiente: hay {fisico_antes} y se intentan retirar {-delta}."
            )

        reservado_antes = stock_reservado(db, producto_id) if producto.tipo == "terminado" else 0
        movimiento = MovimientoInventario(
            producto_id=producto_id,
            cantidad=delta,
            tipo_movimiento=tipo_movimiento,
            pedido_id=pedido_id,
            empleado_id=empleado_id,
            empleado_entrega_id=empleado_entrega_id,
            usuario_id=usuario_id,
            idempotency_key=idempotency_key,
            referencia=referencia,
            observaciones=observaciones,
        )
        db.add(movimiento)
        db.flush()

        fisico_despues = fisico_antes + delta
        advertencias: list[str] = []
        if reservado_antes:
            disponible_antes = fisico_antes - reservado_antes
            disponible_despues = fisico_despues - reservado_antes
            consumido_comprometido = max(0, -disponible_despues) - max(
                0, -disponible_antes
            )
            if consumido_comprometido > 0:
                unidad = producto.unidad_medida or "piezas"
                if consumido_comprometido != 1 and unidad in {"pieza", "unidad"}:
                    unidad += "s"
                advertencias.append(
                    f"Este movimiento usa {consumido_comprometido} {unidad} "
                    "que estaban comprometidas en pedidos pendientes."
                )

        return ResultadoMovimiento(
            movimiento=movimiento,
            stock_antes=fisico_antes,
            stock_despues=fisico_despues,
            advertencias=tuple(advertencias),
        )
