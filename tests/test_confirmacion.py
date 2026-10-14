import pytest
from datetime import datetime, timezone, timedelta

from app.db.modelos import AccionPendiente, Usuario
from app.db.negocio import Producto, MovimientoInventario
from app.servicios.confirmacion import (
    crear_pendiente,
    obtener_pendiente,
    puede_confirmar,
    confirmar_pendiente,
    cancelar_pendiente,
)
from app.agente.tools.ejecutores import (
    ejecutar_registrar_entrada_mercancia,
)
from app.servicios.roles import Rol


@pytest.fixture
def otro_usuario_no_admin(db):
    from passlib.context import CryptContext

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    u = Usuario(
        nombre="Otro",
        username="otro",
        password_hash=pwd.hash("secret"),
        activo=True,
        es_admin=False,
        rol=Rol.SOLO_LECTURA.value,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def admin_usuario(db):
    from passlib.context import CryptContext

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    u = Usuario(
        nombre="Admin",
        username="admin2",
        password_hash=pwd.hash("secret"),
        activo=True,
        es_admin=True,
        rol=Rol.ADMINISTRADOR.value,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_crear_pendiente_reemplaza_anterior(db, usuario):
    crear_pendiente(db, usuario.id, "test", {"x": 1}, "resumen 1")
    crear_pendiente(db, usuario.id, "test", {"x": 2}, "resumen 2")

    pendiente = obtener_pendiente(db, usuario.id)
    assert pendiente.tool == "test"
    assert pendiente.resumen == "resumen 2"
    anteriores = (
        db.query(AccionPendiente)
        .filter(AccionPendiente.usuario_id == usuario.id, AccionPendiente.estado == "cancelada")
        .count()
    )
    assert anteriores == 1


@pytest.mark.anyio
async def test_confirmar_ejecuta_accion(db, usuario):
    producto = Producto(nombre="Tornillos", tipo="componente", unidad_medida="pieza")
    db.add(producto)
    db.commit()

    args = {"producto_id": producto.id, "cantidad": 100}
    resumen = "Entrada de 100 tornillos"
    pendiente = crear_pendiente(db, usuario.id, "registrar_entrada_mercancia", args, resumen)

    resultado = await confirmar_pendiente(db, pendiente, usuario)
    assert "Entrada registrada" in resultado
    assert db.query(MovimientoInventario).count() == 1
    assert pendiente.estado == "confirmada"


@pytest.mark.anyio
async def test_usuario_puede_confirmar_propio(db, usuario):
    pendiente = crear_pendiente(db, usuario.id, "test", {}, "x")
    assert puede_confirmar(pendiente, usuario) is True


@pytest.mark.anyio
async def test_admin_no_puede_confirmar_de_otro(db, usuario, admin_usuario):
    pendiente = crear_pendiente(db, usuario.id, "test", {}, "x")
    assert puede_confirmar(pendiente, admin_usuario) is False


@pytest.mark.anyio
async def test_no_admin_no_puede_confirmar_de_otro(db, usuario, otro_usuario_no_admin):
    pendiente = crear_pendiente(db, usuario.id, "test", {}, "x")
    assert puede_confirmar(pendiente, otro_usuario_no_admin) is False


@pytest.mark.anyio
async def test_confirmar_rechaza_si_rol_no_tiene_permiso(db, usuario):
    pendiente = crear_pendiente(db, usuario.id, "registrar_entrada_mercancia", {}, "x")
    usuario.rol = Rol.SOLO_LECTURA.value
    with pytest.raises(PermissionError):
        await confirmar_pendiente(db, pendiente, usuario)


def test_pendiente_expirada_no_se_devuelve(db, usuario):
    pendiente = AccionPendiente(
        usuario_id=usuario.id,
        tool="test",
        args="{}",
        resumen="x",
        expira_en=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.add(pendiente)
    db.commit()

    assert obtener_pendiente(db, usuario.id) is None
    db.refresh(pendiente)
    assert pendiente.estado == "expirada"


def test_cancelar_pendiente(db, usuario):
    pendiente = crear_pendiente(db, usuario.id, "test", {}, "x")
    cancelar_pendiente(db, pendiente)
    assert pendiente.estado == "cancelada"
