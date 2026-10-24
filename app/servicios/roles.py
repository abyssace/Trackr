from enum import Enum as PyEnum
from typing import Iterable


class Rol(str, PyEnum):
    SOLO_LECTURA = "solo_lectura"
    VENDEDOR = "vendedor"
    ALMACEN = "almacen"
    ENSAMBLADOR = "ensamblador"
    ADMINISTRADOR = "administrador"


_HERRAMIENTAS_LECTURA = {
    "crear_recordatorio",
    "listar_recordatorios",
    "consultar_existencia",
    "listar_stock_bajo",
    "consultar_estado_pedido",
    "contar_productos_activos",
}

_HERRAMIENTAS_ESCRITURA = {
    "crear_pedido",
    "editar_pedido",
    "cancelar_pedido",
    "registrar_entrada_mercancia",
    "registrar_terminado",
    "registrar_envio",
    "marcar_entregado",
    "actualizar_stock_minimo",
}

TODAS_LAS_HERRAMIENTAS = _HERRAMIENTAS_LECTURA | _HERRAMIENTAS_ESCRITURA

PERMISOS_POR_ROL: dict[str, set[str]] = {
    Rol.SOLO_LECTURA.value: set(_HERRAMIENTAS_LECTURA),
    Rol.VENDEDOR.value: set(_HERRAMIENTAS_LECTURA)
    | {"crear_pedido", "editar_pedido", "cancelar_pedido", "marcar_entregado"},
    Rol.ALMACEN.value: set(_HERRAMIENTAS_LECTURA)
    | {
        "registrar_entrada_mercancia",
        "registrar_envio",
        "marcar_entregado",
        "actualizar_stock_minimo",
    },
    Rol.ENSAMBLADOR.value: set(_HERRAMIENTAS_LECTURA) | {"registrar_terminado"},
    Rol.ADMINISTRADOR.value: set(TODAS_LAS_HERRAMIENTAS),
}


def herramientas_permitidas(rol: str | None) -> set[str]:
    return set(PERMISOS_POR_ROL.get(rol, set()))


def puede_usar_tool(rol: str | None, tool_name: str) -> bool:
    return tool_name in herramientas_permitidas(rol)


def filtrar_tools(rol: str | None, tools: Iterable) -> list:
    permitidas = herramientas_permitidas(rol)
    return [t for t in tools if getattr(t, "name", None) in permitidas]


def roles_validos() -> list[str]:
    return [r.value for r in Rol]


def puede_editar_productos(rol: str | None) -> bool:
    return rol in {Rol.ADMINISTRADOR.value, Rol.ALMACEN.value}


def puede_registrar_movimientos(rol: str | None) -> bool:
    return rol in {Rol.ADMINISTRADOR.value, Rol.ALMACEN.value}


def puede_desactivar_productos(rol: str | None) -> bool:
    return rol == Rol.ADMINISTRADOR.value


def puede_ver_precio_compra(rol: str | None) -> bool:
    return rol == Rol.ADMINISTRADOR.value


def puede_ver_precio_venta(rol: str | None) -> bool:
    return rol in {Rol.ADMINISTRADOR.value, Rol.VENDEDOR.value}


def puede_ver_historial_inventario(rol: str | None) -> bool:
    return rol in {Rol.ADMINISTRADOR.value, Rol.ALMACEN.value}
