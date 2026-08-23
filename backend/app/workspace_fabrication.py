from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import AuthContext, require_access
from .database import SessionLocal, get_db
from .models import (
    Component,
    EdaAsset,
    EdaAttachmentLink,
    PersonalProjectAssemblyOperationV2,
    PersonalProjectAssemblyPlacementV2,
    PersonalProjectBoardV2,
    PersonalProjectBomItemV2,
    PersonalProjectFabricationLayerV2,
    PersonalProjectFabricationRevisionV2,
    PersonalProjectSolderPointV2,
    PersonalProjectV2,
    PersonalProjectVersionV2,
)
from .personal_projects_v2 import (
    apply_solder_transition,
    clean_designators,
    create_points_for_board,
    new_id,
    require_project,
    require_version,
)
from .services.eda_storage import (
    consume_stage,
    hash_already_counted,
    resolve_asset_path,
    stage_upload,
    storage_root,
    validate_disk_capacity,
    validate_quota,
)
from .services.fabrication_parser import (
    FabricationParseError,
    normalized_designator,
    parse_fabrication_package_isolated,
)


router = APIRouter(prefix="/api/project-workspace", tags=["personal-project-fabrication-v2"])
_WORKER_EVENT = threading.Event()
_WORKER_LOCK = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None
REVISION_MUTABLE_STATUSES = {"uploaded", "queued", "parsing", "mapping_required", "review", "failed"}


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def json_load(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (json.JSONDecodeError, TypeError):
        return default


def require_scope(
    db: Session,
    project_id: str,
    version_id: str,
    auth: AuthContext,
) -> tuple[PersonalProjectV2, PersonalProjectVersionV2]:
    project = require_project(db, project_id, auth)
    return project, require_version(db, project, version_id)


def revision_for_scope(
    db: Session,
    project: PersonalProjectV2,
    version: PersonalProjectVersionV2,
    revision_id: str,
) -> PersonalProjectFabricationRevisionV2:
    row = db.query(PersonalProjectFabricationRevisionV2).filter(
        PersonalProjectFabricationRevisionV2.id == revision_id,
        PersonalProjectFabricationRevisionV2.project_id == project.id,
        PersonalProjectFabricationRevisionV2.version_id == version.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="制造文件修订不存在")
    return row


def layer_out(row: PersonalProjectFabricationLayerV2) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_name": row.source_name,
        "role": row.role,
        "side": row.side,
        "svg_markup": row.svg_markup,
        "bounds": json_load(row.bounds_json, {}),
    }


def placement_out(row: PersonalProjectAssemblyPlacementV2) -> dict[str, Any]:
    return {
        "id": row.id,
        "bom_item_id": row.bom_item_id,
        "designator": row.designator,
        "designator_key": row.designator_key,
        "board_side": row.board_side,
        "x_mm": row.x_mm,
        "y_mm": row.y_mm,
        "rotation_deg": row.rotation_deg,
        "source_x_mm": row.source_x_mm,
        "source_y_mm": row.source_y_mm,
        "source_rotation_deg": row.source_rotation_deg,
        "source_board_side": row.source_board_side,
        "value": row.value,
        "model": row.model,
        "footprint": row.footprint,
        "dnp": bool(row.dnp),
        "positioned": bool(row.positioned),
        "match_status": row.match_status,
        "source": row.source,
        "confidence": row.confidence,
        "manually_adjusted": bool(row.manually_adjusted),
    }


def revision_out(db: Session, row: PersonalProjectFabricationRevisionV2, *, preview: bool = False) -> dict[str, Any]:
    result = {
        "id": row.id,
        "project_id": row.project_id,
        "version_id": row.version_id,
        "revision_number": row.revision_number,
        "status": row.status,
        "detected_profile": row.detected_profile,
        "source_sha256": row.source_sha256,
        "mapping": json_load(row.mapping_json, {}),
        "summary": json_load(row.summary_json, {}),
        "warnings": json_load(row.warning_json, []),
        "error_message": row.error_message,
        "bounds": json_load(row.bounds_json, {}),
        "calibration": json_load(row.calibration_json, {}),
        "ai_assisted": bool(row.ai_assisted),
        "parsed_at": row.parsed_at,
        "committed_at": row.committed_at,
        "archived_at": row.archived_at,
        "created_at": row.created_at,
    }
    if preview:
        result["layers"] = [
            layer_out(item) for item in db.query(PersonalProjectFabricationLayerV2).filter(
                PersonalProjectFabricationLayerV2.revision_id == row.id
            ).order_by(PersonalProjectFabricationLayerV2.created_at.asc()).all()
        ]
        result["placements"] = [
            placement_out(item) for item in db.query(PersonalProjectAssemblyPlacementV2).filter(
                PersonalProjectAssemblyPlacementV2.revision_id == row.id
            ).order_by(PersonalProjectAssemblyPlacementV2.designator.asc()).all()
        ]
    return result


