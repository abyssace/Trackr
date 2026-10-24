import json
from pydantic import BaseModel, Field, field_validator
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.db.modelos import Usuario
from app.db.negocio import Cliente, Empleado, Pedido, Producto
from app.servicios.confirmacion import crear_pendiente
from app.servicios.inventario import (
    buscar_clientes,
    buscar_empleados,
    buscar_pedidos,
    buscar_productos,
    stock_disponible,
    unidad_con_cantidad,
)
from app.servicios.roles import puede_usar_tool

# Importar para registrar los ejecutores en el dispatcher.
import app.agente.tools.ejecutores  # noqa: F401


def _candidatos_str(candidatos, tipo):
    lineas = [f"Varios {tipo}s coinciden:"]
    for c in candidatos:
        lineas.append(f"- {c.nombre}")
    return "\n".join(lineas)


def _resolver_producto(db: Session, nombre: str):
    productos = buscar_productos(db, nombre)
    if not productos:
        return None, f"No encontré un producto llamado '{nombre}'."
    if len(productos) > 1:
        return None, _candidatos_str(productos, "producto")
    return productos[0], None


def _resolver_cliente(db: Session, nombre: str):
    clientes = buscar_clientes(db, nombre)
    if not clientes:
        return None, f"No encontré un cliente llamado '{nombre}'."
    if len(clientes) > 1:
        return None, _candidatos_str(clientes, "cliente")
    return clientes[0], None


def _resolver_empleado(db: Session, nombre: str):
    if not nombre or not nombre.strip():
        return None, None
    empleados = buscar_empleados(db, nombre)
    if not empleados:
        return None, f"No encontré un empleado llamado '{nombre}'."
    if len(empleados) > 1:
        return None, _candidatos_str(empleados, "empleado")
    return empleados[0], None


def _resolver_pedido(db: Session, texto: str):
    pedidos = buscar_pedidos(db, texto)
    if not pedidos:
        return None, f"No encontré un pedido para '{texto}'."
    if len(pedidos) > 1:
        lineas = ["Varios pedidos coinciden:"]
        for p in pedidos[:5]:
            lineas.append(f"- Pedido {p.id}: {p.estado}, {p.cliente.nombre}")
        return None, "\n".join(lineas)
    return pedidos[0], None


def _empleado_desde_usuario(db: Session, usuario: Usuario):
    return db.query(Empleado).filter(Empleado.usuario_id == usuario.id).first()


def _parse_items_json(db: Session, items_json: str):
    try:
        raw = json.loads(items_json)
    except json.JSONDecodeError as e:
        return None, f"No pude entender los productos: {e}"

    if not isinstance(raw, list) or not raw:
        return None, "La lista de productos está vacía o no es válida."

    items = []
    for idx, it in enumerate(raw, start=1):
        if not isinstance(it, dict):
            return None, f"El ítem {idx} no es válido."
        nombre = it.get("producto") or it.get("nombre")
        cantidad = it.get("cantidad")
        if not nombre:
            return None, f"El ítem {idx} no tiene nombre de producto."
        if not isinstance(cantidad, int) or cantidad <= 0:
            return None, f"El ítem {idx} debe tener una cantidad entera positiva."

        producto, error = _resolver_producto(db, nombre)
        if error:
            return None, f"Ítem {idx}: {error}"

        items.append(
            {
                "producto_id": producto.id,
                "cantidad": cantidad,
                "producto_nombre": producto.nombre,
                "precio_unitario": it.get("precio_unitario"),
            }
        )
    return items, None


def _resumen_items(db: Session, items: list) -> str:
    lineas = []
    for it in items:
        disponible = stock_disponible(db, it["producto_id"])
        lineas.append(
            f"- {it['producto_nombre']}: {it['cantidad']} piezas (disponible actual: {disponible})"
        )
    return "\n".join(lineas)


class CrearPedidoInput(BaseModel):
    cliente: str = Field(description="Nombre del cliente")
    items_json: str = Field(
        description='JSON con lista de productos, ej: [{"producto":"Medidor A-100 1 pulgada","cantidad":10}]'
    )
    tipo_entrega: str | None = Field(
        default=None, description="directa o paqueteria (opcional)"
    )
    observaciones: str | None = Field(default=None, description="Notas adicionales")

    @field_validator("tipo_entrega")
    @classmethod
    def _validar_entrega(cls, v):
        if v is None:
            return v
        v = v.lower()
        if v not in ("directa", "paqueteria"):
            raise ValueError("tipo_entrega debe ser 'directa' o 'paqueteria'")
        return v


class EditarPedidoInput(BaseModel):
    pedido: str = Field(description="Número de pedido o nombre del cliente")
    items_json: str = Field(description='Nueva lista de productos en JSON')


class CancelarPedidoInput(BaseModel):
    pedido: str = Field(description="Número de pedido o nombre del cliente")


