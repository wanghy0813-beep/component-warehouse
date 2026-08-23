from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from sqlalchemy import and_, event, insert, inspect, select, update
from sqlalchemy.orm import Session as SqlAlchemySession

from ..database import Base, DATABASE_URL
from .backup_service import sqlite_database_path
from .sync_core import (
    EXCLUDED_SYNC_FIELDS,
    SYNC_TABLE_NAMES,
    dumps,
    iso_utc,
    json_value,
    primary_key_column,
    stable_entity_uid,
    utc_now,
)


_REGISTERED = False
FILE_ROOTS = {
    "custom_label_assets": "custom-labels",
    "eda_assets": "eda-library",
    "personal_project_files_v2": "project-v2-files",
}


def _capture_enabled() -> bool:
    return os.getenv("SYNC_ENABLED", "0") == "1" or os.getenv("DESKTOP_MODE", "0") == "1"


def _row_values(instance) -> dict:
    table = instance.__table__
    return {column.name: getattr(instance, column.name, None) for column in table.columns}


def _portable_file(table_name: str, row: dict) -> tuple[str | None, Path | None]:
    root_name = FILE_ROOTS.get(table_name)
    raw_value = row.get("storage_path")
    database_path = sqlite_database_path(DATABASE_URL)
    if not root_name or not raw_value or not database_path:
        return None, None
    raw = Path(str(raw_value))
    if root_name in raw.parts:
        index = raw.parts.index(root_name)
        relative = Path(*raw.parts[index + 1 :])
    else:
        relative = raw
    if raw.is_absolute() and root_name not in raw.parts:
        relative = Path(raw.name)
    source = (database_path.parent / root_name / relative).resolve()
    if table_name == "eda_assets" and not raw.is_absolute():
        source = (database_path.parent / root_name / raw).resolve()
        relative = raw
    return f"@data/{root_name}/{relative.as_posix()}", source


def _owner_for_row(connection, table, row: dict, seen: set[tuple[str, str]] | None = None) -> int | None:
    if row.get("scope_type") == "team" or row.get("team_library_id"):
        return None
    if "owner_user_id" in table.c and row.get("owner_user_id") is not None:
        return int(row["owner_user_id"])
    seen = seen or set()
    primary = primary_key_column(table)
    marker = (table.name, str(row.get(primary.name)))
    if marker in seen:
        return None
    seen.add(marker)
    for foreign_key in table.foreign_keys:
        parent = foreign_key.column.table
        if parent.name in {"users", "categories", "components", "inventory_lots", "supplier_parts"}:
            continue
        value = row.get(foreign_key.parent.name)
        if value is None or parent.name not in SYNC_TABLE_NAMES:
            continue
        parent_row = connection.execute(
            select(parent).where(foreign_key.column == value).limit(1)
        ).mappings().first()
        if parent_row:
            owner = _owner_for_row(connection, parent, dict(parent_row), seen)
            if owner is not None:
                return owner
    return None


def _entity_uid_for_local(connection, owner: int, entity_type: str, local_id, *, create_random: bool) -> str:
    entity_table = Base.metadata.tables["sync_entities"]
    existing = connection.execute(
        select(entity_table.c.entity_uid).where(
            entity_table.c.owner_user_id == owner,
            entity_table.c.entity_type == entity_type,
            entity_table.c.local_id == str(local_id),
        ).limit(1)
    ).scalar_one_or_none()
    if existing:
        return str(existing)
    raw = str(local_id)
    try:
        parsed = uuid.UUID(raw)
        if str(parsed) == raw.lower():
            return str(parsed)
    except ValueError:
        pass
    return str(uuid.uuid4()) if create_random else stable_entity_uid(owner, entity_type, local_id)


