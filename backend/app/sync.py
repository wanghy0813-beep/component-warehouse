from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import shutil
import tempfile
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from .auth import AuthContext, ACCOUNT_DESKTOP_CLIENT_ID, require_sync_read, require_sync_write
from .database import Base, DATABASE_URL, get_db
from .models import SyncBlob, SyncBlobUpload, SyncChange, SyncConflict, SyncDevice, SyncEntity, SyncTransaction
from .services.backup_service import sha256_file, sqlite_database_path
from .services.sync_bootstrap import FILE_TABLES, _portable_storage_path, create_personal_bootstrap
from .services.sync_core import (
    CONFLICT_WINDOW_SECONDS,
    SYNC_CHUNK_SIZE,
    SYNC_TABLE_NAMES,
    dumps,
    iso_utc,
    json_value,
    loads,
    parse_utc,
    primary_key_column,
    safe_fields,
    stable_entity_uid,
    utc_now,
)


router = APIRouter(prefix="/api/sync/v1", tags=["desktop-sync"])
SyncRead = Depends(require_sync_read)
SyncWrite = Depends(require_sync_write)
MAX_PUSH_TRANSACTIONS = 100
MAX_CHANGES_PER_TRANSACTION = 500
SYNC_MAX_CLOCK_DRIFT_MS = 5 * 60 * 1000


def _enabled(auth: AuthContext) -> None:
    if os.getenv("SYNC_ENABLED", "0") != "1":
        raise HTTPException(status_code=503, detail="桌面同步尚未启用")
    allowed = {item.strip() for item in os.getenv("SYNC_ALLOWED_ACCOUNT_IDS", "").split(",") if item.strip()}
    if allowed and str(auth.user_id) not in allowed and auth.account_id not in allowed:
        raise HTTPException(status_code=403, detail="当前账号尚未加入桌面同步灰度")


def _device(db: Session, auth: AuthContext, device_id: str) -> SyncDevice:
    row = db.get(SyncDevice, device_id)
    if not row or row.owner_user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="桌面设备不存在")
    if row.status != "active":
        raise HTTPException(status_code=403, detail="桌面设备已解绑")
    return row


def _cursor(db: Session, owner_user_id: int) -> int:
    return int(
        db.query(SyncChange.cursor)
        .filter(SyncChange.owner_user_id == owner_user_id)
        .order_by(SyncChange.cursor.desc())
        .limit(1)
        .scalar()
        or 0
    )


def _server_instance_id() -> str:
    db_path = sqlite_database_path(DATABASE_URL)
    if not db_path:
        return ""
    path = db_path.parent / ".server-instance-id"
    value = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not value:
        value = secrets.token_hex(16)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(value, encoding="utf-8")
        os.replace(temporary, path)
    return value


def _payload_sha(payload: dict) -> str:
    return hashlib.sha256(dumps(payload).encode("utf-8")).hexdigest()


def _cast(column, value):
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value
    if python_type is datetime:
        return parse_utc(value)
    if python_type is date:
        return date.fromisoformat(str(value)[:10])
    if python_type is Decimal:
        return Decimal(str(value))
    if python_type is bool:
        return bool(value)
    if python_type is int:
        return int(value)
    if python_type is float:
        return float(value)
    return str(value) if python_type is str else value


def _entity(db: Session, auth: AuthContext, uid: str) -> SyncEntity | None:
    row = db.get(SyncEntity, uid)
    if row and row.owner_user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="同步实体不存在")
    return row


def _mapped_entity_uid(db: Session, owner_user_id: int, entity_type: str, local_id) -> str:
    row = db.query(SyncEntity.entity_uid).filter(
        SyncEntity.owner_user_id == owner_user_id,
        SyncEntity.entity_type == entity_type,
        SyncEntity.local_id == str(local_id),
    ).scalar()
    return str(row) if row else stable_entity_uid(owner_user_id, entity_type, local_id)


def _resolved_fields(
    db: Session,
    auth: AuthContext,
    table,
    fields: dict,
    refs: dict,
    *,
    pending_entity_uids: set[str] | None = None,
) -> dict:
    values = {name: _cast(table.c[name], value) for name, value in safe_fields(table, fields).items()}
    for field, entity_uid in refs.items():
        if field not in table.c:
            continue
        reference = _entity(db, auth, str(entity_uid))
        if not reference or reference.tombstone:
            if pending_entity_uids and str(entity_uid) in pending_entity_uids:
                continue
            raise HTTPException(status_code=409, detail=f"同步依赖尚未到达：{field}")
        values[field] = _cast(table.c[field], reference.local_id)
    if "owner_user_id" in table.c:
        values["owner_user_id"] = auth.user_id
    if "scope_type" in table.c:
        values["scope_type"] = "personal"
    if "team_library_id" in table.c:
        values["team_library_id"] = None
    if "created_by_user_id" in table.c and not values.get("created_by_user_id"):
        values["created_by_user_id"] = auth.user_id
    return values


