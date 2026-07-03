import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from .features import feature_config
from .models import User


AUTH_MODE = os.getenv("AUTH_MODE", "account-v1").strip().lower()
ACCOUNT_PROVIDER_LABEL = os.getenv("ACCOUNT_PROVIDER_LABEL", "Account V1").strip() or "Account V1"
ACCOUNT_BASE_URL = os.getenv("ACCOUNT_BASE_URL", "").rstrip("/")
ACCOUNT_SERVICE_CLIENT_ID = os.getenv("ACCOUNT_SERVICE_CLIENT_ID", "componentwarehouse-service").strip()
ACCOUNT_WEB_CLIENT_ID = os.getenv("ACCOUNT_WEB_CLIENT_ID", "componentwarehouse-web").strip()
ACCOUNT_CLIENT_SECRET = os.getenv("ACCOUNT_CLIENT_SECRET", "").strip()
ACCOUNT_SSO_REDIRECT_URI = os.getenv("ACCOUNT_SSO_REDIRECT_URI", "").strip()
ACCOUNT_SSO_AUTHORIZE_URL = os.getenv("ACCOUNT_SSO_AUTHORIZE_URL", "").strip()
ACCOUNT_SSO_TOKEN_URL = os.getenv("ACCOUNT_SSO_TOKEN_URL", "").strip()
LEGACY_CLIENT_ID_HEADER = "-".join(["X", "".join(["W", "XY"]), "Client", "Id"])
LEGACY_CLIENT_SECRET_HEADER = "-".join(["X", "".join(["W", "XY"]), "Client", "Secret"])
AUTH_VERIFY_CACHE_SECONDS = max(10, int(os.getenv("AUTH_VERIFY_CACHE_SECONDS", "60")))
AUTH_OUTAGE_GRACE_SECONDS = max(
    AUTH_VERIFY_CACHE_SECONDS,
    int(os.getenv("AUTH_OUTAGE_GRACE_SECONDS", "1800")),
)
AUTH_HTTP_TIMEOUT_SECONDS = max(2.0, float(os.getenv("AUTH_HTTP_TIMEOUT_SECONDS", "8")))
LOCAL_AUTH_SECRET = os.getenv("LOCAL_AUTH_SECRET", os.getenv("TEAM_INVITE_SECRET", "")).strip()
LOCAL_AUTH_ALLOW_REGISTRATION = os.getenv("LOCAL_AUTH_ALLOW_REGISTRATION", "1") == "1"
LOCAL_ACCESS_TOKEN_MINUTES = max(5, int(os.getenv("LOCAL_ACCESS_TOKEN_MINUTES", "60")))
LOCAL_REFRESH_TOKEN_DAYS = max(1, int(os.getenv("LOCAL_REFRESH_TOKEN_DAYS", "30")))
ADMIN_PHONE_NUMBERS = {
    phone.strip()
    for phone in os.getenv(
        "ADMIN_PHONE_NUMBERS",
        os.getenv("LEGACY_COMPONENT_ADMIN_PHONES", ""),
    ).split(",")
    if phone.strip()
}
NO_AUTH_USER_ID = int(os.getenv("NO_AUTH_USER_ID", "1"))
NO_AUTH_PHONE = os.getenv("NO_AUTH_PHONE", "local-user").strip() or "local-user"
NO_AUTH_NICKNAME = os.getenv("NO_AUTH_NICKNAME", "本地用户").strip() or "本地用户"
NO_AUTH_ADMIN = os.getenv("NO_AUTH_ADMIN", "1") == "1"


def account_public_url(path: str) -> str:
    if not ACCOUNT_BASE_URL:
        return ""
    parts = urlsplit(ACCOUNT_BASE_URL)
    if not parts.scheme or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


if not ACCOUNT_SSO_AUTHORIZE_URL:
    ACCOUNT_SSO_AUTHORIZE_URL = account_public_url("/sso/authorize")
if not ACCOUNT_SSO_TOKEN_URL:
    ACCOUNT_SSO_TOKEN_URL = account_public_url("/sso/token")


