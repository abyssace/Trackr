from decimal import Decimal

import pytest

from app.db.modelos import Usuario
from app.db.negocio import (
    Categoria,
    Cliente,
    MovimientoInventario,
    Pedido,
    PedidoItem,
    Producto,
    Proveedor,
)
from app.servicios.auth import get_password_hash
from app.servicios.inventario import (
    calcular_kpis_inventario,
    evaluar_alerta_stock,
)
from app.servicios.roles import (
    Rol,
    puede_desactivar_productos,
    puede_editar_productos,
    puede_registrar_movimientos,
    puede_ver_historial_inventario,
    puede_ver_precio_compra,
    puede_ver_precio_venta,
)


def _crear_usuario(db, rol: str) -> Usuario:
    usuario = Usuario(
        nombre=f"Usuario {rol}",
        username=f"user_{rol}",
        password_hash=get_password_hash("ClaveSegura123"),
        activo=True,
        rol=rol,
        es_admin=rol == Rol.ADMINISTRADOR.value,
    )
    db.add(usuario)
    db.commit()
    return usuario


def _login(client, username: str):
    response = client.post(
        "/api/login",
        json={"username": username, "password": "ClaveSegura123"},
    )
    assert response.status_code == 200


def _catalogo(db):
    categoria = Categoria(nombre="Accesorios Eléctricos")
    proveedor = Proveedor(nombre="Suministros de Monterrey")
    db.add_all([categoria, proveedor])
    db.flush()
    producto = Producto(
        nombre="Medidor eléctrico Álamo",
        tipo="componente",
        unidad_medida="pieza",
        codigo="MX-ABC-123",
        categoria_id=categoria.id,
        proveedor_id=proveedor.id,
        stock_minimo=4,
        precio_compra=Decimal("12.30"),
        precio_venta=Decimal("19.90"),
    )
    sin_precio = Producto(
        nombre="Terminal sin precio",
        tipo="componente",
        unidad_medida="pieza",
        codigo="MX-ABC-124",
        stock_minimo=1,
        precio_compra=None,
        precio_venta=None,
    )
    db.add_all([producto, sin_precio])
    db.flush()
    db.add_all(
        [
            MovimientoInventario(
                producto_id=producto.id,
                cantidad=10,
                tipo_movimiento="entrada",
                referencia="Prueba inventario",
            ),
            MovimientoInventario(
                producto_id=sin_precio.id,
                cantidad=2,
                tipo_movimiento="entrada",
                referencia="Prueba sin precio",
            ),
        ]
    )
    db.commit()
    return producto, sin_precio


@pytest.mark.parametrize(
    "stock,minimo,esperado",
    [(5, 5, True), (4, 5, True), (6, 5, False)],
)
def test_alerta_stock_fisico_incluye_igual_y_menor(stock, minimo, esperado):
    alerta = evaluar_alerta_stock(stock, minimo)
    assert alerta["bajo_minimo"] is esperado


def test_terminado_muestra_alerta_ambar_por_comprometido():
    alerta = evaluar_alerta_stock(
        12,
        5,
        comprometido=7,
        es_terminado=True,
    )
    assert alerta["stock_actual"] == 12
    assert alerta["stock_comprometido"] == 7
    assert alerta["stock_disponible"] == 5
    assert alerta["bajo_minimo"] is False
    assert alerta["disponible_bajo_minimo"] is True


def test_kpi_calcula_valores_con_decimal_y_cuenta_precios_pendientes(db):
    producto, sin_precio = _catalogo(db)
    kpis = calcular_kpis_inventario([(producto, 10), (sin_precio, 2)])
    assert kpis["valor_costo"] == Decimal("123.00")
    assert kpis["valor_venta"] == Decimal("199.00")
    assert kpis["productos_sin_precio_compra"] == 1
    assert kpis["productos_sin_precio_venta"] == 1


@pytest.mark.parametrize(
    "rol,puede_editar,puede_movimiento,puede_desactivar,compra,venta,historial",
    [
        (Rol.ADMINISTRADOR.value, True, True, True, True, True, True),
        (Rol.ALMACEN.value, True, True, False, False, False, True),
        (Rol.VENDEDOR.value, False, False, False, False, True, False),
        (Rol.ENSAMBLADOR.value, False, False, False, False, False, False),
        (Rol.SOLO_LECTURA.value, False, False, False, False, False, False),
    ],
)
def test_permisos_inventario_por_rol(
    rol,
    puede_editar,
    puede_movimiento,
    puede_desactivar,
    compra,
    venta,
    historial,
):
    assert puede_editar_productos(rol) is puede_editar
    assert puede_registrar_movimientos(rol) is puede_movimiento
    assert puede_desactivar_productos(rol) is puede_desactivar
    assert puede_ver_precio_compra(rol) is compra
    assert puede_ver_precio_venta(rol) is venta
    assert puede_ver_historial_inventario(rol) is historial