def _portable_storage_target(table_name: str, value: str) -> tuple[Path, str]:
    if not value.startswith("@data/"):
        return Path(value), value
    relative = PurePosixPath(value.removeprefix("@data/"))
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2:
        raise HTTPException(status_code=400, detail="同步附件目标路径无效")
    db_path = sqlite_database_path(DATABASE_URL)
    if not db_path:
        raise HTTPException(status_code=503, detail="同步附件需要 SQLite 数据目录")
    target = (db_path.parent / Path(*relative.parts)).resolve()
    root = (db_path.parent / relative.parts[0]).resolve()
    if root not in target.parents:
        raise HTTPException(status_code=400, detail="同步附件目标路径越界")
    if table_name == "eda_assets":
        database_value = PurePosixPath(*relative.parts[1:]).as_posix()
    else:
        database_value = str(target)
    return target, database_value


def _conflict(
    db: Session,
    auth: AuthContext,
    device: SyncDevice,
    transaction: SyncTransaction,
    change: dict,
    *,
    reason: str,
    fields: list[str],
    server: dict,
) -> SyncConflict:
    row = SyncConflict(
        id=str(uuid.uuid4()),
        owner_user_id=auth.user_id,
        device_id=device.id,
        transaction_id=transaction.id,
        entity_uid=str(change.get("entity_uid") or "") or None,
        entity_type=str(change.get("entity_type") or "") or None,
        reason=reason,
        conflict_fields_json=dumps(fields),
        server_version_json=dumps(server),
        client_version_json=dumps(change),
        dependencies_json=dumps(change.get("dependencies") or []),
        status="open",
    )
    db.add(row)
    return row


def _preflight_change(
    db: Session,
    auth: AuthContext,
    device: SyncDevice,
    transaction: SyncTransaction,
    change: dict,
    *,
    abnormal_clock: bool,
    pending_entity_uids: set[str],
    inventory_delta_targets: dict[str, int],
    inventory_absolute_targets: set[str],
) -> tuple[dict | None, SyncConflict | None]:
    entity_type = str(change.get("entity_type") or "")
    if entity_type not in SYNC_TABLE_NAMES or entity_type in {"users", "categories"}:
        raise HTTPException(status_code=400, detail=f"不允许同步实体：{entity_type}")
    table = Base.metadata.tables[entity_type]
    entity_uid = str(change.get("entity_uid") or "")
    if not entity_uid:
        raise HTTPException(status_code=400, detail="同步实体缺少 entity_uid")
    entity = _entity(db, auth, entity_uid)
    operation = str(change.get("operation") or "upsert")
    if operation not in {"upsert", "delete"}:
        raise HTTPException(status_code=400, detail="同步操作无效")
    base_version = max(0, int(change.get("base_version") or 0))
    concurrent = bool(entity and int(entity.version or 0) > base_version)
    if operation == "delete" and concurrent:
        return None, _conflict(
            db, auth, device, transaction, change,
            reason="delete_vs_modify", fields=[], server={"version": entity.version, "tombstone": entity.tombstone},
        )
    fields = safe_fields(table, dict(change.get("fields") or {}))
    refs = dict(change.get("refs") or {})
    apply_fields = dict(fields)
    if entity_type == "components" and entity_uid in inventory_delta_targets and entity:
        apply_fields.pop("quantity", None)
    if entity_type == "components" and entity_uid in inventory_absolute_targets and concurrent:
        return None, _conflict(
            db, auth, device, transaction, change,
            reason="absolute_inventory", fields=["quantity"],
            server={"version": entity.version, "field_times": loads(entity.field_times_json, {})},
        )
    if entity_type == "inventory_lots" and concurrent and "remaining_quantity" in apply_fields:
        return None, _conflict(
            db, auth, device, transaction, change,
            reason="inventory_lot_version", fields=["remaining_quantity"],
            server={"version": entity.version, "field_times": loads(entity.field_times_json, {})},
        )
    if concurrent:
        server_times = loads(entity.field_times_json, {})
        client_times = dict(change.get("field_times") or {})
        conflicts: list[str] = []
        for field in list(apply_fields):
            server_time_raw = server_times.get(field)
            if not server_time_raw:
                continue
            if abnormal_clock:
                conflicts.append(field)
                continue
            server_time = parse_utc(server_time_raw)
            client_time = parse_utc(client_times.get(field) or change.get("occurred_at"))
            difference = abs((client_time - server_time).total_seconds())
            if difference <= CONFLICT_WINDOW_SECONDS:
                conflicts.append(field)
            elif server_time > client_time:
                apply_fields.pop(field, None)
        if conflicts:
            return None, _conflict(
                db, auth, device, transaction, change,
                reason="clock_drift" if abnormal_clock else "same_field_window",
                fields=conflicts,
                server={"version": entity.version, "field_times": server_times},
            )
    attachment_hashes = [str(value).lower() for value in change.get("attachments") or []]
    missing = [value for value in attachment_hashes if not db.get(SyncBlob, value)]
    if missing:
        raise HTTPException(status_code=409, detail={"code": "missing_blobs", "sha256": missing})
    values = _resolved_fields(
        db, auth, table, apply_fields, refs, pending_entity_uids=pending_entity_uids
    )
    portable_storage = str(apply_fields.get("storage_path") or "")
    if portable_storage.startswith("@data/"):
        target, database_value = _portable_storage_target(entity_type, portable_storage)
        values["storage_path"] = database_value
    else:
        target = None
    previous_attachment = None
    if entity and "sha256" in table.c:
        primary = primary_key_column(table)
        previous_attachment = db.connection().execute(
            select(table.c.sha256).where(primary == _cast(primary, entity.local_id))
        ).scalar_one_or_none()
    return {
        "change": change,
        "table": table,
        "entity": entity,
        "entity_uid": entity_uid,
        "operation": operation,
        "values": values,
        "apply_fields": apply_fields,
        "refs": refs,
        "base_version": base_version,
        "field_times": dict(change.get("field_times") or {}),
        "attachments": attachment_hashes,
        "attachment_target": target,
        "previous_attachment": str(previous_attachment or "").lower() or None,
    }, None


