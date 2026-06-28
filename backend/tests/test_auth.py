import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import auth
from app.database import Base


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    auth._AUTH_CACHE.clear()
    yield session
    session.close()
    engine.dispose()
    auth._AUTH_CACHE.clear()


def user_payload(user_id=7, admin=False):
    return {
        "ok": True,
        "active": True,
        "tokenType": "opaque",
        "clientId": "componentwarehouse-web",
        "legacyUserId": user_id,
        "isAdmin": admin,
        "user": {
            "accountId": f"00000000-0000-0000-0000-{user_id:012d}",
            "phone": "13800138000",
            "displayName": "统一账号用户",
            "avatarUrl": "https://example.test/avatar.png",
        },
    }


def enable_remote_auth(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "account-v1")
    monkeypatch.setattr(auth, "ACCOUNT_BASE_URL", "https://account.example.test/api/account/v1")
    monkeypatch.setattr(auth, "ACCOUNT_CLIENT_SECRET", "test-secret")


def test_remote_success_cache_and_revocation(db, monkeypatch):
    clock = {"now": 1000.0}
    calls = []

    def remote_post(*args, **kwargs):
        calls.append(args)
        return FakeResponse(200, user_payload(admin=True))

    monkeypatch.setattr(auth.time, "monotonic", lambda: clock["now"])
    enable_remote_auth(monkeypatch)
    monkeypatch.setattr(auth.httpx, "post", remote_post)
    context = auth.verify_remote_token(db, "valid-token")
    assert context.user_id == 7
    assert context.is_admin is True
    assert db.get(auth.User, 7).password_hash is None

    auth.verify_remote_token(db, "valid-token")
    assert len(calls) == 1

    clock["now"] += auth.AUTH_VERIFY_CACHE_SECONDS + 1
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(200, {"ok": True, "active": False}),
    )
    with pytest.raises(HTTPException) as error:
        auth.verify_remote_token(db, "valid-token")
    assert error.value.status_code == 401
    assert auth.cached_auth("valid-token") is None


def test_outage_grace_then_service_unavailable(db, monkeypatch):
    clock = {"now": 2000.0}
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock["now"])
    enable_remote_auth(monkeypatch)
    monkeypatch.setattr(auth.httpx, "post", lambda *args, **kwargs: FakeResponse(200, user_payload()))
    auth.verify_remote_token(db, "grace-token")

    def outage(*args, **kwargs):
        raise httpx.ConnectError(
            "down",
            request=httpx.Request("POST", "https://account.example.com/api/account/v1/introspect"),
        )

    monkeypatch.setattr(auth.httpx, "post", outage)
    clock["now"] += auth.AUTH_VERIFY_CACHE_SECONDS + 1
    degraded = auth.verify_remote_token(db, "grace-token")
    assert degraded.auth_degraded is True

    clock["now"] = 2000.0 + auth.AUTH_OUTAGE_GRACE_SECONDS + 1
    with pytest.raises(HTTPException) as error:
        auth.verify_remote_token(db, "grace-token")
    assert error.value.status_code == 503


def test_invalid_remote_payload_is_rejected(db, monkeypatch):
    enable_remote_auth(monkeypatch)
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(200, {
            "ok": True,
            "active": True,
            "tokenType": "opaque",
            "clientId": "componentwarehouse-web",
            "user": {"accountId": "broken"},
        }),
    )
    with pytest.raises(HTTPException) as error:
        auth.verify_remote_token(db, "broken-payload")
    assert error.value.status_code == 502
