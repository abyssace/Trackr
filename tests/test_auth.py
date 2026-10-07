def test_login_ok(logged_client):
    r = logged_client.get("/api/me")
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "testuser"


def test_login_bad_credentials(client):
    r = client.post("/api/login", json={"username": "testuser", "password": "mal"})
    assert r.status_code == 401


def test_logout(client, usuario):
    client.post("/api/login", json={"username": "testuser", "password": "secret"})
    assert client.get("/api/me").status_code == 200

    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401


def test_protected_chat_requires_login(client):
    r = client.post("/api/chat", json={"mensaje": "hola"})
    assert r.status_code == 401
