from pydantic import BaseModel, Field
from langchain_core.tools import tool
from sqlalchemy import func

from app.db.negocio import Pedido, Producto
from app.servicios.inventario import (
    stock_fisico,
    stock_reservado,
    evaluar_alerta_stock,
    buscar_productos,
    buscar_pedidos,
    unidad_con_cantidad,
)
from app.servicios.inventario import buscar_clientes as _buscar_clientes


def _resumen_producto(db, p) -> str:
    fisico = stock_fisico(db, p.id)
    reservado = stock_reservado(db, p.id) if p.tipo == "terminado" else 0
    disponible = fisico - reservado
    partes = [f"{p.nombre} ({p.tipo})"]
    partes.append(f"físico: {fisico}")
    if p.tipo == "terminado":
        partes.append(f"reservado: {reservado}")
        partes.append(f"disponible: {disponible}")
    if p.stock_minimo is not None:
        partes.append(f"mínimo: {p.stock_minimo}")
    return ", ".join(partes)


def _consultar_existencia(db, nombre: str) -> str:
    productos = buscar_productos(db, nombre)
    if not productos:
        return f"No encontré productos que coincidan con '{nombre}'."

    if len(productos) == 1:
        return _resumen_producto(db, productos[0])

    lineas = ["Encontré varios productos:"]
    for p in productos:
        lineas.append(f"- {_resumen_producto(db, p)}")
    return "\n".join(lineas)


def _listar_stock_bajo(db) -> str:
    productos = db.query(Producto).filter(
        Producto.activo == True,
        Producto.stock_minimo.isnot(None),
    ).all()

    lineas = []

    for p in productos:
        fisico = stock_fisico(db, p.id)
        reservado = stock_reservado(db, p.id) if p.tipo == "terminado" else 0
        alerta = evaluar_alerta_stock(
            fisico,
            p.stock_minimo,
            comprometido=reservado,
            es_terminado=p.tipo == "terminado",
        )
        if p.tipo == "componente":
            if alerta["bajo_minimo"]:
                lineas.append(
                    f"{p.nombre}: {fisico} {unidad_con_cantidad(p.unidad_medida, fisico)}, "
                    f"mínimo {p.stock_minimo}."
                )
        elif p.tipo == "terminado":
            if alerta["bajo_minimo"] or alerta["disponible_bajo_minimo"]:
                detalles = [
                    f"físico {fisico} {unidad_con_cantidad(p.unidad_medida, fisico)}"
                ]
                if alerta["bajo_minimo"]:
                    detalles.append("físico en el mínimo o debajo")
                if reservado:
                    detalles.append(
                        f"comprometido {reservado} {unidad_con_cantidad(p.unidad_medida, reservado)}"
                    )
                    detalles.append(
                        f"disponible {alerta['stock_disponible']} "
                        f"{unidad_con_cantidad(p.unidad_medida, alerta['stock_disponible'])}"
                    )
                detalles.append(f"mínimo {p.stock_minimo}")
                if alerta["disponible_bajo_minimo"]:
                    detalles.append("disponible en el mínimo o debajo")
                lineas.append(f"{p.nombre}: " + ", ".join(detalles) + ".")

    if not lineas:
        return "No hay productos por debajo de su mínimo de stock."
    return "Productos en mínimo o por debajo:\n" + "\n".join(f"- {linea}" for linea in lineas)


def _contar_productos_activos(db) -> int:
    return int(
        db.query(func.count(Producto.id))
        .filter(Producto.activo == True)
        .scalar()
        or 0
    )


def _resumen_pedido(p: Pedido) -> str:
    partes = [
        f"Pedido {p.id} — {p.estado}",
        f"Cliente: {p.cliente.nombre}",
        f"Fecha: {p.fecha_pedido.date().isoformat()}",
    ]
    if p.tipo_entrega:
        partes.append(f"Entrega: {p.tipo_entrega}")
    if p.paqueteria:
        partes.append(f"Paquetería: {p.paqueteria}")
    if p.guia:
        partes.append(f"Guía: {p.guia}")
    return "\n".join(partes)


def _consultar_estado_pedido(db, texto: str) -> str:
    pedidos = buscar_pedidos(db, texto)

    if not pedidos:
        return f"No encontré pedidos para '{texto}'."

    if len(pedidos) == 1:
        return _resumen_pedido(pedidos[0])

    cliente = _buscar_clientes(db, texto)
    if cliente and len(cliente) == 1:
        nombre_cliente = cliente[0].nombre
    else:
        nombre_cliente = "el cliente"

    lineas = [f"{nombre_cliente} tiene {len(pedidos)} pedidos. Mostrando los 5 más recientes:"]
    for p in pedidos[:5]:
        lineas.append(
            f"- Pedido {p.id}: {p.estado}, {p.fecha_pedido.date().isoformat()}"
        )
    if len(pedidos) > 5:
        lineas.append(f"...y {len(pedidos) - 5} más.")
    return "\n".join(lineas)


class ConsultarExistenciaInput(BaseModel):
    nombre: str = Field(description="Nombre, alias o descripción del producto")


class ConsultarEstadoPedidoInput(BaseModel):
    texto: str = Field(description="Número de pedido o nombre del cliente")


def make_negocio_tools(usuario, db):
    @tool(args_schema=ConsultarExistenciaInput)
    def consultar_existencia(nombre: str) -> str:
        """Consulta el stock físico, reservado y disponible de un producto."""
        return _consultar_existencia(db, nombre)

    @tool
    def listar_stock_bajo() -> str:
        """Indica qué productos están en su mínimo o por debajo. Usa físico y reservas."""
        return _listar_stock_bajo(db)

    @tool
    def contar_productos_activos() -> str:
        """Cuenta todos los productos activos. Úsala cuando pregunten cuántos productos hay."""
        total = _contar_productos_activos(db)
        return f"Hay {total} productos activos."

    @tool(args_schema=ConsultarEstadoPedidoInput)
    def consultar_estado_pedido(texto: str) -> str:
        """Consulta el estado de un pedido por número o cliente."""
        return _consultar_estado_pedido(db, texto)

    return [
        consultar_existencia,
        listar_stock_bajo,
        consultar_estado_pedido,
        contar_productos_activos,
    ]
