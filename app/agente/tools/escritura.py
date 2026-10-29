import json
from pydantic import BaseModel, Field, field_validator
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.db.modelos import Usuario
from app.db.negocio import Empleado
from app.servicios.confirmacion import ejecutar_accion_directa
from app.servicios.inventario import (
    buscar_clientes,
    buscar_empleados,
    buscar_pedidos,
    buscar_productos,
)
from app.servicios.roles import puede_usar_tool

# Importar para registrar los ejecutores en el dispatcher.
import app.agente.tools.ejecutores  # noqa: F401


_CONFIRMADO = Field(
    default=False,
    description="true solo si el empleado respondió Sí a los datos mostrados; si no, false",
)
_FALTA_CONFIRMACION = "falta confirmacion"


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


class CrearPedidoInput(BaseModel):
    cliente: str = Field(description="Nombre del cliente")
    items_json: str = Field(
        description='JSON con lista de productos, ej: [{"producto":"Medidor A-100 1 pulgada","cantidad":10}]'
    )
    tipo_entrega: str | None = Field(
        default=None, description="directa o paqueteria (opcional)"
    )
    observaciones: str | None = Field(default=None, description="Notas adicionales")
    confirmado: bool = _CONFIRMADO

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
    confirmado: bool = _CONFIRMADO


class CancelarPedidoInput(BaseModel):
    pedido: str = Field(description="Número de pedido o nombre del cliente")
    confirmado: bool = _CONFIRMADO


class RegistrarEntradaInput(BaseModel):
    producto: str = Field(description="Nombre del producto o componente")
    cantidad: int = Field(description="Cantidad entera positiva", ge=1)
    empleado_recibe: str | None = Field(default=None, description="Empleado que recibe")
    empleado_entrega: str | None = Field(
        default=None, description="Empleado de almacén que entrega/recibe el material"
    )
    referencia: str | None = Field(default=None, description="Factura, remisión, etc.")
    observaciones: str | None = Field(default=None)
    confirmado: bool = _CONFIRMADO


class RegistrarTerminadoInput(BaseModel):
    producto: str = Field(description="Nombre del producto terminado")
    cantidad: int = Field(description="Cantidad entera positiva", ge=1)
    confirmado: bool = _CONFIRMADO


class RegistrarEnvioInput(BaseModel):
    pedido: str = Field(description="Número de pedido o cliente")
    paqueteria: str = Field(description="Nombre de la paquetería")
    guia: str = Field(description="Número de guía")
    confirmado: bool = _CONFIRMADO


class MarcarEntregadoInput(BaseModel):
    pedido: str = Field(description="Número de pedido o cliente")
    confirmado: bool = _CONFIRMADO


class ActualizarStockMinimoInput(BaseModel):
    producto: str = Field(description="Nombre o código del producto")
    stock_minimo: int = Field(description="Nuevo mínimo de alerta; entero igual o mayor que cero", ge=0)
    confirmado: bool = _CONFIRMADO