def _inventory_semantics(db: Session, auth: AuthContext, changes: list[dict]) -> tuple[dict[str, int], set[str]]:
    """Return component deltas and absolute-adjustment targets for new stock events."""
    deltas: dict[str, int] = {}
    absolute: set[str] = set()
    component_changes = {
        str(change.get("entity_uid")): change
        for change in changes
        if change.get("entity_type") == "components" and change.get("operation", "upsert") == "upsert"
    }
    for change in changes:
        if change.get("entity_type") != "stock_movements_v2" or change.get("operation", "upsert") != "upsert":
            continue
        movement_uid = str(change.get("entity_uid") or "")
        if movement_uid and _entity(db, auth, movement_uid):
            continue
        fields = dict(change.get("fields") or {})
        refs = dict(change.get("refs") or {})
        component_uid = str(refs.get("component_id") or "")
        if not component_uid or component_uid not in component_changes:
            raise HTTPException(status_code=400, detail="库存流水必须与对应器件变更同事务提交")
        movement_type = str(fields.get("movement_type") or "")
        if movement_type == "manual_adjustment":
            absolute.add(component_uid)
            continue
        # Component creation already carries its initial absolute quantity.
        if movement_type == "component_create" or not _entity(db, auth, component_uid):
            continue
        deltas[component_uid] = deltas.get(component_uid, 0) + int(fields.get("quantity_delta") or 0)
    return deltas, absolute


def _ordered_plans(db: Session, auth: AuthContext, plans: list[dict]) -> list[dict]:
    """Topologically order new rows so parent/child business transactions stay atomic."""
    remaining = list(plans)
    ordered: list[dict] = []
    completed = {plan["entity_uid"] for plan in plans if plan["entity"] is not None}
    while remaining:
        progressed = False
        for plan in list(remaining):
            dependencies = {str(value) for value in plan["refs"].values() if value}
            if all(uid in completed or _entity(db, auth, uid) for uid in dependencies):
                ordered.append(plan)
                completed.add(plan["entity_uid"])
                remaining.remove(plan)
                progressed = True
        if not progressed:
            raise HTTPException(status_code=409, detail="同步事务存在缺失或循环依赖")
    return ordered


