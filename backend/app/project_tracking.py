import json
import secrets
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .auth import AuthContext, require_access
from .database import get_db
from .models import (
    ActivityLog,
    EdaAsset,
    Project,
    ProjectCodeAlias,
    ProjectExpense,
    ProjectPcbVersion,
    ProjectStatusEvent,
)
from .project_tracking_schemas import (
    ProjectCodeChangeCreate,
    ProjectExpenseCreate,
    ProjectExpenseUpdate,
    ProjectPcbVersionCreate,
    ProjectPcbVersionUpdate,
    ProjectStatusTransitionCreate,
)
from .services.project_tracking import (
    EXPENSE_CATEGORY_LABELS,
    PCB_VERSION_STATUS_LABELS,
    PROJECT_ACTIVE_STATUSES,
    PROJECT_STATUS_LABELS,
    active_version,
    assert_project_code_available,
    cost_summary,
    create_version,
    expense_out,
    fill_unpriced_material_events,
    iso_week_label,
    normalize_project_code,
    normalize_version_code,
    project_by_code_or_alias,
    project_period,
    shanghai_today,
    version_stats,
)


router = APIRouter(tags=["project-tracking"])
Protected = Annotated[AuthContext, Depends(require_access)]


def require_personal_project(db: Session, project_id: int, auth: AuthContext) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.scope_type == "personal",
        Project.owner_user_id == auth.user_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def require_version(db: Session, project: Project, version_id: int) -> ProjectPcbVersion:
    version = db.query(ProjectPcbVersion).filter(
        ProjectPcbVersion.id == version_id,
        ProjectPcbVersion.project_id == project.id,
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="PCB 版本不存在")
    return version


def log_project_activity(
    db: Session,
    project: Project,
    auth: AuthContext,
    action: str,
    summary: str,
    detail: dict | None = None,
) -> None:
    db.add(
        ActivityLog(
            owner_user_id=auth.user_id,
            action=action,
            entity_type="project",
            entity_id=project.id,
            project_id=project.id,
            summary=summary[:300],
            detail=json.dumps(detail or {}, ensure_ascii=False, default=str),
        )
    )