@pytest.mark.parametrize("q", ["MEDIDOR ELECTRICO", "medidor eléctrico", "accesorios electricos"])
def test_busqueda_web_ignora_acentos_y_mayusculas(client, db, q):
    _crear_usuario(db, Rol.SOLO_LECTURA.value)
    _catalogo(db)
    _login(client, "user_solo_lectura")

    response = client.get("/api/inventario/productos", params={"q": q})
    assert response.status_code == 200
    productos = response.json()["productos"]
    assert len(productos) == 1
    assert productos[0]["nombre"] == "Medidor eléctrico Álamo"


def test_busqueda_por_codigo_de_barras(client, db):
    _crear_usuario(db, Rol.SOLO_LECTURA.value)
    _catalogo(db)
    _login(client, "user_solo_lectura")

    response = client.get(
        "/api/inventario/productos",
        params={"q": "mx-abc-123"},
    )
    assert response.status_code == 200
    assert [p["codigo"] for p in response.json()["productos"]] == ["MX-ABC-123"]


def test_busqueda_resuelve_nombre_en_plural(client, db):
    _crear_usuario(db, Rol.SOLO_LECTURA.value)
    db.add(
        Producto(
            nombre="Destornillador allen",
            tipo="componente",
            activo=True,
        )
    )
    db.commit()
    _login(client, "user_solo_lectura")

    response = client.get(
        "/api/inventario/productos",
        params={"q": "destornilladores allen"},
    )
    assert response.status_code == 200
    assert [item["nombre"] for item in response.json()["productos"]] == [
        "Destornillador allen"
    ]


@pytest.mark.parametrize(
    "rol,compra,venta",
    [
        (Rol.ALMACEN.value, False, False),
        (Rol.VENDEDOR.value, False, True),
        (Rol.ENSAMBLADOR.value, False, False),
        (Rol.SOLO_LECTURA.value, False, False),
    ],
)
def test_api_solo_entrega_campos_de_precio_permitidos(client, db, rol, compra, venta):
    _crear_usuario(db, rol)
    _catalogo(db)
    _login(client, f"user_{rol}")

    response = client.get("/api/inventario/productos")
    assert response.status_code == 200
    product = next(
        p for p in response.json()["productos"] if p["codigo"] == "MX-ABC-123"
    )
    assert ("precio_compra" in product) is compra
    assert ("precio_venta" in product) is venta


def test_kpi_api_no_filtra_costo_a_vendedor(client, db):
    _crear_usuario(db, Rol.VENDEDOR.value)
    _catalogo(db)
    _login(client, "user_vendedor")

    response = client.get("/api/inventario/resumen")
    assert response.status_code == 200
    data = response.json()
    assert data["valor_inventario_venta_mxn"] == "199.00"
    assert data["productos_sin_precio_venta"] == 1
    assert "valor_inventario_costo_mxn" not in data
    assert "productos_sin_precio_compra" not in data


def test_catalogo_activo_visible_y_precio_pendiente_marcado(client, db):
    usuario = _crear_usuario(db, Rol.SOLO_LECTURA.value)
    producto, sin_precio = _catalogo(db)
    producto.activo = False
    db.commit()
    _login(client, usuario.username)

    response = client.get("/api/inventario/productos")
    assert response.status_code == 200
    records = response.json()["productos"]
    assert all(item["activo"] for item in records)
    assert "precio_compra" not in records[0]
    assert "precio_venta" not in records[0]


def test_solo_administrador_puede_incluir_inactivos(client, db):
    _crear_usuario(db, Rol.SOLO_LECTURA.value)
    product, _ = _catalogo(db)
    product.activo = False
    db.commit()
    _login(client, "user_solo_lectura")

    response = client.get(
        "/api/inventario/productos",
        params={"incluir_inactivos": "true"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/inventario/productos",
        "/api/inventario/catalogos",
        "/api/inventario/resumen",
        "/api/inventario/movimientos",
    ],
)
def test_administrador_accede_a_modulos_de_inventario(client, db, endpoint):
    admin = _crear_usuario(db, Rol.ADMINISTRADOR.value)
    _login(client, admin.username)
    assert client.get(endpoint).status_code == 200


def test_api_devuelve_alerta_roja_fisica_y_ambar_por_comprometido(client, db):
    _crear_usuario(db, Rol.SOLO_LECTURA.value)
    cliente = Cliente(nombre="Cliente reservado")
    producto = Producto(
        nombre="Medidor terminado reservado",
        tipo="terminado",
        stock_minimo=5,
        unidad_medida="pieza",
    )
    db.add_all([cliente, producto])
    db.flush()
    pedido = Pedido(cliente_id=cliente.id, estado="pendiente")
    db.add(pedido)
    db.flush()
    db.add_all(
        [
            MovimientoInventario(
                producto_id=producto.id,
                cantidad=12,
                tipo_movimiento="entrada",
            ),
            PedidoItem(pedido_id=pedido.id, producto_id=producto.id, cantidad=10),
        ]
    )
    db.commit()
    _login(client, "user_solo_lectura")

    response = client.get("/api/inventario/productos")
    data = response.json()["productos"][0]
    assert response.status_code == 200
    assert data["bajo_minimo"] is False
    assert data["stock_comprometido"] == 10
    assert data["stock_disponible"] == 2
    assert data["disponible_bajo_minimo"] is True
