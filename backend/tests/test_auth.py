"""Tests for the session-auth layer.

These deliberately avoid importing app.main (which pulls in the recorder
stack); they exercise core.auth and routes.auth against a minimal app.
"""
import os
import tempfile

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmp)
    monkeypatch.setenv("RECORDINGS_DIR", os.path.join(tmp, "rec"))
    monkeypatch.setenv("APP_PASSWORD", "correct-horse")

    # Re-import with the patched environment so Settings picks it up.
    import app.config
    import importlib
    importlib.reload(app.config)
    import app.core.auth as auth_mod
    importlib.reload(auth_mod)
    import app.api.routes.auth as auth_routes
    importlib.reload(auth_routes)

    api = FastAPI()
    api.include_router(auth_routes.router, prefix="/api")

    @api.get("/api/secret", dependencies=[Depends(auth_mod.require_auth)])
    def secret():
        return {"ok": True}

    return TestClient(api)


def test_protected_route_rejects_anonymous(client):
    assert client.get("/api/secret").status_code == 401


def test_login_with_wrong_password_is_rejected(client):
    r = client.post("/api/auth/login", json={"password": "wrong"})
    assert r.status_code == 401
    assert client.get("/api/secret").status_code == 401


def test_login_then_access(client):
    r = client.post("/api/auth/login", json={"password": "correct-horse"})
    assert r.status_code == 200, r.text
    assert "camsuite_session" in r.cookies
    assert client.get("/api/secret").status_code == 200


def test_logout_revokes_access(client):
    client.post("/api/auth/login", json={"password": "correct-horse"})
    assert client.get("/api/secret").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/secret").status_code == 401


def test_status_probe_is_unauthenticated(client):
    r = client.get("/api/auth/status")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False, "auth_enabled": True}
    client.post("/api/auth/login", json={"password": "correct-horse"})
    assert client.get("/api/auth/status").json()["authenticated"] is True


def test_forged_token_is_rejected(client):
    import time
    forged = f"{int(time.time()) + 9999}:nonce:{'0' * 64}"
    client.cookies.set("camsuite_session", forged)
    assert client.get("/api/secret").status_code == 401


def test_expired_token_is_rejected(client):
    import app.core.auth as auth_mod
    import hmac, hashlib, time
    state = auth_mod.auth_state()
    payload = f"{int(time.time()) - 10}:nonce"
    sig = hmac.new(state._secret, payload.encode(), hashlib.sha256).hexdigest()
    client.cookies.set("camsuite_session", f"{payload}:{sig}")
    assert client.get("/api/secret").status_code == 401


def test_session_cookie_is_httponly(client):
    r = client.post("/api/auth/login", json={"password": "correct-horse"})
    assert "httponly" in r.headers["set-cookie"].lower()