def _apply_transaction(
    db: Session,
    auth: AuthContext,
    device: SyncDevice,
    payload: dict,
    *,
    request_drift_ms: int,
) -> dict:
    event_id = str(payload.get("event_id") or "").strip()
    if not event_id or len(event_id) > 120:
        raise HTTPException(status_code=400, detail="事务 event_id 无效")
    existing = db.query(SyncTransaction).filter(
        SyncTransaction.owner_user_id == auth.user_id,
        SyncTransaction.event_id == event_id,
    ).first()
    if existing:
        return {"event_id": event_id, "status": existing.status, "idempotent": True}
    changes = list(payload.get("changes") or [])
    if not changes or len(changes) > MAX_CHANGES_PER_TRANSACTION:
        raise HTTPException(status_code=400, detail="同步事务变更数量无效")
    client_created = parse_utc(payload.get("created_at"))
    drift_ms = int(request_drift_ms)
    abnormal_clock = abs(drift_ms) > SYNC_MAX_CLOCK_DRIFT_MS
    transaction = SyncTransaction(
        id=str(payload.get("transaction_id") or uuid.uuid4()),
        event_id=event_id,
        owner_user_id=auth.user_id,
        device_id=device.id,
        base_cursor=max(0, int(payload.get("base_cursor") or 0)),
        client_created_at=client_created,
        status="pending",
        payload_sha256=_payload_sha(payload),
    )
    db.add(transaction)
    db.flush()
    normalized_changes = [dict(change) for change in changes]
    pending_entity_uids = {str(change.get("entity_uid") or "") for change in normalized_changes}
    inventory_delta_targets, inventory_absolute_targets = _inventory_semantics(db, auth, normalized_changes)
    plans: list[dict] = []
    conflicts: list[SyncConflict] = []
    for change in normalized_changes:
        plan, conflict = _preflight_change(
            db,
            auth,
            device,
            transaction,
            change,
            abnormal_clock=abnormal_clock,
            pending_entity_uids=pending_entity_uids,
            inventory_delta_targets=inventory_delta_targets,
            inventory_absolute_targets=inventory_absolute_targets,
        )
        if conflict:
            conflicts.append(conflict)
        elif plan:
            plans.append(plan)
    if conflicts:
        transaction.status = "conflict"
        device.last_clock_offset_ms = drift_ms
        db.commit()
        return {
            "event_id": event_id,
            "status": "conflict",
            "conflict_ids": [row.id for row in conflicts],
            "clock_offset_ms": drift_ms,
        }

    for component_uid, delta in inventory_delta_targets.items():
        entity = _entity(db, auth, component_uid)
        if not entity or entity.entity_type != "components" or entity.tombstone:
            raise HTTPException(status_code=409, detail="库存流水引用的器件不存在")
        component_table = Base.metadata.tables["components"]
        primary = primary_key_column(component_table)
        current_quantity = db.connection().execute(
            select(component_table.c.quantity).where(primary == _cast(primary, entity.local_id))
        ).scalar_one_or_none()
        if current_quantity is None or int(current_quantity or 0) + delta < 0:
            raise HTTPException(status_code=409, detail="库存不足，同步事务已冻结")

    plans = _ordered_plans(db, auth, plans)

    db.info["sync_apply"] = True
    connection = db.connection()
    try:
        for index, plan in enumerate(plans):
            table = plan["table"]
            primary = primary_key_column(table)
            entity = plan["entity"]
            plan["values"] = _resolved_fields(db, auth, table, plan["apply_fields"], plan["refs"])
            if plan.get("attachment_target"):
                portable_storage = str(plan["apply_fields"].get("storage_path") or "")
                if portable_storage.startswith("@data/"):
                    _, plan["values"]["storage_path"] = _portable_storage_target(table.name, portable_storage)
            if plan.get("attachment_target") and plan["attachments"]:
                blob = db.get(SyncBlob, plan["attachments"][0])
                target = plan["attachment_target"]
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".sync-part")
                shutil.copyfile(blob.storage_path, temporary)
                if sha256_file(temporary) != blob.sha256:
                    temporary.unlink(missing_ok=True)
                    raise HTTPException(status_code=409, detail="同步附件落盘校验失败")
                os.replace(temporary, target)
            if plan["operation"] == "delete":
                if entity:
                    connection.execute(delete(table).where(primary == _cast(primary, entity.local_id)))
                    entity.tombstone = True
                    entity.deleted_at = utc_now()
                    entity.version = int(entity.version or 0) + 1
                version = int(entity.version if entity else 1)
            else:
                values = plan["values"]
                if entity:
                    if table.name == "components" and plan["entity_uid"] in inventory_delta_targets:
                        current_quantity = connection.execute(
                            select(table.c.quantity).where(primary == _cast(primary, entity.local_id))
                        ).scalar_one()
                        values["quantity"] = int(current_quantity or 0) + inventory_delta_targets[plan["entity_uid"]]
                    connection.execute(
                        update(table).where(primary == _cast(primary, entity.local_id)).values(**values)
                    )
                    entity.version = int(entity.version or 0) + 1
                    entity.tombstone = False
                    entity.deleted_at = None
                    local_id = entity.local_id
                else:
                    if primary.autoincrement is not True or getattr(primary.type, "python_type", None) is str:
                        values[primary.name] = _cast(primary, plan["change"].get("local_id") or plan["entity_uid"])
                    result = connection.execute(insert(table).values(**values))
                    local_id = str(result.inserted_primary_key[0])
                    entity = SyncEntity(
                        entity_uid=plan["entity_uid"],
                        owner_user_id=auth.user_id,
                        entity_type=table.name,
                        local_id=local_id,
                        version=1,
                        field_times_json="{}",
                        tombstone=False,
                    )
                    db.add(entity)
                field_times = loads(entity.field_times_json, {})
                field_times.update(plan["field_times"])
                fallback_time = str(plan["change"].get("occurred_at") or iso_utc())
                for field in plan["values"]:
                    field_times.setdefault(field, fallback_time)
                entity.field_times_json = dumps(field_times)
                entity.updated_at = utc_now()
                version = int(entity.version or 1)
            previous_attachment = plan.get("previous_attachment")
            current_attachment = plan["attachments"][0] if plan["attachments"] else None
            if previous_attachment and (plan["operation"] == "delete" or current_attachment != previous_attachment):
                previous_blob = db.get(SyncBlob, previous_attachment)
                if previous_blob:
                    previous_blob.reference_count = max(0, int(previous_blob.reference_count or 0) - 1)
                    previous_blob.last_referenced_at = utc_now()
            if current_attachment and current_attachment != previous_attachment:
                current_blob = db.get(SyncBlob, current_attachment)
                if current_blob:
                    current_blob.reference_count = int(current_blob.reference_count or 0) + 1
                    current_blob.last_referenced_at = utc_now()
            output_fields = {key: json_value(value) for key, value in plan["values"].items()}
            if table.name == "components" and plan["entity_uid"] in inventory_delta_targets:
                output_fields.pop("quantity", None)
                output_fields["__inventory_delta__"] = inventory_delta_targets[plan["entity_uid"]]
            db.add(
                SyncChange(
                    transaction_id=transaction.id,
                    event_id=f"{event_id}:{index}",
                    owner_user_id=auth.user_id,
                    device_id=device.id,
                    entity_uid=plan["entity_uid"],
                    entity_type=table.name,
                    operation=plan["operation"],
                    version=version,
                    fields_json=dumps(output_fields),
                    refs_json=dumps(plan["change"].get("refs") or {}),
                    field_times_json=dumps(plan["field_times"]),
                    attachments_json=dumps(plan["attachments"]),
                    occurred_at=parse_utc(plan["change"].get("occurred_at")),
                )
            )
        transaction.status = "accepted"
        device.last_clock_offset_ms = drift_ms
        device.last_sync_at = utc_now()
        db.commit()
    finally:
        db.info.pop("sync_apply", None)
    return {"event_id": event_id, "status": "accepted", "clock_offset_ms": drift_ms}


