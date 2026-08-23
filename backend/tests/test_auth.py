import json

import httpx
import pytest
import asyncio
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import auth
from app import main as main_app
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


def make_request(cookie: str = ""):
    headers = [
        (b"host", b"wxylab.ltd"),
        (b"x-forwarded-proto", b"https"),
    ]
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/component-warehouse/api/auth/account/sso/token",
        "scheme": "https",
        "server": ("wxylab.ltd", 443),
        "headers": headers,
    })


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


def test_desktop_sync_token_is_isolated_from_web_client(db, monkeypatch):
    enable_remote_auth(monkeypatch)
    payload = user_payload()
    payload["clientId"] = "componentwarehouse-desktop-v1"
    payload["scope"] = "account.profile.read hardware.sync.read hardware.sync.write"
    monkeypatch.setattr(auth.httpx, "post", lambda *args, **kwargs: FakeResponse(200, payload))
    context = auth.verify_desktop_sync_token(db, "desktop-token", "hardware.sync.read")
    assert context.user_id == 7
    with pytest.raises(HTTPException) as error:
        auth.verify_remote_token(db, "desktop-token")
    assert error.value.status_code == 401


def test_sso_token_request_validates_required_parameters(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "account-v1")
    monkeypatch.setattr(auth, "ACCOUNT_SSO_TOKEN_URL", "https://account.example.test/sso/token")

    with pytest.raises(HTTPException) as error:
        asyncio.run(main_app.account_sso_token_request({}))
    assert error.value.status_code == 400
    assert "SSO 登录参数不完整" in error.value.detail


def test_sso_start_sets_cookie_and_sanitizes_return_to(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "account-v1")
    monkeypatch.setattr(auth, "LOCAL_AUTH_SECRET", "local-test-secret")
    monkeypatch.setattr(auth, "ACCOUNT_WEB_CLIENT_ID", "componentwarehouse-web")
    monkeypatch.setattr(auth, "ACCOUNT_SSO_AUTHORIZE_URL", "https://account.example.test/sso/authorize")
    monkeypatch.setattr(auth, "ACCOUNT_SSO_TOKEN_URL", "https://account.example.test/sso/token")
    monkeypatch.setattr(auth, "ACCOUNT_SSO_REDIRECT_URI", "https://wxylab.ltd/component-warehouse/personal/auth/callback")

    response = Response()
    started = main_app.account_sso_start(
        {"returnTo": "https://evil.example/phish"},
        make_request(),
        response,
    )

    assert "code_challenge_method=S256" in started["authorizeUrl"]
    assert started["returnTo"] == "https://wxylab.ltd/hardware/"
    assert "Path=/hardware" in response.headers["set-cookie"]
    cookie = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    payload = main_app.parse_sso_cookie(cookie)
    assert payload["state"] == started["state"]
    assert payload["code_verifier"]


def test_sso_token_request_uses_cookie_verifier_and_clears_cookie(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "account-v1")
    monkeypatch.setattr(auth, "LOCAL_AUTH_SECRET", "local-test-secret")
    monkeypatch.setattr(auth, "ACCOUNT_WEB_CLIENT_ID", "componentwarehouse-web")
    monkeypatch.setattr(auth, "ACCOUNT_SSO_AUTHORIZE_URL", "https://account.example.test/sso/authorize")
    monkeypatch.setattr(auth, "ACCOUNT_SSO_TOKEN_URL", "https://account.example.test/sso/token")
    monkeypatch.setattr(auth, "ACCOUNT_SSO_REDIRECT_URI", "https://wxylab.ltd/component-warehouse/personal/auth/callback")
    response = Response()
    started = main_app.account_sso_start(
        {"returnTo": "https://wxylab.ltd/hardware/projects"},
        make_request(),
        response,
    )
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse(200, {"session": {"accessToken": "a", "refreshToken": "r"}, "user": {}})

    monkeypatch.setattr(main_app.httpx, "AsyncClient", FakeAsyncClient)
    result = asyncio.run(main_app.account_sso_token_request(
        {"code": "auth-code", "state": started["state"]},
        make_request(cookie),
    ))

    assert captured["json"]["code_verifier"]
    assert captured["json"]["redirect_uri"] == "https://wxylab.ltd/component-warehouse/personal/auth/callback"
    assert result["returnTo"] == "https://wxylab.ltd/hardware/projects"

    with pytest.raises(HTTPException) as error:
        asyncio.run(main_app.account_sso_token_request(
            {"code": "auth-code", "state": "wrong-state"},
            make_request(cookie),
        ))
    assert error.value.status_code == 400


