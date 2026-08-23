from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO


BACKUP_FORMAT = "cwbackup/v2"
DATABASE_ARCNAME = "database/component_warehouse.snapshot.db"
MANIFEST_ARCNAME = "manifest.json"
DATA_ROOT_NAMES = ("contest-media", "custom-labels", "eda-library", "project-v2-files")
MAX_ARCHIVE_ENTRIES = 50_000
MAX_COMPRESSION_RATIO = 500
DEFAULT_MAX_EXPANDED_BYTES = 8 * 1024 * 1024 * 1024
FILE_REFERENCE_COLUMNS = {
    "contest-media": (("competition_pcbs", "front_image_path", None), ("competition_pcbs", "back_image_path", None)),
    "custom-labels": (("custom_label_assets", "storage_path", "sha256"),),
    "eda-library": (("eda_assets", "storage_path", "sha256"),),
    "project-v2-files": (("personal_project_files_v2", "storage_path", "sha256"),),
}


class BackupError(ValueError):
    pass


@dataclass(frozen=True)
class BackupArtifact:
    path: Path
    manifest: dict


@dataclass(frozen=True)
class BackupInspection:
    path: Path
    manifest: dict
    format_version: str
    scope: str
    snapshot_bytes: int
    snapshot_sha256: str
    file_count: int
    table_count: int
    expanded_bytes: int
    warnings: list[str]
    required_confirm_text: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def sqlite_database_path(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    raw_path = database_url.replace("sqlite:///", "", 1)
    if raw_path == ":memory:":
        return None
    return Path(raw_path).expanduser().resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_stream(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sqlite_snapshot(source_path: Path, target_path: Path) -> None:
    source = sqlite3.connect(str(source_path))
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _safe_archive_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or ".." in path.parts:
        raise BackupError("备份文件包含不安全路径")
    return path.as_posix()


def _referenced_file_path(data_root: Path, root_name: str, raw_value: str) -> tuple[Path, Path]:
    root = (data_root / root_name).resolve()
    raw = Path(str(raw_value or ""))
    if root_name in raw.parts:
        index = raw.parts.index(root_name)
        relative = Path(*raw.parts[index + 1 :])
    elif raw.is_absolute():
        try:
            relative = raw.resolve().relative_to(root)
        except ValueError as error:
            raise BackupError(f"数据库附件路径超出 {root_name} 目录") from error
    else:
        relative = raw
    if not relative.parts or ".." in relative.parts:
        raise BackupError(f"数据库附件路径无效：{root_name}")
    target = (root / relative).resolve()
    if root not in target.parents or target.is_symlink():
        raise BackupError(f"数据库附件路径超出 {root_name} 目录")
    return target, relative


def referenced_data_files(snapshot_path: Path, data_root: Path) -> list[tuple[Path, str, str]]:
    connection = sqlite3.connect(str(snapshot_path))
    connection.row_factory = sqlite3.Row
    referenced: dict[str, tuple[Path, str, set[str]]] = {}
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for root_name, declarations in FILE_REFERENCE_COLUMNS.items():
            for table_name, path_column, hash_column in declarations:
                if table_name not in tables:
                    continue
                columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table_name}")')}
                if path_column not in columns:
                    continue
                selected = f'"{path_column}"'
                if hash_column and hash_column in columns:
                    selected += f', "{hash_column}"'
                rows = connection.execute(
                    f'''SELECT {selected} FROM "{table_name}" WHERE "{path_column}" IS NOT NULL AND trim("{path_column}") != '' '''
                ).fetchall()
                for row in rows:
                    source, relative = _referenced_file_path(data_root, root_name, str(row[path_column]))
                    if not source.is_file():
                        raise BackupError(f"数据库引用的附件不存在：{root_name}/{relative.as_posix()}")
                    if hash_column and hash_column in row.keys() and row[hash_column]:
                        expected = str(row[hash_column]).lower()
                        if sha256_file(source) != expected:
                            raise BackupError(f"数据库引用的附件校验失败：{root_name}/{relative.as_posix()}")
                    arcname = f"data/{root_name}/{relative.as_posix()}"
                    if arcname in referenced:
                        referenced[arcname][2].add(f"{table_name}.{path_column}")
                    else:
                        referenced[arcname] = (source, root_name, {f"{table_name}.{path_column}"})
    finally:
        connection.close()
    return [
        (source, arcname, f"data:{root_name}:{','.join(sorted(purposes))}")
        for arcname, (source, root_name, purposes) in sorted(referenced.items())
    ]


def _add_file(
    archive: zipfile.ZipFile,
    source: Path,
    arcname: str,
    files: list[dict],
    *,
    role: str,
    sensitive: bool = False,
) -> None:
    safe_name = _safe_archive_name(arcname)
    archive.write(source, safe_name)
    files.append(
        {
            "path": safe_name,
            "role": role,
            "bytes": source.stat().st_size,
            "sha256": sha256_file(source),
            "sensitive": sensitive,
        }
    )


def create_backup_archive(
    *,
    database_url: str,
    app_name: str,
    app_version: str,
    backup_type: str = "manual",
    scope: str = "server-full",
    exported_by_user_id: int | None = None,
    server_instance_id: str = "",
    sync_cursor: int = 0,
    team_secret_file: Path | None = None,
    output_dir: Path | None = None,
) -> BackupArtifact:
    db_path = sqlite_database_path(database_url)
    if not db_path or not db_path.is_file():
        raise BackupError("当前 DATABASE_URL 不是可备份的 SQLite 文件路径")
    created_at = utc_now()
    output_root = output_dir or db_path.parent
    output_root.mkdir(parents=True, exist_ok=True)
    fd, raw_output = tempfile.mkstemp(prefix="cwbackup-v2-", suffix=".zip", dir=output_root)
    os.close(fd)
    output_path = Path(raw_output)
    fd, raw_snapshot = tempfile.mkstemp(prefix="cwbackup-db-", suffix=".db", dir=output_root)
    os.close(fd)
    snapshot_path = Path(raw_snapshot)
    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": 2,
        "app": app_name,
        "app_version": app_version,
        "database_schema": "sqlite",
        "created_at": iso_utc(created_at),
        "backup_type": backup_type,
        "scope": scope,
        "server_instance_id": server_instance_id,
        "exported_by_user_id": exported_by_user_id,
        "sync_cursor": max(0, int(sync_cursor or 0)),
        "data_roots": list(DATA_ROOT_NAMES),
        "files": [],
        "warnings": [
            "运行环境 .env、统一账号密钥和第三方 API 凭据不包含在迁移包中。",
            "备份包未单独加密，请存放在启用 BitLocker 的磁盘或加密介质中。",
        ],
    }
    try:
        sqlite_snapshot(db_path, snapshot_path)
        with zipfile.ZipFile(
            output_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            allowZip64=True,
            compresslevel=6,
        ) as archive:
            _add_file(
                archive,
                snapshot_path,
                DATABASE_ARCNAME,
                manifest["files"],
                role="database",
            )
            data_root = db_path.parent
            for path, arcname, role in referenced_data_files(snapshot_path, data_root):
                _add_file(archive, path, arcname, manifest["files"], role=role)
            secret_path = team_secret_file.resolve() if team_secret_file else None
            if secret_path and secret_path.is_file():
                _add_file(
                    archive,
                    secret_path,
                    "secrets/contest-invite-secret",
                    manifest["files"],
                    role="application-secret",
                    sensitive=True,
                )
            archive.writestr(MANIFEST_ARCNAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        return BackupArtifact(path=output_path, manifest=manifest)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        snapshot_path.unlink(missing_ok=True)


def _zip_members(archive: zipfile.ZipFile, *, max_expanded_bytes: int) -> tuple[dict[str, zipfile.ZipInfo], int]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise BackupError("备份文件条目过多")
    members: dict[str, zipfile.ZipInfo] = {}
    expanded = 0
    for info in infos:
        name = _safe_archive_name(info.filename)
        if name in members:
            raise BackupError("备份文件包含重复路径")
        if info.flag_bits & 0x1:
            raise BackupError("不支持加密 ZIP，请上传系统生成的迁移包")
        if info.is_dir():
            members[name] = info
            continue
        expanded += int(info.file_size)
        if expanded > max_expanded_bytes:
            raise BackupError("备份解压后体积超过安全上限")
        compressed = max(1, int(info.compress_size))
        if info.file_size > 10 * 1024 * 1024 and info.file_size / compressed > MAX_COMPRESSION_RATIO:
            raise BackupError("备份文件压缩比异常")
        members[name] = info
    return members, expanded


def _integrity_check_snapshot(archive: zipfile.ZipFile, info: zipfile.ZipInfo, temp_dir: Path) -> tuple[int, str]:
    snapshot_path = temp_dir / "inspect.db"
    digest = hashlib.sha256()
    with archive.open(info) as source, snapshot_path.open("wb") as target:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            target.write(chunk)
    connection = sqlite3.connect(str(snapshot_path))
    try:
        try:
            ok = connection.execute("PRAGMA integrity_check").fetchone()
            if not ok or ok[0] != "ok":
                raise BackupError("数据库快照完整性校验失败")
            table_count = int(connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
        except sqlite3.DatabaseError as error:
            raise BackupError("数据库快照损坏或格式无效") from error
    finally:
        connection.close()
    return table_count, digest.hexdigest()


def inspect_backup_archive(
    path: Path,
    *,
    expected_app_names: set[str],
    max_upload_bytes: int,
    max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
) -> BackupInspection:
    if not path.is_file() or path.stat().st_size <= 0:
        raise BackupError("备份文件为空")
    if path.stat().st_size > max_upload_bytes:
        raise BackupError("备份文件过大")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BackupError("不是有效的 ZIP 备份文件") from exc
    temp_root = Path(tempfile.mkdtemp(prefix="cwbackup-inspect-"))
    try:
        with archive:
            members, expanded = _zip_members(archive, max_expanded_bytes=max_expanded_bytes)
            if MANIFEST_ARCNAME not in members or DATABASE_ARCNAME not in members:
                raise BackupError("缺少 manifest.json 或数据库快照")
            try:
                manifest = json.loads(archive.read(MANIFEST_ARCNAME).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BackupError("manifest.json 无法读取") from exc
            if manifest.get("app") not in expected_app_names:
                raise BackupError("不是当前应用生成的备份")
            is_v2 = manifest.get("format") == BACKUP_FORMAT and int(manifest.get("format_version") or 0) == 2
            declared = manifest.get("files") or []
            if not isinstance(declared, list):
                raise BackupError("备份文件清单格式无效")
            declared_by_name: dict[str, dict] = {}
            for row in declared:
                if not isinstance(row, dict):
                    raise BackupError("备份文件清单格式无效")
                name = _safe_archive_name(str(row.get("path") or ""))
                if name in declared_by_name:
                    raise BackupError("备份清单包含重复路径")
                declared_by_name[name] = row
            if DATABASE_ARCNAME not in declared_by_name and is_v2:
                raise BackupError("备份清单缺少数据库快照")
            for name, row in declared_by_name.items():
                info = members.get(name)
                if not info or info.is_dir():
                    raise BackupError(f"备份缺少清单文件：{name}")
                if int(row.get("bytes") or -1) != int(info.file_size):
                    raise BackupError(f"备份文件大小校验失败：{name}")
                with archive.open(info) as source:
                    actual = sha256_stream(source)
                if actual != str(row.get("sha256") or "").lower():
                    raise BackupError(f"备份文件 SHA256 校验失败：{name}")
            if is_v2:
                allowed = set(declared_by_name) | {MANIFEST_ARCNAME}
                unexpected = [name for name, info in members.items() if not info.is_dir() and name not in allowed]
                if unexpected:
                    raise BackupError("备份包含未声明文件")
            snapshot_info = members[DATABASE_ARCNAME]
            if snapshot_info.file_size <= 0:
                raise BackupError("数据库快照为空")
            table_count, snapshot_sha256 = _integrity_check_snapshot(archive, snapshot_info, temp_root)
            warnings = list(manifest.get("warnings") or [])
            if not is_v2:
                warnings.append("这是旧版数据库备份，只能恢复 SQLite；旧包中的附件不会被当作完整迁移数据恢复。")
            return BackupInspection(
                path=path,
                manifest=manifest,
                format_version="v2" if is_v2 else "legacy-v1",
                scope=str(manifest.get("scope") or ("server-full" if is_v2 else "legacy-database")),
                snapshot_bytes=int(snapshot_info.file_size),
                snapshot_sha256=snapshot_sha256,
                file_count=len([info for info in members.values() if not info.is_dir()]),
                table_count=table_count,
                expanded_bytes=expanded,
                warnings=warnings,
                required_confirm_text="恢复完整备份" if is_v2 else "恢复数据库",
            )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def extract_backup_archive(inspection: BackupInspection, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(inspection.path) as archive:
        declared = inspection.manifest.get("files") or []
        names = (
            [str(row.get("path") or "") for row in declared]
            if inspection.format_version == "v2"
            else [DATABASE_ARCNAME]
        )
        if DATABASE_ARCNAME not in names:
            names.insert(0, DATABASE_ARCNAME)
        for raw_name in names:
            name = _safe_archive_name(raw_name)
            info = archive.getinfo(name)
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return destination


def copy_upload_to_temp(source: BinaryIO, *, max_bytes: int, directory: Path | None = None) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix="cwbackup-upload-", suffix=".zip", dir=directory)
    os.close(fd)
    target = Path(raw_path)
    total = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise BackupError("备份文件过大")
                output.write(chunk)
        if total == 0:
            raise BackupError("备份文件为空")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def backup_type_from_name(path: Path) -> str:
    name = path.name
    if name.startswith("pre-restore-"):
        return "pre_restore"
    if name.startswith("pre-clear-"):
        return "pre_clear"
    if name.startswith("auto-"):
        return "auto"
    return "manual"


def is_v2_archive(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read(MANIFEST_ARCNAME).decode("utf-8"))
            return manifest.get("format") == BACKUP_FORMAT
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError):
        return False


def tiered_auto_retention(paths: list[Path], *, now: datetime | None = None) -> set[Path]:
    current = now or utc_now()
    ordered = sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)
    keep: set[Path] = set()
    daily: set[str] = set()
    weekly: set[str] = set()
    monthly: set[str] = set()
    for path in ordered:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age = current - stamp
        day_key = stamp.strftime("%Y-%m-%d")
        week_key = f"{stamp.isocalendar().year}-W{stamp.isocalendar().week:02d}"
        month_key = stamp.strftime("%Y-%m")
        if age < timedelta(days=7) and day_key not in daily:
            daily.add(day_key)
            keep.add(path)
        elif age < timedelta(weeks=4) and week_key not in weekly:
            weekly.add(week_key)
            keep.add(path)
        elif age < timedelta(days=186) and month_key not in monthly:
            monthly.add(month_key)
            keep.add(path)
    return keep


def prune_v2_backups(root: Path) -> list[Path]:
    auto = [path for path in root.glob("auto-v2-*.zip") if path.is_file() and is_v2_archive(path)]
    keep = tiered_auto_retention(auto)
    removed: list[Path] = []
    for path in auto:
        if path in keep:
            continue
        path.unlink(missing_ok=True)
        removed.append(path)
    for prefix in ("pre-restore-v2-", "pre-clear-v2-"):
        paths = sorted(root.glob(f"{prefix}*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
        for path in paths[7:]:
            if is_v2_archive(path):
                path.unlink(missing_ok=True)
                removed.append(path)
    return removed


def _tree_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())


def _legacy_cleanup_candidates(data_root: Path) -> list[Path]:
    candidates: list[Path] = []
    backup_dir = data_root / "backups"
    if backup_dir.is_dir():
        legacy = [
            path for path in backup_dir.iterdir()
            if path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in {".zip", ".db"}
            and (path.suffix.lower() == ".db" or not is_v2_archive(path))
        ]
        legacy.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
        candidates.extend(legacy[3:])

    release_dir = data_root / "release-backups"
    if release_dir.is_dir():
        history = [
            path for path in release_dir.iterdir()
            if not path.is_symlink()
            and not path.name.startswith("pre-v1.4.0-offline-sync-")
            and (path.is_dir() or path.is_file())
        ]
        history.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
        candidates.extend(history[3:])
    return sorted(candidates, key=lambda item: item.relative_to(data_root).as_posix())


def legacy_cleanup_preview(data_root: Path) -> dict:
    data_root = data_root.resolve()
    candidates = _legacy_cleanup_candidates(data_root)
    items = [
        {
            "path": path.relative_to(data_root).as_posix(),
            "bytes": _tree_bytes(path),
            "modified_at": iso_utc(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)),
        }
        for path in candidates
    ]
    fingerprint = hashlib.sha256(
        "\n".join(
            f"{item['path']}:{item['bytes']}:{candidates[index].stat().st_mtime_ns}"
            for index, item in enumerate(items)
        ).encode("utf-8")
    ).hexdigest()
    return {
        "preview_id": fingerprint,
        "required_confirm_text": "清理旧备份",
        "candidate_count": len(items),
        "reclaimable_bytes": sum(item["bytes"] for item in items),
        "items": items[:200],
        "preserved": "保留最新 3 个旧式业务备份、最新 3 个发布检查点、全部 v2 备份和 v1.4.0 实施前检查点。",
    }


def cleanup_legacy_backups(data_root: Path, *, preview_id: str, confirm_text: str) -> dict:
    root = data_root.resolve()
    preview = legacy_cleanup_preview(root)
    if confirm_text.strip() != preview["required_confirm_text"]:
        raise BackupError("清理确认文本不正确")
    if not preview_id or preview_id != preview["preview_id"]:
        raise BackupError("旧备份列表已变化，请重新预览")
    removed: list[str] = []
    reclaimed = 0
    allowed_parents = {(root / "backups").resolve(), (root / "release-backups").resolve()}
    for path in _legacy_cleanup_candidates(root):
        resolved = path.resolve()
        if resolved.parent not in allowed_parents or path.is_symlink():
            raise BackupError("旧备份清理路径超出允许范围")
        size = _tree_bytes(path)
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        reclaimed += size
        removed.append(relative)
    return {"removed_count": len(removed), "reclaimed_bytes": reclaimed, "removed": removed}
