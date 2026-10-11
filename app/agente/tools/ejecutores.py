from sqlalchemy.orm import Session

from app.db.negocio import (
    Pedido,
    PedidoItem,
    Producto,
    MovimientoInventario,
    Receta,
)
from app.servicios.confirmacion import registrar_ejecutor
from app.servicios.inventario import stock_fisico, stock_disponible


def _deducir_inventario_pedido(db: Session, pedido: Pedido) -> list[str]:
    """Descuenta stock por cada línea del pedido que aún no esté descontada."""
    advertencias = []
    for item in pedido.items:
        if item.inventario_descontado:
            continue
        disponible_antes = stock_disponible(db, item.producto_id)
        mov = MovimientoInventario(
            producto_id=item.producto_id,
            cantidad=-item.cantidad,
            tipo_movimiento="venta",
            pedido_id=pedido.id,
            referencia=f"Venta pedido {pedido.id}",
        )
        db.add(mov)
        item.inventario_descontado = True
        disponible_despues = disponible_antes - item.cantidad
        if disponible_despues < 0:
            advertencias.append(
                f"{item.producto.nombre}: quedará con disponible negativo ({disponible_despues})."
            )
    return advertencias


@registrar_ejecutor("crear_pedido")
async def ejecutar_crear_pedido(db: Session, args: dict) -> str:
    pedido = Pedido(
        cliente_id=args["cliente_id"],
        empleado_id=args.get("empleado_id"),
        estado="pendiente",
        tipo_entrega=args.get("tipo_entrega"),
        observaciones=args.get("observaciones"),
    )
    db.add(pedido)
    db.flush()

    for it in args["items"]:
        item = PedidoItem(
            pedido_id=pedido.id,
            producto_id=it["producto_id"],
            cantidad=it["cantidad"],
            precio_unitario=it.get("precio_unitario"),
        )
        db.add(item)

    advertencias = []
    for it in args["items"]:
        prod = db.get(Producto, it["producto_id"])
        disponible = stock_disponible(db, prod.id)
        if disponible < it["cantidad"]:
            advertencias.append(
                f"{prod.nombre}: disponible {disponible}, pides {it['cantidad']} (quedará negativo)."
            )

    lineas = [f"Pedido {pedido.id} creado para {args['cliente_nombre']}."]
    for it in args["items"]:
        prod = db.get(Producto, it["producto_id"])
        lineas.append(f"- {prod.nombre}: {it['cantidad']} piezas")
    if advertencias:
        lineas.append("\nAdvertencias:")
        lineas.extend(f"- {a}" for a in advertencias)
    return "\n".join(lineas)


@registrar_ejecutor("editar_pedido")
async def ejecutar_editar_pedido(db: Session, args: dict) -> str:
    pedido = db.get(Pedido, args["pedido_id"])
    if pedido.estado != "pendiente":
        raise ValueError(f"No se puede editar un pedido {pedido.estado}.")

    # Si ya se descontó inventario, lo revertimos antes de reemplazar líneas.
    for item in pedido.items:
        if item.inventario_descontado:
            db.add(
                MovimientoInventario(
                    producto_id=item.producto_id,
                    cantidad=item.cantidad,
                    tipo_movimiento="ajuste",
                    pedido_id=pedido.id,
                    referencia=f"Reversión por edición pedido {pedido.id}",
                )
            )
            item.inventario_descontado = False

    db.query(PedidoItem).filter(PedidoItem.pedido_id == pedido.id).delete()

    for it in args["items"]:
        db.add(
            PedidoItem(
                pedido_id=pedido.id,
                producto_id=it["producto_id"],
                cantidad=it["cantidad"],
                precio_unitario=it.get("precio_unitario"),
            )
        )

    lineas = [f"Pedido {pedido.id} actualizado."]
    for it in args["items"]:
        prod = db.get(Producto, it["producto_id"])
        lineas.append(f"- {prod.nombre}: {it['cantidad']} piezas")
    return "\n".join(lineas)


