import pytest

from scripts.seed_negocio import seed


def test_seed_refuses_non_sqlite(monkeypatch):
    monkeypatch.setattr("app.config.settings.DATABASE_URL", "mysql+pymysql://user:pass@localhost/db")
    with pytest.raises(SystemExit):
        seed()