@router.post("/devices")
def register_device(payload: dict, auth: AuthContext = SyncWrite, db: Session = Depends(get_db)):
    _enabled(auth)
    installation_id = str(payload.get("installation_id") or "").strip()
    if len(installation_id) < 16 or len(installation_id) > 200:
        raise HTTPException(status_code=400, detail="installation_id 无效")
    digest = hashlib.sha256(f"{_server_instance_id()}:{installation_id}".encode("utf-8")).hexdigest()
    row = db.query(SyncDevice).filter(
        SyncDevice.owner_user_id == auth.user_id,
        SyncDevice.client_id == ACCOUNT_DESKTOP_CLIENT_ID,
        SyncDevice.installation_id_hash == digest,
    ).first()
    if not row:
        row = SyncDevice(
            id=str(uuid.uuid4()),
            owner_user_id=auth.user_id,
            client_id=ACCOUNT_DESKTOP_CLIENT_ID,
            installation_id_hash=digest,
            installation_hint=installation_id[-8:],
            name=str(payload.get("name") or "WXY LAB Hardware Windows")[:120],
            platform=str(payload.get("platform") or "windows-x64")[:80],
            status="active",
        )
        db.add(row)
    else:
        row.name = str(payload.get("name") or row.name)[:120]
        row.status = "active"
    db.commit()
    return {
        "device_id": row.id,
        "status": row.status,
        "server_time": iso_utc(),
        "server_instance_id": _server_instance_id(),
        "cursor": _cursor(db, auth.user_id),
    }


@router.get("/bootstrap")
def bootstrap(
    device_id: str,
    auth: AuthContext = SyncRead,
    db: Session = Depends(get_db),
):
    _enabled(auth)
    device = _device(db, auth, device_id)
    db_path = sqlite_database_path(DATABASE_URL)
    if not db_path:
        raise HTTPException(status_code=503, detail="首次同步只支持 SQLite 服务")
    path = create_personal_bootstrap(
        db,
        owner_user_id=auth.user_id,
        data_root=db_path.parent,
        server_instance_id=_server_instance_id(),
        cursor=_cursor(db, auth.user_id),
        output_dir=db_path.parent / "backups",
    )
    device.last_sync_at = utc_now()
    db.commit()
    return FileResponse(
        path,
        filename=f"wxy-lab-hardware-personal-bootstrap-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip",
        media_type="application/zip",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.post("/push")
def push(payload: dict, auth: AuthContext = SyncWrite, db: Session = Depends(get_db)):
    _enabled(auth)
    device = _device(db, auth, str(payload.get("device_id") or ""))
    transactions = list(payload.get("transactions") or [])
    if len(transactions) > MAX_PUSH_TRANSACTIONS:
        raise HTTPException(status_code=400, detail="单次推送事务过多")
    request_drift_ms = int((utc_now() - parse_utc(payload.get("client_time") or iso_utc())).total_seconds() * 1000)
    results = [
        _apply_transaction(db, auth, device, dict(item), request_drift_ms=request_drift_ms)
        for item in transactions
    ]
    return {"items": results, "cursor": _cursor(db, auth.user_id), "server_time": iso_utc()}


@router.delete("/devices/{device_id}")
def unbind_device(device_id: str, auth: AuthContext = SyncWrite, db: Session = Depends(get_db)):
    _enabled(auth)
    device = _device(db, auth, device_id)
    device.status = "revoked"
    device.last_sync_at = utc_now()
    db.commit()
    return {"revoked": True, "device_id": device.id}


@router.get("/pull")
def pull(
    device_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    auth: AuthContext = SyncRead,
    db: Session = Depends(get_db),
):
    _enabled(auth)
    device = _device(db, auth, device_id)
    rows = db.query(SyncChange).filter(
        SyncChange.owner_user_id == auth.user_id,
        SyncChange.cursor > after,
    ).order_by(SyncChange.cursor.asc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "cursor": row.cursor,
            "transaction_id": row.transaction_id,
            "event_id": row.event_id,
            "device_id": row.device_id,
            "entity_uid": row.entity_uid,
            "entity_type": row.entity_type,
            "operation": row.operation,
            "version": row.version,
            "fields": loads(row.fields_json, {}),
            "refs": loads(row.refs_json, {}),
            "field_times": loads(row.field_times_json, {}),
            "attachments": loads(row.attachments_json, []),
            "occurred_at": iso_utc(row.occurred_at),
        }
        for row in rows
    ]
    next_cursor = int(rows[-1].cursor if rows else after)
    device.last_cursor = max(device.last_cursor, next_cursor)
    device.last_sync_at = utc_now()
    db.commit()
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "server_time": iso_utc(),
    }


