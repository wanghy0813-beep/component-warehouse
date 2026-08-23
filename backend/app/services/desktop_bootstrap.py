from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from ..database import Base
from .sync_bootstrap import BOOTSTRAP_FORMAT
from .sync_core import SYNC_TABLE_NAMES


class DesktopBootstrapError(ValueError):
    pass


def _safe_name(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or ".." in path.parts:
        raise DesktopBootstrapError("首次数据包包含不安全路径")
    return path.as_posix()


def _stream_hash(source) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def inspect_desktop_bootstrap(path: Path, *, max_expanded_bytes: int = 8 * 1024**3) -> dict:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise DesktopBootstrapError("首次数据包不是有效 ZIP") from error
    with archive:
        infos = archive.infolist()
        if len(infos) > 50_000:
            raise DesktopBootstrapError("首次数据包条目过多")
        members = {}
        expanded = 0
        for info in infos:
            name = _safe_name(info.filename)
            if name in members:
                raise DesktopBootstrapError("首次数据包包含重复路径")
            if info.flag_bits & 0x1:
                raise DesktopBootstrapError("首次数据包不能是加密 ZIP")
            expanded += int(info.file_size)
            if expanded > max_expanded_bytes:
                raise DesktopBootstrapError("首次数据包解压后体积超过安全上限")
            members[name] = info
        if "manifest.json" not in members:
            raise DesktopBootstrapError("首次数据包缺少清单")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DesktopBootstrapError("首次数据包清单无法读取") from error
        if manifest.get("format") != BOOTSTRAP_FORMAT or manifest.get("scope") != "personal":
            raise DesktopBootstrapError("不是个人桌面首次数据包")
        declarations = list(manifest.get("tables", {}).values()) + [manifest.get("entities") or {}] + list(manifest.get("files") or [])
        for declaration in declarations:
            name = _safe_name(str(declaration.get("path") or ""))
            info = members.get(name)
            if not info or info.is_dir():
                raise DesktopBootstrapError(f"首次数据包缺少清单文件：{name}")
            with archive.open(info) as source:
                actual = _stream_hash(source)
            if actual != str(declaration.get("sha256") or "").lower():
                raise DesktopBootstrapError(f"首次数据包校验失败：{name}")
        return {"manifest": manifest, "expanded_bytes": expanded, "members": members}


def _extract_file(archive: zipfile.ZipFile, arcname: str, destination: Path) -> None:
    info = archive.getinfo(_safe_name(arcname))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)


