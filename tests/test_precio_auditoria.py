from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.modelos import Usuario
from app.db.negocio import AuditoriaCambioPrecio, ContextoAuditoriaPrecio, Producto
from app.servicios.auth import get_password_hash
from app.servicios.precios import actualizar_precios_producto
from app.servicios.roles import Rol


ROOT = Path(__file__).resolve().parents[1]


def _migrated_engine(path: Path):
    url = f"sqlite:///{path.as_posix()}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(URL.create("sqlite", database=str(path)))


def _add_account(db: Session, name: str, username: str, role: str) -> Usuario:
    user = Usuario(
        nombre=name,
        username=username,
        password_hash=get_password_hash("PasswordSegura2026!"),
        activo=True,
        rol=role,
        es_admin=role == Rol.ADMINISTRADOR.value,
    )
    db.add(user)
    db.flush()
    return user


def test_sqlite_trigger_audita_precio_anterior_nuevo_actor_y_fecha(tmp_path):
    engine = _migrated_engine(tmp_path / "prices.db")
    try:
        with Session(engine) as db:
            admin = _add_account(db, "Admin", "admin", Rol.ADMINISTRADOR.value)
            vendedor = _add_account(db, "Vendedor", "vendedor", Rol.VENDEDOR.value)
            producto = Producto(
                nombre="Medidor de prueba",
                tipo="componente",
                precio_compra=Decimal("10.00"),
                precio_venta=Decimal("18.00"),
                activo=True,
            )
            db.add(producto)
            db.commit()

            actualizar_precios_producto(
                db,
                producto_id=producto.id,
                usuario=admin,
                precio_compra=Decimal("12.50"),
                precio_venta=Decimal("20.00"),
            )
            db.commit()

            cambios = db.scalars(
                select(AuditoriaCambioPrecio)
                .where(AuditoriaCambioPrecio.producto_id == producto.id)
                .order_by(AuditoriaCambioPrecio.id)
            ).all()
            assert [(c.campo, c.valor_anterior, c.valor_nuevo) for c in cambios] == [
                ("precio_compra", Decimal("10.00"), Decimal("12.50")),
                ("precio_venta", Decimal("18.00"), Decimal("20.00")),
            ]
            assert all(c.usuario_id == admin.id and c.cambiado_en is not None for c in cambios)
            contexto = db.get(ContextoAuditoriaPrecio, 1)
            assert contexto.usuario_id is None

            actualizar_precios_producto(
                db,
                producto_id=producto.id,
                usuario=vendedor,
                precio_venta=Decimal("21.00"),
            )
            db.commit()
            vendedor_change = db.scalars(
                select(AuditoriaCambioPrecio)
                .where(AuditoriaCambioPrecio.usuario_id == vendedor.id)
            ).one()
            assert vendedor_change.campo == "precio_venta"
            assert vendedor_change.valor_anterior == Decimal("20.00")
            assert vendedor_change.valor_nuevo == Decimal("21.00")

            with pytest.raises(PermissionError):
                actualizar_precios_producto(
                    db,
                    producto_id=producto.id,
                    usuario=vendedor,
                    precio_compra=Decimal("1.00"),
                )
            db.rollback()

            with pytest.raises(IntegrityError):
                db.execute(
                    text("UPDATE productos SET precio_venta = 22.00 WHERE id = :id"),
                    {"id": producto.id},
                )
            db.rollback()
            assert db.scalar(
                select(AuditoriaCambioPrecio.id).where(
                    AuditoriaCambioPrecio.producto_id == producto.id
                ).order_by(AuditoriaCambioPrecio.id.desc())
            ) == vendedor_change.id
    finally:
        engine.dispose()


def test_api_admin_ve_y_cambia_ambos_precios_vendedor_solo_venta(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    engine = _migrated_engine(tmp_path / "prices-api.db")
    with Session(engine) as db:
        admin = _add_account(db, "Admin", "admin_api", Rol.ADMINISTRADOR.value)
        vendedor = _add_account(db, "Vendedor", "vendedor_api", Rol.VENDEDOR.value)
        producto = Producto(
            nombre="Medidor API",
            tipo="terminado",
            precio_compra=Decimal("100.00"),
            precio_venta=Decimal("150.00"),
            activo=True,
        )
        db.add(producto)
        db.commit()
        producto_id = producto.id
        admin_id = admin.id
        vendedor_id = vendedor.id

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            assert client.post(
                "/api/login",
                json={"username": "admin_api", "password": "PasswordSegura2026!"},
            ).status_code == 200
            listed = client.get("/api/admin/precios")
            assert listed.status_code == 200
            product = listed.json()["productos"][0]
            assert product["precio_compra"] == "100.00"
            assert product["precio_venta"] == "150.00"

            changed = client.patch(
                f"/api/admin/precios/{producto_id}",
                json={"precio_compra": "105.25", "precio_venta": "160.00"},
            )
            assert changed.status_code == 200
            client.post("/api/logout")

            assert client.post(
                "/api/login",
                json={"username": "vendedor_api", "password": "PasswordSegura2026!"},
            ).status_code == 200
            catalog = client.get("/api/inventario/productos").json()["productos"]
            assert "precio_compra" not in catalog[0]
            assert catalog[0]["precio_venta"] == "160.00"
            assert client.get("/api/admin/precios").status_code == 403

            sale_change = client.patch(
                f"/api/inventario/productos/{producto_id}/precio-venta",
                json={"precio_venta": "165.00"},
            )
            assert sale_change.status_code == 200
            client.post("/api/logout")

            assert client.post(
                "/api/login",
                json={"username": "admin_api", "password": "PasswordSegura2026!"},
            ).status_code == 200
            history = client.get("/api/admin/auditoria-precios").json()["cambios"]
            assert len(history) == 3
            assert {row["usuario_id"] for row in history} == {admin_id, vendedor_id}
            assert all(row["cambiado_en"] for row in history)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