def project_summary(db: Session, project: Project) -> dict:
    version = active_version(db, project)
    version_row = version_stats(db, project, version) if version else None
    costs = cost_summary(db, project)
    period = project_period(project)
    has_bom = bool(version_row and version_row["bom_item_count"])
    unpriced = costs["unpriced_bom_items"] + costs["unpriced_material_events"]
    return {
        "id": project.id,
        "project_code": project.project_code,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "status_label": PROJECT_STATUS_LABELS.get(project.status, project.status),
        "archived": project.archived_at is not None,
        "archived_at": project.archived_at,
        "active_version_id": version.id if version else None,
        "active_version_code": version.version_code if version else None,
        "current_version": version_row,
        "period": period,
        "iso_week": period["end_week"] or period["start_week"],
        "bom_status": "未计价" if has_bom and costs["unpriced_bom_items"] else ("已上传" if has_bom else "未上传"),
        "solder_progress": version_row["solder_progress"] if version_row else 0,
        "actual_material_cost": costs["actual_material_cost"],
        "direct_expense": costs["direct_expense"],
        "comprehensive_cost": costs["comprehensive_cost"],
        "unpriced_count": unpriced,
        "cost_anomaly": unpriced > 0,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


@router.get("/api/projects/overview")
def projects_overview(
    auth: Protected,
    db: Session = Depends(get_db),
    search: str | None = None,
    statuses: str | None = None,
    iso_week: str | None = None,
    cost_anomaly: bool | None = None,
    include_archived: bool = False,
    include_cancelled: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    query = db.query(Project).filter(
        Project.scope_type == "personal",
        Project.owner_user_id == auth.user_id,
    )
    all_projects = query.order_by(Project.updated_at.desc(), Project.id.desc()).all()
    all_rows = [project_summary(db, project) for project in all_projects]

    filtered = all_rows
    if not include_archived:
        filtered = [row for row in filtered if not row["archived"]]
    if not include_cancelled:
        filtered = [row for row in filtered if row["status"] != "cancelled"]
    if search:
        needle = search.strip().lower()
        filtered = [
            row
            for row in filtered
            if needle in str(row["project_code"] or "").lower()
            or needle in str(row["name"] or "").lower()
        ]
    selected_statuses = {item.strip() for item in str(statuses or "").split(",") if item.strip()}
    if selected_statuses:
        filtered = [row for row in filtered if row["status"] in selected_statuses]
    if iso_week:
        filtered = [
            row
            for row in filtered
            if iso_week.upper() in {str(row["period"].get("start_week") or ""), str(row["period"].get("end_week") or "")}
        ]
    if cost_anomaly is not None:
        filtered = [row for row in filtered if bool(row["cost_anomaly"]) == cost_anomaly]

    active_count = sum(1 for row in all_rows if row["status"] in PROJECT_ACTIVE_STATUSES and not row["archived"])
    paused_count = sum(1 for row in all_rows if row["status"] == "paused" and not row["archived"])
    validated_count = sum(1 for row in all_rows if row["status"] in {"validated", "delivered"} and not row["archived"])
    comprehensive = sum((Decimal(str(row["comprehensive_cost"])) for row in all_rows), Decimal("0"))
    unpriced_count = sum(int(row["unpriced_count"] or 0) for row in all_rows)
    status_distribution = [
        {
            "status": status,
            "label": label,
            "count": sum(1 for row in all_rows if row["status"] == status and not row["archived"]),
        }
        for status, label in PROJECT_STATUS_LABELS.items()
        if any(row["status"] == status and not row["archived"] for row in all_rows)
    ]
    weekly_totals: dict[str, Decimal] = {}
    for project in all_projects:
        for item in cost_summary(db, project)["weekly_trend"]:
            weekly_totals[item["week"]] = weekly_totals.get(item["week"], Decimal("0")) + Decimal(str(item["total"]))
    start = (page - 1) * page_size
    return {
        "metrics": {
            "active_count": active_count,
            "paused_count": paused_count,
            "validated_count": validated_count,
            "comprehensive_cost": comprehensive,
            "unpriced_count": unpriced_count,
        },
        "weekly_trend": [{"week": key, "total": value} for key, value in sorted(weekly_totals.items())],
        "status_distribution": status_distribution,
        "projects": filtered[start : start + page_size],
        "pagination": {"page": page, "page_size": page_size, "total": len(filtered)},
        "status_options": [{"value": key, "label": value} for key, value in PROJECT_STATUS_LABELS.items()],
        "version_status_options": [{"value": key, "label": value} for key, value in PCB_VERSION_STATUS_LABELS.items()],
        "expense_category_options": [{"value": key, "label": value} for key, value in EXPENSE_CATEGORY_LABELS.items()],
    }


@router.get("/api/projects/by-code/{project_code}")
def get_project_by_code(project_code: str, auth: Protected, db: Session = Depends(get_db)):
    project, resolved_from_alias = project_by_code_or_alias(db, auth.user_id, project_code)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "project": project_summary(db, project),
        "resolved_from_alias": resolved_from_alias,
        "canonical_code": project.project_code,
    }


@router.get("/api/projects/{project_id}/status-history")
def list_status_history(project_id: int, auth: Protected, db: Session = Depends(get_db)):
    project = require_personal_project(db, project_id, auth)
    rows = db.query(ProjectStatusEvent).filter(ProjectStatusEvent.project_id == project.id).order_by(
        ProjectStatusEvent.created_at.desc()
    ).all()
    return [
        {
            "id": row.id,
            "from_status": row.from_status,
            "from_status_label": PROJECT_STATUS_LABELS.get(row.from_status, row.from_status),
            "to_status": row.to_status,
            "to_status_label": PROJECT_STATUS_LABELS.get(row.to_status, row.to_status),
            "source": row.source,
            "note": row.note,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/api/projects/{project_id}/status-transitions")
def transition_project_status(
    project_id: int,
    payload: ProjectStatusTransitionCreate,
    auth: Protected,
    db: Session = Depends(get_db),
):
    project = require_personal_project(db, project_id, auth)
    if payload.status not in PROJECT_STATUS_LABELS or payload.status == "archived":
        raise HTTPException(status_code=422, detail="不支持的项目状态")
    previous = project.status
    if previous == payload.status:
        return project_summary(db, project)
    project.status = payload.status
    if payload.status == "validated" and not project.end_date:
        project.end_date = shanghai_today()
    elif payload.clear_end_date:
        project.end_date = None
    event = ProjectStatusEvent(
        id=secrets.token_hex(16),
        project_id=project.id,
        from_status=previous,
        to_status=payload.status,
        note=str(payload.note or "").strip() or None,
        source=str(payload.source or "web")[:32],
        created_by_user_id=auth.user_id,
    )
    db.add(event)
    log_project_activity(
        db,
        project,
        auth,
        "project.status.transition",
        f"项目 {project.project_code} 状态由 {PROJECT_STATUS_LABELS.get(previous, previous)} 改为 {PROJECT_STATUS_LABELS[payload.status]}",
        {"from": previous, "to": payload.status, "source": payload.source, "note": payload.note},
    )
    db.commit()
    return project_summary(db, project)


@router.post("/api/projects/{project_id}/code-change")
def change_project_code(
    project_id: int,
    payload: ProjectCodeChangeCreate,
    auth: Protected,
    db: Session = Depends(get_db),
):
    project = require_personal_project(db, project_id, auth)
    try:
        new_code = normalize_project_code(payload.project_code)
        assert_project_code_available(db, new_code, project.id)
    except ValueError as error:
        raise HTTPException(status_code=409 if "存在" in str(error) else 422, detail=str(error)) from error
    old_code = normalize_project_code(project.project_code)
    if new_code == old_code:
        return {"project": project_summary(db, project), "alias_created": False}
    alias = db.query(ProjectCodeAlias).filter(ProjectCodeAlias.old_code == old_code).first()
    if not alias:
        db.add(
            ProjectCodeAlias(
                project_id=project.id,
                old_code=old_code,
                created_by_user_id=auth.user_id,
            )
        )
    project.project_code = new_code
    log_project_activity(
        db,
        project,
        auth,
        "project.code.change",
        f"项目编号由 {old_code} 改为 {new_code}",
        {"old_code": old_code, "new_code": new_code},
    )
    db.commit()
    return {"project": project_summary(db, project), "alias_created": True, "old_code": old_code}


@router.get("/api/projects/{project_id}/versions")
def list_versions(project_id: int, auth: Protected, db: Session = Depends(get_db)):
    project = require_personal_project(db, project_id, auth)
    rows = db.query(ProjectPcbVersion).filter(ProjectPcbVersion.project_id == project.id).order_by(
        ProjectPcbVersion.sequence_number.desc()
    ).all()
    return [version_stats(db, project, row) for row in rows]


@router.post("/api/projects/{project_id}/versions")
def add_version(
    project_id: int,
    payload: ProjectPcbVersionCreate,
    auth: Protected,
    db: Session = Depends(get_db),
):
    project = require_personal_project(db, project_id, auth)
    try:
        version = create_version(
            db,
            project,
            auth.user_id,
            version_code=payload.version_code,
            status=payload.status,
            change_summary=payload.change_summary,
            copy_from_version_id=payload.copy_from_version_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    log_project_activity(
        db,
        project,
        auth,
        "project.version.create",
        f"项目 {project.project_code} 新建 PCB 版本 {version.version_code}",
        {"version_id": version.id, "copy_from_version_id": payload.copy_from_version_id},
    )
    db.commit()
    db.refresh(version)
    return version_stats(db, project, version)


@router.patch("/api/projects/{project_id}/versions/{version_id}")
def update_version(
    project_id: int,
    version_id: int,
    payload: ProjectPcbVersionUpdate,
    auth: Protected,
    db: Session = Depends(get_db),
):
    project = require_personal_project(db, project_id, auth)
    version = require_version(db, project, version_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("version_code") is not None:
        try:
            code = normalize_version_code(values.pop("version_code"))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        duplicate = db.query(ProjectPcbVersion.id).filter(
            ProjectPcbVersion.project_id == project.id,
            ProjectPcbVersion.id != version.id,
            ProjectPcbVersion.version_code == code,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="该项目内 PCB 版本号已存在")
        version.version_code = code
    if values.get("status") is not None:
        status = values.pop("status")
        if status not in PCB_VERSION_STATUS_LABELS:
            raise HTTPException(status_code=422, detail="不支持的 PCB 版本状态")
        version.status = status
        if status == "passed" and not version.validated_at:
            version.validated_at = datetime.utcnow()
        version.archived_at = datetime.utcnow() if status == "retired" else None
    if "change_summary" in values:
        summary = str(values.pop("change_summary") or "").strip() or None
        if version.sequence_number > 1 and not summary:
            raise HTTPException(status_code=422, detail="V2 及后续版本必须填写变更说明")
        version.change_summary = summary
    if values.pop("make_active", False):
        if version.archived_at:
            raise HTTPException(status_code=409, detail="已停用版本不能设为当前版本")
        project.active_pcb_version_id = version.id
        project.active_fabrication_revision_id = version.active_fabrication_revision_id
    log_project_activity(
        db,
        project,
        auth,
        "project.version.update",
        f"更新 PCB 版本 {version.version_code}",
        payload.model_dump(exclude_unset=True),
    )
    db.commit()
    return version_stats(db, project, version)


@router.get("/api/projects/{project_id}/expenses")
def list_expenses(
    project_id: int,
    auth: Protected,
    db: Session = Depends(get_db),
    include_archived: bool = False,
    version_id: int | None = None,
):
    project = require_personal_project(db, project_id, auth)
    query = db.query(ProjectExpense).filter(ProjectExpense.project_id == project.id)
    if not include_archived:
        query = query.filter(ProjectExpense.archived_at.is_(None))
    if version_id is not None:
        require_version(db, project, version_id)
        query = query.filter(ProjectExpense.pcb_version_id == version_id)
    rows = query.order_by(ProjectExpense.occurred_on.desc(), ProjectExpense.created_at.desc()).all()
    versions = {
        item.id: item
        for item in db.query(ProjectPcbVersion).filter(ProjectPcbVersion.project_id == project.id).all()
    }
    return [expense_out(row, versions.get(row.pcb_version_id)) for row in rows]


def validate_expense_values(
    db: Session,
    project: Project,
    auth: AuthContext,
    values: dict,
    *,
    partial: bool,
) -> dict:
    if "category" in values and values["category"] not in EXPENSE_CATEGORY_LABELS:
        raise HTTPException(status_code=422, detail="不支持的费用分类")
    if "pcb_version_id" in values and values["pcb_version_id"] is not None:
        require_version(db, project, int(values["pcb_version_id"]))
    if "attachment_asset_id" in values and values["attachment_asset_id"]:
        asset = db.query(EdaAsset).filter(
            EdaAsset.id == values["attachment_asset_id"],
            EdaAsset.scope_type == "personal",
            EdaAsset.owner_user_id == auth.user_id,
            EdaAsset.archived_at.is_(None),
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="费用凭证文件不存在")
        mime = str(asset.mime_type or "").lower()
        suffix = str(asset.original_name or "").lower()
        if not (mime.startswith("image/") or mime == "application/pdf" or suffix.endswith(".pdf")):
            raise HTTPException(status_code=422, detail="费用凭证仅支持图片或 PDF")
    if not partial and values.get("occurred_on") is None:
        values["occurred_on"] = shanghai_today()
    return values


@router.post("/api/projects/{project_id}/expenses")
def create_expense(
    project_id: int,
    payload: ProjectExpenseCreate,
    auth: Protected,
    db: Session = Depends(get_db),
):
    project = require_personal_project(db, project_id, auth)
    values = validate_expense_values(db, project, auth, payload.model_dump(), partial=False)
    expense = ProjectExpense(
        id=secrets.token_hex(16),
        project_id=project.id,
        currency="CNY",
        created_by_user_id=auth.user_id,
        **values,
    )
    db.add(expense)
    log_project_activity(
        db,
        project,
        auth,
        "project.expense.create",
        f"项目 {project.project_code} 新增费用 ¥{expense.amount}",
        {"expense_id": expense.id, "category": expense.category, "amount": expense.amount},
    )
    db.commit()
    db.refresh(expense)
    version = db.get(ProjectPcbVersion, expense.pcb_version_id) if expense.pcb_version_id else None
    return expense_out(expense, version)


def require_expense(db: Session, project: Project, expense_id: str) -> ProjectExpense:
    expense = db.query(ProjectExpense).filter(
        ProjectExpense.id == expense_id,
        ProjectExpense.project_id == project.id,
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="费用记录不存在")
    return expense


@router.patch("/api/projects/{project_id}/expenses/{expense_id}")
def update_expense(
    project_id: int,
    expense_id: str,
    payload: ProjectExpenseUpdate,
    auth: Protected,
    db: Session = Depends(get_db),
):
    project = require_personal_project(db, project_id, auth)
    expense = require_expense(db, project, expense_id)
    if expense.archived_at:
        raise HTTPException(status_code=409, detail="已归档费用不可编辑，请先恢复")
    values = validate_expense_values(db, project, auth, payload.model_dump(exclude_unset=True), partial=True)
    for key, value in values.items():
        setattr(expense, key, value)
    log_project_activity(db, project, auth, "project.expense.update", f"更新费用 {expense.id}", values)
    db.commit()
    version = db.get(ProjectPcbVersion, expense.pcb_version_id) if expense.pcb_version_id else None
    return expense_out(expense, version)


@router.post("/api/projects/{project_id}/expenses/{expense_id}/archive")
def archive_expense(project_id: int, expense_id: str, auth: Protected, db: Session = Depends(get_db)):
    project = require_personal_project(db, project_id, auth)
    expense = require_expense(db, project, expense_id)
    expense.archived_at = expense.archived_at or datetime.utcnow()
    log_project_activity(db, project, auth, "project.expense.archive", f"归档费用 {expense.id}")
    db.commit()
    return expense_out(expense, db.get(ProjectPcbVersion, expense.pcb_version_id) if expense.pcb_version_id else None)


@router.post("/api/projects/{project_id}/expenses/{expense_id}/restore")
def restore_expense(project_id: int, expense_id: str, auth: Protected, db: Session = Depends(get_db)):
    project = require_personal_project(db, project_id, auth)
    expense = require_expense(db, project, expense_id)
    expense.archived_at = None
    log_project_activity(db, project, auth, "project.expense.restore", f"恢复费用 {expense.id}")
    db.commit()
    return expense_out(expense, db.get(ProjectPcbVersion, expense.pcb_version_id) if expense.pcb_version_id else None)


@router.get("/api/projects/{project_id}/cost-summary")
def get_cost_summary(
    project_id: int,
    auth: Protected,
    db: Session = Depends(get_db),
    version_id: int | None = None,
):
    project = require_personal_project(db, project_id, auth)
    if version_id is not None:
        require_version(db, project, version_id)
    return cost_summary(db, project, version_id=version_id)


@router.post("/api/projects/{project_id}/cost-summary/fill-unpriced")
def fill_unpriced(project_id: int, auth: Protected, db: Session = Depends(get_db)):
    project = require_personal_project(db, project_id, auth)
    result = fill_unpriced_material_events(db, project, auth.user_id)
    log_project_activity(db, project, auth, "project.cost.fill_unpriced", "补齐项目未计价成本快照", result)
    db.commit()
    return {**result, "cost_summary": cost_summary(db, project)}


@router.post("/api/projects/{project_id}/archive")
def archive_project(project_id: int, auth: Protected, db: Session = Depends(get_db)):
    project = require_personal_project(db, project_id, auth)
    project.archived_at = project.archived_at or datetime.utcnow()
    log_project_activity(db, project, auth, "project.archive", f"归档项目 {project.project_code}")
    db.commit()
    return project_summary(db, project)


@router.post("/api/projects/{project_id}/restore")
def restore_project(project_id: int, auth: Protected, db: Session = Depends(get_db)):
    project = require_personal_project(db, project_id, auth)
    project.archived_at = None
    log_project_activity(db, project, auth, "project.restore", f"恢复项目 {project.project_code}")
    db.commit()
    return project_summary(db, project)
