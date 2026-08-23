from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .auth import AuthContext, require_access
from .database import SessionLocal, get_db
from .models import (
    ActivityLog,
    CompetitionActivityLog,
    CompetitionLibraryComponent,
    Component,
    EdaAsset,
    EdaAttachmentLink,
    Project,
    ProjectAssemblyLossEvent,
    ProjectAssemblyOperation,
    ProjectAssemblyPlacement,
    ProjectBoard,
    ProjectBomItem,
    ProjectBomSolderPoint,
    ProjectCodeAlias,
    ProjectFabricationLayer,
    ProjectFabricationRevision,
    ProjectPcbVersion,
    StockMovement,
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
from .services.stock_ledger import record_stock_delta
from .services.project_tracking import (
    active_version as active_project_version,
    append_material_cost_event,
    append_material_release_event,
    reverse_material_events_for_operation,
)
from .team import require_library_editor, require_library_member


router = APIRouter(tags=["project-assembly"])
_WORKER_EVENT = threading.Event()
_WORKER_LOCK = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None
REVISION_MUTABLE_STATUSES = {"uploaded", "queued", "parsing", "mapping_required", "review", "failed"}
LAYER_ORDER = {"outline": 0, "copper": 1, "mask": 2, "silk": 3, "other": 4}


def new_uuid() -> str:
    return str(uuid.uuid4())


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def json_load(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value) if value else default
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed


def request_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() or (request.client.host if request.client else ""))[:80]


def require_scoped_project(
    db: Session,
    project_id: int,
    auth: AuthContext,
    *,
    library_id: str | None = None,
    write: bool = False,
) -> tuple[Project, str | None]:
    if library_id:
        _, member = (
            require_library_editor(db, library_id, auth)
            if write
            else require_library_member(db, library_id, auth)
        )
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.scope_type == "team",
            Project.team_library_id == library_id,
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="团队项目不存在")
        return project, member.role
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.scope_type == "personal",
        Project.owner_user_id == auth.user_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project, "owner"


def scoped_project_route(
    db: Session,
    project_id: int,
    auth: AuthContext,
    library_id: str | None,
    *,
    write: bool,
) -> tuple[Project, str | None]:
    return require_scoped_project(db, project_id, auth, library_id=library_id, write=write)


def audit(
    db: Session,
    project: Project,
    auth: AuthContext,
    request: Request,
    action: str,
    summary: str,
    *,
    entity_type: str = "project",
    entity_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    quantity_delta: int | None = None,
) -> None:
    db.add(
        ActivityLog(
            owner_user_id=project.owner_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=int(entity_id) if str(entity_id or "").isdigit() else None,
            project_id=project.id,
            quantity_delta=quantity_delta,
            summary=summary[:300],
            detail=json_dump(detail) if detail is not None else None,
        )
    )
    if project.scope_type == "team" and project.team_library_id:
        db.add(
            CompetitionActivityLog(
                library_id=project.team_library_id,
                actor_user_id=auth.user_id,
                actor_nickname=auth.nickname[:80],
                actor_phone_last4=str(auth.phone or "")[-4:],
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                summary=summary[:300],
                after_json=json_dump(detail) if detail is not None else None,
                ip_address=request_ip(request),
            )
        )


def create_asset_from_stage(
    db: Session,
    metadata: dict[str, Any],
    *,
    auth: AuthContext,
    project: Project,
) -> EdaAsset:
    asset = EdaAsset(
        id=new_uuid(),
        scope_type=project.scope_type,
        owner_user_id=project.owner_user_id,
        team_library_id=project.team_library_id,
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
    db.add(asset)
    db.flush()
    return asset


def revision_out(revision: ProjectFabricationRevision, *, include_preview: bool = False) -> dict[str, Any]:
    result = {
        "id": revision.id,
        "project_id": revision.project_id,
        "pcb_version_id": revision.pcb_version_id,
        "revision_number": revision.revision_number,
        "status": revision.status,
        "detected_profile": revision.detected_profile,
        "source_sha256": revision.source_sha256,
        "mapping": json_load(revision.mapping_json, {}),
        "summary": json_load(revision.summary_json, {}),
        "warnings": json_load(revision.warning_json, []),
        "error_message": revision.error_message,
        "bounds": json_load(revision.bounds_json, {}),
        "calibration": json_load(revision.calibration_json, {}),
        "ai_assisted": bool(revision.ai_assisted),
        "parsed_at": revision.parsed_at,
        "committed_at": revision.committed_at,
        "archived_at": revision.archived_at,
        "created_at": revision.created_at,
    }
    if include_preview:
        result["placements"] = [placement_out(item) for item in revision.placements]
        result["layers"] = [layer_out(item) for item in revision.layers]
    return result


def layer_out(layer: ProjectFabricationLayer, *, public: bool = False) -> dict[str, Any]:
    result = {
        "id": layer.id,
        "role": layer.role,
        "side": layer.side,
        "svg_markup": layer.svg_markup,
        "bounds": json_load(layer.bounds_json, {}),
    }
    if not public:
        result["source_name"] = layer.source_name
    return result


def placement_out(placement: ProjectAssemblyPlacement) -> dict[str, Any]:
    return {
        "id": placement.id,
        "bom_item_id": placement.bom_item_id,
        "designator": placement.designator,
        "designator_key": placement.designator_key,
        "board_side": placement.board_side,
        "x_mm": placement.x_mm,
        "y_mm": placement.y_mm,
        "rotation_deg": placement.rotation_deg,
        "source_x_mm": placement.source_x_mm,
        "source_y_mm": placement.source_y_mm,
        "source_rotation_deg": placement.source_rotation_deg,
        "source_board_side": placement.source_board_side or placement.board_side,
        "value": placement.value,
        "model": placement.model,
        "footprint": placement.footprint,
        "dnp": bool(placement.dnp),
        "positioned": bool(placement.positioned),
        "match_status": placement.match_status,
        "source": placement.source,
        "confidence": placement.confidence,
        "manually_adjusted": bool(placement.manually_adjusted),
    }


def _supplement_files(db: Session, revision_id: str) -> list[tuple[str, bytes]]:
    rows = (
        db.query(EdaAsset)
        .join(EdaAttachmentLink, EdaAttachmentLink.asset_id == EdaAsset.id)
        .filter(
            EdaAttachmentLink.entity_type == "fabrication_revision",
            EdaAttachmentLink.entity_id == revision_id,
            EdaAttachmentLink.relation_type == "supplement",
            EdaAsset.status == "active",
        )
        .all()
    )
    return [(item.original_name, resolve_asset_path(item.storage_path).read_bytes()) for item in rows]


def persist_derived_svg(
    db: Session,
    revision: ProjectFabricationRevision,
    source_name: str,
    markup: str | None,
) -> EdaAsset | None:
    if not markup:
        return None
    project = db.get(Project, revision.project_id)
    if not project:
        raise FabricationParseError("制造版本所属项目不存在")
    data = markup.encode("utf-8")
    sha256 = hashlib.sha256(data).hexdigest()
    quota_increment = 0 if hash_already_counted(
        db, project.scope_type, project.owner_user_id, project.team_library_id, sha256
    ) else len(data)
    validate_quota(
        db, project.scope_type, project.owner_user_id, project.team_library_id, quota_increment
    )
    validate_disk_capacity(quota_increment)
    object_dir = storage_root() / "objects" / sha256[:2]
    object_dir.mkdir(parents=True, exist_ok=True)
    object_path = object_dir / f"{sha256}.svg"
    if not object_path.exists():
        temporary = object_dir / f".{sha256}.{uuid.uuid4().hex}.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, object_path)
    asset = EdaAsset(
        id=new_uuid(),
        scope_type=project.scope_type,
        owner_user_id=project.owner_user_id,
        team_library_id=project.team_library_id,
        asset_type="image",
        original_name=f"V{revision.revision_number}-{Path(source_name).name}.svg"[:300],
        storage_path=object_path.relative_to(storage_root()).as_posix(),
        sha256=sha256,
        byte_size=len(data),
        mime_type="image/svg+xml",
        verification_status="verified",
        status="active",
        uploaded_by_user_id=revision.created_by_user_id,
    )
    db.add(asset)
    db.flush()
    db.add(
        EdaAttachmentLink(
            id=new_uuid(),
            asset_id=asset.id,
            entity_type="fabrication_revision",
            entity_id=revision.id,
            relation_type="derived_layer",
            created_by_user_id=revision.created_by_user_id,
        )
    )
    return asset


def process_revision(db: Session, revision: ProjectFabricationRevision) -> None:
    revision.status = "parsing"
    revision.error_message = None
    db.commit()
    try:
        source = db.get(EdaAsset, revision.source_asset_id)
        if not source or source.status != "active":
            raise FabricationParseError("制造包原文件不存在或已进入回收站")
        mapping = json_load(revision.mapping_json, {})
        result = parse_fabrication_package_isolated(
            resolve_asset_path(source.storage_path),
            mapping or None,
            allow_ai=not bool(mapping),
            supplements=_supplement_files(db, revision.id),
        )
        old_layer_assets = (
            db.query(EdaAsset)
            .join(EdaAttachmentLink, EdaAttachmentLink.asset_id == EdaAsset.id)
            .filter(
                EdaAttachmentLink.entity_type == "fabrication_revision",
                EdaAttachmentLink.entity_id == revision.id,
                EdaAttachmentLink.relation_type == "derived_layer",
                EdaAsset.status == "active",
            )
            .all()
        )
        for asset in old_layer_assets:
            asset.status = "trash"
            asset.archived_at = datetime.utcnow()
            asset.purge_after = datetime.utcnow() + timedelta(days=30)
        db.query(EdaAttachmentLink).filter(
            EdaAttachmentLink.entity_type == "fabrication_revision",
            EdaAttachmentLink.entity_id == revision.id,
            EdaAttachmentLink.relation_type == "derived_layer",
        ).delete(synchronize_session=False)
        db.query(ProjectFabricationLayer).filter(
            ProjectFabricationLayer.revision_id == revision.id
        ).delete(synchronize_session=False)
        db.query(ProjectAssemblyPlacement).filter(
            ProjectAssemblyPlacement.revision_id == revision.id
        ).delete(synchronize_session=False)
        db.flush()
        for item in result["layers"]:
            svg_asset = persist_derived_svg(
                db, revision, item["source_name"], item.get("svg_markup")
            )
            db.add(
                ProjectFabricationLayer(
                    id=new_uuid(),
                    revision_id=revision.id,
                    source_name=item["source_name"][:300],
                    role=item["role"],
                    side=item["side"],
                    svg_asset_id=svg_asset.id if svg_asset else None,
                    svg_markup=item.get("svg_markup"),
                    bounds_json=json_dump(item.get("bounds") or {}),
                    byte_size=int(item.get("byte_size") or 0),
                    sha256=item.get("sha256"),
                )
            )
        for item in result["placements"]:
            db.add(
                ProjectAssemblyPlacement(
                    id=new_uuid(),
                    revision_id=revision.id,
                    designator=str(item["designator"])[:80],
                    designator_key=str(item["designator_key"])[:80],
                    board_side=item.get("board_side") or "top",
                    x_mm=item.get("x_mm"),
                    y_mm=item.get("y_mm"),
                    rotation_deg=float(item.get("rotation_deg") or 0),
                    source_x_mm=item.get("x_mm"),
                    source_y_mm=item.get("y_mm"),
                    source_rotation_deg=float(item.get("rotation_deg") or 0),
                    source_board_side=item.get("board_side") or "top",
                    value=str(item.get("value") or "")[:200] or None,
                    model=str(item.get("model") or "")[:300] or None,
                    footprint=str(item.get("footprint") or "")[:200] or None,
                    dnp=bool(item.get("dnp")),
                    positioned=bool(item.get("positioned")),
                    match_status=str(item.get("match_status") or "unmatched")[:32],
                    source=str(item.get("source") or "cpl")[:32],
                    confidence=str(item.get("confidence") or "deterministic")[:20],
                )
            )
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
        revision = db.get(ProjectFabricationRevision, revision.id)
        if revision:
            revision.status = "failed"
            revision.error_message = str(exc)[:2000]
            db.commit()


def _worker_loop() -> None:
    while True:
        found = False
        db = SessionLocal()
        try:
            revision = (
                db.query(ProjectFabricationRevision)
                .filter(ProjectFabricationRevision.status == "queued")
                .order_by(ProjectFabricationRevision.created_at.asc())
                .first()
            )
            if revision:
                found = True
                process_revision(db, revision)
        finally:
            db.close()
        if not found:
            _WORKER_EVENT.wait(2)
            _WORKER_EVENT.clear()


def ensure_fabrication_worker() -> None:
    global _WORKER_THREAD
    if os.getenv("FABRICATION_WORKER_ENABLED", "1") != "1":
        return
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        db = SessionLocal()
        try:
            recover_interrupted_revisions(db)
        finally:
            db.close()
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop, name="fabrication-parser", daemon=True
        )
        _WORKER_THREAD.start()
        _WORKER_EVENT.set()


