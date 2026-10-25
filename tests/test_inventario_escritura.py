import pytest

from app.agente.tools.ejecutores import ejecutar_marcar_entregado  # registra ejecutor
from app.db.negocio import Cliente, MovimientoInventario, Pedido, PedidoItem, Producto
from app.db.modelos import Usuario
from app.servicios.confirmacion import crear_pendiente, confirmar_pendiente
from app.servicios.inventario import stock_fisico
from app.servicios.roles import Rol


def _producto_con_stock(db, cantidad=5, tipo="componente", minimo=2):
    producto = Producto(
        nombre="Producto de prueba",
        tipo=tipo,
        unidad_medida="pieza",
        stock_minimo=minimo,
        activo=True,
    )
    db.add(producto)
    db.flush()
    db.add(
        MovimientoInventario(
            producto_id=producto.id,
            cantidad=cantidad,
            tipo_movimiento="entrada",
            referencia="Existencia inicial de prueba",
        )
    )
    db.commit()
    return producto


def _login(client):
    response = client.post("/api/login", json={"username": "testuser", "password": "secret"})
    assert response.status_code == 200


def _login_almacen(client, db, usuario):
    usuario.rol = Rol.ALMACEN.value
    usuario.es_admin = False
    db.commit()
    _login(client)


def test_salida_mayor_al_stock_fisico_se_rechaza_sin_movimiento(client, db, usuario):
    producto = _producto_con_stock(db, cantidad=2)
    _login_almacen(client, db, usuario)
    antes = db.query(MovimientoInventario).count()

    response = client.post(
        "/api/inventario/movimientos",
        json={
            "producto_id": producto.id,
            "tipo_movimiento": "merma",
            "cantidad": 3,
            "idempotency_key": "merma-excesiva-1",
        },
    )

    assert response.status_code == 409
    assert "Existencia insuficiente" in response.json()["detail"]
    assert db.query(MovimientoInventario).count() == antes
    assert stock_fisico(db, producto.id) == 2


@pytest.mark.parametrize("cantidad", [0, -1, 1.5, True])
def test_movimiento_rechaza_cantidad_no_entera_positiva(client, db, usuario, cantidad):
    producto = _producto_con_stock(db)
    _login_almacen(client, db, usuario)
    response = client.post(
        "/api/inventario/movimientos",
        json={
            "producto_id": producto.id,
            "tipo_movimiento": "merma",
            "cantidad": cantidad,
            "idempotency_key": f"cantidad-invalida-{cantidad}",
        },
    )
    assert response.status_code == 422
    assert db.query(MovimientoInventario).filter_by(producto_id=producto.id).count() == 1


