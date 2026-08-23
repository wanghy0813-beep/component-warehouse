from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path, PurePosixPath

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from .database import Base, DATABASE_URL, get_db
from .models import SyncBlob, SyncChange, SyncDevice, SyncEntity, SyncTransaction
from .services.backup_service import sha256_file, sqlite_database_path
from .services.desktop_bootstrap import DesktopBootstrapError, import_desktop_bootstrap
from .services.sync_core import SYNC_CHUNK_SIZE, SYNC_TABLE_NAMES, dumps, iso_utc, loads, parse_utc, primary_key_column, utc_now


router = APIRouter(prefix="/api/desktop/v1", tags=["desktop-local"])


def _require_desktop(x_wxy_desktop_session: str | None = Header(default=None)) -> None:
    if os.getenv("DESKTOP_MODE", "0") != "1":
        raise HTTPException(status_code=404, detail="桌面本地接口未启用")
    expected = os.getenv("DESKTOP_SESSION_KEY", "")
    if not expected or x_wxy_desktop_session != expected:
        raise HTTPException(status_code=403, detail="桌面会话无效")


DesktopLocal = Depends(_require_desktop)


def _data_root() -> Path:
    configured = os.getenv("DESKTOP_DATA_ROOT", "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="桌面数据目录未配置")
    root = Path(configured).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _marker_path() -> Path:
    return _data_root() / "desktop-state.json"


def _state() -> dict:
    try:
        return json.loads(_marker_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(values: dict) -> dict:
    state = {**_state(), **values}
    temporary = _marker_path().with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, _marker_path())
    return state


def _remote_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/api/sync/v1/{path.lstrip('/')}"


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "User-Agent": "WXY-LAB-Hardware-Desktop/1.4.0"}


def _cast(column, value):
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value
    if python_type.__name__ == "datetime":
        return parse_utc(value)
    if python_type.__name__ == "date":
        from datetime import date
        return date.fromisoformat(str(value)[:10])
    if python_type.__name__ == "Decimal":
        from decimal import Decimal
        return Decimal(str(value))
    if python_type is bool:
        return bool(value)
    if python_type is int:
        return int(value)
    if python_type is float:
        return float(value)
    return str(value) if python_type is str else value


def _portable_target(table_name: str, value: str) -> tuple[Path, str]:
    relative = PurePosixPath(value.removeprefix("@data/"))
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2:
        raise HTTPException(status_code=400, detail="同步附件路径无效")
    target = (_data_root() / Path(*relative.parts)).resolve()
    root = (_data_root() / relative.parts[0]).resolve()
    if root not in target.parents:
        raise HTTPException(status_code=400, detail="同步附件路径越界")
    db_value = PurePosixPath(*relative.parts[1:]).as_posix() if table_name == "eda_assets" else str(target)
    return target, db_value


def _upload_missing_blobs(client: httpx.Client, remote_base: str, access_token: str, device_id: str, db: Session, hashes: set[str]) -> None:
    if not hashes:
        return
    response = client.post(
        _remote_url(remote_base, "blobs/probe"), headers=_headers(access_token), json={"sha256": sorted(hashes)}
    )
    response.raise_for_status()
    for digest in response.json().get("missing") or []:
        blob = db.get(SyncBlob, digest)
        if not blob or not Path(blob.storage_path).is_file():
            raise HTTPException(status_code=409, detail=f"待上传附件不存在：{digest}")
        begin = client.post(
            _remote_url(remote_base, "blobs"),
            headers=_headers(access_token),
            json={"device_id": device_id, "sha256": digest, "size_bytes": blob.size_bytes},
        )
        begin.raise_for_status()
        result = begin.json()
        if result.get("present"):
            continue
        received = set(result.get("received_chunks") or [])
        with Path(blob.storage_path).open("rb") as source:
            index = 0
            while True:
                chunk = source.read(int(result.get("chunk_size") or SYNC_CHUNK_SIZE))
                if not chunk:
                    break
                if index not in received:
                    upload = client.put(
                        _remote_url(remote_base, f"blobs/{result['upload_id']}/{index}"),
                        headers={**_headers(access_token), "Content-Type": "application/octet-stream"},
                        content=chunk,
                    )
                    upload.raise_for_status()
                index += 1
        complete = client.post(
            _remote_url(remote_base, f"blobs/{result['upload_id']}/complete"), headers=_headers(access_token)
        )
        complete.raise_for_status()