def recover_interrupted_revisions(db: Session) -> int:
    recovered = db.query(ProjectFabricationRevision).filter(
        ProjectFabricationRevision.status == "parsing"
    ).update({ProjectFabricationRevision.status: "queued"}, synchronize_session=False)
    db.commit()
    return int(recovered or 0)


def notify_fabrication_worker() -> None:
    _WORKER_EVENT.set()


async def upload_revision_impl(
    project: Project,
    file: UploadFile,
    auth: AuthContext,
    request: Request,
    db: Session,
) -> dict[str, Any]:
    if Path(file.filename or "").suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="制造包必须是 ZIP 文件")
    metadata = await stage_upload(
        db,
        file,
        scope_type=project.scope_type,
        owner_user_id=project.owner_user_id,
        team_library_id=project.team_library_id,
        maximum_bytes=200 * 1024**2,
    )
    published = consume_stage(
        metadata["token"],
        scope_type=project.scope_type,
        owner_user_id=project.owner_user_id,
        team_library_id=project.team_library_id,
    )
    asset = create_asset_from_stage(db, published, auth=auth, project=project)
    number = int(
        db.query(func.max(ProjectFabricationRevision.revision_number))
        .filter(ProjectFabricationRevision.project_id == project.id)
        .scalar()
        or 0
    ) + 1
    revision = ProjectFabricationRevision(
        id=new_uuid(),
        project_id=project.id,
        pcb_version_id=(
            active_project_version(db, project, create_if_missing=True).id
            if project.scope_type == "personal"
            else None
        ),
        source_asset_id=asset.id,
        revision_number=number,
        status="queued",
        source_sha256=asset.sha256,
        calibration_json=json_dump(
            {"offset_x_mm": 0, "offset_y_mm": 0, "rotation_deg": 0, "mirror": False}
        ),
        created_by_user_id=auth.user_id,
    )
    db.add(revision)
    db.flush()
    db.add(
        EdaAttachmentLink(
            id=new_uuid(),
            asset_id=asset.id,
            entity_type="fabrication_revision",
            entity_id=revision.id,
            relation_type="source",
            created_by_user_id=auth.user_id,
        )
    )
    audit(
        db,
        project,
        auth,
        request,
        "fabrication.revision.upload",
        f"上传制造包 V{number}",
        entity_type="fabrication_revision",
        entity_id=revision.id,
        detail={"sha256": asset.sha256, "byte_size": asset.byte_size},
    )
    db.commit()
    db.refresh(revision)
    notify_fabrication_worker()
    return revision_out(revision)


