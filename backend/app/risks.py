from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import AuthContext, require_access
from .database import get_db
from .engineering_schemas import RiskIssueCreate, RiskUpdate
from .models import (
    CompetitionLibraryComponent,
    Component,
    EdaAsset,
    EdaComponentBinding,
    Project,
    ProjectBomImportBatch,
    ProjectBomImportRow,
    RiskIssue,
    SupplierPart,
)
from .team import require_library_editor, require_library_member


router = APIRouter(tags=["risks"])


@dataclass(frozen=True)
class RiskScope:
    scope_type: str
    owner_user_id: int | None
    team_library_id: str | None


def personal_scope(auth: AuthContext) -> RiskScope:
    return RiskScope("personal", auth.user_id, None)


def team_scope(db: Session, library_id: str, auth: AuthContext, edit: bool = False) -> RiskScope:
    if edit:
        require_library_editor(db, library_id, auth)
    else:
        require_library_member(db, library_id, auth)
    return RiskScope("team", None, library_id)


def scope_bindings(query, scope: RiskScope):
    query = query.filter(EdaComponentBinding.scope_type == scope.scope_type)
    if scope.scope_type == "team":
        return query.filter(EdaComponentBinding.team_library_id == scope.team_library_id)
    return query.filter(EdaComponentBinding.owner_user_id == scope.owner_user_id)


def scope_supplier_parts(query, scope: RiskScope):
    query = query.filter(SupplierPart.scope_type == scope.scope_type, SupplierPart.status == "active")
    if scope.scope_type == "team":
        return query.filter(SupplierPart.team_library_id == scope.team_library_id)
    return query.filter(SupplierPart.owner_user_id == scope.owner_user_id)


def scope_issues(query, scope: RiskScope):
    query = query.filter(RiskIssue.scope_type == scope.scope_type)
    if scope.scope_type == "team":
        return query.filter(RiskIssue.team_library_id == scope.team_library_id)
    return query.filter(RiskIssue.owner_user_id == scope.owner_user_id)


def components_for_scope(db: Session, scope: RiskScope) -> list[Component]:
    if scope.scope_type == "personal":
        return (
            db.query(Component)
            .filter(Component.owner_user_id == scope.owner_user_id, Component.revoked_at.is_(None))
            .order_by(Component.updated_at.desc())
            .all()
        )
    ids = [
        component_id
        for (component_id,) in db.query(CompetitionLibraryComponent.cw_component_id)
        .filter(
            CompetitionLibraryComponent.library_id == scope.team_library_id,
            CompetitionLibraryComponent.cw_component_id.isnot(None),
        )
        .all()
    ]
    return db.query(Component).filter(Component.id.in_(ids or [0]), Component.revoked_at.is_(None)).order_by(Component.updated_at.desc()).all()


def risk_item(component: Component, risk_type: str, title: str, detail: str, severity: str = "warning") -> dict:
    return {
        "id": f"{risk_type}:{component.id}",
        "component_id": component.id,
        "warehouse_code": component.warehouse_code,
        "component_name": component.name,
        "risk_type": risk_type,
        "title": title,
        "detail": detail,
        "severity": severity,
        "status": "open",
        "source": "system",
    }


