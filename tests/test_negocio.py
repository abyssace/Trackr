import pytest

from app.db.negocio import (
    Cliente,
    Empleado,
    Medidor,
    MovimientoInventario,
    Pedido,
    PedidoItem,
    Producto,
    Tamano,
    TipoMedidor,
    TipoUTD,
)
from app.agente.tools.negocio import (
    _consultar_existencia,
    _listar_stock_bajo,
    _consultar_estado_pedido,
)


def _seed_minimal(db):
    cliente = Cliente(nombre="Juan Pérez")
    db.add(cliente)

    empleado = Empleado(nombre="Pedro Sánchez", rol="Vendedor")
    db.add(empleado)

    tipo = TipoMedidor(nombre="Doméstico")
    db.add(tipo)
    db.flush()

    medidor = Medidor(nombre_modelo="A-100", tipo_medidor_id=tipo.id)
    db.add(medidor)

    tamano = Tamano(pulgadas=1)
    db.add(tamano)

    utd = TipoUTD(nombre="Clásica")
    db.add(utd)
    db.flush()

    componente = Producto(
        nombre="Cajas medianas",
        tipo="componente",
        stock_minimo=10,
        alias="cajas",
    )
    db.add(componente)

    terminado = Producto(
        nombre="Medidor A-100 1 pulgada UTD Clásica",
        tipo="terminado",
        stock_minimo=5,
        medidor_id=medidor.id,
        tamano_id=tamano.id,
        tipo_utd_id=utd.id,
        alias="medidor 1 pulgada",
    )
    db.add(terminado)
    db.flush()

    db.add(MovimientoInventario(producto_id=componente.id, cantidad=8, tipo_movimiento="entrada"))
    db.add(MovimientoInventario(producto_id=terminado.id, cantidad=12, tipo_movimiento="entrada"))

    pedido = Pedido(
        cliente_id=cliente.id,
        empleado_id=empleado.id,
        estado="pendiente",
        tipo_entrega="paqueteria",
        paqueteria="FedEx",
        guia="12345",
    )
    db.add(pedido)
    db.flush()

    db.add(PedidoItem(pedido_id=pedido.id, producto_id=terminado.id, cantidad=10))
    db.commit()

    return {
        "cliente": cliente,
        "componente": componente,
        "terminado": terminado,
        "pedido": pedido,
    }


@pytest.fixture
def negocio(db):
    return _seed_minimal(db)


def test_consultar_existencia_componente(db, negocio):
    resp = _consultar_existencia(db, "cajas")
    assert "Cajas medianas" in resp
    assert "físico: 8" in resp
    assert "componente" in resp


def test_consultar_existencia_terminado(db, negocio):
    resp = _consultar_existencia(db, "medidor 1 pulgada")
    assert "Medidor A-100" in resp
    assert "físico: 12" in resp
    assert "reservado: 10" in resp
    assert "disponible: 2" in resp


def test_consultar_existencia_multiples_coincidencias(db, negocio):
    db.add(Producto(nombre="Cajas grandes", tipo="componente", alias="cajas"))
    db.commit()

    resp = _consultar_existencia(db, "cajas")
    assert "Cajas medianas" in resp
    assert "Cajas grandes" in resp


def test_consultar_existencia_sin_coincidencias(db, negocio):
    resp = _consultar_existencia(db, "tornillos inexistentes")
    assert "No encontré" in resp


def test_listar_stock_bajo_componente(db, negocio):
    resp = _listar_stock_bajo(db)
    assert "Componentes bajo mínimo" in resp
    assert "Cajas medianas" in resp


def test_listar_stock_bajo_terminado(db, negocio):
    # físico 12 - reservado 10 = 2, mínimo 5 => debe aparecer
    resp = _listar_stock_bajo(db)
    assert "Productos terminados" in resp
    assert "Medidor A-100" in resp
    assert "Advertencia ámbar" in resp


def test_consultar_estado_pedido_por_numero(db, negocio):
    resp = _consultar_estado_pedido(db, str(negocio["pedido"].id))
    assert f"Pedido {negocio['pedido'].id}" in resp
    assert "pendiente" in resp
    assert "FedEx" in resp
    assert "12345" in resp


def test_consultar_estado_pedido_cliente_un_pedido(db, negocio):
    resp = _consultar_estado_pedido(db, "Juan Pérez")
    assert f"Pedido {negocio['pedido'].id}" in resp
    assert "pendiente" in resp


def test_consultar_estado_pedido_cliente_multiples(db, negocio):
    # Agregar un segundo pedido para el mismo cliente
    pedido2 = Pedido(
        cliente_id=negocio["cliente"].id,
        empleado_id=negocio["pedido"].empleado_id,
        estado="enviado",
        tipo_entrega="directa",
    )
    db.add(pedido2)
    db.commit()

    resp = _consultar_estado_pedido(db, "Juan Pérez")
    assert "2 pedidos" in resp
    assert "Mostrando los 5 más recientes" in resp
    assert "enviado" in resp
