import hashlib
import ipaddress
import json
import mimetypes
import os
import secrets
import shutil
import socket
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from ..branding import APP_SYNC_USER_AGENT
from fastapi import HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import EdaAsset


EDA_STORAGE_ROOT = Path(os.getenv("EDA_STORAGE_ROOT", "./data/eda-library")).expanduser()
PERSONAL_QUOTA_BYTES = int(float(os.getenv("EDA_PERSONAL_QUOTA_GB", "5")) * 1024**3)
TEAM_QUOTA_BYTES = int(float(os.getenv("EDA_TEAM_QUOTA_GB", "20")) * 1024**3)
MIN_FREE_BYTES = int(float(os.getenv("EDA_MIN_FREE_GB", "5")) * 1024**3)
MIN_FREE_RATIO = max(0.01, min(0.5, float(os.getenv("EDA_MIN_FREE_RATIO", "0.10"))))
STAGE_TTL_HOURS = max(1, int(os.getenv("EDA_STAGE_TTL_HOURS", "24")))

TYPE_LIMITS = {
    "image": int(os.getenv("EDA_MAX_IMAGE_MB", "10")) * 1024**2,
    "table": int(os.getenv("EDA_MAX_TABLE_MB", "20")) * 1024**2,
    "datasheet": int(os.getenv("EDA_MAX_PDF_MB", "50")) * 1024**2,
    "library": int(os.getenv("EDA_MAX_LIBRARY_MB", "200")) * 1024**2,
    "model": int(os.getenv("EDA_MAX_MODEL_MB", "200")) * 1024**2,
    "project": int(os.getenv("EDA_MAX_PROJECT_MB", "200")) * 1024**2,
    "archive": int(os.getenv("EDA_MAX_ARCHIVE_MB", "512")) * 1024**2,
}

EXTENSION_TYPES = {
    ".schlib": "library",
    ".pcblib": "library",
    ".intlib": "archive",
    ".step": "model",
    ".stp": "model",
    ".pdf": "datasheet",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".csv": "table",
    ".xlsx": "table",
    ".xls": "table",
    ".zip": "archive",
    ".prjpcb": "project",
    ".schdoc": "project",
    ".pcbdoc": "project",
    ".outjob": "project",
}

OLE_EXTENSIONS = {".schlib", ".pcblib", ".schdoc", ".pcbdoc", ".xls"}
ZIP_EXTENSIONS = {".zip", ".xlsx"}


def storage_root() -> Path:
    EDA_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    return EDA_STORAGE_ROOT.resolve()


def scope_filter(query, scope_type: str, owner_user_id: int | None, team_library_id: str | None):
    query = query.filter(EdaAsset.scope_type == scope_type)
    if scope_type == "team":
        return query.filter(EdaAsset.team_library_id == team_library_id)
    return query.filter(EdaAsset.owner_user_id == owner_user_id)


def used_bytes(db: Session, scope_type: str, owner_user_id: int | None, team_library_id: str | None) -> int:
    query = scope_filter(
        db.query(EdaAsset.sha256, func.max(EdaAsset.byte_size)),
        scope_type,
        owner_user_id,
        team_library_id,
    ).filter(EdaAsset.status != "purged")
    rows = query.group_by(EdaAsset.sha256).all()
    return sum(int(size or 0) for _, size in rows)


def quota_bytes(scope_type: str) -> int:
    return TEAM_QUOTA_BYTES if scope_type == "team" else PERSONAL_QUOTA_BYTES


def validate_disk_capacity(incoming_bytes: int = 0) -> None:
    usage = shutil.disk_usage(storage_root())
    required_free = max(MIN_FREE_BYTES, int(usage.total * MIN_FREE_RATIO))
    if usage.free - incoming_bytes < required_free:
        raise HTTPException(status_code=507, detail="EDA 存储磁盘剩余空间不足，已停止上传")


def validate_quota(
    db: Session,
    scope_type: str,
    owner_user_id: int | None,
    team_library_id: str | None,
    incoming_bytes: int,
) -> None:
    current = used_bytes(db, scope_type, owner_user_id, team_library_id)
    if current + incoming_bytes > quota_bytes(scope_type):
        raise HTTPException(status_code=413, detail="EDA 存储配额不足，请清理回收站或调整配额")


def hash_already_counted(
    db: Session,
    scope_type: str,
    owner_user_id: int | None,
    team_library_id: str | None,
    sha256: str,
) -> bool:
    return (
        scope_filter(db.query(EdaAsset), scope_type, owner_user_id, team_library_id)
        .filter(EdaAsset.sha256 == sha256, EdaAsset.status != "purged")
        .first()
        is not None
    )