def list_risks_impl(db: Session, scope: RiskScope) -> dict:
    components = components_for_scope(db, scope)
    component_ids = [item.id for item in components]
    bindings = (
        scope_bindings(db.query(EdaComponentBinding), scope)
        .filter(EdaComponentBinding.component_id.in_(component_ids or [0]))
        .all()
    )
    bindings_by_component: dict[int, list[EdaComponentBinding]] = {}
    for binding in bindings:
        bindings_by_component.setdefault(binding.component_id, []).append(binding)
    supplier_component_ids = {
        component_id
        for (component_id,) in scope_supplier_parts(db.query(SupplierPart.component_id), scope)
        .filter(SupplierPart.component_id.in_(component_ids or [0]))
        .distinct()
        .all()
    }
    risks: list[dict] = []
    for component in components:
        component_bindings = bindings_by_component.get(component.id, [])
        if not component_bindings:
            risks.append(risk_item(component, "missing_footprint", "未绑定 AD 封装", "元器件没有 Symbol/Footprint 工程绑定。", "danger"))
            risks.append(risk_item(component, "missing_symbol", "缺少原理图 Symbol", "元器件没有原理图 Symbol 工程绑定。"))
            risks.append(risk_item(component, "unverified_footprint", "封装尚未 Verified", "当前验证状态：raw。", "danger"))
            if not component.datasheet_url:
                risks.append(risk_item(component, "missing_datasheet", "缺少数据手册", "未上传数据手册，也没有登记外部数据手册链接。"))
        else:
            primary = next((item for item in component_bindings if item.is_primary), component_bindings[0])
            if not primary.footprint_id:
                risks.append(risk_item(component, "missing_footprint", "缺少 PCB Footprint", "主 EDA 绑定没有 PCB Footprint。", "danger"))
            if not primary.symbol_id:
                risks.append(risk_item(component, "missing_symbol", "缺少原理图 Symbol", "主 EDA 绑定没有原理图 Symbol。"))
            if primary.verification_status != "verified":
                risks.append(
                    {
                        **risk_item(
                        component,
                        "unverified_footprint",
                        "封装尚未 Verified",
                        f"当前验证状态：{primary.verification_status or 'raw'}。",
                        "danger" if primary.verification_status == "raw" else "warning",
                        ),
                        "verification_status": primary.verification_status or "raw",
                    }
                )
            if not primary.datasheet_asset_id and not component.datasheet_url:
                risks.append(risk_item(component, "missing_datasheet", "缺少数据手册", "未上传数据手册，也没有登记外部数据手册链接。"))
        if not component.lcsc_number and component.id not in supplier_component_ids:
            risks.append(risk_item(component, "missing_supplier_part", "缺少供应商料号", "没有 LCSC 编号或其他供应商料号。"))
        if component.is_common and not component.low_stock_exempt and int(component.quantity or 0) < int(component.safety_quantity or 0):
            risks.append(
                risk_item(
                    component,
                    "low_stock",
                    "库存低于最低值",
                    f"当前 {component.quantity or 0}，最低库存 {component.safety_quantity or 0}。",
                    "danger",
                )
            )
    for issue in scope_issues(db.query(RiskIssue), scope).filter(RiskIssue.status == "open").order_by(RiskIssue.created_at.desc()).all():
        component = db.get(Component, issue.component_id) if issue.component_id else None
        project = db.get(Project, issue.project_id) if issue.project_id else None
        risks.append(
            {
                "id": issue.id,
                "component_id": issue.component_id,
                "project_id": issue.project_id,
                "warehouse_code": component.warehouse_code if component else None,
                "component_name": component.name if component else None,
                "project_name": project.name if project else None,
                "risk_type": issue.risk_type,
                "title": issue.title,
                "detail": issue.detail,
                "severity": issue.severity,
                "status": issue.status,
                "source": "manual",
            }
        )
    project_query = db.query(Project)
    if scope.scope_type == "team":
        project_query = project_query.filter(Project.scope_type == "team", Project.team_library_id == scope.team_library_id)
    else:
        project_query = project_query.filter(Project.owner_user_id == scope.owner_user_id)
    project_ids = [project_id for (project_id,) in project_query.with_entities(Project.id).all()]
    latest_batches: dict[int, ProjectBomImportBatch] = {}
    for batch in (
        db.query(ProjectBomImportBatch)
        .filter(ProjectBomImportBatch.project_id.in_(project_ids or [0]))
        .order_by(ProjectBomImportBatch.created_at.desc())
        .all()
    ):
        latest_batches.setdefault(batch.project_id, batch)
    for project_id, batch in latest_batches.items():
        project = db.get(Project, project_id)
        missing = (
            db.query(ProjectBomImportRow)
            .filter(
                ProjectBomImportRow.batch_id == batch.id,
                ProjectBomImportRow.selected_component_id.is_(None),
                ProjectBomImportRow.status.notin_(["ignored", "imported"]),
            )
            .count()
        )
        if missing:
            risks.append(
                {
                    "id": f"bom_unmatched:{project_id}",
                    "project_id": project_id,
                    "project_name": project.name if project else f"项目 {project_id}",
                    "risk_type": "bom_unmatched",
                    "title": "项目 BOM 存在未匹配元件",
                    "detail": f"最近一次 BOM 导入仍有 {missing} 行未确认。",
                    "severity": "danger",
                    "status": "open",
                    "source": "system",
                }
            )
    counts = {"danger": 0, "warning": 0, "info": 0}
    for item in risks:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    return {"items": risks, "total": len(risks), "counts": counts}


