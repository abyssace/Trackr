from sqlalchemy.orm import Session

from app.db.negocio import (
    Pedido,
    PedidoItem,
    Producto,
    Receta,
)
from app.servicios.confirmacion import registrar_ejecutor
from app.servicios.inventario import stock_disponible
from app.servicios.movimientos import registrar_movimiento


def _registrar_movimiento_agente(db: Session, args: dict, **campos):
    usuario_id = args.get("_responsable_usuario_id")
    clave_base = args.get("_idempotency_base")
    if not usuario_id or not clave_base:
        raise ValueError("El movimiento requiere una sesión confirmada del usuario.")
    return registrar_movimiento(
        db,
        usuario_id=usuario_id,
        idempotency_key=f"{clave_base}:{campos.pop('clave')}"[:120],
        **campos,
    )


def _deducir_inventario_pedido(db: Session, pedido: Pedido, args: dict) -> list[str]:
    """Descuenta stock por cada línea del pedido que aún no esté descontada."""
    advertencias = []
    for item in pedido.items:
        if not item.activo or item.inventario_descontado:
            continue
        resultado = _registrar_movimiento_agente(
            db,
            args,
            clave=f"pedido:{pedido.id}:item:{item.id}:venta",
            producto_id=item.producto_id,
            tipo_movimiento="venta",
            cantidad=item.cantidad,
            pedido_id=pedido.id,
            referencia=f"Venta pedido {pedido.id}",
        )
        item.inventario_descontado = True
        advertencias.extend(resultado.advertencias)
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
        if not item.activo:
            continue
        if item.inventario_descontado:
            _registrar_movimiento_agente(
                db,
                args,
                clave=f"pedido:{pedido.id}:item:{item.id}:reversion-edicion",
                producto_id=item.producto_id,
                tipo_movimiento="ajuste",
                direccion="entrada",
                cantidad=item.cantidad,
                pedido_id=pedido.id,
                referencia=f"Reversión por edición pedido {pedido.id}",
            )
            item.inventario_descontado = False
        item.activo = False

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
        if not item.activo:
            continue
        if item.inventario_descontado:
            _registrar_movimiento_agente(
                db,
                args,
                clave=f"pedido:{pedido.id}:item:{item.id}:reversion-cancelacion",
                producto_id=item.producto_id,
                tipo_movimiento="ajuste",
                direccion="entrada",
                cantidad=item.cantidad,
                pedido_id=pedido.id,
                referencia=f"Reversión por cancelación pedido {pedido.id}",
            )
            item.inventario_descontado = False

    pedido.estado = "cancelado"
    return f"Pedido {pedido.id} cancelado. El stock descontado fue revertido."


@registrar_ejecutor("registrar_entrada_mercancia")
async def ejecutar_registrar_entrada_mercancia(db: Session, args: dict) -> str:
    producto = db.get(Producto, args["producto_id"])
    resultado = _registrar_movimiento_agente(
        db,
        args,
        clave="entrada-mercancia",
        producto_id=producto.id,
        cantidad=args["cantidad"],
        tipo_movimiento="reabastecimiento",
        empleado_id=args.get("empleado_recibe_id"),
        empleado_entrega_id=args.get("empleado_entrega_id"),
        referencia=args.get("referencia") or "Entrada de mercancía",
        observaciones=args.get("observaciones"),
    )
    resultado_texto = (
        f"Entrada registrada: {args['cantidad']} {producto.unidad_medida or 'piezas'} "
        f"de {producto.nombre}. Stock físico ahora: {resultado.stock_despues}."
    )
    if resultado.advertencias:
        resultado_texto += "\n" + "\n".join(resultado.advertencias)
    return resultado_texto


@registrar_ejecutor("registrar_terminado")
async def ejecutar_registrar_terminado(db: Session, args: dict) -> str:
    producto = db.get(Producto, args["producto_id"])
    cantidad = args["cantidad"]
    recetas = db.query(Receta).filter(Receta.producto_terminado_id == producto.id).all()

    advertencias = []
    for receta in recetas:
        total_componente = receta.cantidad_requerida * cantidad
        comp = db.get(Producto, receta.producto_componente_id)
        resultado = _registrar_movimiento_agente(
            db,
            args,
            clave=f"produccion:componente:{receta.id}",
            producto_id=comp.id,
            cantidad=total_componente,
            tipo_movimiento="produccion_salida",
            referencia=f"Producción {cantidad} x {producto.nombre}",
        )
        advertencias.extend(resultado.advertencias)

    _registrar_movimiento_agente(
        db,
        args,
        clave="produccion:producto-terminado",
        producto_id=producto.id,
        cantidad=cantidad,
        tipo_movimiento="produccion_entrada",
        referencia="Producción terminada",
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

    advertencias = _deducir_inventario_pedido(db, pedido, args)
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

    advertencias = _deducir_inventario_pedido(db, pedido, args)
    lineas = [f"Pedido {pedido.id} marcado como entregado (entrega {pedido.tipo_entrega})."]
    if advertencias:
        lineas.append("Advertencias:")
        lineas.extend(f"- {a}" for a in advertencias)
    return "\n".join(lineas)