def import_desktop_bootstrap(
    package_path: Path,
    *,
    database_path: Path,
    data_root: Path,
    marker_path: Path,
) -> dict:
    inspection = inspect_desktop_bootstrap(package_path)
    manifest = inspection["manifest"]
    if shutil.disk_usage(data_root).free < inspection["expanded_bytes"] * 2:
        raise DesktopBootstrapError("本机磁盘空间不足，无法安全导入个人数据")
    stage = Path(tempfile.mkdtemp(prefix="wxy-desktop-bootstrap-", dir=data_root))
    rollback_db = stage / "rollback.db"
    rollback_dirs = stage / "rollback-files"
    rollback_dirs.mkdir()
    staged_files = stage / "files"
    table_rows: dict[str, list[dict]] = {}
    entities: list[dict] = []
    try:
        if database_path.exists():
            source = sqlite3.connect(str(database_path))
            target = sqlite3.connect(str(rollback_db))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        with zipfile.ZipFile(package_path) as archive:
            for table_name, declaration in manifest.get("tables", {}).items():
                if table_name not in SYNC_TABLE_NAMES:
                    raise DesktopBootstrapError(f"首次数据包包含不允许的表：{table_name}")
                with archive.open(declaration["path"]) as source:
                    table_rows[table_name] = [json.loads(line) for line in source if line.strip()]
            with archive.open(manifest["entities"]["path"]) as source:
                entities = [json.loads(line) for line in source if line.strip()]
            for file_row in manifest.get("files") or []:
                target_value = str(file_row.get("target") or "")
                if not target_value.startswith("@data/"):
                    raise DesktopBootstrapError("首次数据包附件目标路径无效")
                relative = _safe_name(target_value.removeprefix("@data/"))
                _extract_file(archive, file_row["path"], staged_files / Path(*PurePosixPath(relative).parts))

        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(database_path))
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("BEGIN IMMEDIATE")
            existing_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table_name in reversed(sorted(SYNC_TABLE_NAMES)):
                if table_name in existing_tables:
                    connection.execute(f'DELETE FROM "{table_name}"')
            for table_name in sorted(table_rows):
                table = Base.metadata.tables[table_name]
                columns = {column.name for column in table.columns}
                for row in table_rows[table_name]:
                    values = {key: value for key, value in row.items() if key in columns}
                    for key, value in list(values.items()):
                        if isinstance(value, str) and value.startswith("@data/"):
                            relative = _safe_name(value.removeprefix("@data/"))
                            values[key] = str((data_root / Path(*PurePosixPath(relative).parts)).resolve())
                            continue
                        column = table.c[key]
                        try:
                            python_type = column.type.python_type
                        except NotImplementedError:
                            python_type = None
                        if python_type is datetime and isinstance(value, str):
                            values[key] = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None).isoformat(sep=" ")
                        elif python_type is date and isinstance(value, str):
                            values[key] = value[:10]
                        elif python_type is bool and value is not None:
                            values[key] = 1 if value else 0
                    names = list(values)
                    placeholders = ",".join("?" for _ in names)
                    quoted = ",".join(f'"{name}"' for name in names)
                    connection.execute(
                        f'INSERT OR REPLACE INTO "{table_name}" ({quoted}) VALUES ({placeholders})',
                        [values[name] for name in names],
                    )
            if "sync_entities" in existing_tables:
                connection.execute("DELETE FROM sync_entities")
                for entity in entities:
                    connection.execute(
                        """
                        INSERT INTO sync_entities
                        (entity_uid, owner_user_id, entity_type, local_id, version, field_times_json, tombstone, deleted_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, CURRENT_TIMESTAMP)
                        """,
                        (
                            entity["entity_uid"],
                            int(manifest["owner_user_id"]),
                            entity["entity_type"],
                            str(entity["local_id"]),
                            int(entity.get("version") or 1),
                            json.dumps(entity.get("field_times") or {}, ensure_ascii=False),
                            1 if entity.get("tombstone") else 0,
                        ),
                    )
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DesktopBootstrapError("导入后的本地数据库完整性检查失败")
            foreign_errors = connection.execute("PRAGMA foreign_key_check").fetchmany(10)
            if foreign_errors:
                raise DesktopBootstrapError("导入后的个人数据外键检查失败")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        roots = {PurePosixPath(str(row["target"]).removeprefix("@data/")).parts[0] for row in manifest.get("files") or []}
        for root_name in roots:
            live = data_root / root_name
            staged = staged_files / root_name
            rollback = rollback_dirs / root_name
            if live.exists():
                live.rename(rollback)
            if staged.exists():
                staged.rename(live)
            else:
                live.mkdir(parents=True, exist_ok=True)

        marker = {
            "format": BOOTSTRAP_FORMAT,
            "owner_user_id": manifest["owner_user_id"],
            "server_instance_id": manifest["server_instance_id"],
            "cursor": int(manifest.get("cursor") or 0),
            "imported_at": datetime.utcnow().isoformat() + "Z",
        }
        temporary_marker = marker_path.with_suffix(".tmp")
        temporary_marker.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_marker, marker_path)
        return marker
    except Exception:
        if rollback_db.exists():
            source = sqlite3.connect(str(rollback_db))
            target = sqlite3.connect(str(database_path))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        for rollback in rollback_dirs.iterdir():
            live = data_root / rollback.name
            if live.exists():
                shutil.rmtree(live)
            rollback.rename(live)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