def detect_asset_type(filename: str) -> tuple[str, str]:
    suffix = Path(filename or "").suffix.lower()
    asset_type = EXTENSION_TYPES.get(suffix)
    if not asset_type:
        raise HTTPException(status_code=400, detail=f"不支持的 EDA 文件类型：{suffix or '无扩展名'}")
    return suffix, asset_type


def validate_signature(suffix: str, header: bytes) -> None:
    if suffix == ".pdf" and not header.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="PDF 文件头无效")
    if suffix == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="PNG 文件头无效")
    if suffix in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="JPEG 文件头无效")
    if suffix == ".webp" and not (header.startswith(b"RIFF") and header[8:12] == b"WEBP"):
        raise HTTPException(status_code=400, detail="WebP 文件头无效")
    if suffix in OLE_EXTENSIONS and not header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise HTTPException(status_code=400, detail="AD/OLE 文件头无效")
    if suffix in ZIP_EXTENSIONS and not header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        raise HTTPException(status_code=400, detail="ZIP/Office 文件头无效")
    if suffix == ".intlib" and not header.startswith(
        (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    ):
        raise HTTPException(status_code=400, detail="IntLib 文件头无效")


def stage_dir() -> Path:
    path = storage_root() / "staging"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_expired_stages() -> None:
    cutoff = datetime.utcnow() - timedelta(hours=STAGE_TTL_HOURS)
    for path in stage_dir().glob("*.json"):
        if datetime.utcfromtimestamp(path.stat().st_mtime) >= cutoff:
            continue
        token = path.stem
        path.unlink(missing_ok=True)
        (stage_dir() / f"{token}.bin").unlink(missing_ok=True)


async def stage_upload(
    db: Session,
    file: UploadFile,
    *,
    scope_type: str,
    owner_user_id: int | None,
    team_library_id: str | None,
) -> dict:
    cleanup_expired_stages()
    suffix, asset_type = detect_asset_type(file.filename or "")
    maximum = TYPE_LIMITS[asset_type]
    validate_disk_capacity()
    token = secrets.token_urlsafe(24)
    target = stage_dir() / f"{token}.bin"
    digest = hashlib.sha256()
    size = 0
    header = b""
    try:
        with open(target, "xb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if not header:
                    header = chunk[:32]
                size += len(chunk)
                if size > maximum:
                    raise HTTPException(status_code=413, detail=f"文件超过 {maximum // 1024**2}MB 上限")
                digest.update(chunk)
                output.write(chunk)
        if size <= 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
        validate_signature(suffix, header)
        quota_increment = 0 if hash_already_counted(
            db,
            scope_type,
            owner_user_id,
            team_library_id,
            digest.hexdigest(),
        ) else size
        validate_quota(db, scope_type, owner_user_id, team_library_id, quota_increment)
        validate_disk_capacity(size)
        metadata = {
            "token": token,
            "scope_type": scope_type,
            "owner_user_id": owner_user_id,
            "team_library_id": team_library_id,
            "original_name": Path(file.filename or "asset").name[:300],
            "suffix": suffix,
            "asset_type": asset_type,
            "mime_type": file.content_type or mimetypes.guess_type(file.filename or "")[0],
            "sha256": digest.hexdigest(),
            "byte_size": size,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        (stage_dir() / f"{token}.json").write_text(
            json.dumps(metadata, ensure_ascii=False),
            encoding="utf-8",
        )
        return metadata
    except Exception:
        target.unlink(missing_ok=True)
        (stage_dir() / f"{token}.json").unlink(missing_ok=True)
        raise


def consume_stage(
    token: str,
    *,
    scope_type: str,
    owner_user_id: int | None,
    team_library_id: str | None,
) -> dict:
    metadata_path = stage_dir() / f"{Path(token).name}.json"
    data_path = stage_dir() / f"{Path(token).name}.bin"
    if not metadata_path.exists() or not data_path.exists():
        raise HTTPException(status_code=404, detail="上传暂存已失效，请重新上传")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        metadata.get("scope_type") != scope_type
        or metadata.get("owner_user_id") != owner_user_id
        or metadata.get("team_library_id") != team_library_id
    ):
        raise HTTPException(status_code=403, detail="不能发布其他作用域的暂存文件")
    suffix = metadata["suffix"]
    sha256 = metadata["sha256"]
    object_dir = storage_root() / "objects" / sha256[:2]
    object_dir.mkdir(parents=True, exist_ok=True)
    existing_objects = list(object_dir.glob(f"{sha256}.*"))
    object_path = existing_objects[0] if existing_objects else object_dir / f"{sha256}{suffix}"
    if object_path.exists():
        data_path.unlink(missing_ok=True)
    else:
        os.replace(data_path, object_path)
    metadata_path.unlink(missing_ok=True)
    metadata["storage_path"] = object_path.relative_to(storage_root()).as_posix()
    return metadata


def resolve_asset_path(relative_path: str) -> Path:
    root = storage_root()
    target = (root / relative_path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=400, detail="文件路径无效")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return target


def public_http_target(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="只允许 http/https 公开地址")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        }
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="下载地址无法解析") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise HTTPException(status_code=400, detail="禁止访问本机、内网或保留地址")
    return url


