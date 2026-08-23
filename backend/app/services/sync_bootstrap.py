from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..database import Base
from ..models import SyncEntity
from ..version import APP_VERSION
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


BOOTSTRAP_FORMAT = "cwbootstrap/v1"
SHARED_REFERENCE_TABLES = {"users", "categories", "components", "inventory_lots", "supplier_parts"}
FILE_TABLES = {
    "custom_label_assets": ("custom-labels", "storage_path"),
    "eda_assets": ("eda-library", "storage_path"),
    "personal_project_files_v2": ("project-v2-files", "storage_path"),
}


def _rows(connection, table, where=None) -> list[dict]:
    statement = select(table)
    if where is not None:
        statement = statement.where(where)
    primary = primary_key_column(table)
    statement = statement.order_by(primary.asc())
    return [dict(row) for row in connection.execute(statement).mappings().all()]


def collect_personal_rows(session: Session, owner_user_id: int) -> dict[str, list[dict]]:
    connection = session.connection()
    tables = {name: Base.metadata.tables[name] for name in SYNC_TABLE_NAMES if name in Base.metadata.tables}
    selected: dict[str, list[dict]] = {name: [] for name in tables}
    selected["categories"] = _rows(connection, tables["categories"])
    selected["users"] = _rows(connection, tables["users"], tables["users"].c.id == owner_user_id)
    for name, table in tables.items():
        if name in {"categories", "users"} or "owner_user_id" not in table.c:
            continue
        condition = table.c.owner_user_id == owner_user_id
        if "scope_type" in table.c:
            condition = and_(condition, table.c.scope_type == "personal")
        selected[name] = _rows(connection, table, condition)

    # Pull aggregate children through their structural foreign keys. User and
    # shared-reference foreign keys never establish ownership.
    changed = True
    while changed:
        changed = False
        for name, table in tables.items():
            if name in {"categories", "users"} or "owner_user_id" in table.c:
                continue
            clauses = []
            for foreign_key in table.foreign_keys:
                parent_name = foreign_key.column.table.name
                if parent_name in SHARED_REFERENCE_TABLES or parent_name not in selected:
                    continue
                parent_rows = selected[parent_name]
                if not parent_rows:
                    continue
                parent_values = {row[foreign_key.column.name] for row in parent_rows}
                clauses.append(foreign_key.parent.in_(parent_values))
            if not clauses:
                continue
            new_rows = _rows(connection, table, or_(*clauses))
            primary_name = primary_key_column(table).name
            known = {row[primary_name] for row in selected[name]}
            additions = [row for row in new_rows if row[primary_name] not in known]
            if additions:
                selected[name].extend(additions)
                changed = True

    for row in selected.get("users", []):
        row["password_hash"] = None
        row["is_admin"] = False
    return selected


def seed_sync_entities(session: Session, owner_user_id: int, selected: dict[str, list[dict]]) -> list[dict]:
    entities: list[dict] = []
    now = utc_now()
    for table_name, rows in selected.items():
        if table_name in {"categories", "users"}:
            continue
        table = Base.metadata.tables[table_name]
        primary_name = primary_key_column(table).name
        for row in rows:
            local_id = str(row[primary_name])
            entity = session.query(SyncEntity).filter(
                SyncEntity.owner_user_id == owner_user_id,
                SyncEntity.entity_type == table_name,
                SyncEntity.local_id == local_id,
            ).first()
            if not entity:
                entity_uid = stable_entity_uid(owner_user_id, table_name, local_id)
                entity = SyncEntity(
                    entity_uid=entity_uid,
                    owner_user_id=owner_user_id,
                    entity_type=table_name,
                    local_id=local_id,
                    version=1,
                    field_times_json=dumps({}),
                    tombstone=False,
                    updated_at=now,
                )
                session.add(entity)
            else:
                entity_uid = entity.entity_uid
            entities.append(
                {
                    "entity_uid": entity_uid,
                    "entity_type": table_name,
                    "local_id": local_id,
                    "version": int(entity.version or 1),
                    "field_times": json.loads(entity.field_times_json or "{}"),
                    "tombstone": bool(entity.tombstone),
                }
            )
    session.flush()
    return entities