def register_sync_journal() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @event.listens_for(SqlAlchemySession, "before_flush")
    def collect_changes(session, _flush_context, _instances):
        if not _capture_enabled() or session.info.get("sync_apply") or session.info.get("sync_emit"):
            return
        pending = session.info.setdefault("sync_pending", [])
        for operation, instances in (("upsert", session.new), ("upsert", session.dirty), ("delete", session.deleted)):
            for instance in list(instances):
                table = getattr(instance, "__table__", None)
                if table is None or table.name not in SYNC_TABLE_NAMES or table.name in {"users", "categories"}:
                    continue
                state = inspect(instance)
                if operation == "upsert" and instance in session.dirty and not session.is_modified(instance, include_collections=False):
                    continue
                if instance in session.new:
                    changed = [column.name for column in table.columns if column.name not in EXCLUDED_SYNC_FIELDS]
                elif operation == "delete":
                    changed = []
                else:
                    changed = [
                        attribute.key
                        for attribute in state.mapper.column_attrs
                        if attribute.key not in EXCLUDED_SYNC_FIELDS
                        and state.attrs[attribute.key].history.has_changes()
                    ]
                pending.append({
                    "instance": instance,
                    "operation": operation,
                    "changed": changed,
                    "is_new": instance in session.new,
                })

    @event.listens_for(SqlAlchemySession, "after_flush_postexec")
    def emit_changes(session, _flush_context):
        pending = session.info.pop("sync_pending", [])
        if not pending or session.info.get("sync_apply"):
            return
        session.info["sync_emit"] = True
        try:
            connection = session.connection()
            now = utc_now()
            emitted: list[dict] = []
            for item in pending:
                instance = item["instance"]
                table = instance.__table__
                row = _row_values(instance)
                owner = _owner_for_row(connection, table, row)
                if owner is None:
                    continue
                primary = primary_key_column(table)
                local_id = row.get(primary.name)
                if local_id is None:
                    continue
                entity_uid = _entity_uid_for_local(
                    connection, owner, table.name, local_id, create_random=True
                )
                existing = connection.execute(
                    select(Base.metadata.tables["sync_entities"]).where(
                        Base.metadata.tables["sync_entities"].c.entity_uid == entity_uid
                    )
                ).mappings().first()
                version = int(existing["version"] if existing else 0) + 1
                previous_times = {}
                if existing:
                    try:
                        import json
                        previous_times = json.loads(existing["field_times_json"] or "{}")
                    except (TypeError, ValueError):
                        previous_times = {}
                changed = item["changed"]
                timestamp = iso_utc(now)
                field_times = {**previous_times, **{field: timestamp for field in changed}}
                if existing:
                    connection.execute(
                        update(Base.metadata.tables["sync_entities"])
                        .where(Base.metadata.tables["sync_entities"].c.entity_uid == entity_uid)
                        .values(
                            local_id=str(local_id),
                            version=version,
                            field_times_json=dumps(field_times),
                            tombstone=item["operation"] == "delete",
                            deleted_at=now if item["operation"] == "delete" else None,
                            updated_at=now,
                        )
                    )
                else:
                    connection.execute(
                        insert(Base.metadata.tables["sync_entities"]).values(
                            entity_uid=entity_uid,
                            owner_user_id=owner,
                            entity_type=table.name,
                            local_id=str(local_id),
                            version=version,
                            field_times_json=dumps(field_times),
                            tombstone=item["operation"] == "delete",
                            deleted_at=now if item["operation"] == "delete" else None,
                            updated_at=now,
                        )
                    )
                fields = {
                    field: json_value(row.get(field))
                    for field in changed
                    if field in table.c and field != primary.name and field not in EXCLUDED_SYNC_FIELDS
                }
                portable_path, attachment_path = _portable_file(table.name, row)
                if portable_path and "storage_path" in fields:
                    fields["storage_path"] = portable_path
                refs = {}
                for foreign_key in table.foreign_keys:
                    field = foreign_key.parent.name
                    value = row.get(field)
                    parent_name = foreign_key.column.table.name
                    if value is not None and parent_name in SYNC_TABLE_NAMES and parent_name != "users":
                        refs[field] = _entity_uid_for_local(
                            connection, owner, parent_name, value, create_random=False
                        )
                attachments = []
                if row.get("sha256") and item["operation"] != "delete":
                    attachments.append(str(row["sha256"]))
                    blob_table = Base.metadata.tables["sync_blobs"]
                    existing_blob = connection.execute(
                        select(blob_table).where(blob_table.c.sha256 == str(row["sha256"]))
                    ).mappings().first()
                    if not existing_blob and attachment_path and attachment_path.is_file():
                        connection.execute(
                            insert(blob_table).values(
                                sha256=str(row["sha256"]),
                                owner_user_id=owner,
                                size_bytes=attachment_path.stat().st_size,
                                mime_type=row.get("mime_type"),
                                storage_path=str(attachment_path),
                                reference_count=1,
                                last_referenced_at=now,
                                created_at=now,
                            )
                        )
                    elif existing_blob and item["is_new"]:
                        connection.execute(
                            update(blob_table)
                            .where(blob_table.c.sha256 == str(row["sha256"]))
                            .values(
                                reference_count=int(existing_blob["reference_count"] or 0) + 1,
                                last_referenced_at=now,
                            )
                        )
                elif row.get("sha256") and item["operation"] == "delete":
                    blob_table = Base.metadata.tables["sync_blobs"]
                    existing_blob = connection.execute(
                        select(blob_table).where(blob_table.c.sha256 == str(row["sha256"]))
                    ).mappings().first()
                    if existing_blob:
                        connection.execute(
                            update(blob_table)
                            .where(blob_table.c.sha256 == str(row["sha256"]))
                            .values(
                                reference_count=max(0, int(existing_blob["reference_count"] or 0) - 1),
                                last_referenced_at=now,
                            )
                        )
                emitted.append(
                    {
                        "owner": owner,
                        "entity_uid": entity_uid,
                        "entity_type": table.name,
                        "operation": item["operation"],
                        "version": version,
                        "fields": fields,
                        "refs": refs,
                        "field_times": {field: field_times[field] for field in changed if field in field_times},
                        "attachments": attachments,
                        "occurred_at": now,
                    }
                )
            if emitted:
                session.info.setdefault("sync_emitted", []).extend(emitted)
        finally:
            session.info.pop("sync_emit", None)

    @event.listens_for(SqlAlchemySession, "before_commit")
    def publish_transaction(session):
        if not _capture_enabled() or session.info.get("sync_apply") or session.info.get("sync_emit"):
            return
        session.flush()
        emitted = session.info.pop("sync_emitted", [])
        if not emitted:
            return
        session.info["sync_emit"] = True
        try:
            connection = session.connection()
            now = utc_now()
            coalesced: dict[tuple[int, str], dict] = {}
            for change in emitted:
                key = (int(change["owner"]), str(change["entity_uid"]))
                current = coalesced.get(key)
                if not current:
                    coalesced[key] = change
                    continue
                current["operation"] = change["operation"]
                current["version"] = change["version"]
                current["fields"].update(change["fields"])
                current["refs"].update(change["refs"])
                current["field_times"].update(change["field_times"])
                current["attachments"] = change["attachments"] or current["attachments"]
                current["occurred_at"] = change["occurred_at"]
                if change["operation"] == "delete":
                    current["fields"] = {}
                    current["attachments"] = []
            emitted = list(coalesced.values())
            inventory_deltas: dict[tuple[int, str], int] = {}
            for change in emitted:
                if change["entity_type"] != "stock_movements_v2" or change["operation"] != "upsert":
                    continue
                movement_type = str(change["fields"].get("movement_type") or "")
                component_uid = str(change["refs"].get("component_id") or "")
                if not component_uid or movement_type in {"manual_adjustment", "component_create"}:
                    continue
                key = (change["owner"], component_uid)
                inventory_deltas[key] = inventory_deltas.get(key, 0) + int(change["fields"].get("quantity_delta") or 0)
            for change in emitted:
                delta = inventory_deltas.get((change["owner"], change["entity_uid"]))
                if change["entity_type"] == "components" and delta:
                    change["fields"].pop("quantity", None)
                    change["fields"]["__inventory_delta__"] = delta

            owners = sorted({int(change["owner"]) for change in emitted})
            tx_table = Base.metadata.tables["sync_transactions"]
            change_table = Base.metadata.tables["sync_changes"]
            for owner in owners:
                owner_changes = [change for change in emitted if change["owner"] == owner]
                transaction_id = str(uuid.uuid4())
                event_id = f"server:{transaction_id}"
                payload_sha = hashlib.sha256(
                    dumps(
                        [
                            {
                                **{key: value for key, value in change.items() if key != "occurred_at"},
                                "occurred_at": iso_utc(change["occurred_at"]),
                            }
                            for change in owner_changes
                        ]
                    ).encode("utf-8")
                ).hexdigest()
                connection.execute(
                    insert(tx_table).values(
                        id=transaction_id,
                        event_id=event_id,
                        owner_user_id=owner,
                        device_id=os.getenv("DESKTOP_DEVICE_ID") or None,
                        base_cursor=0,
                        client_created_at=now,
                        server_received_at=now,
                        status="pending_upload" if os.getenv("DESKTOP_MODE", "0") == "1" else "accepted",
                        payload_sha256=payload_sha,
                    )
                )
                for index, change in enumerate(owner_changes):
                    connection.execute(
                        insert(change_table).values(
                            transaction_id=transaction_id,
                            event_id=f"{event_id}:{index}",
                            owner_user_id=owner,
                            device_id=os.getenv("DESKTOP_DEVICE_ID") or None,
                            entity_uid=change["entity_uid"],
                            entity_type=change["entity_type"],
                            operation=change["operation"],
                            version=change["version"],
                            fields_json=dumps(change["fields"]),
                            refs_json=dumps(change["refs"]),
                            field_times_json=dumps(change["field_times"]),
                            attachments_json=dumps(change["attachments"]),
                            occurred_at=change["occurred_at"],
                        )
                    )
        finally:
            session.info.pop("sync_emit", None)

    @event.listens_for(SqlAlchemySession, "after_rollback")
    def discard_transaction(session):
        session.info.pop("sync_pending", None)
        session.info.pop("sync_emitted", None)
