from sqlalchemy.orm import Session

from ..models import (
    ActivityLog,
    AiKnowledgeCard,
    AppMigration,
    PersonalProjectBoardV2,
    PersonalProjectBomItemV2,
    PersonalProjectCostEventV2,
    PersonalProjectExpenseV2,
    PersonalProjectFileV2,
    PersonalProjectRiskV2,
    PersonalProjectSolderPointV2,
    PersonalProjectStatusEventV2,
    PersonalProjectV2,
    PersonalProjectVersionV2,
    Project,
    ProjectAssemblyLossEvent,
    ProjectAssemblyOperation,
    ProjectAssemblyPlacement,
    ProjectBoard,
    ProjectBomImportBatch,
    ProjectBomImportCandidate,
    ProjectBomImportRow,
    ProjectBomItem,
    ProjectBomSolderPoint,
    ProjectCodeAlias,
    ProjectExpense,
    ProjectFabricationLayer,
    ProjectFabricationRevision,
    ProjectMaterialCostEvent,
    ProjectPcbVersion,
    ProjectStatusEvent,
    PurchaseOrder,
    RiskIssue,
    StockMovement,
)


V130_PERSONAL_PROJECT_V2_RESET = "v1.3.0-personal-project-v2-reset"


def is_legacy_personal_project_api(path: str) -> bool:
    """Identify only the retired personal project surface, never team routes."""

    if path == "/api/projects" or path.startswith("/api/projects/"):
        return True
    if path.startswith("/api/public/projects/") and path.endswith("/assembly-view"):
        # Team projects still use the deliberately enabled, read-only assembly
        # viewer. Retired personal records cannot resolve here after the reset.
        return False
    return path == "/api/public/projects" or path.startswith("/api/public/projects/")


def run_personal_project_v2_reset(db: Session) -> dict:
    """Retire every legacy personal project without changing inventory totals.

    Stock and purchase ledgers are retained as audit history and only lose the
    obsolete legacy-project foreign key. Project-owned detail rows are removed.
    The migration marker makes this destructive cut-over one-shot.
    """

    existing = db.get(AppMigration, V130_PERSONAL_PROJECT_V2_RESET)
    if existing:
        return {"applied": False, "legacy_projects": 0, "v2_projects": 0}

    project_ids = [row[0] for row in db.query(Project.id).filter(Project.scope_type == "personal").all()]
    legacy_count = len(project_ids)
    v2_count = db.query(PersonalProjectV2.id).count()

    # A failed pre-release V2 attempt must not leak into the clean production
    # launch. These tables are independent from inventory and can be cleared.
    for model in (
        PersonalProjectCostEventV2,
        PersonalProjectSolderPointV2,
        PersonalProjectFileV2,
        PersonalProjectRiskV2,
        PersonalProjectExpenseV2,
        PersonalProjectBomItemV2,
        PersonalProjectBoardV2,
        PersonalProjectStatusEventV2,
        PersonalProjectVersionV2,
        PersonalProjectV2,
    ):
        db.query(model).delete(synchronize_session=False)

    if project_ids:
        # Keep durable operational history, but detach it from retired IDs.
        db.query(StockMovement).filter(StockMovement.project_id.in_(project_ids)).update(
            {StockMovement.project_id: None}, synchronize_session=False
        )
        db.query(PurchaseOrder).filter(PurchaseOrder.project_id.in_(project_ids)).update(
            {PurchaseOrder.project_id: None}, synchronize_session=False
        )
        db.query(RiskIssue).filter(RiskIssue.project_id.in_(project_ids)).update(
            {RiskIssue.project_id: None}, synchronize_session=False
        )
        db.query(ActivityLog).filter(
            ActivityLog.project_id.in_(project_ids), ActivityLog.component_id.isnot(None)
        ).update({ActivityLog.project_id: None}, synchronize_session=False)
        db.query(ActivityLog).filter(ActivityLog.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(AiKnowledgeCard).filter(AiKnowledgeCard.project_id.in_(project_ids)).delete(synchronize_session=False)

        operation_ids = [row[0] for row in db.query(ProjectAssemblyOperation.id).filter(
            ProjectAssemblyOperation.project_id.in_(project_ids)
        ).all()]
        bom_item_ids = [row[0] for row in db.query(ProjectBomItem.id).filter(ProjectBomItem.project_id.in_(project_ids)).all()]
        point_ids = [row[0] for row in db.query(ProjectBomSolderPoint.id).filter(
            ProjectBomSolderPoint.bom_item_id.in_(bom_item_ids)
        ).all()] if bom_item_ids else []
        revision_ids = [row[0] for row in db.query(ProjectFabricationRevision.id).filter(
            ProjectFabricationRevision.project_id.in_(project_ids)
        ).all()]
        batch_ids = [row[0] for row in db.query(ProjectBomImportBatch.id).filter(
            ProjectBomImportBatch.project_id.in_(project_ids)
        ).all()]
        row_ids = [row[0] for row in db.query(ProjectBomImportRow.id).filter(
            ProjectBomImportRow.project_id.in_(project_ids)
        ).all()]

        if operation_ids:
            db.query(ProjectAssemblyLossEvent).filter(
                ProjectAssemblyLossEvent.operation_id.in_(operation_ids)
            ).delete(synchronize_session=False)
        if point_ids:
            db.query(ProjectAssemblyLossEvent).filter(
                ProjectAssemblyLossEvent.solder_point_id.in_(point_ids)
            ).delete(synchronize_session=False)
        db.query(ProjectAssemblyOperation).filter(ProjectAssemblyOperation.project_id.in_(project_ids)).delete(synchronize_session=False)
        if revision_ids:
            db.query(ProjectFabricationLayer).filter(ProjectFabricationLayer.revision_id.in_(revision_ids)).delete(synchronize_session=False)
            db.query(ProjectAssemblyPlacement).filter(ProjectAssemblyPlacement.revision_id.in_(revision_ids)).delete(synchronize_session=False)
        if bom_item_ids:
            db.query(ProjectAssemblyPlacement).filter(ProjectAssemblyPlacement.bom_item_id.in_(bom_item_ids)).delete(synchronize_session=False)
            db.query(ProjectBomSolderPoint).filter(ProjectBomSolderPoint.bom_item_id.in_(bom_item_ids)).delete(synchronize_session=False)
        if row_ids:
            db.query(ProjectBomImportCandidate).filter(ProjectBomImportCandidate.import_row_id.in_(row_ids)).delete(synchronize_session=False)
        if batch_ids:
            db.query(ProjectBomImportRow).filter(ProjectBomImportRow.batch_id.in_(batch_ids)).delete(synchronize_session=False)

        for model in (
            ProjectMaterialCostEvent,
            ProjectExpense,
            ProjectCodeAlias,
            ProjectStatusEvent,
            ProjectBomImportRow,
            ProjectBomImportBatch,
            ProjectFabricationRevision,
            ProjectBomItem,
            ProjectBoard,
            ProjectPcbVersion,
        ):
            db.query(model).filter(model.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(Project).filter(Project.id.in_(project_ids)).delete(synchronize_session=False)

    detail = (
        f"已清理 {legacy_count} 个旧个人项目和 {v2_count} 个预发布 V2 项目；"
        "保留库存数量、库存批次、库存流水和采购记录，并解除旧项目关联。"
    )
    db.add(AppMigration(key=V130_PERSONAL_PROJECT_V2_RESET, detail=detail))
    db.commit()
    return {"applied": True, "legacy_projects": legacy_count, "v2_projects": v2_count, "detail": detail}