@dataclass(frozen=True)
class AuthContext:
    user_id: int
    phone: str
    nickname: str
    account_id: str = ""
    avatar_url: str = ""
    is_admin: bool = False
    auth_degraded: bool = False


@dataclass
class CachedAuth:
    context: AuthContext
    verified_at: float


_AUTH_CACHE: dict[str, CachedAuth] = {}
_AUTH_CACHE_LOCK = threading.Lock()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def auth_required() -> bool:
    return AUTH_MODE != "none"


def auth_public_config() -> dict:
    return {
        "auth_required": auth_required(),
        "account_mode": AUTH_MODE,
        "provider_label": ACCOUNT_PROVIDER_LABEL,
        "auth_base_url": ACCOUNT_BASE_URL,
        "web_client_id": ACCOUNT_WEB_CLIENT_ID,
        "sso_enabled": bool(ACCOUNT_SSO_AUTHORIZE_URL and ACCOUNT_SSO_TOKEN_URL),
        "sso_authorize_url": ACCOUNT_SSO_AUTHORIZE_URL,
        "sso_redirect_uri": ACCOUNT_SSO_REDIRECT_URI,
        "sms_captcha_required": False,
        "auth_outage_grace_seconds": AUTH_OUTAGE_GRACE_SECONDS,
        "registration_enabled": False,
        "features": feature_config(),
    }


def extract_bearer_token(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def token_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cached_auth(token: str) -> CachedAuth | None:
    key = token_cache_key(token)
    with _AUTH_CACHE_LOCK:
        return _AUTH_CACHE.get(key)


def cache_auth(token: str, context: AuthContext) -> None:
    key = token_cache_key(token)
    with _AUTH_CACHE_LOCK:
        _AUTH_CACHE[key] = CachedAuth(context=context, verified_at=time.monotonic())
        if len(_AUTH_CACHE) > 2000:
            cutoff = time.monotonic() - AUTH_OUTAGE_GRACE_SECONDS
            stale_keys = [
                cache_key
                for cache_key, item in _AUTH_CACHE.items()
                if item.verified_at < cutoff
            ]
            for cache_key in stale_keys:
                _AUTH_CACHE.pop(cache_key, None)


def forget_auth(token: str) -> None:
    with _AUTH_CACHE_LOCK:
        _AUTH_CACHE.pop(token_cache_key(token), None)


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        scheme, iterations, salt, expected = stored_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        int(iterations),
    ).hex()
    return hmac.compare_digest(digest, expected)


def next_user_id(db: Session) -> int:
    return int(db.query(User.id).order_by(User.id.desc()).limit(1).scalar() or 0) + 1


def ensure_local_auth_secret() -> None:
    if not LOCAL_AUTH_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="本地账号密钥未配置，请设置 LOCAL_AUTH_SECRET",
        )


def sign_local_token(user_id: int, token_type: str, expires_delta: timedelta) -> str:
    ensure_local_auth_secret()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "typ": token_type,
        "iat": now,
        "exp": now + int(expires_delta.total_seconds()),
        "nonce": secrets.token_urlsafe(12),
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(LOCAL_AUTH_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"cwlocal.{body}.{_b64url_encode(signature)}"


def parse_local_token(token: str, expected_type: str = "access") -> int:
    ensure_local_auth_secret()
    try:
        prefix, body, signature = token.split(".", 2)
        if prefix != "cwlocal":
            raise ValueError("invalid token prefix")
        expected = hmac.new(LOCAL_AUTH_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(signature), expected):
            raise ValueError("invalid token signature")
        payload = json.loads(_b64url_decode(body))
    except (ValueError, json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效，请重新登录",
        )
    if payload.get("typ") != expected_type or int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效，请重新登录",
        )
    return int(payload["sub"])


