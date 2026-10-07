import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-no-usar-en-produccion")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from passlib.context import CryptContext

from app.db.base import Base, engine, SessionLocal, get_db
from app.db.modelos import Usuario

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def usuario(db):
    user = Usuario(
        nombre="Test User",
        username="testuser",
        password_hash=pwd_context.hash("secret"),
        activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def otro_usuario(db):
    user = Usuario(
        nombre="Otro",
        username="otro",
        password_hash=pwd_context.hash("secret"),
        activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def logged_client(client, usuario):
    r = client.post("/api/login", json={"username": "testuser", "password": "secret"})
    assert r.status_code == 200
    return client
