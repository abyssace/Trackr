import pytest

from app.db.modelos import Usuario
from app.db.negocio import Empleado, MovimientoInventario, Producto
from app.servicios.auth import get_password_hash
from app.servicios.roles import Rol


def _login(client, username="testuser", password="secret"):
    return client.post("/api/login", json={"username": username, "password": password})


def test_admin_crea_usuario_y_empleado_con_rol_y_cambio_obligatorio(client, db, usuario):
    assert _login(client).status_code == 200
    response = client.post(
        "/api/admin/personal",
        json={
            "nombre": "Ana Martínez",
            "username": "ana.martinez",
            "password_temporal": "TemporalSeguro2026!",
            "rol": "almacen",
        },
    )
    assert response.status_code == 201
    data = response.json()["usuario"]
    assert data["nombre"] == "Ana Martínez"
    assert data["rol"] == "almacen"
    assert data["debe_cambiar_password"] is True
    assert "Registrar entradas y salidas de inventario" in data["permisos"]
    assert "password_hash" not in data
    assert "password_temporal" not in data

    staff = db.query(Usuario).filter_by(username="ana.martinez").one()
    employee = db.query(Empleado).filter_by(usuario_id=staff.id).one()
    assert staff.debe_cambiar_password is True
    assert employee.nombre == staff.nombre
    assert employee.rol == staff.rol

    listing = client.get("/api/admin/personal")
    assert listing.status_code == 200
    listed = next(user for user in listing.json()["usuarios"] if user["id"] == staff.id)
    assert listed["empleado_id"] == employee.id
    assert listed["permisos"] == data["permisos"]


@pytest.mark.parametrize("rol", [r.value for r in Rol])
def test_admin_puede_crear_personal_con_cualquier_rol(client, db, usuario, rol):
    assert _login(client).status_code == 200
    response = client.post(
        "/api/admin/personal",
        json={
            "nombre": f"Persona {rol}",
            "username": f"persona_{rol}",
            "password_temporal": "TemporalSeguro2026!",
            "rol": rol,
        },
    )
    assert response.status_code == 201
    assert response.json()["usuario"]["rol"] == rol


def test_admin_no_acepta_roles_inexistentes(client, db, usuario):
    assert _login(client).status_code == 200
    response = client.post(
        "/api/admin/personal",
        json={
            "nombre": "Persona inválida",
            "username": "persona_invalida",
            "password_temporal": "TemporalSeguro2026!",
            "rol": "supervisor",
        },
    )
    assert response.status_code == 422


def test_rol_almacen_no_puede_administrar_usuarios(client, db):
    user = Usuario(
        nombre="Almacén",
        username="warehouse_staff_admin_test",
        password_hash=get_password_hash("TemporalSeguro2026!"),
        activo=True,
        rol=Rol.ALMACEN.value,
    )
    db.add(user)
    db.commit()
    assert _login(client, user.username, "TemporalSeguro2026!").status_code == 200
    assert client.get("/api/admin/personal").status_code == 403
    response = client.post(
        "/api/admin/personal",
        json={
            "nombre": "No autorizado",
            "username": "no_autorizado",
            "password_temporal": "TemporalSeguro2026!",
            "rol": Rol.VENDEDOR.value,
        },
    )
    assert response.status_code == 403


def test_cuenta_nueva_debe_cambiar_password_antes_de_usar_la_app(client, db, usuario):
    assert _login(client).status_code == 200
    create = client.post(
        "/api/admin/personal",
        json={
            "nombre": "Vendedor nuevo",
            "username": "vendedor_nuevo",
            "password_temporal": "TemporalSeguro2026!",
            "rol": Rol.VENDEDOR.value,
        },
    )
    assert create.status_code == 201

    client.post("/api/logout")
    login = _login(client, "vendedor_nuevo", "TemporalSeguro2026!")
    assert login.status_code == 200
    assert login.json()["usuario"]["debe_cambiar_password"] is True
    assert client.get("/api/me").json()["debe_cambiar_password"] is True
    assert client.get("/api/inventario/productos").status_code == 403
    assert client.post("/api/chat", json={"mensaje": "hola"}).status_code == 403

    change = client.post(
        "/api/cambiar-password",
        json={
            "password_actual": "TemporalSeguro2026!",
            "password_nueva": "NuevaClaveSegura2026!",
            "confirmar_password": "NuevaClaveSegura2026!",
        },
    )
    assert change.status_code == 200
    assert client.get("/api/me").json()["debe_cambiar_password"] is False
    assert client.get("/api/inventario/productos").status_code == 200

    client.post("/api/logout")
    assert _login(client, "vendedor_nuevo", "NuevaClaveSegura2026!").status_code == 200
    assert _login(client, "vendedor_nuevo", "TemporalSeguro2026!").status_code == 401


def test_admin_no_usa_chat_ni_catalogo_general_pero_conserva_excepciones(client, db, usuario):
    producto = Producto(nombre="Producto oculto al admin", tipo="componente", activo=True)
    db.add(producto)
    db.flush()
    db.add(
        MovimientoInventario(
            producto_id=producto.id,
            cantidad=5,
            tipo_movimiento="entrada",
        )
    )
    db.commit()
    assert _login(client).status_code == 200

    assert client.get("/api/inventario/productos").status_code == 403
    assert client.get("/api/inventario/resumen").status_code == 403
    assert client.get("/api/inventario/movimientos").status_code == 403
    assert client.get("/api/inventario/catalogos").status_code == 403
    assert client.get("/api/inventario/catalogos/gestion").status_code == 403
    assert client.post("/api/chat", json={"mensaje": "hola"}).status_code == 403
    assert client.get("/api/historial").status_code == 403
    assert client.get("/api/pendiente").status_code == 403

    minimal = client.get("/api/admin/productos-desactivables")
    assert minimal.status_code == 200
    assert minimal.json()["productos"] == [
        {"id": producto.id, "nombre": producto.nombre, "codigo": None}
    ]
    deactivate = client.post(f"/api/admin/productos/{producto.id}/desactivar")
    assert deactivate.status_code == 200
    db.refresh(producto)
    assert producto.activo is False
