import pytest

from scripts.seed_negocio import seed, _es_sqlite_local


def test_seed_refuses_non_sqlite(monkeypatch):
    monkeypatch.setattr("app.config.settings.DATABASE_URL", "mysql+pymysql://user:pass@localhost/db")
    with pytest.raises(SystemExit):
        seed()


def test_seed_refuses_in_memory_sqlite(monkeypatch):
    monkeypatch.setattr("app.config.settings.DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(SystemExit):
        seed()


def test_seed_accepts_local_sqlite(monkeypatch):
    monkeypatch.setattr("app.config.settings.DATABASE_URL", "sqlite:///./seed_local.db")
    assert _es_sqlite_local() is True
    seed()