def test_legacy_login_entrypoints_are_retired():
    async_functions = [
        main_app.auth_account_login_sms,
        main_app.auth_account_login_password,
        main_app.auth_account_register,
        main_app.auth_account_password_reset,
    ]
    sync_functions = [
        main_app.auth_local_register,
        main_app.auth_local_login,
        main_app.auth_local_refresh,
        main_app.auth_local_logout,
        main_app.auth_local_update_profile,
        main_app.auth_local_change_password,
    ]

    for func in async_functions:
        with pytest.raises(HTTPException) as error:
            asyncio.run(func())
        assert error.value.status_code == 410
        assert "统一账号 SSO 登录" in error.value.detail

    for func in sync_functions:
        with pytest.raises(HTTPException) as error:
            func()
        assert error.value.status_code == 410
        assert "统一账号 SSO 登录" in error.value.detail


def test_account_me_proxies_account_center_profile(monkeypatch):
    captured = {}

    async def fake_proxy(method, path, payload=None, token=None):
        captured.update({"method": method, "path": path, "payload": payload, "token": token})
        return {
            "ok": True,
            "user": {
                "accountId": "account-1",
                "phone": "16794901813",
                "displayName": "浩宇",
                "avatarUrl": "https://wxylab.ltd/account/avatar/default/account-1.svg",
            },
        }

    monkeypatch.setattr(main_app, "account_v1_proxy_request", fake_proxy)
    result = asyncio.run(main_app.auth_account_me("Bearer wxy_at_test"))

    assert result["user"]["avatarUrl"].startswith("https://wxylab.ltd/account/avatar/default/")
    assert captured == {"method": "GET", "path": "/me", "payload": None, "token": "wxy_at_test"}

    with pytest.raises(HTTPException) as error:
        asyncio.run(main_app.auth_account_me(None))
    assert error.value.status_code == 401


def test_health_status_exposes_public_status_contract(db, monkeypatch):
    def fake_get(url, timeout):
        assert url == "https://account.example.test/health"
        assert timeout <= 2.0
        return FakeResponse(200, {"ok": True, "status": "operational"})

    monkeypatch.setattr(main_app.auth_module, "AUTH_MODE", "account-v1")
    monkeypatch.setattr(main_app.auth_module, "ACCOUNT_BASE_URL", "https://account.example.test/api/account/v1")
    monkeypatch.setattr(main_app.auth_module, "AUTH_HTTP_TIMEOUT_SECONDS", 8.0)
    monkeypatch.setattr(main_app.httpx, "get", fake_get)

    data = main_app.health_status(db)

    assert data["service"] == "component-warehouse"
    assert data["version"] == main_app.APP_VERSION
    assert data["status"] in main_app.PUBLIC_STATUS_RANK
    assert data["checkedAt"].endswith("+08:00")
    assert isinstance(data["ok"], bool)
    assert isinstance(data["components"], list)
    assert {item["name"] for item in data["components"]} >= {"web", "database", "warehouse", "ai", "activity", "auth"}
    assert data["metrics"]["uptimeSeconds"] >= 0
    assert data["metrics"]["queuedJobs"] == 0

    dumped = json.dumps(data, ensure_ascii=False)
    for forbidden in ("sqlite", "DATABASE_URL", "ACCOUNT_CLIENT_SECRET", "test-secret", "13800138000", "/opt/", "Traceback"):
        assert forbidden not in dumped
