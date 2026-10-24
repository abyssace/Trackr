import pytest

from app.db.negocio import (
    Cliente,
    Empleado,
    Medidor,
    MovimientoInventario,
    Pedido,
    PedidoItem,
    Producto,
    Receta,
    Tamano,
    TipoMedidor,
    TipoUTD,
)
from app.agente.tools.ejecutores import (
    ejecutar_crear_pedido,
    ejecutar_editar_pedido,
    ejecutar_cancelar_pedido,
    ejecutar_marcar_entregado,
    ejecutar_registrar_entrada_mercancia,
    ejecutar_registrar_terminado,
)
from app.servicios.inventario import stock_reservado


@pytest.fixture
def base_negocio(db):
    cliente = Cliente(nombre="Juan Pérez")
    empleado = Empleado(nombre="Vendedor", rol="Vendedor")
    db.add_all([cliente, empleado])

    tipo = TipoMedidor(nombre="Doméstico")
    db.add(tipo)
    db.flush()
    medidor = Medidor(nombre_modelo="A-100", tipo_medidor_id=tipo.id)
    tamano = Tamano(pulgadas=1)
    utd = TipoUTD(nombre="Clásica")
    db.add_all([medidor, tamano, utd])
    db.flush()

    componente = Producto(nombre="Carcasa", tipo="componente", unidad_medida="pieza")
    terminado = Producto(
        nombre="Medidor A-100 1 pulgada",
        tipo="terminado",
        unidad_medida="pieza",
        medidor_id=medidor.id,
        tamano_id=tamano.id,
        tipo_utd_id=utd.id,
    )
    db.add_all([componente, terminado])
    db.flush()

    db.add(Receta(producto_terminado_id=terminado.id, producto_componente_id=componente.id, cantidad_requerida=1))
    db.add(MovimientoInventario(producto_id=componente.id, cantidad=100, tipo_movimiento="entrada"))
    db.add(MovimientoInventario(producto_id=terminado.id, cantidad=10, tipo_movimiento="entrada"))
    db.commit()

    return {"cliente": cliente, "empleado": empleado, "componente": componente, "terminado": terminado}


@pytest.mark.anyio
async def test_crear_pedido_permite_stock_negativo(db, base_negocio):
    args = {
        "cliente_id": base_negocio["cliente"].id,
        "cliente_nombre": base_negocio["cliente"].nombre,
        "items": [{"producto_id": base_negocio["terminado"].id, "cantidad": 100}],
        "empleado_id": base_negocio["empleado"].id,
    }
    resultado = await ejecutar_crear_pedido(db, args)
    assert "Pedido" in resultado
    assert "quedará negativo" in resultado

    pedido = db.query(Pedido).first()
    assert pedido is not None
    assert pedido.estado == "pendiente"


@pytest.mark.anyio
async def test_marcar_entregado_descuenta_inventario(db, usuario, base_negocio):
    pedido = Pedido(cliente_id=base_negocio["cliente"].id, estado="pendiente", tipo_entrega="directa")
    db.add(pedido)
    db.flush()
    db.add(PedidoItem(pedido_id=pedido.id, producto_id=base_negocio["terminado"].id, cantidad=3))
    db.commit()

    resultado = await ejecutar_marcar_entregado(
        db,
        {
            "pedido_id": pedido.id,
            "_responsable_usuario_id": usuario.id,
            "_idempotency_base": "test-entrega",
        },
    )
    db.commit()
    assert "entregado" in resultado

    item = db.get(PedidoItem, 1)
    assert item.inventario_descontado is True

    mov = db.query(MovimientoInventario).filter(MovimientoInventario.tipo_movimiento == "venta").first()
    assert mov is not None
    assert mov.cantidad == -3


@pytest.mark.anyio
async def test_cancelar_pedido_revierte_inventario(db, usuario, base_negocio):
    pedido = Pedido(cliente_id=base_negocio["cliente"].id, estado="enviado", tipo_entrega="directa")
    db.add(pedido)
    db.flush()
    item = PedidoItem(pedido_id=pedido.id, producto_id=base_negocio["terminado"].id, cantidad=2, inventario_descontado=True)
    db.add(item)
    db.add(MovimientoInventario(producto_id=base_negocio["terminado"].id, cantidad=-2, tipo_movimiento="venta", pedido_id=pedido.id))
    db.commit()

    resultado = await ejecutar_cancelar_pedido(
        db,
        {
            "pedido_id": pedido.id,
            "_responsable_usuario_id": usuario.id,
            "_idempotency_base": "test-cancelacion",
        },
    )
    db.commit()
    assert "cancelado" in resultado
    assert pedido.estado == "cancelado"

    ajuste = (
        db.query(MovimientoInventario)
        .filter(MovimientoInventario.tipo_movimiento == "ajuste")
        .first()
    )
    assert ajuste is not None
    assert ajuste.cantidad == 2


@pytest.mark.anyio
async def test_editar_pedido_archiva_linea_anterior_sin_borrarla(db, base_negocio):
    pedido = Pedido(cliente_id=base_negocio["cliente"].id, estado="pendiente")
    db.add(pedido)
    db.flush()
    anterior = PedidoItem(
        pedido_id=pedido.id,
        producto_id=base_negocio["terminado"].id,
        cantidad=3,
    )
    db.add(anterior)
    db.commit()

    resultado = await ejecutar_editar_pedido(
        db,
        {
            "pedido_id": pedido.id,
            "items": [{"producto_id": base_negocio["terminado"].id, "cantidad": 5}],
        },
    )
    db.commit()

    db.refresh(anterior)
    assert "actualizado" in resultado
    assert anterior.activo is False
    assert db.query(PedidoItem).filter_by(pedido_id=pedido.id).count() == 2
    assert stock_reservado(db, base_negocio["terminado"].id) == 5


@pytest.mark.anyio
async def test_registrar_entrada_aumenta_stock(db, usuario, base_negocio):
    args = {
        "producto_id": base_negocio["componente"].id,
        "cantidad": 50,
        "empleado_recibe_id": base_negocio["empleado"].id,
        "_responsable_usuario_id": usuario.id,
        "_idempotency_base": "test-entrada",
    }
    resultado = await ejecutar_registrar_entrada_mercancia(db, args)
    db.commit()
    assert "Entrada registrada" in resultado

    total = sum(m.cantidad for m in db.query(MovimientoInventario).filter_by(producto_id=base_negocio["componente"].id))
    assert total == 150


@pytest.mark.anyio
async def test_registrar_terminado_descuenta_componentes(db, usuario, base_negocio):
    args = {
        "producto_id": base_negocio["terminado"].id,
        "cantidad": 5,
        "_responsable_usuario_id": usuario.id,
        "_idempotency_base": "test-produccion",
    }
    resultado = await ejecutar_registrar_terminado(db, args)
    db.commit()
    assert "Producción registrada" in resultado

    comp_total = sum(m.cantidad for m in db.query(MovimientoInventario).filter_by(producto_id=base_negocio["componente"].id))
    term_total = sum(m.cantidad for m in db.query(MovimientoInventario).filter_by(producto_id=base_negocio["terminado"].id))
    assert comp_total == 95
    assert term_total == 15
