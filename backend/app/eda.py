import hashlib
import json
import os
import secrets
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from sqlalchemy import or_

from .auth import AuthContext, require_access, require_admin
from .branding import APP_BACKUP_NAME
from .database import get_db
from .features import require_eda_enabled
from .engineering_schemas import (
    EdaAssetPublish,
    EdaBindingCreate,
    EdaLibraryCreate,
    EdaLibraryVersionCreate,
    EdaObjectCreate,
    EdaRemoteDownload,
    EdaQuickBindingCreate,
    EdaSyncDraftCreate,
    EdaSyncTokenCreate,
    EdaVerificationCreate,
    SupplierPartCreate,
)
from .models import (
    CompetitionLibraryComponent,
    Component,
    EdaAsset,
    EdaAttachmentLink,
    EdaComponentBinding,
    EdaFootprint,
    EdaLibrary,
    EdaLibraryVersion,
    EdaSymbol,
    EdaSyncToken,
    EdaVerification,
    SupplierPart,
)
from .services.eda_storage import (
    TYPE_LIMITS,
    consume_stage,
    quota_bytes,
    resolve_asset_path,
    stage_upload,
    stage_remote_download,
    used_bytes,
)
from .services.component_search import keyword_unit_variants
from .team import require_library_editor, require_library_member


router = APIRouter(tags=["eda"], dependencies=[Depends(require_eda_enabled)])
VERIFICATION_STATES = {"raw", "checked", "tested", "verified", "deprecated"}
WORKSPACE_LOCK = threading.Lock()


@dataclass(frozen=True)
class EngineeringScope:
    scope_type: str
    owner_user_id: int | None
    team_library_id: str | None
    auth: AuthContext
    can_edit: bool = True


def new_uuid() -> str:
    return str(uuid4())


def personal_scope(auth: AuthContext) -> EngineeringScope:
    return EngineeringScope("personal", auth.user_id, None, auth, True)


def team_scope(
    db: Session,
    library_id: str,
    auth: AuthContext,
    *,
    edit: bool,
) -> EngineeringScope:
    _, member = (
        require_library_editor(db, library_id, auth)
        if edit
        else require_library_member(db, library_id, auth)
    )
    return EngineeringScope(
        "team",
        None,
        library_id,
        auth,
        member.role in {"captain", "editor", "member"},
    )


def scoped(query, model, scope: EngineeringScope):
    query = query.filter(model.scope_type == scope.scope_type)
    if scope.scope_type == "team":
        return query.filter(model.team_library_id == scope.team_library_id)
    return query.filter(model.owner_user_id == scope.owner_user_id)


def apply_scope(record, scope: EngineeringScope) -> None:
    record.scope_type = scope.scope_type
    record.owner_user_id = scope.owner_user_id
    record.team_library_id = scope.team_library_id


def require_component(db: Session, scope: EngineeringScope, component_id: int) -> Component:
    component = db.get(Component, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="元器件不存在")
    if scope.scope_type == "personal":
        if component.owner_user_id != scope.owner_user_id:
            raise HTTPException(status_code=404, detail="元器件不存在")
    else:
        linked = (
            db.query(CompetitionLibraryComponent)
            .filter(
                CompetitionLibraryComponent.library_id == scope.team_library_id,
                CompetitionLibraryComponent.cw_component_id == component.id,
            )
            .first()
        )
        if not linked:
            raise HTTPException(status_code=404, detail="该元器件未发布到当前团队")
    return component


def require_library(db: Session, scope: EngineeringScope, library_id: str) -> EdaLibrary:
    library = scoped(db.query(EdaLibrary), EdaLibrary, scope).filter(EdaLibrary.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="EDA 库不存在")
    return library


def require_version(db: Session, scope: EngineeringScope, version_id: str) -> EdaLibraryVersion:
    version = db.get(EdaLibraryVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="EDA 库版本不存在")
    require_library(db, scope, version.library_id)
    return version


def require_mutable_version(db: Session, scope: EngineeringScope, version_id: str) -> EdaLibraryVersion:
    version = require_version(db, scope, version_id)
    if version.status == "published":
        raise HTTPException(status_code=409, detail="已发布库版本不可修改，请创建新版本")
    return version


def require_asset(db: Session, scope: EngineeringScope, asset_id: str) -> EdaAsset:
    asset = scoped(db.query(EdaAsset), EdaAsset, scope).filter(EdaAsset.id == asset_id).first()
    if not asset or asset.status == "purged":
        raise HTTPException(status_code=404, detail="EDA 文件不存在")
    return asset


def library_out(db: Session, library: EdaLibrary) -> dict:
    versions = (
        db.query(EdaLibraryVersion)
        .filter(EdaLibraryVersion.library_id == library.id)
        .order_by(EdaLibraryVersion.created_at.desc())
        .all()
    )
    return {
        "id": library.id,
        "scope_type": library.scope_type,
        "name": library.name,
        "category": library.category,
        "description": library.description,
        "status": library.status,
        "created_at": library.created_at,
        "updated_at": library.updated_at,
        "versions": [
            {
                "id": item.id,
                "version": item.version,
                "change_note": item.change_note,
                "compatible_with_previous": item.compatible_with_previous,
                "status": item.status,
                "published_at": item.published_at,
                "created_at": item.created_at,
            }
            for item in versions
        ],
    }


def next_patch_version(versions: list[EdaLibraryVersion]) -> str:
    highest = (0, 0, 0)
    for item in versions:
        parts = str(item.version or "").split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            continue
        highest = max(highest, tuple(int(part) for part in parts))
    return f"{highest[0]}.{highest[1]}.{highest[2] + 1}" if highest != (0, 0, 0) else "0.1.0"


def workspace_impl(db: Session, scope: EngineeringScope) -> dict:
    with WORKSPACE_LOCK:
        library = (
            scoped(db.query(EdaLibrary), EdaLibrary, scope)
            .filter(EdaLibrary.status == "active")
            .order_by(EdaLibrary.created_at.asc())
            .first()
        )
        created_library = False
        if not library:
            library = EdaLibrary(
                id=new_uuid(),
                name="团队 AD 元件库" if scope.scope_type == "team" else "我的 AD 元件库",
                category="通用",
                description="系统自动建立的默认 AD 库，可在高级管理中改名和建立正式版本。",
                status="active",
                created_by_user_id=scope.auth.user_id,
            )
            apply_scope(library, scope)
            db.add(library)
            db.flush()
            created_library = True
        versions = (
            db.query(EdaLibraryVersion)
            .filter(EdaLibraryVersion.library_id == library.id)
            .order_by(EdaLibraryVersion.created_at.desc())
            .all()
        )
        version = next((item for item in versions if item.status != "published"), None)
        created_version = False
        if not version:
            version = EdaLibraryVersion(
                id=new_uuid(),
                library_id=library.id,
                version=next_patch_version(versions),
                change_note="快速模式工作版本",
                compatible_with_previous=True,
                status="raw",
                created_by_user_id=scope.auth.user_id,
            )
            db.add(version)
            created_version = True
        db.commit()
        return {
            "library": library_out(db, library),
            "version": {
                "id": version.id,
                "version": version.version,
                "status": version.status,
                "change_note": version.change_note,
            },
            "created_library": created_library,
            "created_version": created_version,
        }


