import pytest

from app.agente.agente import (
    _extraer_cambio_minimo,
    _respuesta_directa_herramientas,
    _solicita_conteo_productos_activos,
    _system_prompt,
    run_agent,
)
from app.agente.tools.ejecutores import ejecutar_actualizar_stock_minimo
from app.agente.tools.escritura import make_escritura_tools
from app.agente.tools.negocio import _listar_stock_bajo, make_negocio_tools
from app.db.modelos import Usuario
from app.db.negocio import Producto
from app.servicios.auth import get_password_hash
from app.servicios.confirmacion import (
    confirmar_pendiente,
    obtener_pendiente,
    crear_pendiente,
)
from app.servicios.roles import Rol, filtrar_tools


def _usuario(db, rol, nombre="Usuario"):
    user = Usuario(
        nombre=nombre,
        username=f"test_{rol}",
        password_hash=get_password_hash("secret"),
        activo=True,
        rol=rol,
        es_admin=rol == Rol.ADMINISTRADOR.value,
    )
    db.add(user)
    db.commit()
    return user


def test_tool_cuenta_productos_activos_y_excluye_inactivos(db, usuario):
    db.add_all(
        [
            Producto(nombre="Activo 1", tipo="componente", activo=True),
            Producto(nombre="Activo 2", tipo="terminado", activo=True),
            Producto(nombre="Archivado", tipo="componente", activo=False),
        ]
    )
    db.commit()
    tool = next(t for t in make_negocio_tools(usuario, db) if t.name == "contar_productos_activos")

    respuesta = tool.invoke({})

    assert respuesta == "Hay 2 productos activos."


def test_tool_de_minimo_crea_pendiente_y_aplica_solo_al_confirmar(db, usuario):
    producto = Producto(
        nombre="Destornillador allen",
        tipo="componente",
        unidad_medida="pieza",
        stock_minimo=102526,
        activo=True,
    )
    db.add(producto)
    db.commit()
    tool = next(t for t in make_escritura_tools(usuario, db) if t.name == "actualizar_stock_minimo")

    resumen = tool.invoke({"producto": "destornilladores allen", "stock_minimo": 40})
    pendiente = obtener_pendiente(db, usuario.id)

    assert "102526" in resumen
    assert "40 piezas" in resumen
    assert "¿Confirmas?" in resumen
    assert pendiente is not None
    assert pendiente.tool == "actualizar_stock_minimo"
    db.refresh(producto)
    assert producto.stock_minimo == 102526

    resultado = await_confirmar(db, pendiente, usuario)
    db.refresh(producto)
    assert resultado == "Listo. El mínimo de Destornillador allen ahora es 40 piezas."
    assert producto.stock_minimo == 40


def await_confirmar(db, pendiente, usuario):
    import asyncio

    return asyncio.run(confirmar_pendiente(db, pendiente, usuario))


@pytest.mark.parametrize(
    "rol,permitido",
    [
        (Rol.ADMINISTRADOR.value, True),
        (Rol.ALMACEN.value, True),
        (Rol.VENDEDOR.value, False),
        (Rol.ENSAMBLADOR.value, False),
        (Rol.SOLO_LECTURA.value, False),
    ],
)
def test_actualizar_minimo_filtrado_y_protegido_por_rol(db, rol, permitido):
    user = _usuario(db, rol, f"Usuario {rol}")
    tools = make_escritura_tools(user, db)
    filtradas = filtrar_tools(rol, tools)
    assert ("actualizar_stock_minimo" in {t.name for t in filtradas}) is permitido

    if not permitido:
        pendiente = crear_pendiente(
            db,
            user.id,
            "actualizar_stock_minimo",
            {"producto_id": 17, "stock_minimo": 40},
            "cambio",
        )
        with pytest.raises(PermissionError):
            await_confirmar(db, pendiente, user)


def test_prompt_pide_respuestas_humanas_y_uso_de_herramientas():
    prompt = _system_prompt()
    assert "No uses tablas" in prompt
    assert "contar_productos_activos" in prompt
    assert "actualizar_stock_minimo" in prompt


def test_reporte_de_bajo_stock_es_corto_y_sin_tablas(db):
    producto = Producto(
        nombre="Destornillador allen",
        tipo="componente",
        unidad_medida="pieza",
        stock_minimo=40,
        activo=True,
    )
    db.add(producto)
    db.commit()

    reporte = _listar_stock_bajo(db)

    assert "Destornillador allen: 0 piezas, mínimo 40." in reporte
    assert "|" not in reporte
    assert "###" not in reporte
    assert "¿Qué hacer ahora?" not in reporte


def test_resultado_de_lectura_se_entrega_sin_tablas_ni_recomendaciones():
    resultado = _respuesta_directa_herramientas(
        [("contar_productos_activos", "{}", "Hay 12 productos activos.")]
    )
    assert resultado == "Hay 12 productos activos."
    assert "|" not in resultado
    assert "Qué hacer" not in resultado
    assert _respuesta_directa_herramientas(
        [("contar_productos_activos", "{}", "Hay 12."), ("crear_pedido", "{}", "pendiente")]
    ) is None


@pytest.mark.anyio
async def test_pregunta_directa_de_conteo_usa_herramienta_sin_pedir_al_llm():
    class FakeCountTool:
        name = "contar_productos_activos"

        async def ainvoke(self, args):
            assert args == {}
            return "Hay 12 productos activos."

    reply, used = await run_agent(
        "¿Cuántos productos activos tenemos?",
        [FakeCountTool()],
        usuario=None,
    )
    assert reply == "Hay 12 productos activos."
    assert used == [("contar_productos_activos", "{}", "Hay 12 productos activos.")]
    assert _solicita_conteo_productos_activos(
        "¿Cuántos productos activos tenemos y cuáles están agotados?"
    ) is False


@pytest.mark.anyio
async def test_peticion_clara_de_minimo_usa_tool_y_pide_confirmacion():
    class FakeUpdateTool:
        name = "actualizar_stock_minimo"
        received = None

        async def ainvoke(self, args):
            self.received = args
            return "Voy a cambiar el mínimo. ¿Confirmas?"

    tool = FakeUpdateTool()
    reply, used = await run_agent(
        "Puedes cambiar que el mínimo de destornilladores allen sean de 40",
        [tool],
        usuario=None,
    )
    assert _extraer_cambio_minimo(
        "Puedes cambiar que el mínimo de destornilladores allen sean de 40"
    ) == {"producto": "destornilladores allen", "stock_minimo": 40}
    assert tool.received == {"producto": "destornilladores allen", "stock_minimo": 40}
    assert reply == "Voy a cambiar el mínimo. ¿Confirmas?"
    assert used[0][0] == "actualizar_stock_minimo"


def test_pregunta_como_hacer_cambio_no_se_ejecuta_directamente():
    assert _extraer_cambio_minimo(
        "¿Cómo puedo cambiar el mínimo del destornillador allen a 40?"
    ) is None