def _download_blob(client: httpx.Client, remote_base: str, access_token: str, owner_user_id: int, digest: str, db: Session) -> SyncBlob:
    existing = db.get(SyncBlob, digest)
    if existing and Path(existing.storage_path).is_file():
        return existing
    root = _data_root() / "sync-blobs" / digest[:2]
    root.mkdir(parents=True, exist_ok=True)
    target = root / digest
    temporary = target.with_suffix(".part")
    with client.stream("GET", _remote_url(remote_base, f"blobs/{digest}"), headers=_headers(access_token)) as response:
        response.raise_for_status()
        with temporary.open("wb") as output:
            for chunk in response.iter_bytes(1024 * 1024):
                output.write(chunk)
    if sha256_file(temporary) != digest:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="下载附件 SHA256 校验失败")
    os.replace(temporary, target)
    blob = SyncBlob(
        sha256=digest,
        owner_user_id=owner_user_id,
        size_bytes=target.stat().st_size,
        storage_path=str(target),
        reference_count=0,
    )
    db.merge(blob)
    db.flush()
    return blob


def _apply_remote_change(db: Session, owner_user_id: int, change: dict, blobs: dict[str, SyncBlob]) -> None:
    table_name = str(change.get("entity_type") or "")
    if table_name not in SYNC_TABLE_NAMES or table_name in {"users", "categories"}:
        return
    table = Base.metadata.tables[table_name]
    primary = primary_key_column(table)
    entity_uid = str(change["entity_uid"])
    entity = db.get(SyncEntity, entity_uid)
    operation = str(change.get("operation") or "upsert")
    if operation == "delete":
        if entity:
            db.connection().execute(delete(table).where(primary == _cast(primary, entity.local_id)))
            entity.tombstone = True
            entity.deleted_at = utc_now()
            entity.version = int(change.get("version") or entity.version)
        return
    raw_fields = dict(change.get("fields") or {})
    inventory_delta = int(raw_fields.pop("__inventory_delta__", 0) or 0)
    fields = {name: _cast(table.c[name], value) for name, value in raw_fields.items() if name in table.c and name != primary.name}
    if inventory_delta:
        if table_name != "components" or not entity:
            raise HTTPException(status_code=409, detail="库存增量变更缺少本地器件基线")
        current_quantity = db.connection().execute(
            select(table.c.quantity).where(primary == _cast(primary, entity.local_id))
        ).scalar_one_or_none()
        merged_quantity = int(current_quantity or 0) + inventory_delta
        if merged_quantity < 0:
            raise HTTPException(status_code=409, detail="库存不足，服务器事务需要人工处理")
        fields["quantity"] = merged_quantity
    for field, ref_uid in (change.get("refs") or {}).items():
        reference = db.get(SyncEntity, str(ref_uid))
        if not reference or reference.tombstone:
            raise HTTPException(status_code=409, detail=f"服务器变更依赖尚未到达：{field}")
        if field in table.c:
            fields[field] = _cast(table.c[field], reference.local_id)
    if "owner_user_id" in table.c:
        fields["owner_user_id"] = owner_user_id
    if "scope_type" in table.c:
        fields["scope_type"] = "personal"
    portable = str((change.get("fields") or {}).get("storage_path") or "")
    attachments = [str(value) for value in change.get("attachments") or []]
    if portable.startswith("@data/"):
        target, db_value = _portable_target(table_name, portable)
        fields["storage_path"] = db_value
        if attachments:
            blob = blobs[attachments[0]]
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".sync-part")
            shutil.copyfile(blob.storage_path, temporary)
            if sha256_file(temporary) != attachments[0]:
                temporary.unlink(missing_ok=True)
                raise HTTPException(status_code=409, detail="附件写入校验失败")
            os.replace(temporary, target)
    if entity:
        db.connection().execute(update(table).where(primary == _cast(primary, entity.local_id)).values(**fields))
        entity.version = int(change.get("version") or entity.version)
        entity.field_times_json = dumps({**loads(entity.field_times_json, {}), **(change.get("field_times") or {})})
        entity.tombstone = False
        entity.deleted_at = None
    else:
        if primary.autoincrement is not True or getattr(primary.type, "python_type", None) is str:
            fields[primary.name] = _cast(primary, change.get("local_id") or entity_uid)
        result = db.connection().execute(insert(table).values(**fields))
        db.add(
            SyncEntity(
                entity_uid=entity_uid,
                owner_user_id=owner_user_id,
                entity_type=table_name,
                local_id=str(result.inserted_primary_key[0]),
                version=int(change.get("version") or 1),
                field_times_json=dumps(change.get("field_times") or {}),
                tombstone=False,
            )
        )


@router.get("/state")
def desktop_state(_: None = DesktopLocal, db: Session = Depends(get_db)):
    marker = _state()
    pending = db.query(SyncTransaction).filter(SyncTransaction.status == "pending_upload").count()
    conflicts = db.query(SyncTransaction).filter(SyncTransaction.status == "conflict").count()
    return {
        "desktop": True,
        "bootstrap_complete": bool(marker.get("server_instance_id")),
        "device_id": marker.get("device_id"),
        "cursor": int(marker.get("cursor") or 0),
        "pending_upload": pending,
        "conflicts": conflicts,
        "last_success_at": marker.get("last_success_at"),
        "last_error": marker.get("last_error"),
    }


