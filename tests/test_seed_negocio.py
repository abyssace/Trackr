import pytest
from pathlib import Path
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from alembic import command
from alembic.config import Config

from scripts.seed_negocio import seed, _es_sqlite_local
from app.db.negocio import Categoria, MovimientoInventario, Producto, Proveedor


def _prepare_database(path: Path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    command.upgrade(config, "head")


def test_seed_refuses_non_sqlite(monkeypatch):
    monkeypatch.setattr("app.config.settings.DATABASE_URL", "mysql+pymysql://user:pass@localhost/db")
    with pytest.raises(SystemExit):
        seed()


def test_seed_refuses_in_memory_sqlite(monkeypatch):
    monkeypatch.setattr("app.config.settings.DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(SystemExit):
        seed()


def test_seed_refuses_memory_mode_sqlite_uri():
    assert _es_sqlite_local("sqlite:///file:memdb1?mode=memory&cache=shared") is False


def test_seed_accepts_local_sqlite_and_is_additive_idempotent(tmp_path):
    db_path = tmp_path / "seed_local.db"
    _prepare_database(db_path)
    url = f"sqlite:///{db_path.as_posix()}"
    assert _es_sqlite_local(url) is True

    seed(database_url=url)
    engine = create_engine(url)
    with Session(engine) as db:
        first_products = db.query(Producto).count()
        first_movements = db.query(MovimientoInventario).count()
        assert db.query(Categoria).count() >= 3
        assert db.query(Proveedor).count() >= 2
        demo = db.query(Producto).filter_by(codigo="DEMO-MED-001").one()
        assert demo.precio_compra == Decimal("420.00")
        assert demo.precio_venta == Decimal("690.00")
        custom = Producto(nombre="Producto del usuario", tipo="componente", activo=True)
        db.add(custom)
        db.commit()

    seed(database_url=url)
    with Session(engine) as db:
        assert db.query(Producto).count() == first_products + 1
        assert db.query(MovimientoInventario).count() == first_movements
        assert db.query(Producto).filter_by(nombre="Producto del usuario").count() == 1
        assert db.query(Producto.codigo).filter(Producto.codigo.isnot(None)).count() >= 3
    engine.dispose()