@router.get("/status")
def status(device_id: str, auth: AuthContext = SyncRead, db: Session = Depends(get_db)):
    _enabled(auth)
    device = _device(db, auth, device_id)
    conflicts = db.query(SyncConflict).filter(
        SyncConflict.owner_user_id == auth.user_id,
        SyncConflict.status == "open",
    ).count()
    latest = _cursor(db, auth.user_id)
    return {
        "device_id": device.id,
        "device_status": device.status,
        "device_cursor": device.last_cursor,
        "server_cursor": latest,
        "pending_download": max(0, latest - int(device.last_cursor or 0)),
        "conflicts": conflicts,
        "clock_offset_ms": device.last_clock_offset_ms,
        "clock_abnormal": abs(device.last_clock_offset_ms) > SYNC_MAX_CLOCK_DRIFT_MS,
        "last_success_at": iso_utc(device.last_sync_at) if device.last_sync_at else None,
        "server_time": iso_utc(),
    }


@router.get("/conflicts")
def list_conflicts(
    status: str = Query("open"),
    auth: AuthContext = SyncRead,
    db: Session = Depends(get_db),
):
    _enabled(auth)
    rows = db.query(SyncConflict).filter(
        SyncConflict.owner_user_id == auth.user_id,
        SyncConflict.status == status,
    ).order_by(SyncConflict.created_at.desc()).limit(500).all()
    return {
        "items": [
            {
                "id": row.id,
                "transaction_id": row.transaction_id,
                "entity_uid": row.entity_uid,
                "entity_type": row.entity_type,
                "reason": row.reason,
                "conflict_fields": loads(row.conflict_fields_json, []),
                "server_version": loads(row.server_version_json, {}),
                "client_version": loads(row.client_version_json, {}),
                "dependencies": loads(row.dependencies_json, []),
                "status": row.status,
                "resolution": row.resolution,
                "created_at": iso_utc(row.created_at),
            }
            for row in rows
        ]
    }


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: str,
    payload: dict,
    auth: AuthContext = SyncWrite,
    db: Session = Depends(get_db),
):
    _enabled(auth)
    row = db.get(SyncConflict, conflict_id)
    if not row or row.owner_user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="同步冲突不存在")
    if row.status != "open":
        return {"resolved": True, "resolution": row.resolution, "idempotent": True}
    resolution = str(payload.get("resolution") or "")
    if resolution not in {"server", "client", "delete"}:
        raise HTTPException(status_code=400, detail="resolution 必须是 server、client 或 delete")
    client_change = loads(row.client_version_json, {})
    entity = _entity(db, auth, str(row.entity_uid or ""))
    if not entity:
        raise HTTPException(status_code=409, detail="冲突实体映射已不存在")
    table = Base.metadata.tables[entity.entity_type]
    primary = primary_key_column(table)
    if resolution in {"client", "delete"}:
        db.info["sync_apply"] = True
        try:
            if resolution == "delete":
                db.connection().execute(delete(table).where(primary == _cast(primary, entity.local_id)))
                entity.tombstone = True
                entity.deleted_at = utc_now()
            else:
                values = _resolved_fields(
                    db, auth, table, dict(client_change.get("fields") or {}), dict(client_change.get("refs") or {})
                )
                db.connection().execute(
                    update(table).where(primary == _cast(primary, entity.local_id)).values(**values)
                )
                entity.tombstone = False
                entity.deleted_at = None
            entity.version = int(entity.version or 0) + 1
        finally:
            db.info.pop("sync_apply", None)
    else:
        entity.version = int(entity.version or 0) + 1

    now = utc_now()
    operation = "delete" if resolution == "delete" else "upsert"
    resolved_fields: dict = {}
    resolved_refs: dict = {}
    attachments: list[str] = []
    if operation == "upsert":
        current = db.connection().execute(
            select(table).where(primary == _cast(primary, entity.local_id)).limit(1)
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=409, detail="冲突实体已被删除，请选择删除")
        current_values = dict(current)
        resolved_fields = {
            key: json_value(value)
            for key, value in safe_fields(table, current_values).items()
        }
        for foreign_key in table.foreign_keys:
            field = foreign_key.parent.name
            parent_name = foreign_key.column.table.name
            value = current_values.get(field)
            if value is not None and parent_name in SYNC_TABLE_NAMES and parent_name != "users":
                resolved_refs[field] = _mapped_entity_uid(db, auth.user_id, parent_name, value)
        file_config = FILE_TABLES.get(table.name)
        if file_config and current_values.get(file_config[1]):
            db_path = sqlite_database_path(DATABASE_URL)
            if db_path:
                _, portable = _portable_storage_path(
                    db_path.parent, file_config[0], str(current_values[file_config[1]])
                )
                resolved_fields[file_config[1]] = portable
        digest = str(current_values.get("sha256") or "")
        if digest:
            attachments.append(digest)
    field_times = loads(entity.field_times_json, {})
    for field in loads(row.conflict_fields_json, []):
        field_times[str(field)] = iso_utc(now)
    entity.field_times_json = dumps(field_times)
    entity.updated_at = now

    resolution_transaction_id = str(uuid.uuid4())
    resolution_event_id = f"resolution:{row.id}"
    db.add(
        SyncTransaction(
            id=resolution_transaction_id,
            event_id=resolution_event_id,
            owner_user_id=auth.user_id,
            device_id=None,
            base_cursor=_cursor(db, auth.user_id),
            client_created_at=now,
            status="accepted",
            payload_sha256=hashlib.sha256(f"{row.id}:{resolution}".encode("utf-8")).hexdigest(),
        )
    )
    db.add(
        SyncChange(
            transaction_id=resolution_transaction_id,
            event_id=f"{resolution_event_id}:0",
            owner_user_id=auth.user_id,
            device_id=None,
            entity_uid=entity.entity_uid,
            entity_type=entity.entity_type,
            operation=operation,
            version=int(entity.version or 1),
            fields_json=dumps(resolved_fields),
            refs_json=dumps(resolved_refs),
            field_times_json=dumps(field_times),
            attachments_json=dumps(attachments),
            occurred_at=now,
        )
    )
    row.status = "resolved"
    row.resolution = resolution
    row.resolved_by_user_id = auth.user_id
    row.resolved_at = utc_now()
    transaction = db.get(SyncTransaction, row.transaction_id)
    other_open = db.query(SyncConflict).filter(
        SyncConflict.transaction_id == row.transaction_id,
        SyncConflict.status == "open",
        SyncConflict.id != row.id,
    ).count()
    if transaction and other_open == 0:
        transaction.status = "resolved"
    db.commit()
    return {"resolved": True, "resolution": resolution}