def user_context(user: User) -> AuthContext:
    return AuthContext(
        user_id=user.id,
        account_id=user.account_id or f"local-{user.id}",
        phone=user.phone,
        nickname=user.nickname or user.phone,
        avatar_url=user.avatar_url or "",
        is_admin=bool(user.is_admin),
    )


def local_auth_response(user: User) -> dict:
    access_expires_at = datetime.utcnow() + timedelta(minutes=LOCAL_ACCESS_TOKEN_MINUTES)
    refresh_expires_at = datetime.utcnow() + timedelta(days=LOCAL_REFRESH_TOKEN_DAYS)
    return {
        "ok": True,
        "user": {
            "accountId": user.account_id or f"local-{user.id}",
            "phone": user.phone,
            "displayName": user.nickname or user.phone,
            "avatarUrl": user.avatar_url or "",
            "isAdmin": bool(user.is_admin),
        },
        "session": {
            "accessToken": sign_local_token(user.id, "access", timedelta(minutes=LOCAL_ACCESS_TOKEN_MINUTES)),
            "refreshToken": sign_local_token(user.id, "refresh", timedelta(days=LOCAL_REFRESH_TOKEN_DAYS)),
            "accessExpiresAt": access_expires_at.isoformat() + "Z",
            "refreshExpiresAt": refresh_expires_at.isoformat() + "Z",
        },
    }


def local_register(db: Session, phone: str, password: str, nickname: str | None = None) -> dict:
    if AUTH_MODE != "local-password":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="本地账号未启用")
    if not LOCAL_AUTH_ALLOW_REGISTRATION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="本地账号注册已关闭")
    phone = phone.strip()
    nickname = (nickname or phone).strip()[:80]
    if len(phone) < 3 or len(phone) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号长度需为 3-20 个字符")
    if len(password) < 8 or len(password) > 128:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码长度需为 8-128 位")
    if db.query(User).filter(User.phone == phone).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="账号已存在")
    is_first_user = db.query(User.id).first() is None
    user = User(
        id=next_user_id(db),
        account_id=f"local-{secrets.token_hex(16)}",
        phone=phone,
        nickname=nickname,
        password_hash=password_hash(password),
        is_admin=is_first_user or phone in ADMIN_PHONE_NUMBERS,
        last_login_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return local_auth_response(user)


def local_login(db: Session, username: str, password: str) -> dict:
    if AUTH_MODE != "local-password":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="本地账号未启用")
    user = db.query(User).filter(User.phone == username.strip()).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return local_auth_response(user)


def local_refresh(db: Session, refresh_token: str) -> dict:
    if AUTH_MODE != "local-password":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="本地账号未启用")
    user_id = parse_local_token(refresh_token, expected_type="refresh")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")
    return local_auth_response(user)


def upsert_user_mirror(db: Session, payload: dict) -> AuthContext:
    user_payload = payload.get("user") or {}
    account_id = str(user_payload.get("accountId") or "").strip()
    legacy_user_id = int(payload.get("legacyUserId") or 0)
    phone = str(user_payload.get("phone") or "").strip()
    if not account_id or not phone:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="统一账号返回的数据不完整",
        )
    nickname = str(user_payload.get("displayName") or f"用户{phone[-4:]}").strip()[:80]
    avatar_url = str(user_payload.get("avatarUrl") or "").strip()[:500]
    is_admin = bool(payload.get("isAdmin")) or phone in ADMIN_PHONE_NUMBERS
    user = db.query(User).filter(User.account_id == account_id).first()
    if not user and legacy_user_id > 0:
        user = db.get(User, legacy_user_id)
    if not user:
        user = db.query(User).filter(User.phone == phone).first()
    if not user:
        next_id = (
            legacy_user_id
            if legacy_user_id > 0 and not db.get(User, legacy_user_id)
            else int(db.query(User.id).order_by(User.id.desc()).limit(1).scalar() or 0) + 1
        )
        user = User(id=next_id, phone=phone, nickname=nickname, is_admin=is_admin)
        db.add(user)
    phone_conflict = (
        db.query(User)
        .filter(User.phone == phone, User.id != user.id)
        .first()
    )
    if phone_conflict and phone_conflict.account_id != account_id:
        phone_conflict.phone = f"stale-account-{phone_conflict.id}"[:20]
    user.account_id = account_id
    user.phone = phone
    user.nickname = nickname
    user.avatar_url = avatar_url or None
    user.is_admin = is_admin
    user.password_hash = None
    user.last_login_at = datetime.utcnow()
    db.commit()
    return AuthContext(
        user_id=user.id,
        account_id=account_id,
        phone=phone,
        nickname=nickname,
        avatar_url=avatar_url,
        is_admin=is_admin,
    )