@registrar_ejecutor("cancelar_pedido")
async def ejecutar_cancelar_pedido(db: Session, args: dict) -> str:
    pedido = db.get(Pedido, args["pedido_id"])
    if pedido.estado in ("entregado", "cancelado"):
        raise ValueError(f"El pedido ya está {pedido.estado}.")

    for item in pedido.items:
        if item.inventario_descontado:
            db.add(
                MovimientoInventario(
                    producto_id=item.producto_id,
                    cantidad=item.cantidad,
                    tipo_movimiento="ajuste",
                    pedido_id=pedido.id,
                    referencia=f"Reversión por cancelación pedido {pedido.id}",
                )
            )
            item.inventario_descontado = False

    pedido.estado = "cancelado"
    return f"Pedido {pedido.id} cancelado. El stock descontado fue revertido."


@registrar_ejecutor("registrar_entrada_mercancia")
async def ejecutar_registrar_entrada_mercancia(db: Session, args: dict) -> str:
    producto = db.get(Producto, args["producto_id"])
    mov = MovimientoInventario(
        producto_id=producto.id,
        cantidad=args["cantidad"],
        tipo_movimiento="entrada",
        empleado_id=args.get("empleado_recibe_id"),
        empleado_entrega_id=args.get("empleado_entrega_id"),
        referencia=args.get("referencia") or "Entrada de mercancía",
        observaciones=args.get("observaciones"),
    )
    db.add(mov)

    fisico = stock_fisico(db, producto.id) + args["cantidad"]
    return (
        f"Entrada registrada: {args['cantidad']} {producto.unidad_medida or 'piezas'} "
        f"de {producto.nombre}. Stock físico ahora: {fisico}."
    )


@registrar_ejecutor("registrar_terminado")
async def ejecutar_registrar_terminado(db: Session, args: dict) -> str:
    producto = db.get(Producto, args["producto_id"])
    cantidad = args["cantidad"]
    recetas = db.query(Receta).filter(Receta.producto_terminado_id == producto.id).all()

    advertencias = []
    for receta in recetas:
        total_componente = receta.cantidad_requerida * cantidad
        comp = db.get(Producto, receta.producto_componente_id)
        disponible_antes = stock_disponible(db, comp.id)
        db.add(
            MovimientoInventario(
                producto_id=comp.id,
                cantidad=-total_componente,
                tipo_movimiento="salida",
                referencia=f"Producción {cantidad} x {producto.nombre}",
            )
        )
        disponible_despues = disponible_antes - total_componente
        if disponible_despues < 0:
            advertencias.append(
                f"{comp.nombre}: quedará con disponible negativo ({disponible_despues})."
            )

    db.add(
        MovimientoInventario(
            producto_id=producto.id,
            cantidad=cantidad,
            tipo_movimiento="entrada",
            referencia=f"Producción terminada",
        )
    )

    lineas = [f"Producción registrada: {cantidad} {producto.unidad_medida or 'piezas'} de {producto.nombre}."]
    if advertencias:
        lineas.append("Advertencias:")
        lineas.extend(f"- {a}" for a in advertencias)
    return "\n".join(lineas)


@registrar_ejecutor("registrar_envio")
async def ejecutar_registrar_envio(db: Session, args: dict) -> str:
    pedido = db.get(Pedido, args["pedido_id"])
    pedido.estado = "enviado"
    pedido.tipo_entrega = "paqueteria"
    pedido.paqueteria = args["paqueteria"]
    pedido.guia = args["guia"]

    advertencias = _deducir_inventario_pedido(db, pedido)
    lineas = [
        f"Pedido {pedido.id} marcado como enviado.",
        f"Paquetería: {args['paqueteria']}, guía: {args['guia']}.",
    ]
    if advertencias:
        lineas.append("Advertencias:")
        lineas.extend(f"- {a}" for a in advertencias)
    return "\n".join(lineas)


@registrar_ejecutor("marcar_entregado")
async def ejecutar_marcar_entregado(db: Session, args: dict) -> str:
    pedido = db.get(Pedido, args["pedido_id"])
    pedido.estado = "entregado"
    if not pedido.tipo_entrega:
        pedido.tipo_entrega = "directa"

    advertencias = _deducir_inventario_pedido(db, pedido)
    lineas = [f"Pedido {pedido.id} marcado como entregado (entrega {pedido.tipo_entrega})."]
    if advertencias:
        lineas.append("Advertencias:")
        lineas.extend(f"- {a}" for a in advertencias)
    return "\n".join(lineas)
