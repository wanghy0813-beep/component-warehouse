import csv
import hashlib
import io
import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from .auth import AuthContext, require_access
from .database import get_db
from .models import (
    CompetitionLibraryComponent,
    Component,
    Project,
    ProjectBomImportBatch,
    ProjectBomImportCandidate,
    ProjectBomImportRow,
    ProjectBomItem,
)
from .services.bom_match import inspect_bom_fields, match_bom_rows, parse_bom_excel
from .services.inventory import reserved_quantities
from .services.substitutions import substitution_suggestions_for_bom_items
from .team import require_library_editor, require_library_member


router = APIRouter(prefix="/api/team/libraries/{library_id}/projects", tags=["team-projects"])
PROJECT_STATUSES = {
    "draft",
    "designing",
    "purchasing",
    "fabricating",
    "assembly",
    "completed",
    "archived",
}


def project_code() -> str:
    return f"TPJ-{uuid4().hex[:8].upper()}"


def require_project(db: Session, library_id: str, project_id: int) -> Project:
    project = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .filter(
            Project.id == project_id,
            Project.scope_type == "team",
            Project.team_library_id == library_id,
        )
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="团队项目不存在")
    return project


def project_out(db: Session, project: Project) -> dict:
    component_ids = [item.component_id for item in project.bom_items]
    reserved = reserved_quantities(db, component_ids)
    substitutions = substitution_suggestions_for_bom_items(db, project.bom_items, reserved)
    items = []
    for item in project.bom_items:
        component = item.component
        available = max(0, int(component.quantity or 0) - reserved.get(component.id, 0) + int(item.required_quantity or 0))
        required = int(item.required_quantity or 0)
        items.append(
            {
                "id": item.id,
                "component_id": component.id,
                "required_quantity": required,
                "status": item.status,
                "remark": item.remark,
                "available_quantity": available,
                "shortage_quantity": max(0, required - available),
                "enough": available >= required,
                "component": {
                    "id": component.id,
                    "warehouse_code": component.warehouse_code,
                    "name": component.name,
                    "model": component.model,
                    "manufacturer": component.manufacturer,
                    "category": component.category,
                    "category_id": component.category_id,
                    "parameters": component.parameters,
                    "package": component.package,
                    "lcsc_number": component.lcsc_number,
                    "quantity": component.quantity,
                    "available_quantity": max(0, int(component.quantity or 0) - reserved.get(component.id, 0)),
                    "normalized_spec": component.normalized_spec,
                },
                "substitution_suggestions": substitutions.get(item.id, []),
            }
        )
    return {
        "id": project.id,
        "project_code": project.project_code,
        "active_fabrication_revision_id": project.active_fabrication_revision_id,
        "public_assembly_view_enabled": bool(project.public_assembly_view_enabled),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "bom_match_total": project.bom_match_total,
        "bom_match_matched": project.bom_match_matched,
        "bom_match_review": project.bom_match_review,
        "bom_match_missing": project.bom_match_missing,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "bom_items": items,
    }


@router.get("")
def list_team_projects(library_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    require_library_member(db, library_id, auth)
    rows = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .filter(Project.scope_type == "team", Project.team_library_id == library_id)
        .order_by(Project.updated_at.desc())
        .all()
    )
    return [project_out(db, item) for item in rows]