def create_asset(
    db: Session,
    metadata: dict[str, Any],
    project: PersonalProjectV2,
    auth: AuthContext,
) -> EdaAsset:
    row = EdaAsset(
        id=new_id(),
        scope_type="personal",
        owner_user_id=project.owner_user_id,
        team_library_id=None,
        library_version_id=None,
        asset_type=metadata["asset_type"],
        original_name=metadata["original_name"],
        storage_path=metadata["storage_path"],
        sha256=metadata["sha256"],
        byte_size=int(metadata["byte_size"]),
        mime_type=metadata.get("mime_type"),
        verification_status="raw",
        status="active",
        uploaded_by_user_id=auth.user_id,
    )
    db.add(row)
    db.flush()
    return row


def supplements(db: Session, revision_id: str) -> list[tuple[str, bytes]]:
    rows = db.query(EdaAsset).join(EdaAttachmentLink, EdaAttachmentLink.asset_id == EdaAsset.id).filter(
        EdaAttachmentLink.entity_type == "personal_project_fabrication_revision_v2",
        EdaAttachmentLink.entity_id == revision_id,
        EdaAttachmentLink.relation_type == "supplement",
        EdaAsset.status == "active",
    ).all()
    return [(item.original_name, resolve_asset_path(item.storage_path).read_bytes()) for item in rows]


def persist_svg(
    db: Session,
    revision: PersonalProjectFabricationRevisionV2,
    source_name: str,
    markup: str | None,
) -> EdaAsset | None:
    if not markup:
        return None
    project = db.get(PersonalProjectV2, revision.project_id)
    if not project:
        raise FabricationParseError("制造文件所属项目不存在")
    data = markup.encode("utf-8")
    sha256 = hashlib.sha256(data).hexdigest()
    increment = 0 if hash_already_counted(db, "personal", project.owner_user_id, None, sha256) else len(data)
    validate_quota(db, "personal", project.owner_user_id, None, increment)
    validate_disk_capacity(increment)
    directory = storage_root() / "objects" / sha256[:2]
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{sha256}.svg"
    if not target.exists():
        temporary = directory / f".{sha256}.{uuid.uuid4().hex}.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, target)
    asset = EdaAsset(
        id=new_id(), scope_type="personal", owner_user_id=project.owner_user_id,
        team_library_id=None, library_version_id=None, asset_type="image",
        original_name=f"M{revision.revision_number}-{Path(source_name).name}.svg"[:300],
        storage_path=target.relative_to(storage_root()).as_posix(), sha256=sha256,
        byte_size=len(data), mime_type="image/svg+xml", verification_status="verified",
        status="active", uploaded_by_user_id=revision.created_by_user_id,
    )
    db.add(asset)
    db.flush()
    db.add(EdaAttachmentLink(
        id=new_id(), asset_id=asset.id, entity_type="personal_project_fabrication_revision_v2",
        entity_id=revision.id, relation_type="derived_layer", created_by_user_id=revision.created_by_user_id,
    ))
    return asset