def _blob_root() -> Path:
    db_path = sqlite_database_path(DATABASE_URL)
    if not db_path:
        raise HTTPException(status_code=503, detail="附件同步只支持 SQLite 服务")
    root = db_path.parent / "sync-blobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_sync_storage(db: Session) -> None:
    threshold = utc_now() - timedelta(days=30)
    root = _blob_root().resolve()
    stale_blobs = db.query(SyncBlob).filter(
        SyncBlob.reference_count <= 0,
        SyncBlob.created_at < threshold,
    ).limit(500).all()
    for blob in stale_blobs:
        path = Path(blob.storage_path).resolve()
        if root in path.parents and path.is_file() and not path.is_symlink():
            path.unlink(missing_ok=True)
        db.delete(blob)
    expired_uploads = db.query(SyncBlobUpload).filter(
        SyncBlobUpload.expires_at < utc_now(),
        SyncBlobUpload.status == "uploading",
    ).limit(500).all()
    for upload in expired_uploads:
        path = Path(upload.temp_path).resolve()
        if root in path.parents and path.is_file() and not path.is_symlink():
            path.unlink(missing_ok=True)
        db.delete(upload)
    if stale_blobs or expired_uploads:
        db.commit()


@router.post("/blobs/probe")
def probe_blobs(payload: dict, auth: AuthContext = SyncRead, db: Session = Depends(get_db)):
    _enabled(auth)
    _cleanup_sync_storage(db)
    hashes = [str(value).lower() for value in payload.get("sha256") or []][:1000]
    existing = {
        row.sha256 for row in db.query(SyncBlob).filter(
            SyncBlob.owner_user_id == auth.user_id,
            SyncBlob.sha256.in_(hashes),
        ).all()
    } if hashes else set()
    return {"present": sorted(existing), "missing": [value for value in hashes if value not in existing]}


