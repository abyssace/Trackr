from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL


ROOT = Path(__file__).resolve().parents[1]


def _upgrade(database_path: Path):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    url = f"sqlite:///{database_path.as_posix()}"
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


def test_alembic_bootstraps_empty_database_in_temp_directory(tmp_path):
    db_path = tmp_path / "fresh.db"
    _upgrade(db_path)

    engine = create_engine(URL.create("sqlite", database=str(db_path)))
    try:
        inspector = inspect(engine)
        assert {"productos", "categorias", "proveedores", "usuarios"}.issubset(
            set(inspector.get_table_names())
        )
        assert {"contexto_auditoria_precios", "auditoria_cambios_precios"}.issubset(
            set(inspector.get_table_names())
        )
        columns = {column["name"] for column in inspector.get_columns("productos")}
        assert {"codigo", "categoria_id", "proveedor_id", "precio_compra", "precio_venta"}.issubset(columns)
        movement_columns = {
            column["name"] for column in inspector.get_columns("movimientos_inventario")
        }
        assert {"usuario_id", "idempotency_key"}.issubset(movement_columns)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0006_auditoria_precios"
            trigger = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' AND name='trg_auditoria_cambios_precios'"
                )
            ).scalar_one()
        assert trigger == "trg_auditoria_cambios_precios"
    finally:
        engine.dispose()


def test_alembic_adds_catalog_fields_without_losing_legacy_product(tmp_path):
    db_path = tmp_path / "legacy.db"
    engine = create_engine(URL.create("sqlite", database=str(db_path)))
    with engine.begin() as conn:
        conn.execute(
            text(
                """CREATE TABLE productos (
                    id INTEGER PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    descripcion TEXT,
                    tipo VARCHAR(20) NOT NULL,
                    unidad_medida VARCHAR(20),
                    stock_minimo INTEGER,
                    medidor_id INTEGER,
                    tamano_id INTEGER,
                    tipo_utd_id INTEGER,
                    alias VARCHAR(255),
                    activo BOOLEAN NOT NULL
                )"""
            )
        )
        conn.execute(
            text(
                "INSERT INTO productos (id, nombre, tipo, activo) "
                "VALUES (17, 'Producto legado', 'componente', 1)"
            )
        )
    engine.dispose()

    _upgrade(db_path)

    engine = create_engine(URL.create("sqlite", database=str(db_path)))
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, nombre, codigo, precio_compra FROM productos WHERE id = 17")
            ).one()
        assert row == (17, "Producto legado", None, None)
        constraints = inspect(engine).get_unique_constraints("productos")
        assert any(constraint["name"] == "uq_productos_codigo" for constraint in constraints)
    finally:
        engine.dispose()


def test_alembic_adds_responsable_and_idempotency_to_legacy_ledger(tmp_path):
    db_path = tmp_path / "legacy-ledger.db"
    engine = create_engine(URL.create("sqlite", database=str(db_path)))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE productos (id INTEGER PRIMARY KEY, nombre VARCHAR(100) NOT NULL, tipo VARCHAR(20) NOT NULL, activo BOOLEAN NOT NULL)"))
        conn.execute(text("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre VARCHAR(200) NOT NULL, username VARCHAR(100) NOT NULL, password_hash VARCHAR(200) NOT NULL, activo BOOLEAN NOT NULL, es_admin BOOLEAN NOT NULL)"))
        conn.execute(text("INSERT INTO usuarios VALUES (1, 'Admin legado', 'admin', 'hash', 1, 1)"))
        conn.execute(
            text(
                """CREATE TABLE pedido_items (
                    id INTEGER PRIMARY KEY,
                    pedido_id INTEGER NOT NULL,
                    producto_id INTEGER NOT NULL,
                    cantidad INTEGER NOT NULL,
                    precio_unitario FLOAT,
                    inventario_descontado BOOLEAN NOT NULL,
                    observaciones TEXT
                )"""
            )
        )
        conn.execute(
            text(
                "INSERT INTO pedido_items "
                "(id, pedido_id, producto_id, cantidad, inventario_descontado) "
                "VALUES (8, 3, 17, 2, 0)"
            )
        )
        conn.execute(
            text(
                """CREATE TABLE movimientos_inventario (
                    id INTEGER PRIMARY KEY,
                    producto_id INTEGER NOT NULL,
                    cantidad INTEGER NOT NULL,
                    tipo_movimiento VARCHAR(20) NOT NULL,
                    pedido_id INTEGER,
                    empleado_id INTEGER,
                    empleado_entrega_id INTEGER,
                    referencia VARCHAR(100),
                    observaciones TEXT,
                    creado_en DATETIME NOT NULL
                )"""
            )
        )
        conn.execute(
            text(
                "INSERT INTO movimientos_inventario "
                "(id, producto_id, cantidad, tipo_movimiento, creado_en) "
                "VALUES (4, 17, 6, 'entrada', '2026-01-01 12:00:00')"
            )
        )
    engine.dispose()

    _upgrade(db_path)

    engine = create_engine(URL.create("sqlite", database=str(db_path)))
    try:
        columns = {
            column["name"] for column in inspect(engine).get_columns("movimientos_inventario")
        }
        assert {"usuario_id", "idempotency_key"}.issubset(columns)
        user_columns = {column["name"] for column in inspect(engine).get_columns("usuarios")}
        assert {
            "rol",
            "intentos_fallidos",
            "bloqueado_hasta",
            "debe_cambiar_password",
        }.issubset(user_columns)
        order_item_columns = {
            column["name"] for column in inspect(engine).get_columns("pedido_items")
        }
        assert "activo" in order_item_columns
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, producto_id, cantidad, usuario_id, idempotency_key FROM movimientos_inventario WHERE id=4")
            ).one()
            user = conn.execute(
                text("SELECT rol, intentos_fallidos, bloqueado_hasta FROM usuarios WHERE id=1")
            ).one()
            item = conn.execute(
                text("SELECT id, producto_id, cantidad, activo FROM pedido_items WHERE id=8")
            ).one()
        assert row == (4, 17, 6, None, None)
        assert user == ("administrador", 0, None)
        assert item == (8, 17, 2, 1)
        assert inspect(engine).has_table("auditoria")
    finally:
        engine.dispose()