def process_workspace_revision(db: Session, revision: PersonalProjectFabricationRevisionV2) -> None:
    revision.status = "parsing"
    revision.error_message = None
    db.commit()
    try:
        source = db.get(EdaAsset, revision.source_asset_id)
        if not source or source.status != "active":
            raise FabricationParseError("制造包原文件不存在或已进入回收站")
        result = parse_fabrication_package_isolated(
            resolve_asset_path(source.storage_path),
            json_load(revision.mapping_json, {}) or None,
            allow_ai=not bool(json_load(revision.mapping_json, {})),
            supplements=supplements(db, revision.id),
        )
        old_assets = db.query(EdaAsset).join(EdaAttachmentLink, EdaAttachmentLink.asset_id == EdaAsset.id).filter(
            EdaAttachmentLink.entity_type == "personal_project_fabrication_revision_v2",
            EdaAttachmentLink.entity_id == revision.id,
            EdaAttachmentLink.relation_type == "derived_layer",
            EdaAsset.status == "active",
        ).all()
        for asset in old_assets:
            asset.status = "trash"
            asset.archived_at = datetime.utcnow()
            asset.purge_after = datetime.utcnow() + timedelta(days=30)
        db.query(EdaAttachmentLink).filter(
            EdaAttachmentLink.entity_type == "personal_project_fabrication_revision_v2",
            EdaAttachmentLink.entity_id == revision.id,
            EdaAttachmentLink.relation_type == "derived_layer",
        ).delete(synchronize_session=False)
        db.query(PersonalProjectFabricationLayerV2).filter(
            PersonalProjectFabricationLayerV2.revision_id == revision.id
        ).delete(synchronize_session=False)
        db.query(PersonalProjectAssemblyPlacementV2).filter(
            PersonalProjectAssemblyPlacementV2.revision_id == revision.id
        ).delete(synchronize_session=False)
        db.flush()
        for item in result["layers"]:
            svg = persist_svg(db, revision, item["source_name"], item.get("svg_markup"))
            db.add(PersonalProjectFabricationLayerV2(
                id=new_id(), revision_id=revision.id, source_name=item["source_name"][:300],
                role=item["role"], side=item["side"], svg_asset_id=svg.id if svg else None,
                svg_markup=item.get("svg_markup"), bounds_json=json_dump(item.get("bounds") or {}),
                byte_size=int(item.get("byte_size") or 0), sha256=item.get("sha256"),
            ))
        for item in result["placements"]:
            db.add(PersonalProjectAssemblyPlacementV2(
                id=new_id(), revision_id=revision.id, designator=str(item["designator"])[:80],
                designator_key=str(item["designator_key"])[:80], board_side=item.get("board_side") or "top",
                x_mm=item.get("x_mm"), y_mm=item.get("y_mm"), rotation_deg=float(item.get("rotation_deg") or 0),
                source_x_mm=item.get("x_mm"), source_y_mm=item.get("y_mm"),
                source_rotation_deg=float(item.get("rotation_deg") or 0), source_board_side=item.get("board_side") or "top",
                value=str(item.get("value") or "")[:200] or None, model=str(item.get("model") or "")[:300] or None,
                footprint=str(item.get("footprint") or "")[:200] or None, dnp=bool(item.get("dnp")),
                positioned=bool(item.get("positioned")), match_status=str(item.get("match_status") or "unmatched")[:32],
                source=str(item.get("source") or "cpl")[:32], confidence=str(item.get("confidence") or "deterministic")[:20],
            ))
        revision.detected_profile = result["profile"]
        revision.mapping_json = json_dump(result["mapping"])
        revision.summary_json = json_dump({**result["summary"], "files": result["files"]})
        revision.warning_json = json_dump(result["warnings"])
        revision.bounds_json = json_dump(result["bounds"])
        revision.ai_assisted = bool(result["ai_assisted"])
        revision.parsed_at = datetime.utcnow()
        revision.status = "mapping_required" if result["mapping_required"] else "review"
        db.commit()
    except BaseException as exc:
        db.rollback()
        failed = db.get(PersonalProjectFabricationRevisionV2, revision.id)
        if failed:
            failed.status = "failed"
            failed.error_message = str(exc)[:2000]
            db.commit()


def _worker_loop() -> None:
    while True:
        db = SessionLocal()
        found = False
        try:
            row = db.query(PersonalProjectFabricationRevisionV2).filter(
                PersonalProjectFabricationRevisionV2.status == "queued"
            ).order_by(PersonalProjectFabricationRevisionV2.created_at.asc()).first()
            if row:
                found = True
                process_workspace_revision(db, row)
        finally:
            db.close()
        if not found:
            _WORKER_EVENT.wait(2)
            _WORKER_EVENT.clear()


def ensure_workspace_fabrication_worker() -> None:
    global _WORKER_THREAD
    if os.getenv("FABRICATION_WORKER_ENABLED", "1") != "1":
        return
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        db = SessionLocal()
        try:
            db.query(PersonalProjectFabricationRevisionV2).filter(
                PersonalProjectFabricationRevisionV2.status == "parsing"
            ).update({PersonalProjectFabricationRevisionV2.status: "queued"}, synchronize_session=False)
            db.commit()
        finally:
            db.close()
        _WORKER_THREAD = threading.Thread(target=_worker_loop, name="workspace-fabrication-parser", daemon=True)
        _WORKER_THREAD.start()
        _WORKER_EVENT.set()


def notify_worker() -> None:
    _WORKER_EVENT.set()


