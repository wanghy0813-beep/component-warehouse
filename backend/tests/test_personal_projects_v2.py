import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext, require_access
from app.database import Base, get_db
from app.models import (
    AppMigration,
    Component,
    InventoryLot,
    PersonalProjectBomItemV2,
    PersonalProjectCostEventV2,
    PersonalProjectFabricationRevisionV2,
    PersonalProjectV2,
    Project,
    StockMovement,
    User,
)
from app.personal_projects_v2 import router
from app.services import eda_storage
from app.services.personal_project_reset import (
    V130_PERSONAL_PROJECT_V2_RESET,
    is_legacy_personal_project_api,
    run_personal_project_v2_reset,
)
from app.workspace_fabrication import process_workspace_revision, router as workspace_fabrication_router


@pytest.fixture()
def workspace_env(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'project-v2.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    db = Session()
    db.add_all([
        User(id=1, phone="13800000001", nickname="用户一"),
        User(id=2, phone="13800000002", nickname="用户二"),
        Component(id=1, owner_user_id=1, warehouse_code="RES-0001", name="10k 电阻", quantity=20, average_unit_price=Decimal("0.125")),
        Component(id=2, owner_user_id=1, warehouse_code="IC-0002", name="未计价芯片", quantity=5, average_unit_price=None),
    ])
    db.flush()
    db.add_all([
        InventoryLot(id="lot-1", component_id=1, owner_user_id=1, source_type="test", initial_quantity=20, remaining_quantity=20, status="active"),
        InventoryLot(id="lot-2", component_id=2, owner_user_id=1, source_type="test", initial_quantity=5, remaining_quantity=5, status="active"),
    ])
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(router)
    app.include_router(workspace_fabrication_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_auth(x_test_user: int = Header(default=1)) -> AuthContext:
        return AuthContext(user_id=x_test_user, phone=f"1380000000{x_test_user}", nickname=f"用户{x_test_user}")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_access] = override_auth
    monkeypatch.setattr(eda_storage, "EDA_STORAGE_ROOT", tmp_path / "eda")
    monkeypatch.setattr(eda_storage, "MIN_FREE_BYTES", 0)
    monkeypatch.setattr(eda_storage, "MIN_FREE_RATIO", 0.01)
    client = TestClient(app)
    yield {"client": client, "Session": Session}
    client.close()
    engine.dispose()


def create_project(client: TestClient, code: str = "wxy-hp26-hcb") -> dict:
    response = client.post("/api/project-workspace/projects", json={"project_code": code, "name": "桌面电源", "status": "planning"})
    assert response.status_code == 200, response.text
    return response.json()


def workspace_manufacturing_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "JLCPCB/BOM.csv",
            "Designator,Comment,Footprint,MPN,DNP\nR1,10K,0603,R-10K,no\nR2,10K,0603,R-10K,no\n",
        )
        archive.writestr(
            "JLCPCB/PickAndPlace.csv",
            "Designator,Mid X,Mid Y,Layer,Rotation\nR1,12.7,25.4,Top,90\nR2,30,25,Bottom,180\n",
        )
        archive.writestr("Gerber/board.GKO", "%FSLAX46Y46*%\n%MOMM*%\nG04 workspace outline*\nM02*\n")
    return output.getvalue()


def test_legacy_personal_project_api_matcher_never_catches_project_v2_or_team_routes():
    assert is_legacy_personal_project_api("/api/projects")
    assert is_legacy_personal_project_api("/api/projects/123/bom")
    assert is_legacy_personal_project_api("/api/public/projects/PJ-OLD")
    assert not is_legacy_personal_project_api("/api/public/projects/TEAM-BOARD/assembly-view")
    assert not is_legacy_personal_project_api("/api/project-workspace/bootstrap")
    assert not is_legacy_personal_project_api("/api/team/libraries/lib-1/projects")


def test_clean_workspace_project_lifecycle_and_personal_isolation(workspace_env):
    client = workspace_env["client"]
    empty = client.get("/api/project-workspace/bootstrap").json()
    assert empty["schema_version"] == "project-workspace-v2"
    assert empty["projects"] == []

    project = create_project(client)
    assert project["project_code"] == "WXY-HP26-HCB"
    assert project["current_version"]["version_code"] == "V1"
    assert project["period"]["start_date"] is not None

    history = client.get(f"/api/project-workspace/projects/{project['id']}").json()["status_history"]
    assert history[0]["source"] == "create"
    changed = client.post(
        f"/api/project-workspace/projects/{project['id']}/status",
        json={"status": "validated", "source": "web", "note": "功能验证通过"},
    )
    assert changed.status_code == 200
    assert changed.json()["period"]["end_date"] is not None
    assert client.get(f"/api/project-workspace/projects/{project['id']}", headers={"x-test-user": "2"}).status_code == 404


