import pytest

from app.db.modelos import Usuario
from app.db.negocio import Cliente
from app.servicios.auth import get_password_hash
from app.servicios.roles import Rol


def _crear_usuario(db, rol: str) -> Usuario:
    user = Usuario(
        nombre=f"Usuario {rol}",
        username=f"clientes_{rol}",
        password_hash=get_password_hash("ClaveSegura123"),
        activo=True,
        rol=rol,
        es_admin=rol == Rol.ADMINISTRADOR.value,
    )
    db.add(user)
    db.commit()
    return user


def _login(client, user):
    response = client.post(
        "/api/login",
        json={"username": user.username, "password": "ClaveSegura123"},
    )
    assert response.status_code == 200


def test_almacen_crea_cliente_con_datos_completos(client, db):
    _login(client, _crear_usuario(db, Rol.ALMACEN.value))
    response = client.post(
        "/api/inventario/clientes",
        json={
            "nombre": "  Distribuidora del Norte ",
            "razon_social": "Distribuidora del Norte S.A. de C.V.",
            "rfc": "dnn010101ab1",
            "direccion": "Av. Industria 100, Monterrey",
            "telefono": "8112345678",
            "correo": "compras@dnorte.mx",
            "contacto": "Luis Ramírez",
        },
    )
    assert response.status_code == 201
    assert response.json()["cliente"]["nombre"] == "Distribuidora del Norte"
    cliente = db.query(Cliente).filter(Cliente.nombre == "Distribuidora del Norte").one()
    assert cliente.rfc == "DNN010101AB1"
    assert cliente.correo == "compras@dnorte.mx"
    assert cliente.fecha_registro is not None


def test_cliente_solo_requiere_nombre(client, db):
    _login(client, _crear_usuario(db, Rol.ADMINISTRADOR.value))
    response = client.post("/api/inventario/clientes", json={"nombre": "Juan Pérez"})
    assert response.status_code == 201
    cliente = db.query(Cliente).filter(Cliente.nombre == "Juan Pérez").one()
    assert cliente.rfc is None
    assert cliente.telefono is None


def test_no_permite_nombres_duplicados_sin_importar_mayusculas(client, db):
    _login(client, _crear_usuario(db, Rol.ADMINISTRADOR.value))
    assert client.post("/api/inventario/clientes", json={"nombre": "Ana López"}).status_code == 201
    response = client.post("/api/inventario/clientes", json={"nombre": "ANA LÓPEZ"})
    assert response.status_code == 409


def test_vendedor_puede_crear_cliente(client, db):
    _login(client, _crear_usuario(db, Rol.VENDEDOR.value))
    response = client.post("/api/inventario/clientes", json={"nombre": "Cliente Vendedor"})
    assert response.status_code == 201


@pytest.mark.parametrize("rol", [Rol.ENSAMBLADOR.value, Rol.SOLO_LECTURA.value])
def test_roles_sin_alta_no_pueden_crear_clientes(client, db, rol):
    _login(client, _crear_usuario(db, rol))
    response = client.post("/api/inventario/clientes", json={"nombre": "Cliente Prohibido"})
    assert response.status_code == 403
    assert db.query(Cliente).filter(Cliente.nombre == "Cliente Prohibido").count() == 0


def test_valida_nombre_rfc_y_correo(client, db):
    _login(client, _crear_usuario(db, Rol.ALMACEN.value))
    assert client.post("/api/inventario/clientes", json={"nombre": "   "}).status_code == 422
    assert (
        client.post("/api/inventario/clientes", json={"nombre": "Cliente RFC", "rfc": "ABC"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/inventario/clientes",
            json={"nombre": "Cliente correo", "correo": "sin-arroba"},
        ).status_code
        == 422
    )