class RegistrarEntradaInput(BaseModel):
    producto: str = Field(description="Nombre del producto o componente")
    cantidad: int = Field(description="Cantidad entera positiva", ge=1)
    empleado_recibe: str | None = Field(default=None, description="Empleado que recibe")
    empleado_entrega: str | None = Field(
        default=None, description="Empleado de almacén que entrega/recibe el material"
    )
    referencia: str | None = Field(default=None, description="Factura, remisión, etc.")
    observaciones: str | None = Field(default=None)


class RegistrarTerminadoInput(BaseModel):
    producto: str = Field(description="Nombre del producto terminado")
    cantidad: int = Field(description="Cantidad entera positiva", ge=1)


class RegistrarEnvioInput(BaseModel):
    pedido: str = Field(description="Número de pedido o cliente")
    paqueteria: str = Field(description="Nombre de la paquetería")
    guia: str = Field(description="Número de guía")


class MarcarEntregadoInput(BaseModel):
    pedido: str = Field(description="Número de pedido o cliente")


class ActualizarStockMinimoInput(BaseModel):
    producto: str = Field(description="Nombre o código del producto")
    stock_minimo: int = Field(description="Nuevo mínimo de alerta; entero igual o mayor que cero", ge=0)


def make_escritura_tools(usuario: Usuario, db: Session):
    @tool(args_schema=CrearPedidoInput)
    def crear_pedido(
        cliente: str,
        items_json: str,
        tipo_entrega: str | None = None,
        observaciones: str | None = None,
    ) -> str:
        """Crea un pedido nuevo. Requiere confirmación."""
        cliente_obj, error = _resolver_cliente(db, cliente)
        if error:
            return error

        items, error = _parse_items_json(db, items_json)
        if error:
            return error

        empleado = _empleado_desde_usuario(db, usuario)

        args = {
            "cliente_id": cliente_obj.id,
            "cliente_nombre": cliente_obj.nombre,
            "items": [
                {
                    "producto_id": it["producto_id"],
                    "cantidad": it["cantidad"],
                    "precio_unitario": it.get("precio_unitario"),
                }
                for it in items
            ],
            "empleado_id": empleado.id if empleado else None,
            "tipo_entrega": tipo_entrega,
            "observaciones": observaciones,
        }

        resumen = (
            f"Voy a crear un pedido para {cliente_obj.nombre}:\n"
            f"{_resumen_items(db, items)}\n\n"
            f"Entrega: {tipo_entrega or 'por definir'}.\n"
            f"¿Confirmas?"
        )
        crear_pendiente(db, usuario.id, "crear_pedido", args, resumen)
        return resumen

    @tool(args_schema=EditarPedidoInput)
    def editar_pedido(pedido: str, items_json: str) -> str:
        """Edita un pedido pendiente. Requiere confirmación."""
        pedido_obj, error = _resolver_pedido(db, pedido)
        if error:
            return error
        if pedido_obj.estado != "pendiente":
            return f"Solo se pueden editar pedidos pendientes. El pedido {pedido_obj.id} está {pedido_obj.estado}."

        items, error = _parse_items_json(db, items_json)
        if error:
            return error

        args = {
            "pedido_id": pedido_obj.id,
            "items": [
                {
                    "producto_id": it["producto_id"],
                    "cantidad": it["cantidad"],
                    "precio_unitario": it.get("precio_unitario"),
                }
                for it in items
            ],
        }

        resumen = (
            f"Voy a editar el pedido {pedido_obj.id} ({pedido_obj.cliente.nombre}):\n"
            f"{_resumen_items(db, items)}\n\n"
            f"¿Confirmas?"
        )
        crear_pendiente(db, usuario.id, "editar_pedido", args, resumen)
        return resumen

    @tool(args_schema=CancelarPedidoInput)
    def cancelar_pedido(pedido: str) -> str:
        """Cancela un pedido. Requiere confirmación."""
        pedido_obj, error = _resolver_pedido(db, pedido)
        if error:
            return error
        if pedido_obj.estado in ("entregado", "cancelado"):
            return f"El pedido {pedido_obj.id} ya está {pedido_obj.estado}; no se puede cancelar."

        args = {"pedido_id": pedido_obj.id}
        resumen = (
            f"Voy a cancelar el pedido {pedido_obj.id} de {pedido_obj.cliente.nombre}. "
            f"Si ya se descontó inventario, se revertirá. ¿Confirmas?"
        )
        crear_pendiente(db, usuario.id, "cancelar_pedido", args, resumen)
        return resumen

    @tool(args_schema=RegistrarEntradaInput)
    def registrar_entrada_mercancia(
        producto: str,
        cantidad: int,
        empleado_recibe: str | None = None,
        empleado_entrega: str | None = None,
        referencia: str | None = None,
        observaciones: str | None = None,
    ) -> str:
        """Registra una entrada de mercancía al inventario. Requiere confirmación."""
        producto_obj, error = _resolver_producto(db, producto)
        if error:
            return error

        recibe, error = _resolver_empleado(db, empleado_recibe) if empleado_recibe else (None, None)
        if error:
            return error
        entrega, error = _resolver_empleado(db, empleado_entrega) if empleado_entrega else (None, None)
        if error:
            return error

        args = {
            "producto_id": producto_obj.id,
            "cantidad": cantidad,
            "empleado_recibe_id": recibe.id if recibe else None,
            "empleado_entrega_id": entrega.id if entrega else None,
            "referencia": referencia,
            "observaciones": observaciones,
        }

        resumen = (
            f"Voy a registrar una entrada de {cantidad} {producto_obj.unidad_medida or 'piezas'} "
            f"de {producto_obj.nombre}.\n"
        )
        if referencia:
            resumen += f"Referencia: {referencia}.\n"
        resumen += "¿Confirmas?"
        crear_pendiente(db, usuario.id, "registrar_entrada_mercancia", args, resumen)
        return resumen

    @tool(args_schema=RegistrarTerminadoInput)
    def registrar_terminado(producto: str, cantidad: int) -> str:
        """Registra la producción de productos terminados. Requiere confirmación."""
        producto_obj, error = _resolver_producto(db, producto)
        if error:
            return error
        if producto_obj.tipo != "terminado":
            return f"{producto_obj.nombre} no es un producto terminado."

        args = {"producto_id": producto_obj.id, "cantidad": cantidad}
        resumen = (
            f"Voy a registrar {cantidad} {producto_obj.unidad_medida or 'piezas'} de "
            f"{producto_obj.nombre} como terminados. Se descontarán los componentes de la receta. "
            f"¿Confirmas?"
        )
        crear_pendiente(db, usuario.id, "registrar_terminado", args, resumen)
        return resumen

    @tool(args_schema=RegistrarEnvioInput)
    def registrar_envio(pedido: str, paqueteria: str, guia: str) -> str:
        """Marca un pedido como enviado por paquetería. Requiere confirmación."""
        pedido_obj, error = _resolver_pedido(db, pedido)
        if error:
            return error
        if pedido_obj.estado != "pendiente":
            return f"El pedido {pedido_obj.id} ya está {pedido_obj.estado}."

        args = {
            "pedido_id": pedido_obj.id,
            "paqueteria": paqueteria,
            "guia": guia,
        }
        resumen = (
            f"Voy a marcar el pedido {pedido_obj.id} como enviado por {paqueteria}, "
            f"guía {guia}. Se descontará inventario. ¿Confirmas?"
        )
        crear_pendiente(db, usuario.id, "registrar_envio", args, resumen)
        return resumen

    @tool(args_schema=MarcarEntregadoInput)
    def marcar_entregado(pedido: str) -> str:
        """Marca un pedido como entregado. Requiere confirmación."""
        pedido_obj, error = _resolver_pedido(db, pedido)
        if error:
            return error
        if pedido_obj.estado == "entregado":
            return f"El pedido {pedido_obj.id} ya está entregado."
        if pedido_obj.estado == "cancelado":
            return f"El pedido {pedido_obj.id} está cancelado."

        args = {"pedido_id": pedido_obj.id}
        resumen = (
            f"Voy a marcar el pedido {pedido_obj.id} como entregado. "
            f"Se descontará inventario si aún no se había hecho. ¿Confirmas?"
        )
        crear_pendiente(db, usuario.id, "marcar_entregado", args, resumen)
        return resumen

    @tool(args_schema=ActualizarStockMinimoInput)
    def actualizar_stock_minimo(producto: str, stock_minimo: int) -> str:
        """Cambia el mínimo de alerta de un producto. Solo administración/almacén; requiere confirmación."""
        if not puede_usar_tool(usuario.rol, "actualizar_stock_minimo"):
            return "Tu perfil no tiene permiso para cambiar mínimos de stock."
        producto_obj, error = _resolver_producto(db, producto)
        if error:
            return error
        if producto_obj.stock_minimo == stock_minimo:
            return f"{producto_obj.nombre} ya tiene un mínimo de {stock_minimo}."

        anterior = producto_obj.stock_minimo
        args = {"producto_id": producto_obj.id, "stock_minimo": stock_minimo}
        unidad = unidad_con_cantidad(producto_obj.unidad_medida, stock_minimo)
        resumen = (
            f"Voy a cambiar el mínimo de {producto_obj.nombre} de "
            f"{anterior if anterior is not None else 'sin configurar'} a "
            f"{stock_minimo} {unidad}. ¿Confirmas?"
        )
        crear_pendiente(db, usuario.id, "actualizar_stock_minimo", args, resumen)
        return resumen

    return [
        crear_pedido,
        editar_pedido,
        cancelar_pedido,
        registrar_entrada_mercancia,
        registrar_terminado,
        registrar_envio,
        marcar_entregado,
        actualizar_stock_minimo,
    ]
