from pydantic import BaseModel, Field
from langchain_core.tools import tool

from app.db.negocio import Pedido
from app.servicios.inventario import (
    stock_fisico,
    stock_reservado,
    buscar_productos,
    buscar_pedidos,
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
    from app.db.negocio import Producto

    productos = db.query(Producto).filter(
        Producto.activo == True,
        Producto.stock_minimo.isnot(None),
    ).all()

    componentes_bajos = []
    terminados_bajos = []

    for p in productos:
        fisico = stock_fisico(db, p.id)
        if p.tipo == "componente":
            if fisico <= p.stock_minimo:
                componentes_bajos.append(_resumen_producto(db, p))
        elif p.tipo == "terminado":
            disponible = fisico - stock_reservado(db, p.id)
            if disponible <= p.stock_minimo:
                terminados_bajos.append(_resumen_producto(db, p))

    partes = []
    if componentes_bajos:
        partes.append("Componentes bajo mínimo:")
        partes.extend(f"- {l}" for l in componentes_bajos)
    else:
        partes.append("No hay componentes bajo el mínimo.")

    partes.append("")

    if terminados_bajos:
        partes.append("Productos terminados con disponible bajo mínimo:")
        partes.extend(f"- {l}" for l in terminados_bajos)
    else:
        partes.append("No hay productos terminados con disponible bajo el mínimo.")

    return "\n".join(partes)


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
        """Lista componentes bajo su mínimo y productos terminados con disponible bajo mínimo."""
        return _listar_stock_bajo(db)

    @tool(args_schema=ConsultarEstadoPedidoInput)
    def consultar_estado_pedido(texto: str) -> str:
        """Consulta el estado de un pedido por número o cliente."""
        return _consultar_estado_pedido(db, texto)

    return [consultar_existencia, listar_stock_bajo, consultar_estado_pedido]
