import hashlib
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.services.backup_service import (
    BackupError,
    cleanup_legacy_backups,
    create_backup_archive,
    extract_backup_archive,
    inspect_backup_archive,
    legacy_cleanup_preview,
)


def make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO records(value) VALUES ('consistent')")
        connection.commit()
    finally:
        connection.close()


def test_v2_backup_is_complete_hashed_and_excludes_backup_recursion(tmp_path):
    database = tmp_path / "component_warehouse.db"
    make_database(database)
    attachment = tmp_path / "custom-labels" / "personal" / "1" / "asset.svg"
    attachment.parent.mkdir(parents=True)
    attachment.write_text("<svg/>", encoding="utf-8")
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE custom_label_assets (id TEXT PRIMARY KEY, storage_path TEXT NOT NULL, sha256 TEXT)")
    connection.execute(
        "INSERT INTO custom_label_assets VALUES (?, ?, ?)",
        ("asset-1", str(attachment), hashlib.sha256(attachment.read_bytes()).hexdigest()),
    )
    connection.commit()
    connection.close()
    recursive = tmp_path / "release-backups" / "old.db"
    recursive.parent.mkdir()
    recursive.write_bytes(b"must-not-be-included")
    old_backup = tmp_path / "backups" / "old.zip"
    old_backup.parent.mkdir()
    old_backup.write_bytes(b"must-not-be-included")

    artifact = create_backup_archive(
        database_url=f"sqlite:///{database}",
        app_name="component-warehouse",
        app_version="1.4.0",
        exported_by_user_id=1,
        server_instance_id="server-test",
        sync_cursor=12,
        output_dir=tmp_path / "backups",
    )
    inspection = inspect_backup_archive(
        artifact.path,
        expected_app_names={"component-warehouse"},
        max_upload_bytes=128 * 1024 * 1024,
    )
    assert inspection.format_version == "v2"
    assert inspection.scope == "server-full"
    assert inspection.table_count == 2
    assert inspection.manifest["sync_cursor"] == 12
    declared = {row["path"] for row in inspection.manifest["files"]}
    assert "data/custom-labels/personal/1/asset.svg" in declared
    assert all("release-backups" not in name and "backups/old.zip" not in name for name in declared)
    extracted = extract_backup_archive(inspection, tmp_path / "extracted")
    assert (extracted / "database" / "component_warehouse.snapshot.db").is_file()
    assert (extracted / "data" / "custom-labels" / "personal" / "1" / "asset.svg").read_text() == "<svg/>"


def test_v2_backup_rejects_manifest_hash_tampering(tmp_path):
    database = tmp_path / "component_warehouse.db"
    make_database(database)
    artifact = create_backup_archive(
        database_url=f"sqlite:///{database}",
        app_name="component-warehouse",
        app_version="1.4.0",
        output_dir=tmp_path,
    )
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(artifact.path) as source, zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(content)
                manifest["files"][0]["sha256"] = "0" * 64
                content = json.dumps(manifest).encode()
            target.writestr(info.filename, content)
    with pytest.raises(BackupError, match="SHA256"):
        inspect_backup_archive(
            tampered,
            expected_app_names={"component-warehouse"},
            max_upload_bytes=128 * 1024 * 1024,
        )


def test_v2_backup_rejects_missing_referenced_attachment(tmp_path):
    database = tmp_path / "component_warehouse.db"
    make_database(database)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE eda_assets (id TEXT PRIMARY KEY, storage_path TEXT NOT NULL, sha256 TEXT)")
    connection.execute(
        "INSERT INTO eda_assets VALUES (?, ?, ?)",
        ("missing", "objects/aa/missing.zip", "0" * 64),
    )
    connection.commit()
    connection.close()
    with pytest.raises(BackupError, match="不存在"):
        create_backup_archive(
            database_url=f"sqlite:///{database}",
            app_name="component-warehouse",
            app_version="1.4.0",
            output_dir=tmp_path / "backups",
        )


def test_backup_inspection_rejects_traversal_bomb_and_corrupt_database(tmp_path):
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape", b"bad")
    with pytest.raises(BackupError, match="不安全路径"):
        inspect_backup_archive(traversal, expected_app_names={"component-warehouse"}, max_upload_bytes=64 * 1024**2)

    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("huge.bin", b"0" * (11 * 1024**2))
    with pytest.raises(BackupError, match="压缩比异常"):
        inspect_backup_archive(bomb, expected_app_names={"component-warehouse"}, max_upload_bytes=64 * 1024**2)

    corrupt = tmp_path / "corrupt.zip"
    payload = b"not-a-sqlite-database"
    manifest = {
        "format": "cwbackup/v2",
        "format_version": 2,
        "app": "component-warehouse",
        "scope": "server-full",
        "files": [{
            "path": "database/component_warehouse.snapshot.db",
            "role": "database",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }],
    }
    with zipfile.ZipFile(corrupt, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("database/component_warehouse.snapshot.db", payload)
        archive.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(BackupError, match="损坏"):
        inspect_backup_archive(corrupt, expected_app_names={"component-warehouse"}, max_upload_bytes=64 * 1024**2)


def test_legacy_cleanup_requires_fresh_preview_and_preserves_recent_checkpoints(tmp_path):
    backup_root = tmp_path / "backups"
    release_root = tmp_path / "release-backups"
    backup_root.mkdir()
    release_root.mkdir()
    for index in range(6):
        backup = backup_root / f"auto-legacy-{index}.zip"
        backup.write_bytes(bytes([index]) * (index + 1))
        release = release_root / f"direct-host-{index}"
        release.mkdir()
        (release / "snapshot.db").write_bytes(bytes([index]) * (index + 2))
        os.utime(backup, (1000 + index, 1000 + index))
        os.utime(release, (1000 + index, 1000 + index))
    checkpoint = release_root / "pre-v1.4.0-offline-sync-test"
    checkpoint.mkdir()
    (checkpoint / "component_warehouse.db").write_bytes(b"checkpoint")

    preview = legacy_cleanup_preview(tmp_path)
    assert preview["candidate_count"] == 6
    assert checkpoint.exists()
    with pytest.raises(BackupError, match="重新预览"):
        cleanup_legacy_backups(tmp_path, preview_id="stale", confirm_text="清理旧备份")
    result = cleanup_legacy_backups(
        tmp_path,
        preview_id=preview["preview_id"],
        confirm_text=preview["required_confirm_text"],
    )
    assert result["removed_count"] == 6
    assert len(list(backup_root.iterdir())) == 3
    assert len([path for path in release_root.iterdir() if path.name.startswith("direct-host-")]) == 3
    assert checkpoint.exists()
