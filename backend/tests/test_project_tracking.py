from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext, require_access
from app.database import Base, get_db
from app.fabrication import router as fabrication_router
from app.models import (
    Component,
    Project,
    ProjectBoard,
    ProjectBomItem,
    ProjectBomSolderPoint,
    ProjectCodeAlias,
    ProjectExpense,
    ProjectMaterialCostEvent,
    ProjectPcbVersion,
    ProjectStatusEvent,
    PurchaseLine,
    PurchaseOrder,
    User,
)
from app.project_tracking import router as tracking_router
from app.services.project_tracking import create_initial_version, iso_week_label


@pytest.fixture()
def project_env(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'project-tracking.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add_all(
        [
            User(id=1, phone="13800000001", nickname="用户一"),
            User(id=2, phone="13800000002", nickname="用户二"),
            Component(id=1, owner_user_id=1, warehouse_code="RES-1", name="10k", quantity=20, average_unit_price=Decimal("2.50")),
            Component(id=2, owner_user_id=1, warehouse_code="RES-2", name="未计价 IC", quantity=20, average_unit_price=None),
        ]
    )
    project = Project(
        id=1,
        scope_type="personal",
        owner_user_id=1,
        project_code="WXY-HP26-HCB",
        name="生命周期测试",
        status="planning",
        start_date=date(2026, 7, 20),
    )
    other = Project(
        id=2,
        scope_type="personal",
        owner_user_id=2,
        project_code="OTHER-PRIVATE",
        name="其他人的项目",
        status="planning",
        start_date=date(2026, 7, 20),
    )
    db.add_all([project, other])
    db.flush()
    version = create_initial_version(db, project, 1)
    create_initial_version(db, other, 2)
    bom = ProjectBomItem(project_id=project.id, pcb_version_id=version.id, component_id=1, required_quantity=1, status="reserved")
    unpriced_bom = ProjectBomItem(project_id=project.id, pcb_version_id=version.id, component_id=2, required_quantity=1, status="reserved")
    board = ProjectBoard(project_id=project.id, pcb_version_id=version.id, board_index=1, name="第 1 板", status="active")
    db.add_all([bom, unpriced_bom, board])
    db.flush()
    db.add_all(
        [
            ProjectBomSolderPoint(bom_item_id=bom.id, board_id=board.id, designator="R1", active_for_assembly=True, state_version=1),
            ProjectBomSolderPoint(bom_item_id=unpriced_bom.id, board_id=board.id, designator="U1", active_for_assembly=True, state_version=1),
        ]
    )
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(tracking_router)
    app.include_router(fabrication_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_auth(x_test_user: int = Header(default=1)) -> AuthContext:
        session = Session()
        try:
            user = session.get(User, x_test_user)
            return AuthContext(user_id=user.id, phone=user.phone, nickname=user.nickname or "用户", is_admin=False)
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_access] = override_auth
    client = TestClient(app)
    yield {"client": client, "Session": Session}
    client.close()
    engine.dispose()