@router.post("/blobs")
def begin_blob_upload(payload: dict, auth: AuthContext = SyncWrite, db: Session = Depends(get_db)):
    _enabled(auth)
    device = _device(db, auth, str(payload.get("device_id") or ""))
    digest = str(payload.get("sha256") or "").lower()
    size = int(payload.get("size_bytes") or 0)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest) or size <= 0:
        raise HTTPException(status_code=400, detail="附件 SHA256 或大小无效")
    existing = db.get(SyncBlob, digest)
    if existing and existing.owner_user_id == auth.user_id:
        return {"present": True, "sha256": digest}
    upload = db.query(SyncBlobUpload).filter(
        SyncBlobUpload.owner_user_id == auth.user_id,
        SyncBlobUpload.device_id == device.id,
        SyncBlobUpload.sha256 == digest,
        SyncBlobUpload.status == "uploading",
    ).first()
    if not upload:
        fd, temp_path = tempfile.mkstemp(prefix="cw-sync-blob-", suffix=".part", dir=_blob_root())
        os.close(fd)
        upload = SyncBlobUpload(
            id=str(uuid.uuid4()),
            owner_user_id=auth.user_id,
            device_id=device.id,
            sha256=digest,
            size_bytes=size,
            chunk_size=SYNC_CHUNK_SIZE,
            received_chunks_json="[]",
            temp_path=temp_path,
            status="uploading",
            expires_at=utc_now() + timedelta(days=1),
        )
        db.add(upload)
        db.commit()
    return {
        "present": False,
        "upload_id": upload.id,
        "chunk_size": upload.chunk_size,
        "received_chunks": loads(upload.received_chunks_json, []),
    }


@router.put("/blobs/{upload_id}/{chunk_index}")
async def upload_blob_chunk(
    upload_id: str,
    chunk_index: int,
    request: Request,
    auth: AuthContext = SyncWrite,
    db: Session = Depends(get_db),
):
    _enabled(auth)
    upload = db.get(SyncBlobUpload, upload_id)
    if not upload or upload.owner_user_id != auth.user_id or upload.status != "uploading":
        raise HTTPException(status_code=404, detail="附件上传会话不存在")
    expected_chunks = math.ceil(upload.size_bytes / upload.chunk_size)
    if chunk_index < 0 or chunk_index >= expected_chunks:
        raise HTTPException(status_code=400, detail="附件分块编号无效")
    content = await request.body()
    expected_size = min(upload.chunk_size, upload.size_bytes - chunk_index * upload.chunk_size)
    if len(content) != expected_size:
        raise HTTPException(status_code=400, detail="附件分块大小不匹配")
    with Path(upload.temp_path).open("r+b") as target:
        target.seek(chunk_index * upload.chunk_size)
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    received = set(int(value) for value in loads(upload.received_chunks_json, []))
    received.add(chunk_index)
    upload.received_chunks_json = dumps(sorted(received))
    upload.expires_at = utc_now() + timedelta(days=1)
    db.commit()
    return {"received": chunk_index, "remaining": expected_chunks - len(received)}


@router.post("/blobs/{upload_id}/complete")
def complete_blob_upload(upload_id: str, auth: AuthContext = SyncWrite, db: Session = Depends(get_db)):
    _enabled(auth)
    upload = db.get(SyncBlobUpload, upload_id)
    if not upload or upload.owner_user_id != auth.user_id or upload.status != "uploading":
        raise HTTPException(status_code=404, detail="附件上传会话不存在")
    expected_chunks = math.ceil(upload.size_bytes / upload.chunk_size)
    if set(loads(upload.received_chunks_json, [])) != set(range(expected_chunks)):
        raise HTTPException(status_code=409, detail="附件分块尚未全部上传")
    source = Path(upload.temp_path)
    if source.stat().st_size != upload.size_bytes or sha256_file(source) != upload.sha256:
        raise HTTPException(status_code=400, detail="附件 SHA256 完成校验失败")
    target = _blob_root() / upload.sha256[:2] / upload.sha256
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    blob = SyncBlob(
        sha256=upload.sha256,
        owner_user_id=auth.user_id,
        size_bytes=upload.size_bytes,
        mime_type=None,
        storage_path=str(target),
        reference_count=0,
    )
    db.merge(blob)
    upload.status = "complete"
    db.commit()
    return {"complete": True, "sha256": upload.sha256, "size_bytes": upload.size_bytes}


@router.get("/blobs/{sha256}")
def download_blob(sha256: str, auth: AuthContext = SyncRead, db: Session = Depends(get_db)):
    _enabled(auth)
    blob = db.get(SyncBlob, sha256.lower())
    if not blob or blob.owner_user_id != auth.user_id or not Path(blob.storage_path).is_file():
        raise HTTPException(status_code=404, detail="同步附件不存在")
    return FileResponse(blob.storage_path, media_type=blob.mime_type or "application/octet-stream", filename=blob.sha256)