@router.post("")
def create_team_project(library_id: str, payload: dict, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    require_library_editor(db, library_id, auth)
    name = str(payload.get("name") or "").strip()
    status = str(payload.get("status") or "draft").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写项目名称")
    if status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail="项目状态无效")
    project = Project(
        scope_type="team",
        owner_user_id=None,
        team_library_id=library_id,
        project_code=project_code(),
        name=name[:200],
        description=str(payload.get("description") or "").strip() or None,
        status=status,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_out(db, project)


@router.put("/{project_id}")
def update_team_project(library_id: str, project_id: int, payload: dict, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    require_library_editor(db, library_id, auth)
    project = require_project(db, library_id, project_id)
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="项目名称不能为空")
        project.name = name[:200]
    if "description" in payload:
        project.description = str(payload.get("description") or "").strip() or None
    if "status" in payload:
        status = str(payload.get("status") or "").strip()
        if status not in PROJECT_STATUSES:
            raise HTTPException(status_code=400, detail="项目状态无效")
        project.status = status
    db.commit()
    return project_out(db, project)


@router.post("/{project_id}/bom")
def add_team_bom_item(library_id: str, project_id: int, payload: dict, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    require_library_editor(db, library_id, auth)
    project = require_project(db, library_id, project_id)
    component_id = int(payload.get("component_id") or 0)
    required = max(1, int(payload.get("required_quantity") or 1))
    linked = (
        db.query(CompetitionLibraryComponent)
        .filter(
            CompetitionLibraryComponent.library_id == library_id,
            CompetitionLibraryComponent.cw_component_id == component_id,
        )
        .first()
    )
    if not linked:
        raise HTTPException(status_code=400, detail="元器件未加入当前团队库")
    existing = (
        db.query(ProjectBomItem)
        .filter(ProjectBomItem.project_id == project.id, ProjectBomItem.component_id == component_id)
        .first()
    )
    if existing:
        existing.required_quantity += required
        existing.remark = "\n".join(filter(None, [existing.remark, str(payload.get("remark") or "").strip()])) or None
    else:
        db.add(
            ProjectBomItem(
                project_id=project.id,
                component_id=component_id,
                required_quantity=required,
                status="reserved",
                remark=str(payload.get("remark") or "").strip() or None,
            )
        )
    db.commit()
    db.refresh(project)
    return project_out(db, project)


def team_project_csv(db: Session, project: Project, shortage_only: bool) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["项目", "名称", "厂商", "型号", "封装", "需求数量", "可用库存", "缺料数量", "LCSC", "位号/备注"])
    for item in project_out(db, project)["bom_items"]:
        if shortage_only and item["enough"]:
            continue
        component = item["component"]
        writer.writerow(
            [
                project.name,
                component["name"],
                component.get("manufacturer") or "",
                component.get("model") or "",
                component.get("package") or "",
                item["required_quantity"],
                item["available_quantity"],
                item["shortage_quantity"],
                component.get("lcsc_number") or "",
                item.get("remark") or "",
            ]
        )
    suffix = "shortage" if shortage_only else "bom"
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="team-project-{project.id}-{suffix}.csv"'},
    )