@router.post("/projects/{project_id}/versions/{version_id}/fabrication-revisions")
async def upload_revision(
    project_id: str,
    version_id: str,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    del request
    project, version = require_scope(db, project_id, version_id, auth)
    if Path(file.filename or "").suffix.lower() != ".zip":
        raise HTTPException(status_code=422, detail="Gerber 制造包必须为 ZIP 文件")
    staged = await stage_upload(
        db, file, scope_type="personal", owner_user_id=project.owner_user_id,
        team_library_id=None, maximum_bytes=200 * 1024**2,
    )
    published = consume_stage(
        staged["token"], scope_type="personal", owner_user_id=project.owner_user_id, team_library_id=None,
    )
    asset = create_asset(db, published, project, auth)
    number = int(db.query(func.max(PersonalProjectFabricationRevisionV2.revision_number)).filter(
        PersonalProjectFabricationRevisionV2.version_id == version.id
    ).scalar() or 0) + 1
    row = PersonalProjectFabricationRevisionV2(
        id=new_id(), project_id=project.id, version_id=version.id, source_asset_id=asset.id,
        revision_number=number, status="queued", source_sha256=asset.sha256,
        calibration_json=json_dump({"offset_x_mm": 0, "offset_y_mm": 0, "rotation_deg": 0, "mirror": False}),
        created_by_user_id=auth.user_id,
    )
    db.add(row)
    db.flush()
    db.add(EdaAttachmentLink(
        id=new_id(), asset_id=asset.id, entity_type="personal_project_fabrication_revision_v2",
        entity_id=row.id, relation_type="source", created_by_user_id=auth.user_id,
    ))
    db.commit()
    notify_worker()
    return revision_out(db, row)


@router.get("/projects/{project_id}/versions/{version_id}/fabrication-revisions")
def list_revisions(
    project_id: str, version_id: str,
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    rows = db.query(PersonalProjectFabricationRevisionV2).filter(
        PersonalProjectFabricationRevisionV2.project_id == project.id,
        PersonalProjectFabricationRevisionV2.version_id == version.id,
    ).order_by(PersonalProjectFabricationRevisionV2.revision_number.desc()).all()
    return [revision_out(db, row) for row in rows]


@router.get("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}")
def revision_detail(
    project_id: str, version_id: str, revision_id: str,
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    return revision_out(db, revision_for_scope(db, project, version, revision_id), preview=True)


@router.post("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}/mapping")
def update_mapping(
    project_id: str, version_id: str, revision_id: str, payload: dict[str, Any],
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    row = revision_for_scope(db, project, version, revision_id)
    if row.status not in REVISION_MUTABLE_STATUSES:
        raise HTTPException(status_code=409, detail="已启用或归档的制造文件不能修改映射")
    mapping = payload.get("mapping") if isinstance(payload.get("mapping"), dict) else payload
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=422, detail="映射格式无效")
    row.mapping_json = json_dump(mapping)
    row.status = "queued"
    row.error_message = None
    db.commit()
    notify_worker()
    return revision_out(db, row)


@router.post("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}/supplements")
async def upload_supplement(
    project_id: str, version_id: str, revision_id: str,
    file: UploadFile = File(...), auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    row = revision_for_scope(db, project, version, revision_id)
    if row.status not in REVISION_MUTABLE_STATUSES:
        raise HTTPException(status_code=409, detail="当前制造文件不能补传资料")
    if Path(file.filename or "").suffix.lower() not in {".csv", ".txt", ".pos", ".xlsx"}:
        raise HTTPException(status_code=422, detail="仅支持补传 CSV、TXT、POS 或 XLSX 格式的 BOM/CPL")
    staged = await stage_upload(db, file, scope_type="personal", owner_user_id=project.owner_user_id, team_library_id=None)
    published = consume_stage(staged["token"], scope_type="personal", owner_user_id=project.owner_user_id, team_library_id=None)
    asset = create_asset(db, published, project, auth)
    db.add(EdaAttachmentLink(
        id=new_id(), asset_id=asset.id, entity_type="personal_project_fabrication_revision_v2",
        entity_id=row.id, relation_type="supplement", created_by_user_id=auth.user_id,
    ))
    row.status = "queued"
    row.error_message = None
    db.commit()
    notify_worker()
    return revision_out(db, row)


def placements_for(db: Session, revision_id: str) -> list[PersonalProjectAssemblyPlacementV2]:
    return db.query(PersonalProjectAssemblyPlacementV2).filter(
        PersonalProjectAssemblyPlacementV2.revision_id == revision_id
    ).order_by(PersonalProjectAssemblyPlacementV2.designator.asc()).all()


def compare_revision(
    db: Session,
    version: PersonalProjectVersionV2,
    row: PersonalProjectFabricationRevisionV2,
) -> dict[str, Any]:
    target = {(item.board_side, item.designator_key): item for item in placements_for(db, row.id) if not item.dnp}
    previous = db.get(PersonalProjectFabricationRevisionV2, version.active_fabrication_revision_id) if version.active_fabrication_revision_id else None
    source = {
        (item.board_side, item.designator_key): item
        for item in (placements_for(db, previous.id) if previous and previous.id != row.id else [])
        if not item.dnp
    }
    added, removed, moved, changed = [], [], [], []
    for key, item in target.items():
        old = source.get(key)
        if not old:
            added.append(placement_out(item))
        elif (old.model or "", old.footprint or "", old.value or "") != (item.model or "", item.footprint or "", item.value or ""):
            changed.append({"before": placement_out(old), "after": placement_out(item)})
        elif (old.x_mm, old.y_mm, old.rotation_deg) != (item.x_mm, item.y_mm, item.rotation_deg):
            moved.append({"before": placement_out(old), "after": placement_out(item)})
    for key, item in source.items():
        if key not in target:
            removed.append(placement_out(item))
    history_keys = {
        normalized_designator(point.designator)
        for point in db.query(PersonalProjectSolderPointV2).filter(
            PersonalProjectSolderPointV2.version_id == version.id,
            PersonalProjectSolderPointV2.state != "pending",
        ).all()
    }
    conflicts = [item for item in removed if item["designator_key"] in history_keys]
    return {
        "added": added, "removed": removed, "moved": moved, "changed": changed, "conflicts": conflicts,
        "summary": {
            "added": len(added), "removed": len(removed), "moved": len(moved),
            "changed": len(changed), "conflicts": len(conflicts),
        },
    }


@router.get("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}/diff")
def revision_diff(
    project_id: str, version_id: str, revision_id: str,
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    return compare_revision(db, version, revision_for_scope(db, project, version, revision_id))


def bom_designator_map(db: Session, version_id: str) -> dict[str, PersonalProjectBomItemV2]:
    result: dict[str, PersonalProjectBomItemV2] = {}
    rows = db.query(PersonalProjectBomItemV2).filter(
        PersonalProjectBomItemV2.version_id == version_id,
        PersonalProjectBomItemV2.archived_at.is_(None),
    ).all()
    for item in rows:
        for designator in clean_designators(item.designators, int(item.quantity_per_board or 1), f"I{item.id[:4].upper()}-"):
            result.setdefault(normalized_designator(designator), item)
    return result


def reconcile_revision(
    db: Session,
    project: PersonalProjectV2,
    version: PersonalProjectVersionV2,
    row: PersonalProjectFabricationRevisionV2,
    *,
    accept_conflicts: bool,
) -> dict[str, Any]:
    diff = compare_revision(db, version, row)
    if diff["conflicts"] and not accept_conflicts:
        raise HTTPException(status_code=409, detail={"message": "新制造文件与已有装配历史冲突", "diff": diff})
    boards = db.query(PersonalProjectBoardV2).filter(
        PersonalProjectBoardV2.version_id == version.id,
        PersonalProjectBoardV2.status != "archived",
    ).order_by(PersonalProjectBoardV2.board_number.asc()).all()
    if not boards:
        board = PersonalProjectBoardV2(
            id=new_id(), project_id=project.id, version_id=version.id, board_number=1,
            name=f"{version.version_code} · 第 1 块板", status="assembly",
        )
        db.add(board)
        db.flush()
        create_points_for_board(db, board)
        db.flush()
        boards = [board]
    by_designator = bom_designator_map(db, version.id)
    placements = placements_for(db, row.id)
    linked = unmatched = 0
    existing_points = db.query(PersonalProjectSolderPointV2).filter(
        PersonalProjectSolderPointV2.version_id == version.id
    ).all()
    for existing_point in existing_points:
        existing_point.active_for_assembly = False
    for placement in placements:
        item = by_designator.get(placement.designator_key)
        placement.bom_item_id = item.id if item else None
        if placement.dnp:
            placement.match_status = "dnp"
            continue
        if not item:
            placement.match_status = "cpl_only" if placement.positioned else "bom_only"
            unmatched += 1
            continue
        placement.match_status = "matched" if placement.positioned else "bom_only"
        for board in boards:
            point = db.query(PersonalProjectSolderPointV2).filter(
                PersonalProjectSolderPointV2.board_id == board.id,
                PersonalProjectSolderPointV2.bom_item_id == item.id,
                PersonalProjectSolderPointV2.designator == placement.designator,
            ).first()
            if not point:
                point = PersonalProjectSolderPointV2(
                    id=new_id(), project_id=project.id, version_id=version.id, board_id=board.id,
                    bom_item_id=item.id, designator=placement.designator,
                )
                db.add(point)
            point.board_side = placement.board_side
            point.assembly_placement_id = placement.id
            point.active_for_assembly = True
            linked += 1
    if version.active_fabrication_revision_id and version.active_fabrication_revision_id != row.id:
        previous = db.get(PersonalProjectFabricationRevisionV2, version.active_fabrication_revision_id)
        if previous:
            previous.status = "archived"
            previous.archived_at = datetime.utcnow()
    row.status = "active"
    row.committed_at = datetime.utcnow()
    row.archived_at = None
    version.active_fabrication_revision_id = row.id
    return {"linked_points": linked, "unmatched_placements": unmatched, "diff": diff}


@router.post("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}/commit")
@router.post("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}/activate")
def activate_revision(
    project_id: str, version_id: str, revision_id: str, payload: dict[str, Any] | None = None,
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    row = revision_for_scope(db, project, version, revision_id)
    if row.status not in {"review", "archived", "active"}:
        raise HTTPException(status_code=409, detail="制造文件尚未解析完成或仍需确认映射")
    result = reconcile_revision(db, project, version, row, accept_conflicts=bool((payload or {}).get("accept_conflicts")))
    db.commit()
    return {"revision": revision_out(db, row), "result": result}


@router.post("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}/archive")
def archive_revision(
    project_id: str, version_id: str, revision_id: str,
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    row = revision_for_scope(db, project, version, revision_id)
    if version.active_fabrication_revision_id == row.id:
        raise HTTPException(status_code=409, detail="当前启用的制造文件不能归档")
    row.status = "archived"
    row.archived_at = datetime.utcnow()
    db.commit()
    return revision_out(db, row)


@router.get("/projects/{project_id}/versions/{version_id}/assembly-view")
def assembly_view(
    project_id: str, version_id: str, side: str = "top", board_id: str | None = None,
    revision_id: str | None = None, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    revision_key = revision_id or version.active_fabrication_revision_id
    if not revision_key:
        return {
            "project": {"id": project.id, "name": project.name, "project_code": project.project_code},
            "version": {"id": version.id, "version_code": version.version_code},
            "revision": None, "boards": [], "placements": [], "layers": [],
            "stats": {"total": 0, "pending": 0, "soldered": 0, "losses": 0, "unpositioned": 0},
            "can_edit": True,
        }
    revision = revision_for_scope(db, project, version, revision_key)
    boards = db.query(PersonalProjectBoardV2).filter(
        PersonalProjectBoardV2.version_id == version.id
    ).order_by(PersonalProjectBoardV2.board_number.asc()).all()
    board = next((item for item in boards if item.id == board_id), None) if board_id else next(
        (item for item in boards if item.status != "archived"), boards[0] if boards else None
    )
    placements = [item for item in placements_for(db, revision.id) if side == "all" or item.board_side == side]
    points = db.query(PersonalProjectSolderPointV2).filter(
        PersonalProjectSolderPointV2.board_id == board.id,
        PersonalProjectSolderPointV2.active_for_assembly.is_(True),
    ).all() if board else []
    point_by_placement = {point.assembly_placement_id: point for point in points if point.assembly_placement_id}
    result_placements = []
    for placement in placements:
        data = placement_out(placement)
        point = point_by_placement.get(placement.id)
        if point:
            item = db.get(PersonalProjectBomItemV2, point.bom_item_id)
            component = db.get(Component, item.component_id) if item else None
            data.update({
                "point_id": point.id, "point_state": point.state, "state_version": point.state_version,
                "soldered": point.state == "soldered", "loss_count": 1 if point.state == "lost" else 0,
                "status": "unpositioned" if not placement.positioned else point.state,
                "component_id": component.id if component else None,
                "component_name": component.name if component else "未匹配物料",
                "stock_quantity": int(component.quantity or 0) if component else 0,
            })
        else:
            data.update({
                "point_id": None, "point_state": None, "state_version": 1, "soldered": False,
                "loss_count": 0, "status": "dnp" if placement.dnp else ("risk" if placement.positioned else "unpositioned"),
            })
        result_placements.append(data)
    layers = db.query(PersonalProjectFabricationLayerV2).filter(
        PersonalProjectFabricationLayerV2.revision_id == revision.id
    ).order_by(PersonalProjectFabricationLayerV2.created_at.asc()).all()
    return {
        "project": {"id": project.id, "name": project.name, "project_code": project.project_code},
        "version": {"id": version.id, "version_code": version.version_code},
        "revision": revision_out(db, revision),
        "boards": [{
            "id": item.id, "name": item.name, "status": item.status, "board_index": item.board_number,
        } for item in boards],
        "active_board_id": board.id if board else None,
        "placements": result_placements,
        "layers": [layer_out(item) for item in layers],
        "stats": {
            "total": len(result_placements),
            "pending": sum(1 for item in result_placements if item["status"] == "pending"),
            "soldered": sum(1 for item in result_placements if item["status"] == "soldered"),
            "losses": sum(int(item["loss_count"]) for item in result_placements),
            "unpositioned": sum(1 for item in result_placements if item["status"] == "unpositioned"),
        },
        "can_edit": True,
    }


@router.patch("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}/calibration")
def save_calibration(
    project_id: str, version_id: str, revision_id: str, payload: dict[str, Any],
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    row = revision_for_scope(db, project, version, revision_id)
    row.calibration_json = json_dump({
        "offset_x_mm": float(payload.get("offset_x_mm") or 0),
        "offset_y_mm": float(payload.get("offset_y_mm") or 0),
        "rotation_deg": float(payload.get("rotation_deg") or 0),
        "mirror": bool(payload.get("mirror")),
    })
    db.commit()
    return revision_out(db, row)


@router.patch("/projects/{project_id}/versions/{version_id}/fabrication-revisions/{revision_id}/placements/{placement_id}")
def save_placement(
    project_id: str, version_id: str, revision_id: str, placement_id: str, payload: dict[str, Any],
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    revision_for_scope(db, project, version, revision_id)
    row = db.query(PersonalProjectAssemblyPlacementV2).filter(
        PersonalProjectAssemblyPlacementV2.id == placement_id,
        PersonalProjectAssemblyPlacementV2.revision_id == revision_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="位号不存在")
    if payload.get("reset"):
        row.x_mm, row.y_mm = row.source_x_mm, row.source_y_mm
        row.rotation_deg, row.board_side = row.source_rotation_deg, row.source_board_side
        row.positioned, row.manually_adjusted = row.x_mm is not None and row.y_mm is not None, False
    else:
        for key in ("x_mm", "y_mm", "rotation_deg", "board_side"):
            if key in payload:
                setattr(row, key, payload[key])
        row.positioned = row.x_mm is not None and row.y_mm is not None
        row.manually_adjusted = True
    db.commit()
    return placement_out(row)


@router.post("/projects/{project_id}/versions/{version_id}/boards/batch")
def batch_create_boards(
    project_id: str, version_id: str, payload: dict[str, Any],
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    count = max(1, min(100, int(payload.get("count") or 1)))
    start = int(db.query(func.max(PersonalProjectBoardV2.board_number)).filter(
        PersonalProjectBoardV2.version_id == version.id
    ).scalar() or 0) + 1
    prefix = str(payload.get("name_prefix") or "").strip()
    rows = []
    for offset in range(count):
        number = start + offset
        board = PersonalProjectBoardV2(
            id=new_id(), project_id=project.id, version_id=version.id, board_number=number,
            name=f"{prefix} {number}" if prefix else f"{version.version_code} · 第 {number} 块板",
            status="assembly",
        )
        db.add(board)
        db.flush()
        create_points_for_board(db, board)
        rows.append(board)
    active = db.get(PersonalProjectFabricationRevisionV2, version.active_fabrication_revision_id) if version.active_fabrication_revision_id else None
    if active:
        reconcile_revision(db, project, version, active, accept_conflicts=True)
    db.commit()
    return {"created": len(rows), "boards": [{"id": row.id, "name": row.name, "status": row.status} for row in rows]}


@router.patch("/projects/{project_id}/versions/{version_id}/boards/{board_id}/assembly")
def update_board(
    project_id: str, version_id: str, board_id: str, payload: dict[str, Any],
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    row = db.query(PersonalProjectBoardV2).filter(
        PersonalProjectBoardV2.id == board_id,
        PersonalProjectBoardV2.project_id == project.id,
        PersonalProjectBoardV2.version_id == version.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="实物板不存在")
    if "name" in payload:
        row.name = str(payload["name"]).strip()[:120] or row.name
    if "status" in payload:
        status = str(payload["status"])
        row.status = {"active": "assembly", "completed": "completed", "archived": "archived"}.get(status, status)
    db.commit()
    return {"id": row.id, "name": row.name, "status": row.status}


def point_snapshot(point: PersonalProjectSolderPointV2) -> dict[str, Any]:
    return {"id": point.id, "state": point.state, "state_version": point.state_version}


@router.post("/projects/{project_id}/versions/{version_id}/assembly-actions")
def assembly_action(
    project_id: str, version_id: str, payload: dict[str, Any],
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    board_id = str(payload.get("board_id") or "")
    board = db.query(PersonalProjectBoardV2).filter(
        PersonalProjectBoardV2.id == board_id, PersonalProjectBoardV2.version_id == version.id
    ).first()
    if not board:
        raise HTTPException(status_code=404, detail="实物板不存在")
    key = str(payload.get("idempotency_key") or "")[:120]
    if not key:
        raise HTTPException(status_code=422, detail="缺少幂等键")
    existing = db.query(PersonalProjectAssemblyOperationV2).filter(
        PersonalProjectAssemblyOperationV2.project_id == project.id,
        PersonalProjectAssemblyOperationV2.idempotency_key == key,
    ).first()
    if existing:
        return {"operation_id": existing.id, "action": existing.action, "processed": len(json_load(existing.point_ids_json, []))}
    point_ids = [str(value) for value in payload.get("point_ids") or []]
    versions = {str(key): int(value) for key, value in (payload.get("versions") or {}).items()}
    points = db.query(PersonalProjectSolderPointV2).filter(
        PersonalProjectSolderPointV2.id.in_(point_ids),
        PersonalProjectSolderPointV2.board_id == board.id,
        PersonalProjectSolderPointV2.version_id == version.id,
        PersonalProjectSolderPointV2.active_for_assembly.is_(True),
    ).all()
    if len(points) != len(set(point_ids)):
        raise HTTPException(status_code=404, detail="部分焊点不存在或已失效")
    before = [point_snapshot(point) for point in points]
    for point in points:
        apply_solder_transition(db, project, version, point, str(payload.get("action") or ""), versions.get(point.id, -1), auth)
    operation = PersonalProjectAssemblyOperationV2(
        id=new_id(), project_id=project.id, version_id=version.id, board_id=board.id,
        actor_user_id=auth.user_id, idempotency_key=key, action=str(payload.get("action") or ""),
        point_ids_json=json_dump(point_ids), before_json=json_dump(before),
        after_json=json_dump([point_snapshot(point) for point in points]),
    )
    db.add(operation)
    db.commit()
    return {"operation_id": operation.id, "action": operation.action, "processed": len(points)}


@router.post("/projects/{project_id}/versions/{version_id}/assembly-actions/{operation_id}/undo")
def undo_action(
    project_id: str, version_id: str, operation_id: str, payload: dict[str, Any] | None = None,
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    del payload
    project, version = require_scope(db, project_id, version_id, auth)
    operation = db.query(PersonalProjectAssemblyOperationV2).filter(
        PersonalProjectAssemblyOperationV2.id == operation_id,
        PersonalProjectAssemblyOperationV2.project_id == project.id,
        PersonalProjectAssemblyOperationV2.version_id == version.id,
    ).first()
    if not operation:
        raise HTTPException(status_code=404, detail="装配操作不存在")
    if operation.undone_at:
        return {"operation_id": operation.id, "undone": True}
    inverse = {"solder": "unsolder", "unsolder": "solder", "loss": "undo_loss", "undo_loss": "loss"}.get(operation.action)
    if not inverse:
        raise HTTPException(status_code=409, detail="该操作不能撤销")
    points = db.query(PersonalProjectSolderPointV2).filter(
        PersonalProjectSolderPointV2.id.in_(json_load(operation.point_ids_json, []))
    ).all()
    for point in points:
        apply_solder_transition(db, project, version, point, inverse, point.state_version, auth)
    operation.undone_at = datetime.utcnow()
    operation.undone_by_user_id = auth.user_id
    db.commit()
    return {"operation_id": operation.id, "undone": True}


@router.patch("/projects/{project_id}/versions/{version_id}/assembly-actions/{operation_id}/note")
def update_action_note(
    project_id: str, version_id: str, operation_id: str, payload: dict[str, Any],
    auth: AuthContext = Depends(require_access), db: Session = Depends(get_db),
):
    project, version = require_scope(db, project_id, version_id, auth)
    operation = db.query(PersonalProjectAssemblyOperationV2).filter(
        PersonalProjectAssemblyOperationV2.id == operation_id,
        PersonalProjectAssemblyOperationV2.project_id == project.id,
        PersonalProjectAssemblyOperationV2.version_id == version.id,
    ).first()
    if not operation:
        raise HTTPException(status_code=404, detail="装配操作不存在")
    operation.note = str(payload.get("note") or "").strip()[:2000] or None
    db.commit()
    return {"operation_id": operation.id, "note": operation.note}