def test_salida_puede_usar_reservas_si_hay_stock_fisico_y_avisar(client, db, usuario):
    cliente = Cliente(nombre="Cliente con pedido")
    producto = _producto_con_stock(db, cantidad=12, tipo="terminado", minimo=5)
    db.add(cliente)
    db.flush()
    pedido = Pedido(cliente_id=cliente.id, estado="pendiente")
    db.add(pedido)
    db.flush()
    db.add(PedidoItem(pedido_id=pedido.id, producto_id=producto.id, cantidad=10))
    db.commit()
    _login_almacen(client, db, usuario)

    response = client.post(
        "/api/inventario/movimientos",
        json={
            "producto_id": producto.id,
            "tipo_movimiento": "venta_mostrador",
            "cantidad": 4,
            "idempotency_key": "venta-mostrador-comprometido",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["stock_actual"] == 8
    assert data["advertencias"]
    assert "2 piezas" in data["advertencias"][0]
    assert db.query(MovimientoInventario).filter_by(tipo_movimiento="venta_mostrador").count() == 1


def test_movimiento_idempotente_registra_ledger_una_sola_vez(client, db, usuario):
    producto = _producto_con_stock(db)
    _login_almacen(client, db, usuario)
    payload = {
        "producto_id": producto.id,
        "tipo_movimiento": "merma",
        "cantidad": 1,
        "idempotency_key": "merma-idempotente-1",
    }

    primera = client.post("/api/inventario/movimientos", json=payload)
    segunda = client.post("/api/inventario/movimientos", json=payload)

    assert primera.status_code == 201
    assert segunda.status_code == 201
    assert segunda.json()["duplicado"] is True
    assert segunda.json()["movimiento"]["id"] == primera.json()["movimiento"]["id"]
    rows = db.query(MovimientoInventario).filter_by(idempotency_key="merma-idempotente-1").all()
    assert len(rows) == 1
    assert rows[0].usuario_id == usuario.id
    assert rows[0].cantidad == -1


@pytest.mark.parametrize(
    "extra",
    [
        {"tipo_movimiento": "venta"},
        {"tipo_movimiento": "venta_mostrador", "pedido_id": 1},
        {"tipo_movimiento": "merma", "usuario_id": 999},
    ],
)
def test_movimiento_manual_no_acepta_ventas_de_pedido_ni_actor_del_cliente(
    client, db, usuario, extra
):
    producto = _producto_con_stock(db)
    _login_almacen(client, db, usuario)
    payload = {
        "producto_id": producto.id,
        "tipo_movimiento": "merma",
        "cantidad": 1,
        "idempotency_key": "payload-no-permitido-1",
        **extra,
    }

    response = client.post("/api/inventario/movimientos", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("rol,esperado", [(Rol.ADMINISTRADOR.value, 403), (Rol.ALMACEN.value, 201), (Rol.VENDEDOR.value, 403), (Rol.ENSAMBLADOR.value, 403), (Rol.SOLO_LECTURA.value, 403)])
def test_permisos_de_movimientos_se_validan_en_api(client, db, rol, esperado):
    from app.servicios.auth import get_password_hash

    usuario = Usuario(
        nombre=f"Usuario {rol}",
        username=f"mov_{rol}",
        password_hash=get_password_hash("secreto"),
        activo=True,
        rol=rol,
    )
    producto = _producto_con_stock(db)
    db.add(usuario)
    db.commit()
    login = client.post("/api/login", json={"username": usuario.username, "password": "secreto"})
    assert login.status_code == 200

    response = client.post(
        "/api/inventario/movimientos",
        json={
            "producto_id": producto.id,
            "tipo_movimiento": "compra",
            "cantidad": 1,
            "idempotency_key": f"permiso-{rol}",
        },
    )
    assert response.status_code == esperado


def test_producto_se_guarda_sin_precios(client, db, usuario):
    _login_almacen(client, db, usuario)
    response = client.post(
        "/api/inventario/productos",
        json={"nombre": "Producto sin precio", "tipo": "componente"},
    )
    assert response.status_code == 201
    assert "precio_compra" not in response.json()["producto"]
    assert "precio_venta" not in response.json()["producto"]


def test_administrador_no_accede_a_productos(client, db, usuario):
    producto = _producto_con_stock(db)
    _login(client)
    assert client.get("/api/inventario/productos").status_code == 403
    assert client.patch(
        f"/api/inventario/productos/{producto.id}",
        json={"nombre": "Producto corregido"},
    ).status_code == 403
    db.refresh(producto)
    assert producto.nombre == "Producto de prueba"


def test_almacen_puede_editar_datos_no_monetarios(client, db):
    from app.servicios.auth import get_password_hash

    producto = _producto_con_stock(db)
    user = Usuario(
        nombre="Almacén editor",
        username="warehouse-edit-test",
        password_hash=get_password_hash("secreto"),
        activo=True,
        rol=Rol.ALMACEN.value,
    )
    db.add(user)
    db.commit()
    client.post(
        "/api/login",
        json={"username": user.username, "password": "secreto"},
    )

    response = client.patch(
        f"/api/inventario/productos/{producto.id}",
        json={"stock_minimo": 3},
    )
    assert response.status_code == 200
    assert response.json()["producto"]["stock_minimo"] == 3
    assert "precio_compra" not in response.json()["producto"]


def test_producto_no_acepta_codigo_duplicado(client, db, usuario):
    _login_almacen(client, db, usuario)
    first = client.post(
        "/api/inventario/productos",
        json={"nombre": "Código A", "tipo": "componente", "codigo": "dup-001"},
    )
    second = client.post(
        "/api/inventario/productos",
        json={"nombre": "Código B", "tipo": "componente", "codigo": "DUP-001"},
    )
    assert first.status_code == 201
    assert second.status_code == 409


def test_almacen_no_puede_enviar_campos_de_precio(client, db):
    from app.servicios.auth import get_password_hash

    user = Usuario(
        nombre="Almacén",
        username="warehouse-price-test",
        password_hash=get_password_hash("secreto"),
        activo=True,
        rol=Rol.ALMACEN.value,
    )
    db.add(user)
    db.commit()
    _login_response = client.post(
        "/api/login",
        json={"username": user.username, "password": "secreto"},
    )
    assert _login_response.status_code == 200

    response = client.post(
        "/api/inventario/productos",
        json={
            "nombre": "Producto de almacén",
            "tipo": "componente",
            "precio_compra": "10.00",
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "rol,esperado",
    [
        (Rol.ADMINISTRADOR.value, 403),
        (Rol.ALMACEN.value, 201),
        (Rol.VENDEDOR.value, 403),
        (Rol.ENSAMBLADOR.value, 403),
        (Rol.SOLO_LECTURA.value, 403),
    ],
)
def test_permisos_para_crear_producto_se_validan_en_api(client, db, rol, esperado):
    from app.servicios.auth import get_password_hash

    user = Usuario(
        nombre=f"Usuario {rol}",
        username=f"crear_producto_{rol}",
        password_hash=get_password_hash("secreto"),
        activo=True,
        rol=rol,
    )
    db.add(user)
    db.commit()
    login = client.post(
        "/api/login",
        json={"username": user.username, "password": "secreto"},
    )
    assert login.status_code == 200

    response = client.post(
        "/api/inventario/productos",
        json={"nombre": "Producto con rol", "tipo": "componente"},
    )
    assert response.status_code == esperado


def test_desactivar_conserva_producto_y_movimientos(client, db, usuario):
    producto = _producto_con_stock(db)
    _login(client)
    count_before = db.query(MovimientoInventario).count()

    response = client.post(f"/api/inventario/productos/{producto.id}/desactivar")

    assert response.status_code == 200
    db.refresh(producto)
    assert producto.activo is False
    assert db.get(Producto, producto.id) is not None
    assert db.query(MovimientoInventario).count() == count_before
    assert client.delete(f"/api/inventario/productos/{producto.id}").status_code == 405


def test_almacen_no_puede_desactivar_producto(client, db):
    from app.servicios.auth import get_password_hash

    producto = _producto_con_stock(db)
    user = Usuario(
        nombre="Almacén",
        username="warehouse-deactivate-test",
        password_hash=get_password_hash("secreto"),
        activo=True,
        rol=Rol.ALMACEN.value,
    )
    db.add(user)
    db.commit()
    client.post(
        "/api/login",
        json={"username": user.username, "password": "secreto"},
    )

    response = client.post(f"/api/inventario/productos/{producto.id}/desactivar")
    assert response.status_code == 403
    db.refresh(producto)
    assert producto.activo is True


def test_vendedor_no_puede_consultar_historial(client, db):
    from app.servicios.auth import get_password_hash

    user = Usuario(
        nombre="Vendedor",
        username="seller-history-test",
        password_hash=get_password_hash("secreto"),
        activo=True,
        rol=Rol.VENDEDOR.value,
    )
    db.add(user)
    db.commit()
    client.post(
        "/api/login",
        json={"username": user.username, "password": "secreto"},
    )
    assert client.get("/api/inventario/movimientos").status_code == 403


def test_historial_filtra_por_producto_tipo_usuario_y_rango(client, db, usuario):
    producto = _producto_con_stock(db)
    _login_almacen(client, db, usuario)
    movement_response = client.post(
        "/api/inventario/movimientos",
        json={
            "producto_id": producto.id,
            "tipo_movimiento": "compra",
            "cantidad": 2,
            "idempotency_key": "history-purchase-1",
        },
    )
    assert movement_response.status_code == 201
    movement = movement_response.json()["movimiento"]

    response = client.get(
        "/api/inventario/movimientos",
        params={
            "producto_id": producto.id,
            "tipo": "compra",
            "usuario_id": usuario.id,
            "desde": "2020-01-01T00:00:00+00:00",
            "hasta": "2099-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 200
    records = response.json()["movimientos"]
    assert len(records) == 1
    assert records[0]["id"] == movement["id"]
    assert records[0]["responsable"] == usuario.nombre


@pytest.mark.anyio
async def test_venta_de_pedido_solo_se_registra_al_entregar_y_no_se_duplica(db, usuario):
    usuario.rol = Rol.ALMACEN.value
    usuario.es_admin = False
    db.commit()
    cliente = Cliente(nombre="Venta ligada a pedido")
    producto = _producto_con_stock(db, cantidad=10)
    db.add(cliente)
    db.flush()
    pedido = Pedido(cliente_id=cliente.id, estado="pendiente", tipo_entrega="directa")
    db.add(pedido)
    db.flush()
    item = PedidoItem(pedido_id=pedido.id, producto_id=producto.id, cantidad=3)
    db.add(item)
    db.commit()

    for intento in (1, 2):
        pendiente = crear_pendiente(
            db,
            usuario.id,
            "marcar_entregado",
            {"pedido_id": pedido.id},
            "Confirmar entrega",
        )
        await confirmar_pendiente(db, pendiente, usuario)

    ventas = (
        db.query(MovimientoInventario)
        .filter(
            MovimientoInventario.producto_id == producto.id,
            MovimientoInventario.tipo_movimiento == "venta",
            MovimientoInventario.pedido_id == pedido.id,
        )
        .all()
    )
    assert len(ventas) == 1
    assert ventas[0].cantidad == -3
    assert ventas[0].usuario_id == usuario.id
    assert stock_fisico(db, producto.id) == 7


@pytest.mark.parametrize(
    "tool,args",
    [
        ("registrar_envio", {"paqueteria": "Mensajería Demo", "guia": "GUIA-1"}),
        ("marcar_entregado", {}),
    ],
)
@pytest.mark.anyio
async def test_envio_y_entrega_rechazan_salida_mayor_a_stock_y_revierte_todo(
    db, usuario, tool, args
):
    usuario.rol = Rol.ALMACEN.value
    usuario.es_admin = False
    db.commit()
    producto = _producto_con_stock(db, cantidad=2)
    cliente = Cliente(nombre="Pedido sin existencia suficiente")
    db.add(cliente)
    db.flush()
    pedido = Pedido(cliente_id=cliente.id, estado="pendiente", tipo_entrega="directa")
    db.add(pedido)
    db.flush()
    item = PedidoItem(pedido_id=pedido.id, producto_id=producto.id, cantidad=3)
    db.add(item)
    db.commit()

    action_args = {"pedido_id": pedido.id, **args}
    pendiente = crear_pendiente(db, usuario.id, tool, action_args, "Procesar pedido")
    with pytest.raises(ValueError, match="Existencia insuficiente"):
        await confirmar_pendiente(db, pendiente, usuario)

    db.refresh(pedido)
    db.refresh(item)
    assert pedido.estado == "pendiente"
    assert item.inventario_descontado is False
    assert db.query(MovimientoInventario).filter_by(pedido_id=pedido.id).count() == 0
    assert stock_fisico(db, producto.id) == 2
