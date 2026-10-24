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
        columns = {column["name"] for column in inspector.get_columns("productos")}
        assert {"codigo", "categoria_id", "proveedor_id", "precio_compra", "precio_venta"}.issubset(columns)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_inventory_catalog"
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
