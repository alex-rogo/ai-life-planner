"""Public demo sessions and account tokens must never share planner state."""

from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_demo_visitors_are_isolated(tmp_path, monkeypatch):
    import app.db as database
    import app.main as main

    settings = Settings(
        workspace_root=str(tmp_path / "workspaces"),
        proxy_shared_secret="test-proxy-secret",
        ai_mode="demo",
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "settings", settings)
    headers = {"X-Tomo-Proxy-Key": "test-proxy-secret"}
    with TestClient(app, headers=headers) as first, TestClient(app, headers=headers) as second:
        assert first.get("/api/goals").status_code == 401
        assert first.post("/api/workspaces/demo").status_code == 200
        assert second.post("/api/workspaces/demo").status_code == 200
        assert first.get("/api/workspaces/status").json() == {"mode": "demo"}
        before = second.get("/api/goals").json()
        assert before
        assert first.post("/api/workspaces/demo").status_code == 200
        assert first.get("/api/goals").json() == before
        assert first.post("/api/demo/clear").status_code == 204
        assert first.get("/api/goals").json() == []
        assert second.get("/api/goals").json() == before
        assert first.get("/api/messages").status_code == 200


def test_railway_origin_cannot_bypass_proxy(tmp_path, monkeypatch):
    import app.db as database
    import app.main as main

    settings = Settings(workspace_root=str(tmp_path), proxy_shared_secret="secret")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "settings", settings)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/api/workspaces/demo").status_code == 403
        assert client.get("/api/goals").status_code == 403


def test_signed_in_users_are_isolated_and_cannot_reset_accounts(tmp_path, monkeypatch):
    import app.db as database
    import app.main as main
    import app.workspaces as workspaces

    settings = Settings(workspace_root=str(tmp_path), proxy_shared_secret="secret")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(
        workspaces, "_clerk_user", lambda request, _settings: request.headers["Authorization"][7:]
    )
    common = {"X-Tomo-Proxy-Key": "secret"}
    with (
        TestClient(app, headers={**common, "Authorization": "Bearer user-one"}) as first,
        TestClient(app, headers={**common, "Authorization": "Bearer user-two"}) as second,
    ):
        assert first.get("/api/workspaces/status").json() == {"mode": "account"}
        assert second.get("/api/goals").json() == []
        assert first.post("/api/goals", json={"title": "Only mine"}).status_code == 201
        assert [item["title"] for item in first.get("/api/goals").json()] == ["Only mine"]
        assert second.get("/api/goals").json() == []
        assert first.post("/api/demo/clear").status_code == 403


def test_clerk_session_signature_and_origin_are_checked(tmp_path, monkeypatch):
    import app.db as database
    import app.main as main

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    settings = Settings(
        workspace_root=str(tmp_path), proxy_shared_secret="secret", clerk_jwt_key=public,
        clerk_authorized_parties="https://tomoplanner.app",
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "settings", settings)
    now = datetime.now(UTC)

    def token(origin: str, signing_key=key):
        return jwt.encode(
            {"sub": "user-one", "sid": "session-one", "azp": origin,
             "iat": now, "exp": now + timedelta(minutes=5)},
            signing_key, algorithm="RS256",
        )

    with TestClient(app, headers={"X-Tomo-Proxy-Key": "secret"}) as client:
        assert client.get("/api/workspaces/status", headers={"Authorization": f"Bearer {token('https://tomoplanner.app')}"}).json() == {"mode": "account"}
        assert client.get("/api/workspaces/status", headers={"Authorization": f"Bearer {token('https://other.example')}"}).status_code == 401
        another = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        assert client.get("/api/workspaces/status", headers={"Authorization": f"Bearer {token('https://tomoplanner.app', another)}"}).status_code == 401