def _portable_storage_path(data_root: Path, root_name: str, raw_path: str) -> tuple[Path, str]:
    raw = Path(str(raw_path or ""))
    parts = raw.parts
    if root_name in parts:
        index = parts.index(root_name)
        relative = Path(*parts[index + 1 :])
    else:
        relative = raw if not raw.is_absolute() else Path(raw.name)
    relative_posix = PurePosixPath(relative.as_posix())
    if ".." in relative_posix.parts or relative_posix.is_absolute():
        raise ValueError("附件路径超出允许目录")
    source = (data_root / root_name / Path(*relative_posix.parts)).resolve()
    expected_root = (data_root / root_name).resolve()
    if source != expected_root and expected_root not in source.parents:
        raise ValueError("附件路径超出允许目录")
    return source, f"@data/{root_name}/{relative_posix.as_posix()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_personal_bootstrap(
    session: Session,
    *,
    owner_user_id: int,
    data_root: Path,
    server_instance_id: str,
    cursor: int,
    output_dir: Path,
) -> Path:
    selected = collect_personal_rows(session, owner_user_id)
    entities = seed_sync_entities(session, owner_user_id, selected)
    fd, raw_output = tempfile.mkstemp(prefix="cw-personal-bootstrap-", suffix=".zip", dir=output_dir)
    os.close(fd)
    output_path = Path(raw_output)
    manifest = {
        "format": BOOTSTRAP_FORMAT,
        "app_version": APP_VERSION,
        "scope": "personal",
        "owner_user_id": owner_user_id,
        "server_instance_id": server_instance_id,
        "cursor": int(cursor or 0),
        "created_at": iso_utc(),
        "tables": {},
        "files": [],
        "excluded": ["team data", "tokens", "audit logs", "AI cache"],
    }
    written_files: set[str] = set()
    pending_files: dict[str, tuple[Path, str]] = {}
    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as archive:
            for table_name in sorted(selected):
                rows = selected[table_name]
                if not rows:
                    continue
                arcname = f"tables/{table_name}.jsonl"
                digest = hashlib.sha256()
                count = 0
                with archive.open(arcname, "w", force_zip64=True) as output:
                    for original in rows:
                        row = dict(original)
                        if table_name in FILE_TABLES and row.get(FILE_TABLES[table_name][1]):
                            root_name, field_name = FILE_TABLES[table_name]
                            source, portable = _portable_storage_path(data_root, root_name, str(row[field_name]))
                            row[field_name] = portable
                            if not source.is_file():
                                raise ValueError(f"个人数据引用的附件不存在：{table_name}/{row.get('id')}")
                            expected_hash = str(row.get("sha256") or "").lower()
                            if expected_hash and _sha256(source) != expected_hash:
                                raise ValueError(f"个人数据引用的附件校验失败：{table_name}/{row.get('id')}")
                            relative = portable.removeprefix("@data/")
                            file_arcname = f"files/{relative}"
                            pending_files.setdefault(file_arcname, (source, portable))
                        payload = {
                            key: json_value(value)
                            for key, value in row.items()
                            if key not in EXCLUDED_SYNC_FIELDS
                        }
                        if table_name == "components":
                            payload["ai_status"] = "pending"
                        line = (dumps(payload) + "\n").encode("utf-8")
                        output.write(line)
                        digest.update(line)
                        count += 1
                manifest["tables"][table_name] = {"path": arcname, "rows": count, "sha256": digest.hexdigest()}
            for file_arcname, (source, portable) in sorted(pending_files.items()):
                archive.write(source, file_arcname)
                written_files.add(file_arcname)
                manifest["files"].append(
                    {
                        "path": file_arcname,
                        "target": portable,
                        "bytes": source.stat().st_size,
                        "sha256": _sha256(source),
                    }
                )
            entity_arcname = "sync/entities.jsonl"
            entity_digest = hashlib.sha256()
            with archive.open(entity_arcname, "w", force_zip64=True) as output:
                for entity in entities:
                    line = (dumps(entity) + "\n").encode("utf-8")
                    output.write(line)
                    entity_digest.update(line)
            manifest["entities"] = {
                "path": entity_arcname,
                "rows": len(entities),
                "sha256": entity_digest.hexdigest(),
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return output_path
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