@router.post("/api/projects/{project_id}/fabrication-revisions")
async def upload_personal_revision(
    project_id: int,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return await upload_revision_impl(project, file, auth, request, db)


@router.post("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions")
async def upload_team_revision(
    library_id: str,
    project_id: int,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return await upload_revision_impl(project, file, auth, request, db)


def list_revisions_impl(db: Session, project: Project) -> list[dict[str, Any]]:
    query = db.query(ProjectFabricationRevision).filter(ProjectFabricationRevision.project_id == project.id)
    if project.scope_type == "personal":
        version = active_project_version(db, project)
        if version:
            query = query.filter(ProjectFabricationRevision.pcb_version_id == version.id)
    rows = query.order_by(ProjectFabricationRevision.revision_number.desc()).all()
    return [revision_out(item) for item in rows]


@router.get("/api/projects/{project_id}/fabrication-revisions")
def list_personal_revisions(
    project_id: int,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth)
    return list_revisions_impl(db, project)


@router.get("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions")
def list_team_revisions(
    library_id: str,
    project_id: int,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id)
    return list_revisions_impl(db, project)


def revision_for_project(
    db: Session, project: Project, revision_id: str, *, preview: bool = False
) -> ProjectFabricationRevision:
    query = db.query(ProjectFabricationRevision)
    if preview:
        query = query.options(
            joinedload(ProjectFabricationRevision.layers),
            joinedload(ProjectFabricationRevision.placements),
        )
    revision = query.filter(
        ProjectFabricationRevision.id == revision_id,
        ProjectFabricationRevision.project_id == project.id,
    ).first()
    if not revision:
        raise HTTPException(status_code=404, detail="制造版本不存在")
    return revision


@router.get("/api/projects/{project_id}/fabrication-revisions/{revision_id}")
def personal_revision_detail(
    project_id: int,
    revision_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth)
    return revision_out(revision_for_project(db, project, revision_id, preview=True), include_preview=True)


@router.get("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}")
def team_revision_detail(
    library_id: str,
    project_id: int,
    revision_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id)
    return revision_out(revision_for_project(db, project, revision_id, preview=True), include_preview=True)


def compare_revision(db: Session, project: Project, revision: ProjectFabricationRevision) -> dict[str, Any]:
    target = {
        (item.board_side, item.designator_key): item
        for item in revision.placements
        if not item.dnp
    }
    previous = None
    version = db.get(ProjectPcbVersion, revision.pcb_version_id) if revision.pcb_version_id else None
    active_revision_id = version.active_fabrication_revision_id if version else project.active_fabrication_revision_id
    if active_revision_id and active_revision_id != revision.id:
        previous = revision_for_project(db, project, active_revision_id, preview=True)
    source = {
        (item.board_side, item.designator_key): item
        for item in (previous.placements if previous else [])
        if not item.dnp
    }
    added = []
    removed = []
    moved = []
    changed = []
    for key, item in target.items():
        old = source.get(key)
        if not old:
            added.append(placement_out(item))
            continue
        if (old.model or "", old.footprint or "", old.value or "") != (
            item.model or "",
            item.footprint or "",
            item.value or "",
        ):
            changed.append({"before": placement_out(old), "after": placement_out(item)})
        elif (old.x_mm, old.y_mm, old.rotation_deg) != (item.x_mm, item.y_mm, item.rotation_deg):
            moved.append({"before": placement_out(old), "after": placement_out(item)})
    for key, item in source.items():
        if key not in target:
            removed.append(placement_out(item))
    history_keys = {
        (point.board_side or "top", point.designator_key or normalized_designator(point.designator))
        for point in db.query(ProjectBomSolderPoint)
        .join(ProjectBomItem, ProjectBomItem.id == ProjectBomSolderPoint.bom_item_id)
        .filter(
            ProjectBomItem.project_id == project.id,
            ProjectBomItem.pcb_version_id == revision.pcb_version_id if revision.pcb_version_id is not None else True,
            (ProjectBomSolderPoint.stock_applied.is_(True)) | (ProjectBomSolderPoint.lost.is_(True)),
        )
        .all()
    }
    conflicts = [
        item for item in removed if (item["board_side"], item["designator_key"]) in history_keys
    ] + [
        item for item in changed if (item["before"]["board_side"], item["before"]["designator_key"]) in history_keys
    ]
    return {
        "base_revision_id": previous.id if previous else None,
        "target_revision_id": revision.id,
        "added": added,
        "removed": removed,
        "moved": moved,
        "changed": changed,
        "conflicts": conflicts,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "moved": len(moved),
            "changed": len(changed),
            "conflicts": len(conflicts),
        },
    }


@router.get("/api/projects/{project_id}/fabrication-revisions/{revision_id}/diff")
def personal_revision_diff(
    project_id: int,
    revision_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth)
    return compare_revision(db, project, revision_for_project(db, project, revision_id, preview=True))


@router.get("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}/diff")
def team_revision_diff(
    library_id: str,
    project_id: int,
    revision_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id)
    return compare_revision(db, project, revision_for_project(db, project, revision_id, preview=True))


def submit_mapping_impl(
    db: Session,
    project: Project,
    revision_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    revision = revision_for_project(db, project, revision_id)
    if revision.status in {"active", "archived"}:
        raise HTTPException(status_code=409, detail="已启用或归档版本不能修改映射")
    mapping = payload.get("mapping") if isinstance(payload.get("mapping"), dict) else payload
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="映射格式无效")
    revision.mapping_json = json_dump(mapping)
    revision.status = "queued"
    revision.error_message = None
    db.commit()
    notify_fabrication_worker()
    return revision_out(revision)


@router.post("/api/projects/{project_id}/fabrication-revisions/{revision_id}/mapping")
def personal_mapping(
    project_id: int,
    revision_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return submit_mapping_impl(db, project, revision_id, payload)


@router.post("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}/mapping")
def team_mapping(
    library_id: str,
    project_id: int,
    revision_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return submit_mapping_impl(db, project, revision_id, payload)


async def supplement_impl(
    db: Session,
    project: Project,
    revision_id: str,
    file: UploadFile,
    auth: AuthContext,
) -> dict[str, Any]:
    revision = revision_for_project(db, project, revision_id)
    if revision.status not in REVISION_MUTABLE_STATUSES:
        raise HTTPException(status_code=409, detail="当前制造版本不能补传文件")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".txt", ".pos", ".xlsx"}:
        raise HTTPException(status_code=400, detail="仅支持补传 CSV/TXT/POS/XLSX 格式的 BOM 或 CPL")
    metadata = await stage_upload(
        db,
        file,
        scope_type=project.scope_type,
        owner_user_id=project.owner_user_id,
        team_library_id=project.team_library_id,
    )
    published = consume_stage(
        metadata["token"],
        scope_type=project.scope_type,
        owner_user_id=project.owner_user_id,
        team_library_id=project.team_library_id,
    )
    asset = create_asset_from_stage(db, published, auth=auth, project=project)
    db.add(
        EdaAttachmentLink(
            id=new_uuid(),
            asset_id=asset.id,
            entity_type="fabrication_revision",
            entity_id=revision.id,
            relation_type="supplement",
            created_by_user_id=auth.user_id,
        )
    )
    revision.status = "queued"
    revision.error_message = None
    db.commit()
    notify_fabrication_worker()
    return revision_out(revision)


@router.post("/api/projects/{project_id}/fabrication-revisions/{revision_id}/supplements")
async def personal_supplement(
    project_id: int,
    revision_id: str,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return await supplement_impl(db, project, revision_id, file, auth)


@router.post("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}/supplements")
async def team_supplement(
    library_id: str,
    project_id: int,
    revision_id: str,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return await supplement_impl(db, project, revision_id, file, auth)


def item_by_designator(
    db: Session,
    project: Project,
    pcb_version_id: int | None = None,
) -> dict[str, ProjectBomItem]:
    query = (
        db.query(ProjectBomItem)
        .options(joinedload(ProjectBomItem.solder_points), joinedload(ProjectBomItem.component))
        .filter(ProjectBomItem.project_id == project.id)
    )
    if pcb_version_id is not None:
        query = query.filter(ProjectBomItem.pcb_version_id == pcb_version_id)
    items = query.all()
    result: dict[str, ProjectBomItem] = {}
    for item in items:
        for point in item.solder_points:
            key = point.designator_key or normalized_designator(point.designator)
            if key:
                result.setdefault(key, item)
        for match in re.finditer(
            r"(?:BOM\s*)?位号\s*[:：]\s*([^；;\n]+)",
            str(item.remark or ""),
            flags=re.IGNORECASE,
        ):
            for designator in re.split(r"[,，、\s]+", match.group(1)):
                key = normalized_designator(designator.strip().strip(";；"))
                if key and key != "-":
                    result.setdefault(key, item)
    return result


def identity_changed(point: ProjectBomSolderPoint, placement: ProjectAssemblyPlacement) -> bool:
    comparable = (
        (point.bom_model or "", placement.model or ""),
        (point.bom_footprint or "", placement.footprint or ""),
        (point.bom_value or "", placement.value or ""),
    )
    return any(old and new and old.strip().lower() != new.strip().lower() for old, new in comparable)


def reconcile_revision(
    db: Session,
    project: Project,
    revision: ProjectFabricationRevision,
    *,
    conflicts_accepted: bool,
) -> dict[str, Any]:
    diff = compare_revision(db, project, revision)
    if diff["conflicts"] and not conflicts_accepted:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "新版本包含已有消耗历史的删除或物料变化，请确认冲突后再启用",
                "diff": diff,
            },
        )
    by_key = item_by_designator(db, project, revision.pcb_version_id)
    board_query = db.query(ProjectBoard).filter(
        ProjectBoard.project_id == project.id,
        ProjectBoard.status != "archived",
    )
    if revision.pcb_version_id is not None:
        board_query = board_query.filter(ProjectBoard.pcb_version_id == revision.pcb_version_id)
    boards = board_query.all()
    if not boards:
        board = ProjectBoard(
            project_id=project.id,
            pcb_version_id=revision.pcb_version_id,
            board_index=1,
            name="第 1 板",
            status="active",
        )
        db.add(board)
        db.flush()
        boards = [board]
    project_points = (
        db.query(ProjectBomSolderPoint)
        .join(ProjectBomItem, ProjectBomItem.id == ProjectBomSolderPoint.bom_item_id)
        .filter(
            ProjectBomItem.project_id == project.id,
            ProjectBomItem.pcb_version_id == revision.pcb_version_id if revision.pcb_version_id is not None else True,
        )
        .all()
    )
    current_keys = set()
    created = linked = inactive = conflicts = 0
    for placement in revision.placements:
        item = by_key.get(placement.designator_key)
        placement.bom_item_id = item.id if item else None
        if placement.dnp:
            placement.match_status = "dnp"
            continue
        if not item:
            placement.match_status = "cpl_only" if placement.positioned else "bom_only"
            continue
        placement.match_status = "matched" if placement.positioned else "bom_only"
        for board in boards:
            stable = (board.id, placement.board_side, placement.designator_key)
            current_keys.add(stable)
            candidates = [
                point
                for point in project_points
                if point.board_id == board.id
                and point.bom_item_id == item.id
                and (point.designator_key or normalized_designator(point.designator)) == placement.designator_key
                and (point.board_side or placement.board_side) == placement.board_side
            ]
            candidates.sort(
                key=lambda candidate: (
                    candidate.assembly_placement_id == placement.id,
                    not identity_changed(candidate, placement),
                    bool(candidate.active_for_assembly),
                    bool(candidate.stock_applied or candidate.lost or candidate.loss_stock_applied),
                ),
                reverse=True,
            )
            point = candidates[0] if candidates else None
            has_history = bool(point and (point.stock_applied or point.lost or point.loss_stock_applied))
            if point and identity_changed(point, placement) and has_history:
                point.active_for_assembly = False
                point = None
                conflicts += 1
            if not point:
                point = ProjectBomSolderPoint(
                    bom_item_id=item.id,
                    board_id=board.id,
                    designator=placement.designator,
                    designator_key=placement.designator_key,
                    board_side=placement.board_side,
                    assembly_placement_id=placement.id,
                    active_for_assembly=True,
                    state_version=1,
                    bom_value=placement.value,
                    bom_model=placement.model,
                    bom_footprint=placement.footprint,
                )
                db.add(point)
                project_points.append(point)
                created += 1
            else:
                point.designator_key = placement.designator_key
                point.board_side = placement.board_side
                point.assembly_placement_id = placement.id
                point.active_for_assembly = True
                point.bom_value = placement.value or point.bom_value
                point.bom_model = placement.model or point.bom_model
                point.bom_footprint = placement.footprint or point.bom_footprint
                linked += 1
            for other in candidates:
                if other is not point and other.active_for_assembly:
                    other.active_for_assembly = False
                    inactive += 1
    for point in project_points:
        stable = (
            point.board_id,
            point.board_side or "top",
            point.designator_key or normalized_designator(point.designator),
        )
        if stable not in current_keys and point.active_for_assembly:
            point.active_for_assembly = False
            inactive += 1
    previous_active_query = db.query(ProjectFabricationRevision).filter(
        ProjectFabricationRevision.project_id == project.id,
        ProjectFabricationRevision.status == "active",
        ProjectFabricationRevision.id != revision.id,
    )
    if revision.pcb_version_id is not None:
        previous_active_query = previous_active_query.filter(
            ProjectFabricationRevision.pcb_version_id == revision.pcb_version_id
        )
    previous_active = previous_active_query.all()
    for old in previous_active:
        old.status = "archived"
        old.archived_at = datetime.utcnow()
    revision.status = "active"
    revision.committed_at = datetime.utcnow()
    revision.archived_at = None
    project.active_fabrication_revision_id = revision.id
    if revision.pcb_version_id:
        version = db.get(ProjectPcbVersion, revision.pcb_version_id)
        if version:
            version.active_fabrication_revision_id = revision.id
            project.active_pcb_version_id = version.id
    return {
        "created_points": created,
        "linked_points": linked,
        "inactive_points": inactive,
        "preserved_conflicts": conflicts,
        "diff": diff,
    }


def commit_revision_impl(
    db: Session,
    project: Project,
    revision_id: str,
    payload: dict[str, Any],
    auth: AuthContext,
    request: Request,
) -> dict[str, Any]:
    revision = revision_for_project(db, project, revision_id, preview=True)
    if revision.status not in {"review", "archived", "active"}:
        raise HTTPException(status_code=409, detail="制造版本尚未解析完成或仍需确认映射")
    result = reconcile_revision(
        db,
        project,
        revision,
        conflicts_accepted=bool(payload.get("accept_conflicts")),
    )
    audit(
        db,
        project,
        auth,
        request,
        "fabrication.revision.activate",
        f"启用制造版本 V{revision.revision_number}",
        entity_type="fabrication_revision",
        entity_id=revision.id,
        detail=result,
    )
    db.commit()
    return {"revision": revision_out(revision), "result": result}


@router.post("/api/projects/{project_id}/fabrication-revisions/{revision_id}/commit")
@router.post("/api/projects/{project_id}/fabrication-revisions/{revision_id}/activate")
def personal_commit_revision(
    project_id: int,
    revision_id: str,
    request: Request,
    payload: dict[str, Any] | None = None,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return commit_revision_impl(db, project, revision_id, payload or {}, auth, request)


@router.post("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}/commit")
@router.post("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}/activate")
def team_commit_revision(
    library_id: str,
    project_id: int,
    revision_id: str,
    request: Request,
    payload: dict[str, Any] | None = None,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return commit_revision_impl(db, project, revision_id, payload or {}, auth, request)


def archive_revision_impl(db: Session, project: Project, revision_id: str) -> dict[str, Any]:
    revision = revision_for_project(db, project, revision_id)
    revision_version = db.get(ProjectPcbVersion, revision.pcb_version_id) if revision.pcb_version_id else None
    active_revision_id = (
        revision_version.active_fabrication_revision_id
        if revision_version
        else project.active_fabrication_revision_id
    )
    if active_revision_id == revision.id:
        raise HTTPException(status_code=409, detail="当前启用版本不能归档，请先启用其他版本")
    revision.status = "archived"
    revision.archived_at = datetime.utcnow()
    db.commit()
    return revision_out(revision)


@router.post("/api/projects/{project_id}/fabrication-revisions/{revision_id}/archive")
def personal_archive_revision(
    project_id: int,
    revision_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return archive_revision_impl(db, project, revision_id)


@router.post("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}/archive")
def team_archive_revision(
    library_id: str,
    project_id: int,
    revision_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return archive_revision_impl(db, project, revision_id)


def loss_counts(db: Session, point_ids: list[int]) -> dict[int, int]:
    if not point_ids:
        return {}
    return {
        int(point_id): int(count)
        for point_id, count in db.query(
            ProjectAssemblyLossEvent.solder_point_id,
            func.count(ProjectAssemblyLossEvent.id),
        )
        .filter(
            ProjectAssemblyLossEvent.solder_point_id.in_(point_ids),
            ProjectAssemblyLossEvent.reversed_at.is_(None),
        )
        .group_by(ProjectAssemblyLossEvent.solder_point_id)
        .all()
    }


def assembly_view_impl(
    db: Session,
    project: Project,
    *,
    board_id: int | None,
    side: str,
    revision_id: str | None,
    public: bool = False,
    role: str | None = None,
) -> dict[str, Any]:
    version = active_project_version(db, project) if project.scope_type == "personal" else None
    revision_key = revision_id or (
        version.active_fabrication_revision_id if version else project.active_fabrication_revision_id
    )
    if not revision_key:
        return {
            "project": {"id": project.id, "name": project.name},
            "revision": None,
            "boards": [],
            "placements": [],
            "layers": [],
            "stats": {"total": 0, "soldered": 0, "pending": 0, "losses": 0},
            "can_edit": False if public else role != "viewer",
        }
    revision = revision_for_project(db, project, revision_key, preview=True)
    board_query = db.query(ProjectBoard).filter(ProjectBoard.project_id == project.id)
    if version:
        board_query = board_query.filter(ProjectBoard.pcb_version_id == version.id)
    boards = board_query.order_by(ProjectBoard.board_index.asc()).all()
    board = next((item for item in boards if item.id == board_id), None) if board_id else next(
        (item for item in boards if item.status != "archived"), boards[0] if boards else None
    )
    if public and board and board.status == "archived":
        raise HTTPException(status_code=404, detail="实物板不存在")
    placements = [item for item in revision.placements if side == "all" or item.board_side == side]
    placement_ids = {item.id for item in placements}
    points = []
    if board:
        points = (
            db.query(ProjectBomSolderPoint)
            .options(joinedload(ProjectBomSolderPoint.bom_item).joinedload(ProjectBomItem.component))
            .filter(
                ProjectBomSolderPoint.board_id == board.id,
                ProjectBomSolderPoint.assembly_placement_id.in_(placement_ids) if placement_ids else False,
                ProjectBomSolderPoint.active_for_assembly.is_(True),
            )
            .all()
        )
    point_by_placement = {point.assembly_placement_id: point for point in points}
    counts = loss_counts(db, [point.id for point in points])
    result_placements = []
    for placement in placements:
        data = placement_out(placement)
        if public:
            for private_key in (
                "bom_item_id",
                "designator_key",
                "source_x_mm",
                "source_y_mm",
                "source_rotation_deg",
                "source_board_side",
                "source",
                "confidence",
                "manually_adjusted",
            ):
                data.pop(private_key, None)
        point = point_by_placement.get(placement.id)
        if point:
            component = point.bom_item.component
            data.update(
                {
                    "point_id": point.id,
                    "state_version": int(point.state_version or 1),
                    "soldered": bool(point.soldered),
                    "loss_count": counts.get(point.id, 0),
                    "status": (
                        "unpositioned"
                        if not placement.positioned
                        else ("soldered" if point.soldered else "pending")
                    ),
                }
            )
            if not public:
                data.update(
                    {
                        "component_id": component.id,
                        "component_name": component.name,
                        "stock_quantity": int(component.quantity or 0),
                        "stock_owner_user_id": component.owner_user_id,
                    }
                )
            else:
                data.pop("point_id", None)
                data.pop("state_version", None)
        else:
            data.update(
                {
                    "point_id": None,
                    "state_version": None,
                    "soldered": False,
                    "loss_count": 0,
                    "status": "dnp" if placement.dnp else (
                        "unpositioned" if not placement.positioned else "risk"
                    ),
                }
            )
        if public:
            data.pop("point_id", None)
            data.pop("state_version", None)
        data["_has_point"] = bool(point)
        result_placements.append(data)
    progress_points = [item for item in result_placements if item["_has_point"] and item["positioned"] and not item["dnp"]]
    stats = {
        "total": len(progress_points),
        "soldered": sum(1 for item in progress_points if item["soldered"]),
        "pending": sum(1 for item in progress_points if not item["soldered"]),
        "losses": sum(int(item["loss_count"]) for item in result_placements),
        "dnp": sum(1 for item in result_placements if item["dnp"]),
        "unpositioned": sum(1 for item in result_placements if not item["positioned"]),
        "risks": sum(1 for item in result_placements if item["status"] == "risk"),
    }
    for item in result_placements:
        item.pop("_has_point", None)
    return {
        "project": {
            "name": project.name,
            "project_code": project.project_code if not public else None,
            "pcb_version_id": version.id if version and not public else None,
            "pcb_version_code": version.version_code if version and not public else None,
            "public_assembly_view_enabled": bool(project.public_assembly_view_enabled) if not public else True,
            **({"id": project.id} if not public else {}),
        },
        "revision": (
            {
                "id": revision.id,
                "revision_number": revision.revision_number,
                "detected_profile": revision.detected_profile,
                "bounds": json_load(revision.bounds_json, {}),
                "calibration": json_load(revision.calibration_json, {}),
            }
            if public
            else revision_out(revision)
        ),
        "boards": [
            {
                "id": item.id,
                "pcb_version_id": item.pcb_version_id if not public else None,
                "board_index": item.board_index,
                "name": item.name,
                "status": item.status,
            }
            for item in boards
            if not public or item.status != "archived"
        ],
        "active_board_id": board.id if board else None,
        "side": side,
        "placements": result_placements,
        "layers": [
            layer_out(item, public=public)
            for item in sorted(revision.layers, key=lambda row: LAYER_ORDER.get(row.role, 99))
            if side == "all" or item.side in {"both", side}
        ],
        "stats": stats,
        "can_edit": False if public else role != "viewer",
    }


@router.get("/api/projects/{project_id}/assembly-view")
def personal_assembly_view(
    project_id: int,
    board_id: int | None = None,
    side: str = "top",
    revision_id: str | None = None,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, role = require_scoped_project(db, project_id, auth)
    return assembly_view_impl(db, project, board_id=board_id, side=side, revision_id=revision_id, role=role)


@router.get("/api/team/libraries/{library_id}/projects/{project_id}/assembly-view")
def team_assembly_view(
    library_id: str,
    project_id: int,
    board_id: int | None = None,
    side: str = "top",
    revision_id: str | None = None,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, role = require_scoped_project(db, project_id, auth, library_id=library_id)
    return assembly_view_impl(db, project, board_id=board_id, side=side, revision_id=revision_id, role=role)


@router.get("/api/public/projects/{project_code}/assembly-view")
def public_assembly_view(
    project_code: str,
    board_id: int | None = None,
    side: str = "top",
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(
        func.upper(Project.project_code) == str(project_code or "").strip().upper(),
        Project.public_assembly_view_enabled.is_(True),
        Project.active_fabrication_revision_id.isnot(None),
    ).first()
    if not project:
        alias = db.query(ProjectCodeAlias).filter(
            func.upper(ProjectCodeAlias.old_code) == str(project_code or "").strip().upper()
        ).first()
        project = (
            db.query(Project).filter(
                Project.id == alias.project_id,
                Project.public_assembly_view_enabled.is_(True),
                Project.active_fabrication_revision_id.isnot(None),
            ).first()
            if alias
            else None
        )
    if not project:
        raise HTTPException(status_code=404, detail="公开装配简图未开启")
    return assembly_view_impl(
        db, project, board_id=board_id, side=side, revision_id=None, public=True, role="viewer"
    )


def save_calibration_impl(
    db: Session, project: Project, revision_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    revision = revision_for_project(db, project, revision_id)
    calibration = {
        "offset_x_mm": float(payload.get("offset_x_mm") or 0),
        "offset_y_mm": float(payload.get("offset_y_mm") or 0),
        "rotation_deg": float(payload.get("rotation_deg") or 0) % 360,
        "mirror": bool(payload.get("mirror")),
    }
    if abs(calibration["offset_x_mm"]) > 10000 or abs(calibration["offset_y_mm"]) > 10000:
        raise HTTPException(status_code=400, detail="校准偏移超出范围")
    revision.calibration_json = json_dump(calibration)
    db.commit()
    return calibration


@router.patch("/api/projects/{project_id}/fabrication-revisions/{revision_id}/calibration")
def personal_calibration(
    project_id: int,
    revision_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return save_calibration_impl(db, project, revision_id, payload)


@router.patch("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}/calibration")
def team_calibration(
    library_id: str,
    project_id: int,
    revision_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return save_calibration_impl(db, project, revision_id, payload)


def patch_placement_impl(
    db: Session,
    project: Project,
    revision_id: str,
    placement_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    revision_for_project(db, project, revision_id)
    placement = db.query(ProjectAssemblyPlacement).filter(
        ProjectAssemblyPlacement.id == placement_id,
        ProjectAssemblyPlacement.revision_id == revision_id,
    ).first()
    if not placement:
        raise HTTPException(status_code=404, detail="器件坐标不存在")
    if payload.get("reset"):
        placement.x_mm = placement.source_x_mm
        placement.y_mm = placement.source_y_mm
        placement.rotation_deg = placement.source_rotation_deg
        placement.board_side = placement.source_board_side or "top"
        placement.manually_adjusted = False
    else:
        if "x_mm" in payload:
            placement.x_mm = float(payload["x_mm"])
        if "y_mm" in payload:
            placement.y_mm = float(payload["y_mm"])
        if "rotation_deg" in payload:
            placement.rotation_deg = float(payload["rotation_deg"]) % 360
        if "board_side" in payload:
            side = str(payload["board_side"])
            if side not in {"top", "bottom"}:
                raise HTTPException(status_code=400, detail="板面无效")
            collision = db.query(ProjectAssemblyPlacement.id).filter(
                ProjectAssemblyPlacement.revision_id == revision_id,
                ProjectAssemblyPlacement.designator_key == placement.designator_key,
                ProjectAssemblyPlacement.board_side == side,
                ProjectAssemblyPlacement.id != placement.id,
            ).first()
            if collision:
                raise HTTPException(status_code=409, detail="目标板面已存在相同位号")
            placement.board_side = side
        placement.positioned = placement.x_mm is not None and placement.y_mm is not None
        placement.manually_adjusted = True
    linked_points = db.query(ProjectBomSolderPoint).filter(
        ProjectBomSolderPoint.assembly_placement_id == placement.id,
        ProjectBomSolderPoint.active_for_assembly.is_(True),
    ).all()
    for point in linked_points:
        if point.board_side != placement.board_side:
            point.board_side = placement.board_side
            point.state_version = int(point.state_version or 1) + 1
    db.commit()
    return placement_out(placement)


@router.patch("/api/projects/{project_id}/fabrication-revisions/{revision_id}/placements/{placement_id}")
def personal_patch_placement(
    project_id: int,
    revision_id: str,
    placement_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return patch_placement_impl(db, project, revision_id, placement_id, payload)


@router.patch("/api/team/libraries/{library_id}/projects/{project_id}/fabrication-revisions/{revision_id}/placements/{placement_id}")
def team_patch_placement(
    library_id: str,
    project_id: int,
    revision_id: str,
    placement_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return patch_placement_impl(db, project, revision_id, placement_id, payload)


def batch_boards_impl(db: Session, project: Project, payload: dict[str, Any]) -> list[dict[str, Any]]:
    count = int(payload.get("count") or 1)
    if count < 1 or count > 100:
        raise HTTPException(status_code=400, detail="一次可创建 1-100 块实物板")
    prefix = str(payload.get("name_prefix") or "第").strip()[:80]
    max_index = int(
        db.query(func.max(ProjectBoard.board_index)).filter(ProjectBoard.project_id == project.id).scalar()
        or 0
    )
    placements = []
    if project.active_fabrication_revision_id:
        placements = db.query(ProjectAssemblyPlacement).filter(
            ProjectAssemblyPlacement.revision_id == project.active_fabrication_revision_id,
            ProjectAssemblyPlacement.bom_item_id.isnot(None),
            ProjectAssemblyPlacement.positioned.is_(True),
            ProjectAssemblyPlacement.dnp.is_(False),
        ).all()
    created = []
    for offset in range(1, count + 1):
        index = max_index + offset
        name = f"{prefix} {index} 板" if prefix != "第" else f"第 {index} 板"
        board = ProjectBoard(project_id=project.id, board_index=index, name=name, status="active")
        db.add(board)
        db.flush()
        for placement in placements:
            db.add(
                ProjectBomSolderPoint(
                    bom_item_id=placement.bom_item_id,
                    board_id=board.id,
                    designator=placement.designator,
                    designator_key=placement.designator_key,
                    board_side=placement.board_side,
                    assembly_placement_id=placement.id,
                    active_for_assembly=True,
                    state_version=1,
                    bom_value=placement.value,
                    bom_model=placement.model,
                    bom_footprint=placement.footprint,
                )
            )
        created.append(board)
    db.commit()
    return [
        {"id": item.id, "board_index": item.board_index, "name": item.name, "status": item.status}
        for item in created
    ]


@router.post("/api/projects/{project_id}/boards/batch")
def personal_batch_boards(
    project_id: int,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return batch_boards_impl(db, project, payload)


@router.post("/api/team/libraries/{library_id}/projects/{project_id}/boards/batch")
def team_batch_boards(
    library_id: str,
    project_id: int,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return batch_boards_impl(db, project, payload)


def patch_board_impl(db: Session, project: Project, board_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    board = db.query(ProjectBoard).filter(
        ProjectBoard.id == board_id, ProjectBoard.project_id == project.id
    ).first()
    if not board:
        raise HTTPException(status_code=404, detail="实物板不存在")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="实物板名称不能为空")
        board.name = name[:120]
    if "status" in payload:
        status = str(payload["status"])
        if status not in {"active", "completed", "archived"}:
            raise HTTPException(status_code=400, detail="实物板状态无效")
        board.status = status
        board.completed_at = datetime.utcnow() if status == "completed" else board.completed_at
    db.commit()
    return {"id": board.id, "board_index": board.board_index, "name": board.name, "status": board.status}


@router.patch("/api/projects/{project_id}/boards/{board_id}")
def personal_patch_board(
    project_id: int,
    board_id: int,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return patch_board_impl(db, project, board_id, payload)


@router.patch("/api/team/libraries/{library_id}/projects/{project_id}/boards/{board_id}")
def team_patch_board(
    library_id: str,
    project_id: int,
    board_id: int,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return patch_board_impl(db, project, board_id, payload)


def point_snapshot(point: ProjectBomSolderPoint, count: int) -> dict[str, Any]:
    return {
        "id": point.id,
        "soldered": bool(point.soldered),
        "soldered_at": point.soldered_at.isoformat() if point.soldered_at else None,
        "stock_applied": bool(point.stock_applied),
        "lost": bool(point.lost),
        "lost_at": point.lost_at.isoformat() if point.lost_at else None,
        "loss_stock_applied": bool(point.loss_stock_applied),
        "loss_note": point.loss_note,
        "state_version": int(point.state_version or 1),
        "loss_count": count,
    }


def apply_inventory(
    db: Session,
    component: Component,
    delta: int,
    *,
    project: Project,
    auth: AuthContext,
    movement_type: str,
    reason: str,
) -> None:
    if delta < 0 and int(component.quantity or 0) < abs(delta):
        raise HTTPException(
            status_code=409,
            detail=f"库存不足：{component.name} 需要 {abs(delta)}，现有 {int(component.quantity or 0)}；整次操作已回滚",
        )
    component.quantity = int(component.quantity or 0) + delta
    record_stock_delta(
        db,
        component,
        delta,
        movement_type=movement_type,
        reason=reason,
        project_id=project.id,
        actor_user_id=auth.user_id,
    )


def current_loss_events(db: Session, point_id: int) -> list[ProjectAssemblyLossEvent]:
    return (
        db.query(ProjectAssemblyLossEvent)
        .filter(
            ProjectAssemblyLossEvent.solder_point_id == point_id,
            ProjectAssemblyLossEvent.reversed_at.is_(None),
        )
        .order_by(ProjectAssemblyLossEvent.created_at.desc(), ProjectAssemblyLossEvent.id.desc())
        .all()
    )


def assembly_action_impl(
    db: Session,
    project: Project,
    payload: dict[str, Any],
    auth: AuthContext,
    request: Request,
) -> dict[str, Any]:
    if db.bind and db.bind.dialect.name == "sqlite":
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))
    action = str(payload.get("action") or "").lower()
    if action == "unloss":
        action = "undo_loss"
    if action not in {"solder", "unsolder", "loss", "undo_loss"}:
        raise HTTPException(status_code=400, detail="装配操作无效")
    idempotency_key = str(payload.get("idempotency_key") or "").strip()[:120]
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="缺少幂等键 idempotency_key")
    existing = db.query(ProjectAssemblyOperation).filter(
        ProjectAssemblyOperation.project_id == project.id,
        ProjectAssemblyOperation.idempotency_key == idempotency_key,
    ).first()
    if existing:
        return {
            "operation_id": existing.id,
            "idempotent_replay": True,
            "action": existing.action,
            "points": json_load(existing.after_json, {}).get("points", []),
            "inventory_changes": json_load(existing.after_json, {}).get("inventory_changes", []),
            "undo_available": existing.undone_at is None,
        }
    board_id = int(payload.get("board_id") or 0)
    board = db.query(ProjectBoard).filter(
        ProjectBoard.id == board_id, ProjectBoard.project_id == project.id
    ).first()
    if not board or board.status == "archived":
        raise HTTPException(status_code=404, detail="实物板不存在或已归档")
    point_ids = sorted({int(item) for item in payload.get("point_ids") or []})
    if not point_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个位号")
    points = (
        db.query(ProjectBomSolderPoint)
        .options(joinedload(ProjectBomSolderPoint.bom_item).joinedload(ProjectBomItem.component))
        .filter(
            ProjectBomSolderPoint.id.in_(point_ids),
            ProjectBomSolderPoint.board_id == board.id,
            ProjectBomSolderPoint.active_for_assembly.is_(True),
        )
        .all()
    )
    if len(points) != len(point_ids):
        raise HTTPException(status_code=404, detail="部分位号不存在、已归档或不属于当前实物板")
    versions = {int(key): int(value) for key, value in (payload.get("versions") or {}).items()}
    missing_versions = [point.id for point in points if point.id not in versions]
    if missing_versions:
        raise HTTPException(
            status_code=409,
            detail={"message": "缺少位号状态版本，请刷新后重试", "point_ids": missing_versions},
        )
    stale = [point.id for point in points if point.id in versions and int(point.state_version or 1) != versions[point.id]]
    if stale:
        raise HTTPException(status_code=409, detail={"message": "装配状态已被其他成员更新，请刷新", "point_ids": stale})
    before_counts = loss_counts(db, point_ids)
    before = {"points": [point_snapshot(point, before_counts.get(point.id, 0)) for point in points]}
    operation_id = new_uuid()
    inventory_changes: dict[int, int] = {}
    inventory_source_user_ids: set[int] = set()
    loss_event_ids: list[str] = []
    now = datetime.utcnow()
    note = str(payload.get("note") or "默认报损原因：装配损坏").strip()[:1000]
    for point in points:
        component = point.bom_item.component
        was_soldered = bool(point.soldered)
        if component.owner_user_id is not None:
            inventory_source_user_ids.add(int(component.owner_user_id))
        if project.scope_type == "team":
            linked = db.query(CompetitionLibraryComponent.id).filter(
                CompetitionLibraryComponent.library_id == project.team_library_id,
                CompetitionLibraryComponent.cw_component_id == component.id,
                CompetitionLibraryComponent.sync_status == "live",
            ).first()
            if not linked:
                raise HTTPException(status_code=409, detail=f"{component.name} 未链接到当前团队库成员库存")
        delta = 0
        if action == "solder":
            if not point.soldered:
                delta = 0 if point.bom_item.status == "picked" else -1
                point.soldered = True
                point.soldered_at = now
                point.stock_applied = delta < 0
        elif action == "unsolder":
            if point.soldered:
                delta = 1 if point.stock_applied else 0
                point.soldered = False
                point.soldered_at = None
                point.stock_applied = False
        elif action == "loss":
            prior_soldered = bool(point.soldered)
            prior_stock_applied = bool(point.stock_applied)
            if prior_soldered:
                delta = 0
                point.soldered = False
                point.soldered_at = None
                point.stock_applied = False
                db.add(
                    StockMovement(
                        id=new_uuid(),
                        component_id=component.id,
                        lot_id=None,
                        owner_user_id=component.owner_user_id,
                        movement_type="solder_to_loss_reclassification",
                        quantity_delta=0,
                        reason=f"{point.designator} 已焊器件判坏，焊接消耗重分类为报损",
                        project_id=project.id,
                        created_by_user_id=auth.user_id,
                    )
                )
            else:
                delta = 0 if point.bom_item.status == "picked" else -1
            loss_event = ProjectAssemblyLossEvent(
                id=new_uuid(),
                solder_point_id=point.id,
                operation_id=operation_id,
                actor_user_id=auth.user_id,
                note=note,
                stock_applied=delta < 0,
                inventory_delta=delta,
                prior_soldered=prior_soldered,
                prior_stock_applied=prior_stock_applied,
                created_at=now,
            )
            db.add(loss_event)
            loss_event_ids.append(loss_event.id)
        elif action == "undo_loss":
            event = next(iter(current_loss_events(db, point.id)), None)
            if not event:
                raise HTTPException(status_code=409, detail=f"{point.designator} 没有可撤销的报损事件")
            delta = -int(event.inventory_delta or 0)
            event.reversed_at = now
            event.reversed_by_user_id = auth.user_id
            loss_event_ids.append(event.id)
            if event.prior_soldered:
                point.soldered = True
                point.soldered_at = now
                point.stock_applied = bool(event.prior_stock_applied)
        if project.scope_type == "personal":
            if action == "solder" and not was_soldered:
                append_material_cost_event(
                    db,
                    project=project,
                    point=point,
                    component=component,
                    event_type="solder",
                    quantity_delta=1,
                    actor_user_id=auth.user_id,
                    source_operation_id=operation_id,
                    note=str(payload.get("note") or "").strip() or None,
                )
            elif action == "unsolder" and was_soldered:
                append_material_release_event(
                    db,
                    project=project,
                    point=point,
                    component=component,
                    event_type="unsolder",
                    actor_user_id=auth.user_id,
                    source_operation_id=operation_id,
                    note=str(payload.get("note") or "").strip() or None,
                )
            elif action == "loss":
                append_material_cost_event(
                    db,
                    project=project,
                    point=point,
                    component=component,
                    event_type="solder_to_loss" if was_soldered else "loss",
                    quantity_delta=0 if was_soldered else 1,
                    actor_user_id=auth.user_id,
                    source_operation_id=operation_id,
                    note=note,
                )
            elif action == "undo_loss":
                if event.prior_soldered:
                    append_material_cost_event(
                        db,
                        project=project,
                        point=point,
                        component=component,
                        event_type="loss_to_solder",
                        quantity_delta=0,
                        actor_user_id=auth.user_id,
                        source_operation_id=operation_id,
                        note=str(payload.get("note") or "").strip() or None,
                    )
                else:
                    append_material_release_event(
                        db,
                        project=project,
                        point=point,
                        component=component,
                        event_type="undo_loss",
                        actor_user_id=auth.user_id,
                        source_operation_id=operation_id,
                        note=str(payload.get("note") or "").strip() or None,
                    )
        if delta:
            inventory_changes[component.id] = inventory_changes.get(component.id, 0) + delta
        point.state_version = int(point.state_version or 1) + 1
    for component_id, delta in inventory_changes.items():
        component = db.get(Component, component_id)
        apply_inventory(
            db,
            component,
            delta,
            project=project,
            auth=auth,
            movement_type={
                "solder": "solder_consume",
                "unsolder": "solder_restore",
                "loss": "assembly_loss",
                "undo_loss": "assembly_loss_restore",
            }[action],
            reason=f"装配工作台 {action}",
        )
    db.flush()
    after_counts = loss_counts(db, point_ids)
    for point in points:
        count = after_counts.get(point.id, 0)
        point.lost = count > 0
        point.lost_at = now if count else None
        point.loss_stock_applied = any(event.inventory_delta < 0 for event in current_loss_events(db, point.id))
        if action == "loss":
            point.loss_note = note
        elif not count:
            point.loss_note = None
    after = {
        "points": [point_snapshot(point, after_counts.get(point.id, 0)) for point in points],
        "inventory_changes": [
            {
                "component_id": component_id,
                "delta": delta,
                "source_user_id": db.get(Component, component_id).owner_user_id,
            }
            for component_id, delta in inventory_changes.items()
        ],
        "loss_event_ids": loss_event_ids,
    }
    operation = ProjectAssemblyOperation(
        id=operation_id,
        project_id=project.id,
        board_id=board.id,
        actor_user_id=auth.user_id,
        idempotency_key=idempotency_key,
        action=action,
        point_ids_json=json_dump(point_ids),
        before_json=json_dump(before),
        after_json=json_dump(after),
        inventory_source_user_ids_json=json_dump(
            sorted(inventory_source_user_ids)
        ),
        note=note if action == "loss" else str(payload.get("note") or "").strip() or None,
    )
    db.add(operation)
    audit(
        db,
        project,
        auth,
        request,
        f"assembly.{action}",
        f"{board.name} {action} {len(points)} 个位号",
        entity_type="assembly_operation",
        entity_id=operation.id,
        detail=after,
        quantity_delta=sum(inventory_changes.values()),
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = db.query(ProjectAssemblyOperation).filter(
            ProjectAssemblyOperation.project_id == project.id,
            ProjectAssemblyOperation.idempotency_key == idempotency_key,
        ).first()
        if replay:
            return {
                "operation_id": replay.id,
                "idempotent_replay": True,
                "action": replay.action,
                "points": json_load(replay.after_json, {}).get("points", []),
                "inventory_changes": json_load(replay.after_json, {}).get("inventory_changes", []),
                "undo_available": replay.undone_at is None,
            }
        raise
    return {
        "operation_id": operation.id,
        "idempotent_replay": False,
        "action": action,
        "points": after["points"],
        "inventory_changes": after["inventory_changes"],
        "undo_available": True,
    }


@router.post("/api/projects/{project_id}/assembly-actions")
def personal_assembly_action(
    project_id: int,
    payload: dict[str, Any],
    request: Request,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return assembly_action_impl(db, project, payload, auth, request)


@router.post("/api/team/libraries/{library_id}/projects/{project_id}/assembly-actions")
def team_assembly_action(
    library_id: str,
    project_id: int,
    payload: dict[str, Any],
    request: Request,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return assembly_action_impl(db, project, payload, auth, request)


def undo_operation_impl(
    db: Session,
    project: Project,
    operation_id: str,
    payload: dict[str, Any],
    auth: AuthContext,
    request: Request,
) -> dict[str, Any]:
    if db.bind and db.bind.dialect.name == "sqlite":
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))
    operation = db.query(ProjectAssemblyOperation).filter(
        ProjectAssemblyOperation.id == operation_id,
        ProjectAssemblyOperation.project_id == project.id,
    ).first()
    if not operation:
        raise HTTPException(status_code=404, detail="装配操作不存在")
    if operation.undone_at or operation.undone_by_operation_id:
        raise HTTPException(status_code=409, detail="该操作已经撤销")
    idempotency_key = str(payload.get("idempotency_key") or f"undo:{operation.id}")[:120]
    existing = db.query(ProjectAssemblyOperation).filter(
        ProjectAssemblyOperation.project_id == project.id,
        ProjectAssemblyOperation.idempotency_key == idempotency_key,
    ).first()
    if existing:
        return {"operation_id": existing.id, "idempotent_replay": True, "undone_operation_id": operation.id}
    before_data = json_load(operation.before_json, {})
    after_data = json_load(operation.after_json, {})
    before_by_id = {int(item["id"]): item for item in before_data.get("points", [])}
    after_by_id = {int(item["id"]): item for item in after_data.get("points", [])}
    points = db.query(ProjectBomSolderPoint).filter(ProjectBomSolderPoint.id.in_(before_by_id)).all()
    stale = [
        point.id
        for point in points
        if int(point.state_version or 1) != int(after_by_id[point.id]["state_version"])
    ]
    if stale:
        raise HTTPException(
            status_code=409,
            detail={"message": "操作后已有成员更新这些位号，请刷新后人工处理", "point_ids": stale},
        )
    inverse_changes = []
    for item in after_data.get("inventory_changes", []):
        component = db.get(Component, int(item["component_id"]))
        inverse = -int(item["delta"])
        apply_inventory(
            db,
            component,
            inverse,
            project=project,
            auth=auth,
            movement_type="assembly_operation_undo",
            reason=f"撤销装配操作 {operation.id}",
        )
        inverse_changes.append({"component_id": component.id, "delta": inverse, "source_user_id": component.owner_user_id})
    now = datetime.utcnow()
    for event_id in after_data.get("loss_event_ids", []):
        event = db.get(ProjectAssemblyLossEvent, event_id)
        if event and not event.reversed_at:
            event.reversed_at = now
            event.reversed_by_user_id = auth.user_id
        elif event and operation.action == "undo_loss":
            event.reversed_at = None
            event.reversed_by_user_id = None
    for point in points:
        state = before_by_id[point.id]
        point.soldered = bool(state["soldered"])
        point.soldered_at = datetime.fromisoformat(state["soldered_at"]) if state.get("soldered_at") else None
        point.stock_applied = bool(state["stock_applied"])
        point.lost = bool(state["lost"])
        point.lost_at = datetime.fromisoformat(state["lost_at"]) if state.get("lost_at") else None
        point.loss_stock_applied = bool(state["loss_stock_applied"])
        point.loss_note = state.get("loss_note")
        point.state_version = int(point.state_version or 1) + 1
    undo_id = new_uuid()
    if project.scope_type == "personal":
        reverse_material_events_for_operation(
            db,
            project=project,
            operation_id=operation.id,
            actor_user_id=auth.user_id,
            reversal_operation_id=undo_id,
        )
    undo = ProjectAssemblyOperation(
        id=undo_id,
        project_id=project.id,
        board_id=operation.board_id,
        actor_user_id=auth.user_id,
        idempotency_key=idempotency_key,
        action="undo",
        point_ids_json=operation.point_ids_json,
        before_json=operation.after_json,
        after_json=json_dump(
            {
                "points": [point_snapshot(point, int(before_by_id[point.id].get("loss_count") or 0)) for point in points],
                "inventory_changes": inverse_changes,
                "undo_of_operation_id": operation.id,
            }
        ),
        inventory_source_user_ids_json=json_dump(
            sorted({item["source_user_id"] for item in inverse_changes if item["source_user_id"] is not None})
        ),
        undo_of_operation_id=operation.id,
        note=str(payload.get("note") or "").strip() or None,
    )
    operation.undone_at = now
    operation.undone_by_user_id = auth.user_id
    operation.undone_by_operation_id = undo.id
    db.add(undo)
    audit(
        db,
        project,
        auth,
        request,
        "assembly.undo",
        f"撤销装配操作 {operation.id}",
        entity_type="assembly_operation",
        entity_id=undo.id,
        detail={"undo_of_operation_id": operation.id, "inventory_changes": inverse_changes},
        quantity_delta=sum(item["delta"] for item in inverse_changes),
    )
    db.commit()
    return {"operation_id": undo.id, "undone_operation_id": operation.id, "idempotent_replay": False}


def update_operation_note_impl(
    db: Session,
    project: Project,
    operation_id: str,
    payload: dict[str, Any],
    auth: AuthContext,
) -> dict[str, Any]:
    operation = db.query(ProjectAssemblyOperation).filter(
        ProjectAssemblyOperation.id == operation_id,
        ProjectAssemblyOperation.project_id == project.id,
    ).first()
    if not operation:
        raise HTTPException(status_code=404, detail="装配操作不存在")
    note = str(payload.get("note") or "").strip()[:1000]
    if not note:
        raise HTTPException(status_code=400, detail="请填写原因或备注")
    operation.note = note
    if operation.action == "loss":
        db.query(ProjectAssemblyLossEvent).filter(
            ProjectAssemblyLossEvent.operation_id == operation.id,
            ProjectAssemblyLossEvent.reversed_at.is_(None),
        ).update({ProjectAssemblyLossEvent.note: note}, synchronize_session=False)
        point_ids = json_load(operation.point_ids_json, [])
        db.query(ProjectBomSolderPoint).filter(ProjectBomSolderPoint.id.in_(point_ids)).update(
            {ProjectBomSolderPoint.loss_note: note}, synchronize_session=False
        )
    db.commit()
    return {"operation_id": operation.id, "note": note}


@router.patch("/api/projects/{project_id}/assembly-actions/{operation_id}/note")
def personal_operation_note(
    project_id: int,
    operation_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return update_operation_note_impl(db, project, operation_id, payload, auth)


@router.patch("/api/team/libraries/{library_id}/projects/{project_id}/assembly-actions/{operation_id}/note")
def team_operation_note(
    library_id: str,
    project_id: int,
    operation_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return update_operation_note_impl(db, project, operation_id, payload, auth)


@router.post("/api/projects/{project_id}/assembly-actions/{operation_id}/undo")
def personal_undo_operation(
    project_id: int,
    operation_id: str,
    request: Request,
    payload: dict[str, Any] | None = None,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return undo_operation_impl(db, project, operation_id, payload or {}, auth, request)


@router.post("/api/team/libraries/{library_id}/projects/{project_id}/assembly-actions/{operation_id}/undo")
def team_undo_operation(
    library_id: str,
    project_id: int,
    operation_id: str,
    request: Request,
    payload: dict[str, Any] | None = None,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return undo_operation_impl(db, project, operation_id, payload or {}, auth, request)


def public_setting_impl(db: Session, project: Project, payload: dict[str, Any]) -> dict[str, Any]:
    project.public_assembly_view_enabled = bool(payload.get("enabled"))
    db.commit()
    return {"enabled": bool(project.public_assembly_view_enabled)}


@router.patch("/api/projects/{project_id}/assembly-public-setting")
def personal_public_setting(
    project_id: int,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, write=True)
    return public_setting_impl(db, project, payload)


@router.patch("/api/team/libraries/{library_id}/projects/{project_id}/assembly-public-setting")
def team_public_setting(
    library_id: str,
    project_id: int,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    project, _ = require_scoped_project(db, project_id, auth, library_id=library_id, write=True)
    return public_setting_impl(db, project, payload)