def test_workspace_gerber_visual_assembly_tracks_v2_stock_cost_and_undo(workspace_env):
    client = workspace_env["client"]
    project = create_project(client, "WXY-GERBER-V2")
    version_id = project["current_version"]["id"]
    bom = client.post(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/bom",
        json={"component_id": 1, "quantity_per_board": 2, "designators": "R1,R2"},
    )
    assert bom.status_code == 200, bom.text
    uploaded = client.post(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/fabrication-revisions",
        files={"file": ("manufacturing.zip", workspace_manufacturing_zip(), "application/zip")},
    )
    assert uploaded.status_code == 200, uploaded.text
    revision_id = uploaded.json()["id"]

    db = workspace_env["Session"]()
    revision = db.get(PersonalProjectFabricationRevisionV2, revision_id)
    process_workspace_revision(db, revision)
    db.refresh(revision)
    assert revision.status == "review", revision.error_message
    db.close()

    preview = client.get(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/fabrication-revisions/{revision_id}"
    )
    assert preview.status_code == 200
    assert preview.json()["summary"]["placement_count"] == 2
    activated = client.post(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/fabrication-revisions/{revision_id}/commit",
        json={},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["result"]["linked_points"] == 2

    view = client.get(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/assembly-view",
        params={"side": "top"},
    ).json()
    assert view["revision"]["id"] == revision_id
    assert len(view["layers"]) == 1
    r1 = next(item for item in view["placements"] if item["designator"] == "R1")
    action = client.post(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/assembly-actions",
        json={
            "board_id": view["active_board_id"], "action": "solder", "point_ids": [r1["point_id"]],
            "versions": {r1["point_id"]: r1["state_version"]}, "idempotency_key": "workspace-gerber-solder-1",
        },
    )
    assert action.status_code == 200, action.text
    operation_id = action.json()["operation_id"]
    refreshed = client.get(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/assembly-view",
        params={"side": "top"},
    ).json()
    assert next(item for item in refreshed["placements"] if item["designator"] == "R1")["status"] == "soldered"

    db = workspace_env["Session"]()
    assert db.get(Component, 1).quantity == 19
    db.close()
    undone = client.post(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/assembly-actions/{operation_id}/undo",
        json={"idempotency_key": "workspace-gerber-undo-1"},
    )
    assert undone.status_code == 200, undone.text
    db = workspace_env["Session"]()
    assert db.get(Component, 1).quantity == 20
    assert sum(Decimal(str(row.amount or 0)) for row in db.query(PersonalProjectCostEventV2).all()) == Decimal("0")
    db.close()

    isolated = client.get(
        f"/api/project-workspace/projects/{project['id']}/versions/{version_id}/fabrication-revisions",
        headers={"x-test-user": "2"},
    )
    assert isolated.status_code == 404


def test_backdated_create_builds_a_real_reached_lifecycle(workspace_env):
    client = workspace_env["client"]
    started = date.today() - timedelta(days=8)
    component_selected = started + timedelta(days=2)
    schematic_started = started + timedelta(days=3)
    pcb_started = started + timedelta(days=6)
    response = client.post("/api/project-workspace/projects", json={
        "project_code": "WXY-TIMELINE-PCB",
        "name": "追溯时间线",
        "status": "pcb_design",
        "start_date": started.isoformat(),
        "lifecycle_dates": {
            "planning": started.isoformat(),
            "component_selection": component_selected.isoformat(),
            "schematic": schematic_started.isoformat(),
            "pcb_design": pcb_started.isoformat(),
        },
    })
    assert response.status_code == 200, response.text
    detail = client.get(f"/api/project-workspace/projects/{response.json()['id']}").json()
    reached = [row for row in detail["lifecycle"]["nodes"] if row["state"] != "upcoming"]
    assert [row["status"] for row in reached] == ["planning", "component_selection", "schematic", "pcb_design"]
    assert reached[0]["occurred_on"] == started.isoformat()
    assert reached[0]["ended_on"] == component_selected.isoformat()
    assert reached[2]["occurred_on"] == schematic_started.isoformat()
    assert reached[2]["ended_on"] == pcb_started.isoformat()
    assert reached[-1]["state"] == "current"
    assert reached[-1]["ongoing"] is True
    assert all(reached[index]["occurred_at"] < reached[index + 1]["occurred_at"] for index in range(3))
    assert len(detail["status_history"]) == 4
    assert all(row["source"] == "timeline_actual" for row in detail["status_history"])
    assert all(row["occurred_precision"] == "date" for row in detail["status_history"])


def test_later_stage_without_actual_dates_is_explicitly_estimated(workspace_env):
    client = workspace_env["client"]
    started = date.today() - timedelta(days=8)
    project = client.post("/api/project-workspace/projects", json={
        "project_code": "WXY-TIMELINE-ESTIMATE",
        "name": "估算时间线",
        "status": "pcb_design",
        "start_date": started.isoformat(),
    }).json()
    detail = client.get(f"/api/project-workspace/projects/{project['id']}").json()
    assert all(row["source"] == "timeline_estimate" for row in detail["status_history"])
    assert all(row["occurred_precision"] == "datetime" for row in detail["status_history"])


def test_initial_timeline_can_be_backfilled_but_manual_audit_history_is_never_overwritten(workspace_env):
    client = workspace_env["client"]
    project = client.post("/api/project-workspace/projects", json={
        "project_code": "WXY-BACKFILL",
        "name": "后补周期",
        "status": "pcb_design",
    }).json()
    started = date.today() - timedelta(days=8)
    backfilled = client.post(
        f"/api/project-workspace/projects/{project['id']}/timeline/backfill",
        json={"start_date": started.isoformat()},
    )
    assert backfilled.status_code == 200, backfilled.text
    assert backfilled.json()["period"]["start_date"] == started.isoformat()
    assert backfilled.json()["lifecycle"]["nodes"][0]["occurred_on"] == started.isoformat()

    actual = client.put(
        f"/api/project-workspace/projects/{project['id']}/timeline/actual",
        json={"lifecycle_dates": {
            "planning": started.isoformat(),
            "component_selection": (started + timedelta(days=2)).isoformat(),
            "schematic": (started + timedelta(days=3)).isoformat(),
            "pcb_design": (started + timedelta(days=6)).isoformat(),
        }},
    )
    assert actual.status_code == 200, actual.text
    assert all(row["source"] == "timeline_actual" for row in actual.json()["status_history"])

    changed = client.post(
        f"/api/project-workspace/projects/{project['id']}/status",
        json={"status": "fabricating", "source": "web", "note": "已提交板厂"},
    )
    assert changed.status_code == 200
    refused = client.post(
        f"/api/project-workspace/projects/{project['id']}/timeline/backfill",
        json={"start_date": (started - timedelta(days=2)).isoformat()},
    )
    assert refused.status_code == 409
    refused_actual = client.put(
        f"/api/project-workspace/projects/{project['id']}/timeline/actual",
        json={"lifecycle_dates": {
            "planning": started.isoformat(),
            "component_selection": (started + timedelta(days=2)).isoformat(),
            "schematic": (started + timedelta(days=3)).isoformat(),
            "pcb_design": (started + timedelta(days=6)).isoformat(),
            "fabricating": (started + timedelta(days=7)).isoformat(),
        }},
    )
    assert refused_actual.status_code == 409


def test_project_start_date_cannot_be_in_the_future(workspace_env):
    response = workspace_env["client"].post("/api/project-workspace/projects", json={
        "project_code": "WXY-FUTURE",
        "name": "未来项目",
        "start_date": (date.today() + timedelta(days=1)).isoformat(),
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "开始日期不能晚于今天"


def test_version_bom_board_assembly_cost_and_expense(workspace_env):
    client = workspace_env["client"]
    project = create_project(client)
    project_id = project["id"]
    v1_id = project["current_version"]["id"]

    bom = client.post(
        f"/api/project-workspace/projects/{project_id}/versions/{v1_id}/bom",
        json={"component_id": 1, "quantity_per_board": 2, "designators": "R1,R2"},
    )
    assert bom.status_code == 200, bom.text
    board = client.post(f"/api/project-workspace/projects/{project_id}/versions/{v1_id}/boards", json={}).json()
    assert board["point_count"] == 2

    point = board["points"][0]
    solder = client.post(
        f"/api/project-workspace/projects/{project_id}/versions/{v1_id}/boards/{board['id']}/points/{point['id']}/action",
        json={"action": "solder", "expected_version": point["state_version"]},
    )
    assert solder.status_code == 200, solder.text
    assert Decimal(str(solder.json()["cost"]["actual_material_cost"])) == Decimal("0.125")

    point_after = solder.json()["point"]
    unsolder = client.post(
        f"/api/project-workspace/projects/{project_id}/versions/{v1_id}/boards/{board['id']}/points/{point['id']}/action",
        json={"action": "unsolder", "expected_version": point_after["state_version"]},
    )
    assert Decimal(str(unsolder.json()["cost"]["actual_material_cost"])) == Decimal("0")

    expense = client.post(
        f"/api/project-workspace/projects/{project_id}/expenses",
        json={"category": "pcb_fabrication", "amount": "88.50", "occurred_on": "2026-08-18", "vendor": "板厂"},
    )
    assert expense.status_code == 200
    detail = client.get(f"/api/project-workspace/projects/{project_id}").json()
    assert Decimal(str(detail["cost"]["comprehensive_cost"])) == Decimal("88.50")

    v2 = client.post(
        f"/api/project-workspace/projects/{project_id}/versions",
        json={"version_code": "V2", "change_summary": "修正 USB 供电"},
    )
    assert v2.status_code == 200, v2.text
    v2_workspace = client.get(
        f"/api/project-workspace/projects/{project_id}/versions/{v2.json()['id']}/workspace"
    ).json()
    assert len(v2_workspace["bom"]) == 1
    assert v2_workspace["boards"] == []
    assert Decimal(str(v2_workspace["cost"]["actual_material_cost"])) == Decimal("0")

    db = workspace_env["Session"]()
    assert db.get(Component, 1).quantity == 20
    assert db.query(PersonalProjectCostEventV2).filter(PersonalProjectCostEventV2.project_id == project_id).count() == 2
    db.close()


def test_bom_import_risk_and_unpriced_fill(workspace_env):
    client = workspace_env["client"]
    project = create_project(client)
    project_id = project["id"]
    version_id = project["current_version"]["id"]
    content = "仓库编号,数量,位号\nIC-0002,1,U1\nNOT-FOUND,2,R1 R2\n"
    imported = client.post(
        f"/api/project-workspace/projects/{project_id}/versions/{version_id}/bom/import",
        files={"file": ("bom.csv", content.encode("utf-8"), "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 1
    assert len(imported.json()["unmatched"]) == 1

    risk = client.post(
        f"/api/project-workspace/projects/{project_id}/risks",
        json={"severity": "high", "title": "USB 过流", "detail": "复测保险丝"},
    )
    assert risk.status_code == 200
    resolved = client.patch(
        f"/api/project-workspace/projects/{project_id}/risks/{risk.json()['id']}", json={"status": "resolved"}
    )
    assert resolved.json()["status"] == "resolved"

    db = workspace_env["Session"]()
    item = db.query(PersonalProjectBomItemV2).filter(PersonalProjectBomItemV2.project_id == project_id).one()
    assert item.component_id == 2
    db.close()


def test_one_shot_reset_removes_old_personal_projects_without_stock_reversal(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reset.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    db = Session()
    db.add(User(id=1, phone="13800000001", nickname="用户一"))
    component = Component(id=1, owner_user_id=1, warehouse_code="R-1", name="电阻", quantity=7)
    project = Project(id=1, scope_type="personal", owner_user_id=1, project_code="PJ-OLD", name="旧项目", status="active")
    db.add_all([component, project])
    db.flush()
    db.add(StockMovement(
        id="movement-1", component_id=1, owner_user_id=1, movement_type="solder_consume",
        quantity_delta=-1, project_id=1, created_by_user_id=1,
    ))
    db.commit()

    result = run_personal_project_v2_reset(db)
    assert result["applied"] is True
    assert result["legacy_projects"] == 1
    assert db.query(Project).count() == 0
    assert db.query(PersonalProjectV2).count() == 0
    assert db.get(Component, 1).quantity == 7
    assert db.get(StockMovement, "movement-1").project_id is None
    assert db.get(AppMigration, V130_PERSONAL_PROJECT_V2_RESET) is not None
    assert run_personal_project_v2_reset(db)["applied"] is False
    db.close()
    engine.dispose()