@router.get("/{project_id}/export")
def export_team_project_bom(library_id: str, project_id: int, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    require_library_member(db, library_id, auth)
    return team_project_csv(db, require_project(db, library_id, project_id), False)


@router.get("/{project_id}/shortage/export")
def export_team_project_shortage(library_id: str, project_id: int, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    require_library_member(db, library_id, auth)
    return team_project_csv(db, require_project(db, library_id, project_id), True)


def save_import_batch(
    db: Session,
    project: Project,
    filename: str | None,
    content: bytes,
    rows: list[dict],
    field_mapping: dict | None = None,
) -> ProjectBomImportBatch:
    batch = ProjectBomImportBatch(
        project_id=project.id,
        source_file=filename,
        source_sha256=hashlib.sha256(content).hexdigest(),
        status="pending",
        total_count=len(rows),
        matched_count=sum(1 for row in rows if row.get("selected_component_id")),
        review_count=sum(1 for row in rows if row.get("status") == "review"),
        missing_count=sum(1 for row in rows if row.get("status") in {"missing", "supplier_missing"}),
        field_mapping_json=json.dumps(
            field_mapping or {"mode": "auto_exact_headers"},
            ensure_ascii=False,
        ),
        analysis_json=json.dumps(
            {
                "matching_policy": "exact_only",
                "generated_at": datetime.utcnow().isoformat() + "Z",
            },
            ensure_ascii=False,
        ),
    )
    db.add(batch)
    db.flush()
    for row in rows:
        import_row = ProjectBomImportRow(
            batch_id=batch.id,
            project_id=project.id,
            source_row=row.get("source_row"),
            designator=row.get("designator"),
            required_quantity=int(row.get("required_quantity") or 1),
            comment=row.get("comment"),
            footprint=row.get("footprint"),
            value=row.get("value"),
            manufacturer_part=row.get("manufacturer_part"),
            supplier_part=row.get("supplier_part"),
            status=row.get("status") or "missing",
            selected_component_id=row.get("selected_component_id"),
            match_confidence=int(row.get("match_confidence") or 0),
            role=row.get("role"),
            ai_reason=row.get("ai_reason"),
        )
        db.add(import_row)
        db.flush()
        row["id"] = import_row.id
        for rank, match in enumerate(row.get("matches") or []):
            component = match.get("component") or {}
            if not component.get("id"):
                continue
            db.add(
                ProjectBomImportCandidate(
                    import_row_id=import_row.id,
                    component_id=int(component["id"]),
                    score=int(match.get("score") or 0),
                    match_type=match.get("match_type"),
                    reason=match.get("reason"),
                    flags=",".join(match.get("flags") or []),
                    available_quantity=int(match.get("available_quantity") or 0),
                    shortage_quantity=int(match.get("shortage_quantity") or 0),
                    enough=bool(match.get("enough")),
                    rank=rank,
                )
            )
    project.bom_match_total = batch.total_count
    project.bom_match_matched = batch.matched_count
    project.bom_match_review = batch.review_count
    project.bom_match_missing = batch.missing_count
    project.bom_match_updated_at = datetime.utcnow()
    db.commit()
    return batch


@router.post("/{project_id}/bom/import")
async def import_team_bom(
    library_id: str,
    project_id: int,
    file: UploadFile = File(...),
    field_mapping_json: str | None = Form(None),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    require_library_editor(db, library_id, auth)
    project = require_project(db, library_id, project_id)
    content = await file.read()
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="BOM 文件为空或超过 20MB")
    try:
        field_mapping = json.loads(field_mapping_json) if field_mapping_json else None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="BOM 字段映射格式无效") from exc
    rows = parse_bom_excel(content, file.filename, field_mapping)
    component_ids = [
        component_id
        for (component_id,) in db.query(CompetitionLibraryComponent.cw_component_id)
        .filter(
            CompetitionLibraryComponent.library_id == library_id,
            CompetitionLibraryComponent.cw_component_id.isnot(None),
        )
        .all()
    ]
    matched = match_bom_rows(
        db,
        rows,
        component_ids=component_ids,
        supplier_scope_type="team",
        supplier_team_library_id=library_id,
    )
    batch = save_import_batch(db, project, file.filename, content, matched, field_mapping)
    return {
        "batch_id": batch.id,
        "total_count": batch.total_count,
        "matched_count": batch.matched_count,
        "review_count": batch.review_count,
        "missing_count": batch.missing_count,
        "rows": matched,
    }


@router.post("/{project_id}/bom/inspect")
async def inspect_team_bom(
    library_id: str,
    project_id: int,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    require_library_editor(db, library_id, auth)
    require_project(db, library_id, project_id)
    content = await file.read()
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="BOM 文件为空或超过 20MB")
    try:
        return inspect_bom_fields(content, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"BOM 字段读取失败：{exc}") from exc


@router.post("/{project_id}/bom/import/{batch_id}/commit")
def commit_team_bom(library_id: str, project_id: int, batch_id: int, payload: dict, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    require_library_editor(db, library_id, auth)
    project = require_project(db, library_id, project_id)
    batch = (
        db.query(ProjectBomImportBatch)
        .filter(ProjectBomImportBatch.id == batch_id, ProjectBomImportBatch.project_id == project.id)
        .first()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="BOM 导入批次不存在")
    selections = {
        int(item.get("row_id")): int(item.get("component_id"))
        for item in payload.get("items", [])
        if item.get("row_id") and item.get("component_id")
    }
    rows = db.query(ProjectBomImportRow).filter(ProjectBomImportRow.batch_id == batch.id).all()
    added = updated = 0
    for row in rows:
        component_id = selections.get(row.id) or row.selected_component_id
        if not component_id:
            continue
        linked = (
            db.query(CompetitionLibraryComponent)
            .filter(
                CompetitionLibraryComponent.library_id == library_id,
                CompetitionLibraryComponent.cw_component_id == component_id,
            )
            .first()
        )
        if not linked:
            continue
        item = (
            db.query(ProjectBomItem)
            .filter(ProjectBomItem.project_id == project.id, ProjectBomItem.component_id == component_id)
            .first()
        )
        remark = f"BOM 批次:{batch.id}；位号:{row.designator or '-'}；封装:{row.footprint or '-'}"
        if item:
            item.required_quantity += int(row.required_quantity or 1)
            item.remark = "\n".join(filter(None, [item.remark, remark]))
            updated += 1
        else:
            db.add(
                ProjectBomItem(
                    project_id=project.id,
                    component_id=component_id,
                    required_quantity=int(row.required_quantity or 1),
                    status="reserved",
                    remark=remark,
                )
            )
            added += 1
        row.selected_component_id = component_id
        row.status = "imported"
        row.auto_imported = True
    batch.status = "committed"
    db.commit()
    db.refresh(project)
    return {"added": added, "updated": updated, "project": project_out(db, project)}