async def download_public_file(url: str, maximum: int = TYPE_LIMITS["archive"]) -> tuple[bytes, str, str]:
    current = public_http_target(url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
        for _ in range(5):
            response = await client.get(current, headers={"User-Agent": APP_SYNC_USER_AGENT})
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise HTTPException(status_code=400, detail="下载重定向缺少地址")
                current = public_http_target(urljoin(current, location))
                continue
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=f"公开文件下载失败：HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > maximum:
                raise HTTPException(status_code=413, detail="下载文件为空或超过大小上限")
            name = Path(urlparse(current).path).name or "download"
            return content, name, response.headers.get("content-type", "application/octet-stream")
    raise HTTPException(status_code=400, detail="下载重定向次数过多")


async def stage_remote_download(
    db: Session,
    url: str,
    *,
    scope_type: str,
    owner_user_id: int | None,
    team_library_id: str | None,
) -> dict:
    cleanup_expired_stages()
    current = public_http_target(url)
    token = secrets.token_urlsafe(24)
    target = stage_dir() / f"{token}.bin"
    digest = hashlib.sha256()
    size = 0
    header = b""
    filename = "download"
    content_type = "application/octet-stream"
    suffix = ""
    asset_type = ""
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
            for _ in range(5):
                async with client.stream(
                    "GET",
                    current,
                    headers={"User-Agent": APP_SYNC_USER_AGENT},
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(status_code=400, detail="下载重定向缺少地址")
                        current = public_http_target(urljoin(current, location))
                        continue
                    if response.status_code != 200:
                        raise HTTPException(status_code=400, detail=f"公开文件下载失败：HTTP {response.status_code}")
                    filename = Path(urlparse(current).path).name or "download"
                    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
                    if not Path(filename).suffix:
                        inferred = {
                            "application/pdf": ".pdf",
                            "image/png": ".png",
                            "image/jpeg": ".jpg",
                            "image/webp": ".webp",
                            "application/zip": ".zip",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                        }.get(content_type)
                        if inferred:
                            filename += inferred
                    suffix, asset_type = detect_asset_type(filename)
                    maximum = TYPE_LIMITS[asset_type]
                    declared = int(response.headers.get("content-length") or 0)
                    if declared > maximum:
                        raise HTTPException(status_code=413, detail=f"远程文件超过 {maximum // 1024**2}MB 上限")
                    validate_disk_capacity(declared)
                    with open(target, "xb") as output:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            if not chunk:
                                continue
                            if not header:
                                header = chunk[:32]
                            size += len(chunk)
                            if size > maximum:
                                raise HTTPException(status_code=413, detail=f"远程文件超过 {maximum // 1024**2}MB 上限")
                            digest.update(chunk)
                            output.write(chunk)
                    break
            else:
                raise HTTPException(status_code=400, detail="下载重定向次数过多")
        if size <= 0:
            raise HTTPException(status_code=400, detail="下载文件为空")
        validate_signature(suffix, header)
        sha256 = digest.hexdigest()
        quota_increment = 0 if hash_already_counted(
            db,
            scope_type,
            owner_user_id,
            team_library_id,
            sha256,
        ) else size
        validate_quota(db, scope_type, owner_user_id, team_library_id, quota_increment)
        validate_disk_capacity(size)
        metadata = {
            "token": token,
            "scope_type": scope_type,
            "owner_user_id": owner_user_id,
            "team_library_id": team_library_id,
            "original_name": filename[:300],
            "suffix": suffix,
            "asset_type": asset_type,
            "mime_type": content_type,
            "sha256": sha256,
            "byte_size": size,
            "source_url": url,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        (stage_dir() / f"{token}.json").write_text(
            json.dumps(metadata, ensure_ascii=False),
            encoding="utf-8",
        )
        return metadata
    except Exception:
        target.unlink(missing_ok=True)
        (stage_dir() / f"{token}.json").unlink(missing_ok=True)
        raise