@router.post("/api/eda/workspace")
def personal_workspace(auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return workspace_impl(db, personal_scope(auth))


@router.post("/api/team/libraries/{library_id}/eda/workspace")
def team_workspace(library_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return workspace_impl(db, team_scope(db, library_id, auth, edit=True))


def asset_out(asset: EdaAsset) -> dict:
    return {
        "id": asset.id,
        "scope_type": asset.scope_type,
        "library_version_id": asset.library_version_id,
        "asset_type": asset.asset_type,
        "original_name": asset.original_name,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "mime_type": asset.mime_type,
        "version_label": asset.version_label,
        "source_url": asset.source_url,
        "source_license": asset.source_license,
        "verification_status": asset.verification_status,
        "status": asset.status,
        "created_at": asset.created_at,
        "archived_at": asset.archived_at,
        "purge_after": asset.purge_after,
    }


def binding_out(db: Session, binding: EdaComponentBinding) -> dict:
    symbol = db.get(EdaSymbol, binding.symbol_id) if binding.symbol_id else None
    footprint = db.get(EdaFootprint, binding.footprint_id) if binding.footprint_id else None
    datasheet = db.get(EdaAsset, binding.datasheet_asset_id) if binding.datasheet_asset_id else None
    model = db.get(EdaAsset, binding.model_asset_id) if binding.model_asset_id else None
    return {
        "id": binding.id,
        "component_id": binding.component_id,
        "library_version_id": binding.library_version_id,
        "symbol": {"id": symbol.id, "name": symbol.name} if symbol else None,
        "footprint": {"id": footprint.id, "name": footprint.name} if footprint else None,
        "datasheet": asset_out(datasheet) if datasheet else None,
        "model": asset_out(model) if model else None,
        "is_primary": binding.is_primary,
        "verification_status": binding.verification_status,
        "source": binding.source,
        "note": binding.note,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def entity_assets_impl(
    db: Session,
    scope: EngineeringScope,
    entity_type: str,
    entity_id: str,
) -> list[dict]:
    links = (
        db.query(EdaAttachmentLink)
        .filter(
            EdaAttachmentLink.entity_type == entity_type,
            EdaAttachmentLink.entity_id == entity_id,
        )
        .order_by(EdaAttachmentLink.created_at.desc())
        .all()
    )
    asset_ids = [item.asset_id for item in links]
    assets = {
        item.id: item
        for item in scoped(db.query(EdaAsset), EdaAsset, scope)
        .filter(EdaAsset.id.in_(asset_ids or [""]), EdaAsset.status != "purged")
        .all()
    }
    return [
        {**asset_out(assets[link.asset_id]), "relation_type": link.relation_type}
        for link in links
        if link.asset_id in assets
    ]


def create_library_impl(db: Session, scope: EngineeringScope, payload: EdaLibraryCreate) -> dict:
    library = EdaLibrary(
        id=new_uuid(),
        name=payload.name.strip(),
        category=(payload.category or "").strip() or None,
        description=(payload.description or "").strip() or None,
        status="active",
        created_by_user_id=scope.auth.user_id,
    )
    apply_scope(library, scope)
    db.add(library)
    db.commit()
    return library_out(db, library)


def list_libraries_impl(db: Session, scope: EngineeringScope) -> list[dict]:
    rows = scoped(db.query(EdaLibrary), EdaLibrary, scope).order_by(EdaLibrary.updated_at.desc()).all()
    return [library_out(db, item) for item in rows]


@router.get("/api/eda/summary")
def personal_summary(auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return summary_impl(db, personal_scope(auth))


@router.get("/api/team/libraries/{library_id}/eda/summary")
def team_summary(library_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return summary_impl(db, team_scope(db, library_id, auth, edit=False))


def summary_impl(db: Session, scope: EngineeringScope) -> dict:
    assets = scoped(db.query(EdaAsset), EdaAsset, scope)
    bindings = scoped(db.query(EdaComponentBinding), EdaComponentBinding, scope)
    libraries = scoped(db.query(EdaLibrary), EdaLibrary, scope)
    used = used_bytes(db, scope.scope_type, scope.owner_user_id, scope.team_library_id)
    return {
        "library_count": libraries.filter(EdaLibrary.status == "active").count(),
        "asset_count": assets.filter(EdaAsset.status == "active").count(),
        "binding_count": bindings.count(),
        "raw_count": bindings.filter(EdaComponentBinding.verification_status == "raw").count(),
        "verified_count": bindings.filter(EdaComponentBinding.verification_status == "verified").count(),
        "used_bytes": used,
        "quota_bytes": quota_bytes(scope.scope_type),
    }


@router.get("/api/eda/libraries")
def personal_libraries(auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_libraries_impl(db, personal_scope(auth))


@router.post("/api/eda/libraries")
def create_personal_library(payload: EdaLibraryCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_library_impl(db, personal_scope(auth), payload)


@router.get("/api/team/libraries/{library_id}/eda/libraries")
def team_libraries(library_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_libraries_impl(db, team_scope(db, library_id, auth, edit=False))


@router.post("/api/team/libraries/{library_id}/eda/libraries")
def create_team_library(library_id: str, payload: EdaLibraryCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_library_impl(db, team_scope(db, library_id, auth, edit=True), payload)


def create_version_impl(db: Session, scope: EngineeringScope, library_id: str, payload: EdaLibraryVersionCreate) -> dict:
    require_library(db, scope, library_id)
    exists = (
        db.query(EdaLibraryVersion)
        .filter(EdaLibraryVersion.library_id == library_id, EdaLibraryVersion.version == payload.version.strip())
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="该版本号已存在")
    version = EdaLibraryVersion(
        id=new_uuid(),
        library_id=library_id,
        version=payload.version.strip(),
        change_note=(payload.change_note or "").strip() or None,
        compatible_with_previous=payload.compatible_with_previous,
        status="raw",
        created_by_user_id=scope.auth.user_id,
    )
    db.add(version)
    db.commit()
    return {"id": version.id, "version": version.version, "status": version.status}


@router.post("/api/eda/libraries/{library_id}/versions")
def create_personal_version(library_id: str, payload: EdaLibraryVersionCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_version_impl(db, personal_scope(auth), library_id, payload)


@router.post("/api/team/libraries/{team_library_id}/eda/libraries/{library_id}/versions")
def create_team_version(team_library_id: str, library_id: str, payload: EdaLibraryVersionCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_version_impl(db, team_scope(db, team_library_id, auth, edit=True), library_id, payload)


def publish_check_impl(db: Session, scope: EngineeringScope, version: EdaLibraryVersion) -> dict:
    assets = (
        scoped(db.query(EdaAsset), EdaAsset, scope)
        .filter(EdaAsset.library_version_id == version.id, EdaAsset.status == "active")
        .order_by(EdaAsset.created_at.asc())
        .all()
    )
    bindings = (
        scoped(db.query(EdaComponentBinding), EdaComponentBinding, scope)
        .filter(EdaComponentBinding.library_version_id == version.id)
        .order_by(EdaComponentBinding.updated_at.desc())
        .all()
    )
    risks: list[dict] = []
    if not any(item.asset_type in {"library", "archive"} for item in assets):
        risks.append({"type": "missing_library_file", "message": "没有 SchLib、PcbLib 或 IntLib 库文件"})
    for binding in bindings:
        if not binding.symbol_id:
            risks.append({"type": "missing_symbol", "component_id": binding.component_id, "message": "缺少原理图符号"})
        if not binding.footprint_id:
            risks.append({"type": "missing_footprint", "component_id": binding.component_id, "message": "缺少 PCB 封装"})
        if not binding.datasheet_asset_id:
            risks.append({"type": "missing_datasheet", "component_id": binding.component_id, "message": "缺少数据手册"})
        if binding.verification_status != "verified":
            risks.append(
                {
                    "type": "unverified_binding",
                    "component_id": binding.component_id,
                    "message": f"关联状态为 {binding.verification_status}",
                }
            )
    return {
        "version_id": version.id,
        "version": version.version,
        "empty": not assets,
        "asset_count": len(assets),
        "binding_count": len(bindings),
        "risk_count": len(risks),
        "risks": risks,
        "can_publish": bool(assets),
    }


def publish_version_impl(
    db: Session,
    scope: EngineeringScope,
    version_id: str,
    *,
    confirm_risks: bool = False,
) -> dict:
    version = require_version(db, scope, version_id)
    if version.status == "published":
        return {"id": version.id, "version": version.version, "status": version.status, "published_at": version.published_at}
    check = publish_check_impl(db, scope, version)
    if check["empty"]:
        raise HTTPException(status_code=400, detail="工作版本中还没有文件，不能发布")
    if check["risk_count"] and not confirm_risks:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "该版本仍有风险，请查看风险清单并确认后发布",
                "publish_check": check,
            },
        )
    version.status = "published"
    version.published_at = datetime.utcnow()
    db.commit()
    return {"id": version.id, "version": version.version, "status": version.status, "published_at": version.published_at}


def publish_version_impl_with_confirmation(
    db: Session,
    scope: EngineeringScope,
    version_id: str,
    confirm_risks: bool,
) -> dict:
    return publish_version_impl(db, scope, version_id, confirm_risks=confirm_risks)


@router.get("/api/eda/versions/{version_id}/publish-check")
def personal_publish_check(version_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    scope = personal_scope(auth)
    return publish_check_impl(db, scope, require_version(db, scope, version_id))


@router.get("/api/team/libraries/{library_id}/eda/versions/{version_id}/publish-check")
def team_publish_check(
    library_id: str,
    version_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    scope = team_scope(db, library_id, auth, edit=False)
    return publish_check_impl(db, scope, require_version(db, scope, version_id))


@router.post("/api/eda/versions/{version_id}/publish")
def publish_personal_version(
    version_id: str,
    confirm_risks: bool = Query(False),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return publish_version_impl_with_confirmation(db, personal_scope(auth), version_id, confirm_risks)


@router.post("/api/team/libraries/{library_id}/eda/versions/{version_id}/publish")
def publish_team_version(
    library_id: str,
    version_id: str,
    confirm_risks: bool = Query(False),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return publish_version_impl_with_confirmation(
        db,
        team_scope(db, library_id, auth, edit=True),
        version_id,
        confirm_risks,
    )


def create_object_impl(db: Session, scope: EngineeringScope, version_id: str, payload: EdaObjectCreate, kind: str) -> dict:
    require_mutable_version(db, scope, version_id)
    model = EdaSymbol if kind == "symbol" else EdaFootprint
    existing = db.query(model).filter(model.library_version_id == version_id, model.name == payload.name.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail="同版本中已存在同名对象")
    item = model(
        id=new_uuid(),
        library_version_id=version_id,
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        verification_status="raw",
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "name": item.name, "verification_status": item.verification_status}


@router.post("/api/eda/versions/{version_id}/symbols")
def create_personal_symbol(version_id: str, payload: EdaObjectCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_object_impl(db, personal_scope(auth), version_id, payload, "symbol")


@router.post("/api/eda/versions/{version_id}/footprints")
def create_personal_footprint(version_id: str, payload: EdaObjectCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_object_impl(db, personal_scope(auth), version_id, payload, "footprint")


@router.post("/api/team/libraries/{library_id}/eda/versions/{version_id}/symbols")
def create_team_symbol(library_id: str, version_id: str, payload: EdaObjectCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_object_impl(db, team_scope(db, library_id, auth, edit=True), version_id, payload, "symbol")


@router.post("/api/team/libraries/{library_id}/eda/versions/{version_id}/footprints")
def create_team_footprint(library_id: str, version_id: str, payload: EdaObjectCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_object_impl(db, team_scope(db, library_id, auth, edit=True), version_id, payload, "footprint")


def list_objects_impl(db: Session, scope: EngineeringScope, version_id: str) -> dict:
    require_version(db, scope, version_id)
    symbols = db.query(EdaSymbol).filter(EdaSymbol.library_version_id == version_id).order_by(EdaSymbol.name.asc()).all()
    footprints = db.query(EdaFootprint).filter(EdaFootprint.library_version_id == version_id).order_by(EdaFootprint.name.asc()).all()
    return {
        "symbols": [
            {"id": item.id, "name": item.name, "description": item.description, "verification_status": item.verification_status}
            for item in symbols
        ],
        "footprints": [
            {"id": item.id, "name": item.name, "description": item.description, "verification_status": item.verification_status}
            for item in footprints
        ],
    }


@router.get("/api/eda/versions/{version_id}/objects")
def list_personal_objects(version_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_objects_impl(db, personal_scope(auth), version_id)


@router.get("/api/team/libraries/{library_id}/eda/versions/{version_id}/objects")
def list_team_objects(library_id: str, version_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_objects_impl(db, team_scope(db, library_id, auth, edit=False), version_id)


async def stage_impl(db: Session, scope: EngineeringScope, file: UploadFile) -> dict:
    return await stage_upload(
        db,
        file,
        scope_type=scope.scope_type,
        owner_user_id=scope.owner_user_id,
        team_library_id=scope.team_library_id,
    )


@router.post("/api/eda/uploads/stage")
async def stage_personal_upload(file: UploadFile = File(...), auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return await stage_impl(db, personal_scope(auth), file)


@router.post("/api/team/libraries/{library_id}/eda/uploads/stage")
async def stage_team_upload(library_id: str, file: UploadFile = File(...), auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return await stage_impl(db, team_scope(db, library_id, auth, edit=True), file)


async def remote_stage_impl(db: Session, scope: EngineeringScope, payload: EdaRemoteDownload) -> dict:
    return await stage_remote_download(
        db,
        payload.url,
        scope_type=scope.scope_type,
        owner_user_id=scope.owner_user_id,
        team_library_id=scope.team_library_id,
    )


@router.post("/api/eda/uploads/download")
async def download_personal_to_stage(payload: EdaRemoteDownload, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return await remote_stage_impl(db, personal_scope(auth), payload)


@router.post("/api/team/libraries/{library_id}/eda/uploads/download")
async def download_team_to_stage(library_id: str, payload: EdaRemoteDownload, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return await remote_stage_impl(db, team_scope(db, library_id, auth, edit=True), payload)


def publish_asset_impl(db: Session, scope: EngineeringScope, payload: EdaAssetPublish) -> dict:
    if payload.verification_status not in VERIFICATION_STATES:
        raise HTTPException(status_code=400, detail="验证状态无效")
    if payload.library_version_id:
        require_mutable_version(db, scope, payload.library_version_id)
    metadata = consume_stage(
        payload.upload_token,
        scope_type=scope.scope_type,
        owner_user_id=scope.owner_user_id,
        team_library_id=scope.team_library_id,
    )
    asset = EdaAsset(
        id=new_uuid(),
        library_version_id=payload.library_version_id,
        asset_type=metadata["asset_type"],
        original_name=metadata["original_name"],
        storage_path=metadata["storage_path"],
        sha256=metadata["sha256"],
        byte_size=metadata["byte_size"],
        mime_type=metadata.get("mime_type"),
        version_label=(payload.version_label or "").strip() or None,
        source_url=(payload.source_url or "").strip() or None,
        source_license=(payload.source_license or "").strip() or None,
        verification_status=payload.verification_status,
        status="active",
        uploaded_by_user_id=scope.auth.user_id,
    )
    apply_scope(asset, scope)
    db.add(asset)
    if payload.entity_type and payload.entity_id:
        db.add(
            EdaAttachmentLink(
                id=new_uuid(),
                asset_id=asset.id,
                entity_type=payload.entity_type[:40],
                entity_id=payload.entity_id[:80],
                relation_type=payload.relation_type[:40],
                created_by_user_id=scope.auth.user_id,
            )
        )
    db.commit()
    return asset_out(asset)


@router.post("/api/eda/assets")
def publish_personal_asset(payload: EdaAssetPublish, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return publish_asset_impl(db, personal_scope(auth), payload)


@router.post("/api/team/libraries/{library_id}/eda/assets")
def publish_team_asset(library_id: str, payload: EdaAssetPublish, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return publish_asset_impl(db, team_scope(db, library_id, auth, edit=True), payload)


def list_assets_impl(db: Session, scope: EngineeringScope, status: str | None) -> list[dict]:
    query = scoped(db.query(EdaAsset), EdaAsset, scope)
    if status:
        query = query.filter(EdaAsset.status == status)
    else:
        query = query.filter(EdaAsset.status != "purged")
    return [asset_out(item) for item in query.order_by(EdaAsset.created_at.desc()).all()]


@router.get("/api/eda/assets")
def list_personal_assets(status: str | None = None, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_assets_impl(db, personal_scope(auth), status)


@router.get("/api/eda/attachments/{entity_type}/{entity_id}")
def list_personal_entity_assets(entity_type: str, entity_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return entity_assets_impl(db, personal_scope(auth), entity_type[:40], entity_id[:80])


@router.get("/api/team/libraries/{library_id}/eda/assets")
def list_team_assets(library_id: str, status: str | None = None, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_assets_impl(db, team_scope(db, library_id, auth, edit=False), status)


@router.get("/api/team/libraries/{library_id}/eda/attachments/{entity_type}/{entity_id}")
def list_team_entity_assets(library_id: str, entity_type: str, entity_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return entity_assets_impl(db, team_scope(db, library_id, auth, edit=False), entity_type[:40], entity_id[:80])


def download_asset_impl(db: Session, scope: EngineeringScope, asset_id: str):
    asset = require_asset(db, scope, asset_id)
    return FileResponse(
        resolve_asset_path(asset.storage_path),
        media_type=asset.mime_type or "application/octet-stream",
        filename=asset.original_name,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/api/eda/assets/{asset_id}/download")
def download_personal_asset(asset_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return download_asset_impl(db, personal_scope(auth), asset_id)


@router.get("/api/team/libraries/{library_id}/eda/assets/{asset_id}/download")
def download_team_asset(library_id: str, asset_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return download_asset_impl(db, team_scope(db, library_id, auth, edit=False), asset_id)


def archive_asset_impl(db: Session, scope: EngineeringScope, asset_id: str) -> dict:
    asset = require_asset(db, scope, asset_id)
    if asset.library_version_id:
        version = require_version(db, scope, asset.library_version_id)
        if version.status == "published":
            raise HTTPException(status_code=409, detail="已发布版本文件不可归档，请创建替代版本")
    asset.status = "trash"
    asset.archived_at = datetime.utcnow()
    asset.purge_after = datetime.utcnow() + timedelta(days=30)
    db.commit()
    return asset_out(asset)


def restore_asset_impl(db: Session, scope: EngineeringScope, asset_id: str) -> dict:
    asset = require_asset(db, scope, asset_id)
    asset.status = "active"
    asset.archived_at = None
    asset.purge_after = None
    db.commit()
    return asset_out(asset)


def purge_asset_impl(db: Session, scope: EngineeringScope, asset_id: str, confirm: str) -> dict:
    asset = require_asset(db, scope, asset_id)
    if confirm != "永久删除":
        raise HTTPException(status_code=400, detail="确认文本不正确")
    if asset.status != "trash":
        raise HTTPException(status_code=409, detail="文件必须先进入回收站才能永久删除")
    if asset.library_version_id:
        version = require_version(db, scope, asset.library_version_id)
        if version.status == "published":
            raise HTTPException(status_code=409, detail="已发布版本文件不可永久删除")
    path = resolve_asset_path(asset.storage_path)
    duplicate = (
        db.query(EdaAsset)
        .filter(
            EdaAsset.id != asset.id,
            EdaAsset.storage_path == asset.storage_path,
            EdaAsset.status != "purged",
        )
        .first()
    )
    if not duplicate:
        path.unlink(missing_ok=True)
    db.query(EdaAttachmentLink).filter(EdaAttachmentLink.asset_id == asset.id).delete(
        synchronize_session=False
    )
    db.query(EdaComponentBinding).filter(
        EdaComponentBinding.datasheet_asset_id == asset.id
    ).update({EdaComponentBinding.datasheet_asset_id: None}, synchronize_session=False)
    db.query(EdaComponentBinding).filter(
        EdaComponentBinding.model_asset_id == asset.id
    ).update({EdaComponentBinding.model_asset_id: None}, synchronize_session=False)
    db.query(EdaVerification).filter(
        EdaVerification.evidence_asset_id == asset.id
    ).update({EdaVerification.evidence_asset_id: None}, synchronize_session=False)
    asset.status = "purged"
    asset.archived_at = asset.archived_at or datetime.utcnow()
    asset.purge_after = None
    db.commit()
    return {"purged": True, "id": asset.id}


def purge_expired_assets(db: Session) -> int:
    rows = (
        db.query(EdaAsset)
        .filter(
            EdaAsset.status == "trash",
            EdaAsset.purge_after.isnot(None),
            EdaAsset.purge_after <= datetime.utcnow(),
        )
        .all()
    )
    count = 0
    for asset in rows:
        scope = EngineeringScope(
            asset.scope_type,
            asset.owner_user_id,
            asset.team_library_id,
            AuthContext(asset.uploaded_by_user_id or 0, "", "system"),
            True,
        )
        purge_asset_impl(db, scope, asset.id, "永久删除")
        count += 1
    return count


@router.post("/api/eda/assets/{asset_id}/archive")
def archive_personal_asset(asset_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return archive_asset_impl(db, personal_scope(auth), asset_id)


@router.post("/api/eda/assets/{asset_id}/restore")
def restore_personal_asset(asset_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return restore_asset_impl(db, personal_scope(auth), asset_id)


@router.delete("/api/eda/assets/{asset_id}")
def purge_personal_asset(asset_id: str, confirm: str = Query(""), auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return purge_asset_impl(db, personal_scope(auth), asset_id, confirm)


@router.post("/api/team/libraries/{library_id}/eda/assets/{asset_id}/archive")
def archive_team_asset(library_id: str, asset_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return archive_asset_impl(db, team_scope(db, library_id, auth, edit=True), asset_id)


@router.post("/api/team/libraries/{library_id}/eda/assets/{asset_id}/restore")
def restore_team_asset(library_id: str, asset_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return restore_asset_impl(db, team_scope(db, library_id, auth, edit=True), asset_id)


@router.delete("/api/team/libraries/{library_id}/eda/assets/{asset_id}")
def purge_team_asset(library_id: str, asset_id: str, confirm: str = Query(""), auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return purge_asset_impl(db, team_scope(db, library_id, auth, edit=True), asset_id, confirm)


def create_binding_impl(db: Session, scope: EngineeringScope, payload: EdaBindingCreate) -> dict:
    require_component(db, scope, payload.component_id)
    if payload.library_version_id:
        require_version(db, scope, payload.library_version_id)
    symbol = db.get(EdaSymbol, payload.symbol_id) if payload.symbol_id else None
    footprint = db.get(EdaFootprint, payload.footprint_id) if payload.footprint_id else None
    if payload.symbol_id and not symbol:
        raise HTTPException(status_code=404, detail="Symbol 不存在")
    if payload.footprint_id and not footprint:
        raise HTTPException(status_code=404, detail="Footprint 不存在")
    if symbol:
        require_version(db, scope, symbol.library_version_id)
    if footprint:
        require_version(db, scope, footprint.library_version_id)
    if symbol and payload.library_version_id and symbol.library_version_id != payload.library_version_id:
        raise HTTPException(status_code=400, detail="Symbol 不属于所选库版本")
    if footprint and payload.library_version_id and footprint.library_version_id != payload.library_version_id:
        raise HTTPException(status_code=400, detail="Footprint 不属于所选库版本")
    for asset_id in [payload.datasheet_asset_id, payload.model_asset_id]:
        if asset_id:
            require_asset(db, scope, asset_id)
    if payload.is_primary:
        scoped(db.query(EdaComponentBinding), EdaComponentBinding, scope).filter(
            EdaComponentBinding.component_id == payload.component_id,
            EdaComponentBinding.is_primary == True,
        ).update({EdaComponentBinding.is_primary: False}, synchronize_session=False)
    binding = EdaComponentBinding(
        id=new_uuid(),
        component_id=payload.component_id,
        library_version_id=payload.library_version_id,
        symbol_id=payload.symbol_id,
        footprint_id=payload.footprint_id,
        datasheet_asset_id=payload.datasheet_asset_id,
        model_asset_id=payload.model_asset_id,
        is_primary=payload.is_primary,
        verification_status="raw",
        source=(payload.source or "").strip() or None,
        note=(payload.note or "").strip() or None,
        created_by_user_id=scope.auth.user_id,
    )
    apply_scope(binding, scope)
    db.add(binding)
    db.commit()
    return binding_out(db, binding)


def component_options_impl(db: Session, scope: EngineeringScope, keyword: str, limit: int) -> list[dict]:
    query = db.query(Component).filter(Component.revoked_at.is_(None))
    if scope.scope_type == "personal":
        query = query.filter(Component.owner_user_id == scope.owner_user_id)
    else:
        query = (
            query.join(
                CompetitionLibraryComponent,
                CompetitionLibraryComponent.cw_component_id == Component.id,
            )
            .filter(CompetitionLibraryComponent.library_id == scope.team_library_id)
        )
    text = str(keyword or "").strip()
    if text:
        filters = []
        for variant in keyword_unit_variants(text):
            like = f"%{variant}%"
            filters.extend(
                [
                    Component.warehouse_code.ilike(like),
                    Component.name.ilike(like),
                    Component.model.ilike(like),
                    Component.lcsc_number.ilike(like),
                    Component.parameters.ilike(like),
                    Component.normalized_spec.ilike(like),
                ]
            )
        query = query.filter(or_(*filters))
    rows = query.order_by(Component.name.asc(), Component.id.asc()).limit(limit).all()
    return [
        {
            "id": item.id,
            "warehouse_code": item.warehouse_code,
            "name": item.name,
            "model": item.model,
            "lcsc_number": item.lcsc_number,
            "package": item.package,
            "category": item.category.name if item.category else None,
        }
        for item in rows
    ]


@router.get("/api/eda/component-options")
def personal_component_options(
    q: str = Query("", max_length=160),
    limit: int = Query(20, ge=1, le=50),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return component_options_impl(db, personal_scope(auth), q, limit)


@router.get("/api/team/libraries/{library_id}/eda/component-options")
def team_component_options(
    library_id: str,
    q: str = Query("", max_length=160),
    limit: int = Query(20, ge=1, le=50),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return component_options_impl(db, team_scope(db, library_id, auth, edit=False), q, limit)


def exact_object(db: Session, version_id: str, name: str | None, model):
    clean = str(name or "").strip()
    if not clean:
        return None
    item = db.query(model).filter(model.library_version_id == version_id, model.name == clean).first()
    if item:
        return item
    item = model(
        id=new_uuid(),
        library_version_id=version_id,
        name=clean,
        verification_status="raw",
    )
    db.add(item)
    db.flush()
    return item


def quick_binding_impl(db: Session, scope: EngineeringScope, payload: EdaQuickBindingCreate) -> dict:
    require_component(db, scope, payload.component_id)
    version_id = payload.library_version_id
    if not version_id:
        version_id = workspace_impl(db, scope)["version"]["id"]
    require_mutable_version(db, scope, version_id)
    symbol = exact_object(db, version_id, payload.symbol_name, EdaSymbol)
    footprint = exact_object(db, version_id, payload.footprint_name, EdaFootprint)
    for asset_id in [payload.datasheet_asset_id, payload.model_asset_id]:
        if asset_id:
            require_asset(db, scope, asset_id)
    binding = (
        scoped(db.query(EdaComponentBinding), EdaComponentBinding, scope)
        .filter(
            EdaComponentBinding.component_id == payload.component_id,
            EdaComponentBinding.is_primary == True,
        )
        .first()
    )
    if binding and binding.library_version_id != version_id:
        binding.is_primary = False
        binding = None
    previous_status = binding.verification_status if binding else None
    previous_values = (
        binding.symbol_id,
        binding.footprint_id,
        binding.datasheet_asset_id,
        binding.model_asset_id,
        binding.library_version_id,
    ) if binding else None
    if not binding:
        binding = EdaComponentBinding(
            id=new_uuid(),
            component_id=payload.component_id,
            is_primary=True,
            verification_status="raw",
            created_by_user_id=scope.auth.user_id,
        )
        apply_scope(binding, scope)
        db.add(binding)
    binding.library_version_id = version_id
    binding.symbol_id = symbol.id if symbol else None
    binding.footprint_id = footprint.id if footprint else None
    binding.datasheet_asset_id = payload.datasheet_asset_id
    binding.model_asset_id = payload.model_asset_id
    binding.source = (payload.source or "").strip() or None
    binding.note = (payload.note or "").strip() or None
    current_values = (
        binding.symbol_id,
        binding.footprint_id,
        binding.datasheet_asset_id,
        binding.model_asset_id,
        binding.library_version_id,
    )
    if previous_values is None or previous_values != current_values:
        binding.verification_status = "raw"
        if previous_status and previous_status != "raw":
            db.add(
                EdaVerification(
                    id=new_uuid(),
                    binding_id=binding.id,
                    from_status=previous_status,
                    to_status="raw",
                    checklist_json="{}",
                    note="工程关联已修改，系统自动退回待检查",
                    verified_by_user_id=scope.auth.user_id,
                )
            )
    db.commit()
    return binding_out(db, binding)


@router.post("/api/eda/quick-bindings")
def personal_quick_binding(
    payload: EdaQuickBindingCreate,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return quick_binding_impl(db, personal_scope(auth), payload)


@router.post("/api/team/libraries/{library_id}/eda/quick-bindings")
def team_quick_binding(
    library_id: str,
    payload: EdaQuickBindingCreate,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return quick_binding_impl(db, team_scope(db, library_id, auth, edit=True), payload)


@router.post("/api/eda/bindings")
def create_personal_binding(payload: EdaBindingCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_binding_impl(db, personal_scope(auth), payload)


@router.post("/api/team/libraries/{library_id}/eda/bindings")
def create_team_binding(library_id: str, payload: EdaBindingCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_binding_impl(db, team_scope(db, library_id, auth, edit=True), payload)


def list_bindings_impl(db: Session, scope: EngineeringScope, component_id: int | None) -> list[dict]:
    query = scoped(db.query(EdaComponentBinding), EdaComponentBinding, scope)
    if component_id:
        require_component(db, scope, component_id)
        query = query.filter(EdaComponentBinding.component_id == component_id)
    return [binding_out(db, item) for item in query.order_by(EdaComponentBinding.updated_at.desc()).all()]


@router.get("/api/eda/bindings")
def list_personal_bindings(component_id: int | None = None, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_bindings_impl(db, personal_scope(auth), component_id)


@router.get("/api/team/libraries/{library_id}/eda/bindings")
def list_team_bindings(library_id: str, component_id: int | None = None, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_bindings_impl(db, team_scope(db, library_id, auth, edit=False), component_id)


def verify_binding_impl(db: Session, scope: EngineeringScope, binding_id: str, payload: EdaVerificationCreate) -> dict:
    if payload.status not in VERIFICATION_STATES:
        raise HTTPException(status_code=400, detail="验证状态无效")
    binding = scoped(db.query(EdaComponentBinding), EdaComponentBinding, scope).filter(EdaComponentBinding.id == binding_id).first()
    if not binding:
        raise HTTPException(status_code=404, detail="EDA 绑定不存在")
    if payload.evidence_asset_id:
        require_asset(db, scope, payload.evidence_asset_id)
    if payload.status == "verified":
        checklist = payload.checklist or {}
        required = {"datasheet_checked", "symbol_checked", "footprint_checked"}
        if not all(bool(checklist.get(key)) for key in required):
            raise HTTPException(status_code=400, detail="Verified 需要完成数据手册、Symbol 和 Footprint 检查")
        if not (payload.note or payload.evidence_asset_id):
            raise HTTPException(status_code=400, detail="Verified 需要复核说明或证据附件")
    previous = binding.verification_status
    binding.verification_status = payload.status
    verification = EdaVerification(
        id=new_uuid(),
        binding_id=binding.id,
        from_status=previous,
        to_status=payload.status,
        checklist_json=json.dumps(payload.checklist or {}, ensure_ascii=False),
        evidence_asset_id=payload.evidence_asset_id,
        note=(payload.note or "").strip() or None,
        verified_by_user_id=scope.auth.user_id,
    )
    db.add(verification)
    db.commit()
    return binding_out(db, binding)


@router.post("/api/eda/bindings/{binding_id}/verify")
def verify_personal_binding(binding_id: str, payload: EdaVerificationCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return verify_binding_impl(db, personal_scope(auth), binding_id, payload)


@router.post("/api/team/libraries/{library_id}/eda/bindings/{binding_id}/verify")
def verify_team_binding(library_id: str, binding_id: str, payload: EdaVerificationCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return verify_binding_impl(db, team_scope(db, library_id, auth, edit=True), binding_id, payload)


def supplier_parts_impl(db: Session, scope: EngineeringScope, component_id: int | None = None) -> list[dict]:
    query = scoped(db.query(SupplierPart), SupplierPart, scope).filter(SupplierPart.status == "active")
    if component_id:
        require_component(db, scope, component_id)
        query = query.filter(SupplierPart.component_id == component_id)
    return [
        {
            "id": item.id,
            "component_id": item.component_id,
            "supplier": item.supplier,
            "supplier_part_number": item.supplier_part_number,
            "purchase_url": item.purchase_url,
            "currency": item.currency,
            "unit_price": item.unit_price,
            "is_preferred": item.is_preferred,
        }
        for item in query.order_by(SupplierPart.is_preferred.desc(), SupplierPart.updated_at.desc()).all()
    ]


def create_supplier_part_impl(db: Session, scope: EngineeringScope, payload: SupplierPartCreate) -> dict:
    require_component(db, scope, payload.component_id)
    if payload.is_preferred:
        scoped(db.query(SupplierPart), SupplierPart, scope).filter(
            SupplierPart.component_id == payload.component_id
        ).update({SupplierPart.is_preferred: False}, synchronize_session=False)
    item = SupplierPart(
        id=new_uuid(),
        component_id=payload.component_id,
        supplier=payload.supplier.strip(),
        supplier_part_number=payload.supplier_part_number.strip(),
        purchase_url=(payload.purchase_url or "").strip() or None,
        currency=payload.currency.strip().upper()[:8] or "CNY",
        unit_price=payload.unit_price,
        is_preferred=payload.is_preferred,
        status="active",
    )
    apply_scope(item, scope)
    db.add(item)
    db.commit()
    return supplier_parts_impl(db, scope, payload.component_id)[0 if item.is_preferred else -1]


@router.get("/api/eda/supplier-parts")
def list_personal_supplier_parts(component_id: int | None = None, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return supplier_parts_impl(db, personal_scope(auth), component_id)


@router.post("/api/eda/supplier-parts")
def create_personal_supplier_part(payload: SupplierPartCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_supplier_part_impl(db, personal_scope(auth), payload)


@router.get("/api/team/libraries/{library_id}/eda/supplier-parts")
def list_team_supplier_parts(library_id: str, component_id: int | None = None, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return supplier_parts_impl(db, team_scope(db, library_id, auth, edit=False), component_id)


@router.post("/api/team/libraries/{library_id}/eda/supplier-parts")
def create_team_supplier_part(library_id: str, payload: SupplierPartCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_supplier_part_impl(db, team_scope(db, library_id, auth, edit=True), payload)


def create_sync_token_impl(db: Session, scope: EngineeringScope, payload: EdaSyncTokenCreate) -> dict:
    raw = f"eda_{secrets.token_urlsafe(36)}"
    expires_at = datetime.utcnow() + timedelta(days=payload.expires_in_days or 365)
    record = EdaSyncToken(
        id=new_uuid(),
        name=payload.name.strip(),
        token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        token_prefix=raw[:12],
        status="active",
        created_by_user_id=scope.auth.user_id,
        expires_at=expires_at,
    )
    apply_scope(record, scope)
    db.add(record)
    db.commit()
    return {
        "id": record.id,
        "name": record.name,
        "token": raw,
        "token_prefix": record.token_prefix,
        "expires_at": record.expires_at,
    }


def list_sync_tokens_impl(db: Session, scope: EngineeringScope) -> list[dict]:
    rows = scoped(db.query(EdaSyncToken), EdaSyncToken, scope).order_by(EdaSyncToken.created_at.desc()).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "token_prefix": item.token_prefix,
            "status": item.status,
            "last_used_at": item.last_used_at,
            "expires_at": item.expires_at,
            "revoked_at": item.revoked_at,
            "created_at": item.created_at,
        }
        for item in rows
    ]


@router.get("/api/eda/sync-tokens")
def list_personal_sync_tokens(auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_sync_tokens_impl(db, personal_scope(auth))


@router.get("/api/team/libraries/{library_id}/eda/sync-tokens")
def list_team_sync_tokens(library_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_sync_tokens_impl(db, team_scope(db, library_id, auth, edit=False))


@router.post("/api/eda/sync-tokens")
def create_personal_sync_token(payload: EdaSyncTokenCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_sync_token_impl(db, personal_scope(auth), payload)


@router.post("/api/team/libraries/{library_id}/eda/sync-tokens")
def create_team_sync_token(library_id: str, payload: EdaSyncTokenCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_sync_token_impl(db, team_scope(db, library_id, auth, edit=True), payload)


def revoke_sync_token_impl(db: Session, scope: EngineeringScope, token_id: str) -> dict:
    record = scoped(db.query(EdaSyncToken), EdaSyncToken, scope).filter(EdaSyncToken.id == token_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="同步令牌不存在")
    record.status = "revoked"
    record.revoked_at = datetime.utcnow()
    db.commit()
    return {"revoked": True, "id": record.id}


@router.delete("/api/eda/sync-tokens/{token_id}")
def revoke_personal_sync_token(token_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return revoke_sync_token_impl(db, personal_scope(auth), token_id)


@router.delete("/api/team/libraries/{library_id}/eda/sync-tokens/{token_id}")
def revoke_team_sync_token(library_id: str, token_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return revoke_sync_token_impl(db, team_scope(db, library_id, auth, edit=True), token_id)


def sync_scope(db: Session, raw_token: str) -> EngineeringScope:
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    record = db.query(EdaSyncToken).filter(EdaSyncToken.token_hash == token_hash).first()
    if (
        not record
        or record.status != "active"
        or (record.expires_at and record.expires_at <= datetime.utcnow())
    ):
        raise HTTPException(status_code=401, detail="同步令牌无效或已过期")
    record.last_used_at = datetime.utcnow()
    user_id = record.owner_user_id or record.created_by_user_id
    scope = EngineeringScope(
        record.scope_type,
        record.owner_user_id,
        record.team_library_id,
        AuthContext(user_id, "", "EDA Sync"),
        True,
    )
    db.commit()
    return scope


@router.get("/api/eda/sync/manifest")
def sync_manifest(
    x_eda_sync_token: str = Header(..., alias="X-EDA-Sync-Token"),
    db: Session = Depends(get_db),
):
    scope = sync_scope(db, x_eda_sync_token)
    versions = (
        scoped(
            db.query(EdaLibraryVersion, EdaLibrary)
            .join(EdaLibrary, EdaLibrary.id == EdaLibraryVersion.library_id),
            EdaLibrary,
            scope,
        )
        .filter(EdaLibraryVersion.status == "published")
        .all()
    )
    version_ids = [version.id for version, _ in versions]
    assets = (
        scoped(db.query(EdaAsset), EdaAsset, scope)
        .filter(
            EdaAsset.status == "active",
            EdaAsset.library_version_id.in_(version_ids or [""]),
        )
        .order_by(EdaAsset.created_at.asc())
        .all()
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "scope_type": scope.scope_type,
        "team_library_id": scope.team_library_id,
        "libraries": [
            {
                "id": library.id,
                "name": library.name,
                "version_id": version.id,
                "version": version.version,
                "published_at": version.published_at,
            }
            for version, library in versions
        ],
        "assets": [
            {
                **asset_out(asset),
                "download_url": f"/api/eda/sync/assets/{asset.id}",
            }
            for asset in assets
        ],
    }


@router.get("/api/eda/sync/assets/{asset_id}")
def sync_download_asset(
    asset_id: str,
    x_eda_sync_token: str = Header(..., alias="X-EDA-Sync-Token"),
    db: Session = Depends(get_db),
):
    scope = sync_scope(db, x_eda_sync_token)
    return download_asset_impl(db, scope, asset_id)


def create_draft_from_version(
    db: Session,
    scope: EngineeringScope,
    payload: EdaSyncDraftCreate,
) -> dict:
    base = require_version(db, scope, payload.base_version_id)
    if base.status != "published":
        raise HTTPException(status_code=409, detail="只能基于已发布版本建立同步草稿")
    versions = (
        db.query(EdaLibraryVersion)
        .filter(EdaLibraryVersion.library_id == base.library_id)
        .order_by(EdaLibraryVersion.created_at.desc())
        .all()
    )
    version_label = str(payload.version or "").strip() or next_patch_version(versions)
    if any(item.version == version_label for item in versions):
        version_label = f"{version_label}-local-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    draft = EdaLibraryVersion(
        id=new_uuid(),
        library_id=base.library_id,
        version=version_label,
        change_note=(payload.change_note or "").strip() or f"Windows 客户端基于 {base.version} 创建",
        compatible_with_previous=True,
        status="raw",
        created_by_user_id=scope.auth.user_id,
    )
    db.add(draft)
    db.flush()
    asset_map: dict[str, str] = {}
    for source in (
        scoped(db.query(EdaAsset), EdaAsset, scope)
        .filter(EdaAsset.library_version_id == base.id, EdaAsset.status == "active")
        .all()
    ):
        clone = EdaAsset(
            id=new_uuid(),
            library_version_id=draft.id,
            asset_type=source.asset_type,
            original_name=source.original_name,
            storage_path=source.storage_path,
            sha256=source.sha256,
            byte_size=source.byte_size,
            mime_type=source.mime_type,
            version_label=draft.version,
            source_url=source.source_url,
            source_license=source.source_license,
            verification_status=source.verification_status,
            status="active",
            uploaded_by_user_id=scope.auth.user_id,
        )
        apply_scope(clone, scope)
        db.add(clone)
        asset_map[source.id] = clone.id
    symbol_map: dict[str, str] = {}
    for source in db.query(EdaSymbol).filter(EdaSymbol.library_version_id == base.id).all():
        clone = EdaSymbol(
            id=new_uuid(),
            library_version_id=draft.id,
            name=source.name,
            description=source.description,
            verification_status=source.verification_status,
        )
        db.add(clone)
        symbol_map[source.id] = clone.id
    footprint_map: dict[str, str] = {}
    for source in db.query(EdaFootprint).filter(EdaFootprint.library_version_id == base.id).all():
        clone = EdaFootprint(
            id=new_uuid(),
            library_version_id=draft.id,
            name=source.name,
            description=source.description,
            verification_status=source.verification_status,
            preview_asset_id=asset_map.get(source.preview_asset_id),
            model_asset_id=asset_map.get(source.model_asset_id),
        )
        db.add(clone)
        footprint_map[source.id] = clone.id
    for source in (
        scoped(db.query(EdaComponentBinding), EdaComponentBinding, scope)
        .filter(EdaComponentBinding.library_version_id == base.id)
        .all()
    ):
        clone = EdaComponentBinding(
            id=new_uuid(),
            component_id=source.component_id,
            library_version_id=draft.id,
            symbol_id=symbol_map.get(source.symbol_id),
            footprint_id=footprint_map.get(source.footprint_id),
            datasheet_asset_id=asset_map.get(source.datasheet_asset_id, source.datasheet_asset_id),
            model_asset_id=asset_map.get(source.model_asset_id, source.model_asset_id),
            is_primary=False,
            verification_status="raw",
            source=source.source,
            note=f"从已发布版本 {base.version} 复制；本地修改后需重新检查",
            created_by_user_id=scope.auth.user_id,
        )
        apply_scope(clone, scope)
        db.add(clone)
    db.commit()
    return {
        "id": draft.id,
        "library_id": draft.library_id,
        "version": draft.version,
        "status": draft.status,
        "base_version_id": base.id,
        "asset_count": len(asset_map),
        "symbol_count": len(symbol_map),
        "footprint_count": len(footprint_map),
    }


@router.post("/api/eda/sync/drafts")
def sync_create_draft(
    payload: EdaSyncDraftCreate,
    x_eda_sync_token: str = Header(..., alias="X-EDA-Sync-Token"),
    db: Session = Depends(get_db),
):
    return create_draft_from_version(db, sync_scope(db, x_eda_sync_token), payload)


@router.post("/api/eda/sync/uploads/stage")
async def sync_stage_upload(
    file: UploadFile = File(...),
    x_eda_sync_token: str = Header(..., alias="X-EDA-Sync-Token"),
    db: Session = Depends(get_db),
):
    scope = sync_scope(db, x_eda_sync_token)
    return await stage_impl(db, scope, file)


@router.post("/api/eda/sync/assets")
def sync_publish_asset(
    payload: EdaAssetPublish,
    x_eda_sync_token: str = Header(..., alias="X-EDA-Sync-Token"),
    db: Session = Depends(get_db),
):
    scope = sync_scope(db, x_eda_sync_token)
    payload.verification_status = "raw"
    result = publish_asset_impl(db, scope, payload)
    if payload.library_version_id:
        current = db.get(EdaAsset, result["id"])
        duplicates = (
            scoped(db.query(EdaAsset), EdaAsset, scope)
            .filter(
                EdaAsset.library_version_id == payload.library_version_id,
                EdaAsset.original_name == current.original_name,
                EdaAsset.id != current.id,
                EdaAsset.status == "active",
            )
            .all()
        )
        for duplicate in duplicates:
            duplicate.status = "trash"
            duplicate.archived_at = datetime.utcnow()
            duplicate.purge_after = datetime.utcnow() + timedelta(days=30)
        db.commit()
    return result


@router.get("/api/admin/eda/archive")
def export_eda_archive(
    since: datetime | None = Query(default=None),
    _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(EdaAsset).filter(EdaAsset.status != "purged")
    if since:
        query = query.filter(EdaAsset.created_at >= since)
    assets = query.order_by(EdaAsset.created_at.asc()).all()
    unique_paths: dict[str, EdaAsset] = {}
    for asset in assets:
        unique_paths.setdefault(asset.storage_path, asset)
    temp = tempfile.NamedTemporaryFile(prefix="component-warehouse-eda-", suffix=".zip", delete=False)
    temp_path = temp.name
    temp.close()
    manifest = {
        "app": APP_BACKUP_NAME,
        "type": "eda-incremental" if since else "eda-full",
        "since": since.isoformat() if since else None,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "files": [],
    }
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative_path, asset in unique_paths.items():
                path = resolve_asset_path(relative_path)
                arcname = relative_path
                archive.write(path, arcname)
                manifest["files"].append(
                    {
                        "path": arcname,
                        "sha256": asset.sha256,
                        "bytes": asset.byte_size,
                        "original_name": asset.original_name,
                    }
                )
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    except Exception:
        os.unlink(temp_path)
        raise
    filename = f"component-warehouse-eda-{'incremental' if since else 'full'}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip"
    return FileResponse(
        temp_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: os.path.exists(temp_path) and os.unlink(temp_path)),
    )