def operation(client: TestClient, board_id: int, point_id: int, state_version: int, action: str, key: str):
    response = client.post(
        "/api/projects/1/assembly-actions",
        json={
            "board_id": board_id,
            "point_ids": [point_id],
            "versions": {str(point_id): state_version},
            "action": action,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_code_alias_status_history_iso_week_and_personal_isolation(project_env):
    client = project_env["client"]
    assert iso_week_label(date(2026, 7, 20)) == "2026W30"

    changed = client.post("/api/projects/1/code-change", json={"project_code": "wxy-hp26-hcb-v2"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["project"]["project_code"] == "WXY-HP26-HCB-V2"
    alias = client.get("/api/projects/by-code/WXY-HP26-HCB")
    assert alias.status_code == 200
    assert alias.json()["resolved_from_alias"] is True
    assert alias.json()["canonical_code"] == "WXY-HP26-HCB-V2"

    validated = client.post(
        "/api/projects/1/status-transitions",
        json={"status": "validated", "source": "board_drag", "note": "验证通过"},
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["period"]["end_date"] is not None
    history = client.get("/api/projects/1/status-history").json()
    assert history[0]["to_status"] == "validated"
    assert history[0]["source"] == "board_drag"

    overview = client.get("/api/projects/overview").json()
    assert overview["pagination"]["total"] == 1
    assert {row["project_code"] for row in overview["projects"]} == {"WXY-HP26-HCB-V2"}
    assert client.get("/api/projects/2/versions").status_code == 404


def test_v2_copies_only_bom_and_keeps_physical_and_cost_state_isolated(project_env):
    client = project_env["client"]
    versions = client.get("/api/projects/1/versions").json()
    v1 = versions[0]
    created = client.post(
        "/api/projects/1/versions",
        json={"version_code": "V2", "change_summary": "修复 USB 接口兼容性", "copy_from_version_id": v1["id"]},
    )
    assert created.status_code == 200, created.text
    v2 = created.json()
    assert v2["bom_item_count"] == 2
    assert v2["board_count"] == 0
    assert v2["solder_total"] == 0
    assert v2["actual_material_cost"] == 0

    db = project_env["Session"]()
    assert db.query(ProjectBomItem).filter(ProjectBomItem.pcb_version_id == v1["id"]).count() == 2
    assert db.query(ProjectBomItem).filter(ProjectBomItem.pcb_version_id == v2["id"]).count() == 2
    assert db.query(ProjectBoard).filter(ProjectBoard.pcb_version_id == v2["id"]).count() == 0
    db.close()


def test_material_snapshots_duplicate_loss_undo_unpriced_fill_and_purchase_exclusion(project_env):
    client = project_env["client"]
    db = project_env["Session"]()
    board = db.query(ProjectBoard).filter(ProjectBoard.project_id == 1).one()
    points = db.query(ProjectBomSolderPoint).order_by(ProjectBomSolderPoint.id.asc()).all()
    priced_point, unpriced_point = points
    db.close()

    solder = operation(client, board.id, priced_point.id, 1, "solder", "cost-solder-1")
    summary = client.get("/api/projects/1/cost-summary").json()
    assert Decimal(str(summary["actual_material_cost"])) == Decimal("2.500000")

    unsolder = operation(client, board.id, priced_point.id, 2, "unsolder", "cost-unsolder-1")
    assert Decimal(str(client.get("/api/projects/1/cost-summary").json()["actual_material_cost"])) == 0
    undone = client.post(
        f"/api/projects/1/assembly-actions/{unsolder['operation_id']}/undo",
        json={"idempotency_key": "cost-undo-unsolder-1"},
    )
    assert undone.status_code == 200, undone.text
    assert Decimal(str(client.get("/api/projects/1/cost-summary").json()["actual_material_cost"])) == Decimal("2.500000")

    loss = operation(client, board.id, priced_point.id, 4, "loss", "cost-loss-1")
    duplicate_loss = operation(client, board.id, priced_point.id, 5, "loss", "cost-loss-2")
    assert Decimal(str(client.get("/api/projects/1/cost-summary").json()["actual_material_cost"])) == Decimal("5.000000")
    operation(client, board.id, priced_point.id, 6, "undo_loss", "cost-loss-undo-2")
    assert Decimal(str(client.get("/api/projects/1/cost-summary").json()["actual_material_cost"])) == Decimal("2.500000")

    operation(client, board.id, unpriced_point.id, 1, "solder", "cost-unpriced-solder-1")
    summary = client.get("/api/projects/1/cost-summary").json()
    assert summary["unpriced_material_events"] == 1
    db = project_env["Session"]()
    db.get(Component, 2).average_unit_price = Decimal("1.20")
    db.commit()
    db.close()
    filled = client.post("/api/projects/1/cost-summary/fill-unpriced").json()
    assert filled["filled"] == 1
    assert filled["remaining"] == 0

    expense = client.post(
        "/api/projects/1/expenses",
        json={"category": "pcb_fabrication", "amount": "10.00", "occurred_on": "2026-07-21", "vendor": "板厂"},
    )
    assert expense.status_code == 200, expense.text
    db = project_env["Session"]()
    order = PurchaseOrder(
        id="order-1", scope_type="personal", owner_user_id=1, project_id=1, status="planned", currency="CNY", created_by_user_id=1
    )
    db.add(order)
    db.add(PurchaseLine(id="line-1", purchase_order_id=order.id, component_id=1, description="电阻", ordered_quantity=2, unit_price=5))
    db.commit()
    db.close()
    summary = client.get("/api/projects/1/cost-summary").json()
    assert Decimal(str(summary["actual_material_cost"])) == Decimal("3.700000")
    assert Decimal(str(summary["direct_expense"])) == Decimal("10.000000")
    assert Decimal(str(summary["comprehensive_cost"])) == Decimal("13.700000")
    assert Decimal(str(summary["planned_purchase_amount"])) == Decimal("10.000000")

    db = project_env["Session"]()
    assert db.query(ProjectMaterialCostEvent).filter(ProjectMaterialCostEvent.source_operation_id == solder["operation_id"]).count() == 1
    assert db.query(ProjectMaterialCostEvent).filter(ProjectMaterialCostEvent.source_operation_id == loss["operation_id"]).count() == 1
    assert db.query(ProjectMaterialCostEvent).filter(ProjectMaterialCostEvent.source_operation_id == duplicate_loss["operation_id"]).count() == 1
    assert db.query(ProjectExpense).filter(ProjectExpense.project_id == 1).count() == 1
    assert db.query(ProjectCodeAlias).count() == 0
    assert db.query(ProjectStatusEvent).count() == 0
    db.close()