def make_escritura_tools(usuario: Usuario, db: Session):
    @tool(args_schema=CrearPedidoInput)
    async def crear_pedido(
        cliente: str,
        items_json: str,
        tipo_entrega: str | None = None,
        observaciones: str | None = None,
        confirmado: bool = False,
    ) -> str:
        """Crea un pedido nuevo. Escribe solo si confirmado es true, después de que el empleado respondió Sí."""
        if not confirmado:
            return _FALTA_CONFIRMACION
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
        return await ejecutar_accion_directa(db, "crear_pedido", args, usuario)

    @tool(args_schema=EditarPedidoInput)
    async def editar_pedido(pedido: str, items_json: str, confirmado: bool = False) -> str:
        """Edita los productos de un pedido pendiente. Escribe solo si confirmado es true, después de que el empleado respondió Sí."""
        if not confirmado:
            return _FALTA_CONFIRMACION
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
        return await ejecutar_accion_directa(db, "editar_pedido", args, usuario)

    @tool(args_schema=CancelarPedidoInput)
    async def cancelar_pedido(pedido: str, confirmado: bool = False) -> str:
        """Cancela un pedido. Escribe solo si confirmado es true, después de que el empleado respondió Sí."""
        if not confirmado:
            return _FALTA_CONFIRMACION
        pedido_obj, error = _resolver_pedido(db, pedido)
        if error:
            return error
        if pedido_obj.estado in ("entregado", "cancelado"):
            return f"El pedido {pedido_obj.id} ya está {pedido_obj.estado}; no se puede cancelar."

        args = {"pedido_id": pedido_obj.id}
        return await ejecutar_accion_directa(db, "cancelar_pedido", args, usuario)

    @tool(args_schema=RegistrarEntradaInput)
    async def registrar_entrada_mercancia(
        producto: str,
        cantidad: int,
        empleado_recibe: str | None = None,
        empleado_entrega: str | None = None,
        referencia: str | None = None,
        observaciones: str | None = None,
        confirmado: bool = False,
    ) -> str:
        """Registra una entrada de mercancía al inventario. Escribe solo si confirmado es true, después de que el empleado respondió Sí."""
        if not confirmado:
            return _FALTA_CONFIRMACION
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
        return await ejecutar_accion_directa(db, "registrar_entrada_mercancia", args, usuario)

    @tool(args_schema=RegistrarTerminadoInput)
    async def registrar_terminado(producto: str, cantidad: int, confirmado: bool = False) -> str:
        """Registra la producción de productos terminados. Escribe solo si confirmado es true, después de que el empleado respondió Sí."""
        if not confirmado:
            return _FALTA_CONFIRMACION
        producto_obj, error = _resolver_producto(db, producto)
        if error:
            return error
        if producto_obj.tipo != "terminado":
            return f"{producto_obj.nombre} no es un producto terminado."

        args = {"producto_id": producto_obj.id, "cantidad": cantidad}
        return await ejecutar_accion_directa(db, "registrar_terminado", args, usuario)

    @tool(args_schema=RegistrarEnvioInput)
    async def registrar_envio(pedido: str, paqueteria: str, guia: str, confirmado: bool = False) -> str:
        """Marca un pedido como enviado por paquetería. Escribe solo si confirmado es true, después de que el empleado respondió Sí."""
        if not confirmado:
            return _FALTA_CONFIRMACION
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
        return await ejecutar_accion_directa(db, "registrar_envio", args, usuario)

    @tool(args_schema=MarcarEntregadoInput)
    async def marcar_entregado(pedido: str, confirmado: bool = False) -> str:
        """Marca un pedido como entregado. Escribe solo si confirmado es true, después de que el empleado respondió Sí."""
        if not confirmado:
            return _FALTA_CONFIRMACION
        pedido_obj, error = _resolver_pedido(db, pedido)
        if error:
            return error
        if pedido_obj.estado == "entregado":
            return f"El pedido {pedido_obj.id} ya está entregado."
        if pedido_obj.estado == "cancelado":
            return f"El pedido {pedido_obj.id} está cancelado."

        args = {"pedido_id": pedido_obj.id}
        return await ejecutar_accion_directa(db, "marcar_entregado", args, usuario)

    @tool(args_schema=ActualizarStockMinimoInput)
    async def actualizar_stock_minimo(producto: str, stock_minimo: int, confirmado: bool = False) -> str:
        """Cambia el mínimo de alerta de un producto. Solo administración/almacén; escribe solo si confirmado es true, después de que el empleado respondió Sí."""
        if not confirmado:
            return _FALTA_CONFIRMACION
        if not puede_usar_tool(usuario.rol, "actualizar_stock_minimo"):
            return "Tu perfil no tiene permiso para cambiar mínimos de stock."
        producto_obj, error = _resolver_producto(db, producto)
        if error:
            return error
        if producto_obj.stock_minimo == stock_minimo:
            return f"{producto_obj.nombre} ya tiene un mínimo de {stock_minimo}."

        args = {"producto_id": producto_obj.id, "stock_minimo": stock_minimo}
        return await ejecutar_accion_directa(db, "actualizar_stock_minimo", args, usuario)

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
