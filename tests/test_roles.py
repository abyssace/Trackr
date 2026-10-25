import pytest
from unittest.mock import MagicMock

from app.servicios.roles import (
    Rol,
    PERMISOS_POR_ROL,
    TODAS_LAS_HERRAMIENTAS,
    herramientas_permitidas,
    puede_usar_tool,
    filtrar_tools,
)


def _tool(name: str):
    t = MagicMock()
    t.name = name
    return t


@pytest.mark.parametrize(
    "rol,tool,esperado",
    [
        (Rol.SOLO_LECTURA.value, "consultar_existencia", True),
        (Rol.SOLO_LECTURA.value, "crear_pedido", False),
        (Rol.VENDEDOR.value, "crear_pedido", True),
        (Rol.VENDEDOR.value, "editar_pedido", True),
        (Rol.VENDEDOR.value, "cancelar_pedido", True),
        (Rol.VENDEDOR.value, "marcar_entregado", True),
        (Rol.VENDEDOR.value, "registrar_entrada_mercancia", False),
        (Rol.ALMACEN.value, "registrar_entrada_mercancia", True),
        (Rol.ALMACEN.value, "registrar_envio", True),
        (Rol.ALMACEN.value, "crear_pedido", False),
        (Rol.ENSAMBLADOR.value, "registrar_terminado", True),
        (Rol.ENSAMBLADOR.value, "crear_pedido", False),
        (Rol.ADMINISTRADOR.value, "crear_pedido", False),
        (Rol.ADMINISTRADOR.value, "registrar_terminado", False),
        (Rol.ADMINISTRADOR.value, "consultar_existencia", False),
        ("rol_inexistente", "consultar_existencia", False),
    ],
)
def test_puede_usar_tool(rol, tool, esperado):
    assert puede_usar_tool(rol, tool) is esperado


@pytest.mark.parametrize("rol", [r.value for r in Rol])
def test_herramientas_permitidas_son_subconjunto_de_todas(rol):
    assert herramientas_permitidas(rol).issubset(TODAS_LAS_HERRAMIENTAS)


def test_solo_lectura_solo_puede_lectura():
    assert herramientas_permitidas(Rol.SOLO_LECTURA.value) == {
        "crear_recordatorio",
        "listar_recordatorios",
        "consultar_existencia",
        "listar_stock_bajo",
        "consultar_estado_pedido",
        "contar_productos_activos",
    }


def test_administrador_no_recibe_tools_de_negocio():
    assert herramientas_permitidas(Rol.ADMINISTRADOR.value) == set()


def test_filtrar_tools_mantiene_solo_permitidas():
    tools = [
        _tool("consultar_existencia"),
        _tool("crear_pedido"),
        _tool("registrar_entrada_mercancia"),
    ]
    filtradas = filtrar_tools(Rol.VENDEDOR.value, tools)
    assert [t.name for t in filtradas] == ["consultar_existencia", "crear_pedido"]


def test_filtrar_tools_ignora_sin_nombre():
    t = MagicMock()
    t.name = None
    assert filtrar_tools(Rol.ADMINISTRADOR.value, [t]) == []