@router.post("/bootstrap/import")
def import_bootstrap(payload: dict, _: None = DesktopLocal):
    package_path = Path(str(payload.get("path") or "")).resolve()
    staging_root = (_data_root() / "staging").resolve()
    if staging_root not in package_path.parents or not package_path.is_file():
        raise HTTPException(status_code=400, detail="首次数据包必须位于桌面暂存目录")
    database_path = sqlite_database_path(DATABASE_URL)
    if not database_path:
        raise HTTPException(status_code=503, detail="桌面数据库路径无效")
    try:
        result = import_desktop_bootstrap(
            package_path,
            database_path=database_path,
            data_root=_data_root(),
            marker_path=_marker_path(),
        )
    except DesktopBootstrapError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if payload.get("device_id"):
        result = _write_state({**result, "device_id": str(payload["device_id"])})
    return {"imported": True, **result}


@router.post("/sync-now")
def sync_now(payload: dict, _: None = DesktopLocal, db: Session = Depends(get_db)):
    remote_base = str(payload.get("remote_base") or "").strip()
    access_token = str(payload.get("access_token") or "").strip()
    device_id = str(payload.get("device_id") or _state().get("device_id") or "")
    if not remote_base.startswith("https://") or not access_token or not device_id:
        raise HTTPException(status_code=400, detail="桌面同步参数不完整")
    state = _state()
    owner_user_id = int(state.get("owner_user_id") or 0)
    pending = db.query(SyncTransaction).filter(SyncTransaction.status == "pending_upload").order_by(
        SyncTransaction.server_received_at.asc()
    ).limit(100).all()
    transaction_payloads = []
    attachment_hashes: set[str] = set()
    for transaction in pending:
        rows = db.query(SyncChange).filter(SyncChange.transaction_id == transaction.id).order_by(SyncChange.cursor.asc()).all()
        changes = []
        for row in rows:
            attachments = loads(row.attachments_json, [])
            attachment_hashes.update(attachments)
            changes.append(
                {
                    "entity_uid": row.entity_uid,
                    "entity_type": row.entity_type,
                    "operation": row.operation,
                    "base_version": max(0, int(row.version or 1) - 1),
                    "fields": loads(row.fields_json, {}),
                    "refs": loads(row.refs_json, {}),
                    "field_times": loads(row.field_times_json, {}),
                    "attachments": attachments,
                    "occurred_at": iso_utc(row.occurred_at),
                }
            )
        transaction_payloads.append(
            {
                "transaction_id": transaction.id,
                "event_id": transaction.event_id,
                "base_cursor": transaction.base_cursor,
                "created_at": iso_utc(transaction.client_created_at or transaction.server_received_at),
                "changes": changes,
            }
        )
    try:
        with httpx.Client(timeout=httpx.Timeout(60, read=300)) as client:
            _upload_missing_blobs(client, remote_base, access_token, device_id, db, attachment_hashes)
            if transaction_payloads:
                response = client.post(
                    _remote_url(remote_base, "push"),
                    headers=_headers(access_token),
                    json={"device_id": device_id, "client_time": iso_utc(), "transactions": transaction_payloads},
                )
                response.raise_for_status()
                by_event = {item["event_id"]: item for item in response.json().get("items") or []}
                for transaction in pending:
                    result = by_event.get(transaction.event_id) or {}
                    transaction.status = "synced" if result.get("status") == "accepted" else str(result.get("status") or "pending_upload")
                db.commit()
            cursor = int(state.get("cursor") or 0)
            pulled = 0
            while True:
                response = client.get(
                    _remote_url(remote_base, "pull"),
                    headers=_headers(access_token),
                    params={"device_id": device_id, "after": cursor, "limit": 500},
                )
                response.raise_for_status()
                page = response.json()
                items = page.get("items") or []
                blobs: dict[str, SyncBlob] = {}
                for item in items:
                    for digest in item.get("attachments") or []:
                        blobs[digest] = _download_blob(client, remote_base, access_token, owner_user_id, digest, db)
                db.info["sync_apply"] = True
                try:
                    for item in items:
                        if item.get("device_id") != device_id:
                            _apply_remote_change(db, owner_user_id, item, blobs)
                        cursor = max(cursor, int(item.get("cursor") or 0))
                        pulled += 1
                    db.commit()
                finally:
                    db.info.pop("sync_apply", None)
                if not page.get("has_more"):
                    break
            _write_state({"device_id": device_id, "cursor": cursor, "last_success_at": iso_utc(), "last_error": None})
            return {"synced": True, "uploaded": len(transaction_payloads), "downloaded": pulled, "cursor": cursor}
    except (httpx.HTTPError, OSError) as error:
        db.rollback()
        _write_state({"last_error": str(error)[:500]})
        raise HTTPException(status_code=503, detail="在线服务暂时不可用，本地改动已保留") from error
