import pytest

from app.db.modelos import Usuario
from app.db.negocio import Categoria, Producto, Proveedor
from app.servicios.auth import get_password_hash
from app.servicios.roles import Rol


def _crear_usuario(db, rol: str) -> Usuario:
    user = Usuario(
        nombre=f"Usuario {rol}",
        username=f"catalogos_{rol}",
        password_hash=get_password_hash("ClaveSegura123"),
        activo=True,
        rol=rol,
        es_admin=rol == Rol.ADMINISTRADOR.value,
    )
    db.add(user)
    db.commit()
    return user


def _login(client, user):
    password = "secret" if user.username == "testuser" else "ClaveSegura123"
    response = client.post(
        "/api/login",
        json={"username": user.username, "password": password},
    )
    assert response.status_code == 200


def test_administrador_crea_y_edita_categoria_y_proveedor(client, db, usuario):
    _login(client, usuario)
    category_response = client.post(
        "/api/inventario/categorias",
        json={"nombre": "Refacciones", "descripcion": "Piezas de reemplazo"},
    )
    supplier_response = client.post(
        "/api/inventario/proveedores",
        json={"nombre": "Proveedor Uno", "contacto": "Ana", "telefono": "8180000000"},
    )
    assert category_response.status_code == 201
    assert supplier_response.status_code == 201
    category_id = category_response.json()["categoria"]["id"]
    supplier_id = supplier_response.json()["proveedor"]["id"]

    category_update = client.patch(
        f"/api/inventario/categorias/{category_id}",
        json={"nombre": "Refacciones hidráulicas"},
    )
    supplier_update = client.patch(
        f"/api/inventario/proveedores/{supplier_id}",
        json={"correo": "ventas@ejemplo.mx"},
    )
    assert category_update.status_code == 200
    assert category_update.json()["categoria"]["nombre"] == "Refacciones hidráulicas"
    assert supplier_update.status_code == 200
    assert db.get(Proveedor, supplier_id).correo == "ventas@ejemplo.mx"

    catalogos = client.get("/api/inventario/catalogos").json()
    assert "Refacciones hidráulicas" in [item["nombre"] for item in catalogos["categorias"]]
    assert "Proveedor Uno" in [item["nombre"] for item in catalogos["proveedores"]]


@pytest.mark.parametrize("rol", [Rol.VENDEDOR.value, Rol.ENSAMBLADOR.value, Rol.SOLO_LECTURA.value])
def test_roles_sin_edicion_no_pueden_crear_catalogos(client, db, rol):
    user = _crear_usuario(db, rol)
    _login(client, user)
    assert client.post("/api/inventario/categorias", json={"nombre": "Bloqueada"}).status_code == 403
    assert client.post("/api/inventario/proveedores", json={"nombre": "Bloqueado"}).status_code == 403


def test_almacen_puede_crear_catalogos_pero_no_desactivarlos(client, db):
    user = _crear_usuario(db, Rol.ALMACEN.value)
    _login(client, user)
    category = client.post("/api/inventario/categorias", json={"nombre": "Almacén"})
    supplier = client.post("/api/inventario/proveedores", json={"nombre": "Proveedor Almacén"})
    assert category.status_code == 201
    assert supplier.status_code == 201

    category_id = category.json()["categoria"]["id"]
    supplier_id = supplier.json()["proveedor"]["id"]
    assert client.post(f"/api/inventario/categorias/{category_id}/desactivar").status_code == 403
    assert client.post(f"/api/inventario/proveedores/{supplier_id}/desactivar").status_code == 403


def test_admin_desactiva_sin_borrar_categoria_ni_proveedor(client, db, usuario):
    category = Categoria(nombre="Categoría para archivar")
    supplier = Proveedor(nombre="Proveedor para archivar")
    db.add_all([category, supplier])
    db.commit()
    _login(client, usuario)

    category_response = client.post(f"/api/inventario/categorias/{category.id}/desactivar")
    supplier_response = client.post(f"/api/inventario/proveedores/{supplier.id}/desactivar")

    assert category_response.status_code == 200
    assert supplier_response.status_code == 200
    db.refresh(category)
    db.refresh(supplier)
    assert category.activo is False
    assert supplier.activo is False
    assert db.get(Categoria, category.id) is not None
    assert db.get(Proveedor, supplier.id) is not None
    assert client.delete(f"/api/inventario/categorias/{category.id}").status_code == 405
    assert client.delete(f"/api/inventario/proveedores/{supplier.id}").status_code == 405
    active_catalog = client.get("/api/inventario/catalogos").json()
    assert category.nombre not in [row["nombre"] for row in active_catalog["categorias"]]
    assert supplier.nombre not in [row["nombre"] for row in active_catalog["proveedores"]]


@pytest.mark.parametrize(
    "path,model,name",
    [
        ("categorias", Categoria, "Bebidas Frías"),
        ("proveedores", Proveedor, "Suministros del Norte"),
    ],
)
def test_nombre_catalogo_unico_sin_importar_acentos_o_mayusculas(
    client, db, usuario, path, model, name
):
    db.add(model(nombre=name))
    db.commit()
    _login(client, usuario)

    response = client.post(
        f"/api/inventario/{path}",
        json={"nombre": "bebidas frias" if path == "categorias" else "suministros del norte"},
    )
    assert response.status_code == 409


def test_no_se_desactiva_categoria_en_uso_por_producto_activo(client, db, usuario):
    category = Categoria(nombre="Categoría asignada")
    db.add(category)
    db.flush()
    product = Producto(
        nombre="Producto asignado",
        tipo="componente",
        categoria_id=category.id,
        activo=True,
    )
    db.add(product)
    db.commit()
    _login(client, usuario)

    response = client.post(f"/api/inventario/categorias/{category.id}/desactivar")
    assert response.status_code == 409
    db.refresh(category)
    assert category.activo is True
    assert db.get(Producto, product.id).categoria_id == category.id