def no_auth_context(db: Session) -> AuthContext:
    user = db.get(User, NO_AUTH_USER_ID)
    if not user:
        user = User(
            id=NO_AUTH_USER_ID,
            phone=NO_AUTH_PHONE,
            nickname=NO_AUTH_NICKNAME,
            is_admin=NO_AUTH_ADMIN,
        )
        db.add(user)
    user.phone = NO_AUTH_PHONE
    user.nickname = NO_AUTH_NICKNAME
    user.is_admin = NO_AUTH_ADMIN
    user.account_id = user.account_id or f"local-{NO_AUTH_USER_ID}"
    user.last_login_at = datetime.utcnow()
    db.commit()
    return AuthContext(
        user_id=user.id,
        account_id=user.account_id,
        phone=user.phone,
        nickname=user.nickname or NO_AUTH_NICKNAME,
        avatar_url=user.avatar_url or "",
        is_admin=bool(user.is_admin),
    )


def verify_remote_token(db: Session, token: str) -> AuthContext:
    if AUTH_MODE != "account-v1":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="当前认证模式不支持外部账号令牌校验",
        )
    cached = cached_auth(token)
    now = time.monotonic()
    if cached and now - cached.verified_at <= AUTH_VERIFY_CACHE_SECONDS:
        return cached.context

    try:
        if not ACCOUNT_BASE_URL or not ACCOUNT_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="账号服务端地址或凭据未配置",
            )
        response = httpx.post(
            f"{ACCOUNT_BASE_URL}/introspect",
            headers={
                "X-Account-Client-Id": ACCOUNT_SERVICE_CLIENT_ID,
                "X-Account-Client-Secret": ACCOUNT_CLIENT_SECRET,
                LEGACY_CLIENT_ID_HEADER: ACCOUNT_SERVICE_CLIENT_ID,
                LEGACY_CLIENT_SECRET_HEADER: ACCOUNT_CLIENT_SECRET,
            },
            json={"token": token},
            timeout=AUTH_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as error:
        if cached and now - cached.verified_at <= AUTH_OUTAGE_GRACE_SECONDS:
            return replace(cached.context, auth_degraded=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="统一账号暂时不可用，请稍后重试",
        ) from error

    if response.status_code >= 500:
        if cached and now - cached.verified_at <= AUTH_OUTAGE_GRACE_SECONDS:
            return replace(cached.context, auth_degraded=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="统一账号暂时不可用，请稍后重试",
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="统一账号服务端校验暂时不可用",
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="统一账号返回格式异常",
        ) from error
    if (
        not payload.get("ok")
        or not payload.get("active")
        or payload.get("tokenType") != "opaque"
        or payload.get("clientId") != ACCOUNT_WEB_CLIENT_ID
    ):
        forget_auth(token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效，请使用新版账号重新登录",
        )

    context = upsert_user_mirror(db, payload)
    cache_auth(token, context)
    return context


def verify_local_access(db: Session, token: str) -> AuthContext:
    user_id = parse_local_token(token, expected_type="access")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")
    return user_context(user)


def require_access(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not auth_required():
        return no_auth_context(db)
    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    if AUTH_MODE == "local-password":
        return verify_local_access(db, token)
    return verify_remote_token(db, token)


def require_admin(auth: AuthContext = Depends(require_access)) -> AuthContext:
    if not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可操作",
        )
    return auth