@router.get("/api/risks")
def personal_risks(auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_risks_impl(db, personal_scope(auth))


@router.get("/api/team/libraries/{library_id}/risks")
def team_risks(library_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_risks_impl(db, team_scope(db, library_id, auth))


def validate_issue_targets(db: Session, scope: RiskScope, payload: RiskIssueCreate) -> None:
    if not payload.component_id and not payload.project_id:
        raise HTTPException(status_code=400, detail="问题必须关联元件或项目")
    if payload.component_id:
        component_ids = {item.id for item in components_for_scope(db, scope)}
        if payload.component_id not in component_ids:
            raise HTTPException(status_code=404, detail="元器件不存在")
    if payload.project_id:
        project = db.get(Project, payload.project_id)
        valid = bool(
            project
            and (
                (scope.scope_type == "personal" and project.owner_user_id == scope.owner_user_id)
                or (
                    scope.scope_type == "team"
                    and project.scope_type == "team"
                    and project.team_library_id == scope.team_library_id
                )
            )
        )
        if not valid:
            raise HTTPException(status_code=404, detail="项目不存在")


def create_issue_impl(db: Session, scope: RiskScope, payload: RiskIssueCreate) -> dict:
    validate_issue_targets(db, scope, payload)
    issue = RiskIssue(
        id=str(uuid4()),
        scope_type=scope.scope_type,
        owner_user_id=scope.owner_user_id,
        team_library_id=scope.team_library_id,
        component_id=payload.component_id,
        project_id=payload.project_id,
        risk_type=payload.risk_type,
        severity=payload.severity,
        status="open",
        title=payload.title.strip(),
        detail=(payload.detail or "").strip() or None,
        source="manual",
    )
    db.add(issue)
    db.commit()
    return {"id": issue.id, "status": issue.status}


@router.post("/api/risks")
def create_personal_issue(payload: RiskIssueCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_issue_impl(db, personal_scope(auth), payload)


@router.post("/api/team/libraries/{library_id}/risks")
def create_team_issue(library_id: str, payload: RiskIssueCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_issue_impl(db, team_scope(db, library_id, auth, True), payload)


def update_issue_impl(db: Session, scope: RiskScope, issue_id: str, payload: RiskUpdate) -> dict:
    if payload.status not in {"open", "resolved", "ignored"}:
        raise HTTPException(status_code=400, detail="问题状态无效")
    issue = scope_issues(db.query(RiskIssue), scope).filter(RiskIssue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    issue.status = payload.status
    issue.resolved_at = datetime.utcnow() if payload.status != "open" else None
    db.commit()
    return {"id": issue.id, "status": issue.status}


@router.patch("/api/risks/{issue_id}")
def update_personal_issue(issue_id: str, payload: RiskUpdate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return update_issue_impl(db, personal_scope(auth), issue_id, payload)


@router.patch("/api/team/libraries/{library_id}/risks/{issue_id}")
def update_team_issue(library_id: str, issue_id: str, payload: RiskUpdate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return update_issue_impl(db, team_scope(db, library_id, auth, True), issue_id, payload)
