import hashlib
from decimal import Decimal
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext, require_access
from app.codex_integration import SlidingWindowLimiter, router
from app.database import Base, get_db
from app.models import (
    Category,
    Component,
    IntegrationAccessToken,
    IntegrationOperation,
    InventoryLot,
    OrderImportBatch,
    PersonalProjectBomItemV2,
    PersonalProjectExpenseV2,
    PersonalProjectV2,
    PersonalProjectVersionV2,
    Project,
    ProjectBomItem,
    ProjectExpense,
    ProjectPcbVersion,
    PurchaseLine,
    PurchaseOrder,
    PurchaseReceipt,
    StockMovement,
    User,
)


@pytest.fixture()
def codex_env(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'codex-integration.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add_all(
        [
            User(id=1, phone="13800000001", nickname="库主"),
            User(id=2, phone="13800000002", nickname="其他用户"),
            Category(id=1, name="电阻", color="#fff", code_prefix="RES", code_prefix_locked=True),
            Category(id=2, name="设备", color="#eee", code_prefix="EQP", code_prefix_locked=True),
        ]
    )
    db.add(
        InventoryLot(
            id="lot-owner-1",
            component_id=1,
            owner_user_id=1,
            source_type="test_seed",
            initial_quantity=20,
            remaining_quantity=20,
            status="active",
        )
    )
    db.add_all(
        [
            Component(
                id=1,
                owner_user_id=1,
                warehouse_code="RES-00000001",
                name="10k 电阻",
                model="RC0603FR-0710KL",
                manufacturer="Yageo",
                parameters="10kΩ 1%",
                normalized_spec="10kΩ",
                package="0603",
                lcsc_number="C25804",
                quantity=20,
                average_unit_price=Decimal("0.125"),
                category_id=1,
            ),
            Component(
                id=2,
                owner_user_id=2,
                warehouse_code="RES-00000002",
                name="秘密器件",
                model="PRIVATE-ONLY",
                parameters="5kΩ",
                normalized_spec="5kΩ",
                package="0603",
                quantity=500,
                category_id=1,
            ),
        ]
    )
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_auth(x_test_user: int = Header(default=1)) -> AuthContext:
        return AuthContext(x_test_user, f"1380000000{x_test_user}", f"用户{x_test_user}")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_access] = override_auth
    with TestClient(app) as client:
        yield {"client": client, "Session": Session}
    engine.dispose()


def create_machine_token(codex_env) -> tuple[str, dict]:
    response = codex_env["client"].post(
        "/api/integrations/codex/tokens",
        json={"name": "测试 Codex", "expires_in_days": 365},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["token"], {"Authorization": f"Bearer {payload['token']}"}


def test_token_is_shown_once_hashed_and_personal_reads_are_isolated(codex_env):
    raw_token, headers = create_machine_token(codex_env)
    assert raw_token.startswith("cw_codex_")
    db = codex_env["Session"]()
    stored = db.query(IntegrationAccessToken).one()
    assert stored.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert raw_token not in stored.token_hash
    db.close()

    session = codex_env["client"].get("/api/integrations/codex/v1/session", headers=headers)
    assert session.status_code == 200
    assert session.json()["scopes"] == ["inventory:read"]
    categories = codex_env["client"].get("/api/integrations/codex/v1/categories", headers=headers)
    assert categories.status_code == 200
    assert categories.json()["items"] == [
        {
            "id": 1,
            "name": "电阻",
            "color": "#fff",
            "code_prefix": "RES",
            "zone": None,
            "location": None,
            "summary": None,
        },
        {
            "id": 2,
            "name": "设备",
            "color": "#eee",
            "code_prefix": "EQP",
            "zone": None,
            "location": None,
            "summary": None,
        },
    ]
    assert categories.json()["classification_standard"] == "WXY LAB Hardware 17-zone"
    result = codex_env["client"].get(
        "/api/integrations/codex/v1/components/search",
        params={"q": "电阻"},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    assert [row["warehouse_code"] for row in result.json()["items"]] == ["RES-00000001"]
    assert result.json()["items"][0]["average_unit_price"] == 0.125
    assert result.json()["items"][0]["price_currency"] == "CNY"
    assert "PRIVATE-ONLY" not in result.text

    match = codex_env["client"].post(
        "/api/integrations/codex/v1/components/match",
        headers=headers,
        json={
            "items": [
                {
                    "designator": "R1",
                    "quantity": 2,
                    "manufacturer_part": "RC0603FR-0710KL",
                    "value": "10kΩ",
                    "footprint": "0603",
                }
            ]
        },
    )
    assert match.status_code == 200, match.text
    row = match.json()["items"][0]
    assert row["classification"] == "exact"
    assert row["auto_selected"] is True
    assert {candidate["component"]["id"] for candidate in row["matches"]} == {1}
    assert row["matches"][0]["component"]["warehouse_code"] == "RES-00000001"
    assert row["matches"][0]["component"]["average_unit_price"] == 0.125
    assert row["matches"][0]["component"]["price_currency"] == "CNY"
    assert "PRIVATE-ONLY" not in match.text

    unsafe_candidates = codex_env["client"].post(
        "/api/integrations/codex/v1/components/match",
        headers=headers,
        json={
            "items": [
                {
                    "designator": "D1",
                    "quantity": 1,
                    "manufacturer_part": "BZT52C12",
                    "parameters": "12V 稳压二极管",
                    "footprint": "0603",
                },
                {
                    "designator": "RFREQ",
                    "quantity": 1,
                    "parameters": "RFREQ",
                    "footprint": "0603",
                },
            ]
        },
    )
    assert unsafe_candidates.status_code == 200, unsafe_candidates.text
    assert [item["classification"] for item in unsafe_candidates.json()["items"]] == ["missing", "missing"]
    assert all(not item["matches"] for item in unsafe_candidates.json()["items"])
    assert unsafe_candidates.json()["items"][0]["ignored_input"] is False
    assert unsafe_candidates.json()["items"][1]["ignored_input"] is True
    assert unsafe_candidates.json()["items"][1]["missing_suggestion"] is None

    db = codex_env["Session"]()
    project = Project(scope_type="personal", owner_user_id=1, project_code="PRJ-RESERVED", name="预留测试")
    db.add(project)
    db.flush()
    db.add(ProjectBomItem(project_id=project.id, component_id=1, required_quantity=19, status="reserved"))
    db.commit()
    db.close()
    shortage = codex_env["client"].post(
        "/api/integrations/codex/v1/components/match",
        headers=headers,
        json={"items": [{"designator": "R3,R4", "quantity": 2, "manufacturer_part": "RC0603FR-0710KL", "footprint": "0603"}]},
    )
    shortage_row = shortage.json()["items"][0]
    assert shortage_row["classification"] == "shortage"
    assert shortage_row["auto_selected"] is False
    assert shortage_row["selected_component_id"] is None
    assert shortage_row["matches"][0]["available_quantity"] == 1


def test_complete_workspace_read_is_paginated_personal_and_safe(codex_env):
    db = codex_env["Session"]()
    db.add_all(
        [
            Component(
                id=3,
                owner_user_id=1,
                warehouse_code="CAP-00000003",
                name="1uF 电容",
                quantity=5,
                category_id=1,
            ),
            OrderImportBatch(id=1, owner_user_id=1, source_file="/tmp/private.xlsx", order_number="OWNER-ORDER"),
            OrderImportBatch(id=2, owner_user_id=2, source_file="/tmp/other.xlsx", order_number="OTHER-ORDER"),
        ]
    )
    db.commit()
    db.close()
    _, headers = create_machine_token(codex_env)
    session = codex_env["client"].get("/api/integrations/codex/v1/session", headers=headers)
    assert session.status_code == 200, session.text
    assert session.json()["service_name"] == "WXY LAB Hardware"
    assert session.json()["read_mode"] == "full_personal_workspace"
    assert session.json()["write_mode"] == "browser_approval_only"

    catalog = codex_env["client"].get("/api/integrations/codex/v1/workspace", headers=headers)
    assert catalog.status_code == 200, catalog.text
    payload = catalog.json()
    assert payload["complete_personal_read"] is True
    datasets = {row["dataset"]: row for row in payload["datasets"]}
    assert datasets["components"]["count"] == 2
    assert datasets["inventory_lots"]["count"] == 1
    assert "users" not in datasets
    assert "integration_access_tokens" not in datasets
    assert "activity_logs" not in datasets
    assert "competition_libraries" not in datasets
    assert "storage_path" not in datasets["personal_project_files_v2"]["fields"]
    assert datasets["order_import_batches"]["count"] == 1
    assert "source_file" not in datasets["order_import_batches"]["fields"]
    assert all("user_id" not in field for row in datasets.values() for field in row["fields"])

    components = codex_env["client"].get(
        "/api/integrations/codex/v1/workspace/components",
        params={"limit": 1},
        headers=headers,
    )
    assert components.status_code == 200, components.text
    assert components.json()["total"] == 2
    assert components.json()["complete"] is False
    assert components.json()["next_cursor"] == "1"
    assert [row["warehouse_code"] for row in components.json()["items"]] == ["RES-00000001"]
    item = components.json()["items"][0]
    assert "owner_user_id" not in item
    assert "ai_summary" not in item
    assert "PRIVATE-ONLY" not in components.text

    second_page = codex_env["client"].get(
        "/api/integrations/codex/v1/workspace/components",
        params={"cursor": components.json()["next_cursor"], "limit": 1},
        headers=headers,
    )
    assert second_page.status_code == 200, second_page.text
    assert second_page.json()["complete"] is True
    assert second_page.json()["next_cursor"] is None
    assert [row["warehouse_code"] for row in second_page.json()["items"]] == ["CAP-00000003"]

    lots = codex_env["client"].get(
        "/api/integrations/codex/v1/workspace/inventory_lots",
        headers=headers,
    )
    assert lots.status_code == 200, lots.text
    assert [row["id"] for row in lots.json()["items"]] == ["lot-owner-1"]
    assert "owner_user_id" not in lots.json()["items"][0]

    imports = codex_env["client"].get(
        "/api/integrations/codex/v1/workspace/order_import_batches",
        headers=headers,
    )
    assert imports.status_code == 200, imports.text
    assert [row["order_number"] for row in imports.json()["items"]] == ["OWNER-ORDER"]
    assert "source_file" not in imports.json()["items"][0]
    assert "OTHER-ORDER" not in imports.text

    assert codex_env["client"].get(
        "/api/integrations/codex/v1/workspace/users",
        headers=headers,
    ).status_code == 404
    invalid_cursor = codex_env["client"].get(
        "/api/integrations/codex/v1/workspace/components",
        params={"cursor": "not-a-real-id"},
        headers=headers,
    )
    assert invalid_cursor.status_code == 422


def test_proposal_never_writes_and_browser_approval_and_undo_use_ledger(codex_env):
    _, headers = create_machine_token(codex_env)
    proposal = codex_env["client"].post(
        "/api/integrations/codex/v1/operations",
        headers=headers,
        json={
            "idempotency_key": "stock-loss-test-0001",
            "reason": "测试报损",
            "actions": [
                {
                    "action": "stock.adjust",
                    "target_id": "RES-00000001",
                    "payload": {"delta": -3, "movement_type": "loss", "reason": "测试损坏"},
                }
            ],
        },
    )
    assert proposal.status_code == 200, proposal.text
    operation_id = proposal.json()["id"]
    db = codex_env["Session"]()
    assert db.get(Component, 1).quantity == 20
    assert db.query(StockMovement).count() == 0
    db.close()

    forbidden = codex_env["client"].post(
        f"/api/integrations/codex/operations/{operation_id}/approve",
        headers={"X-Test-User": "2"},
    )
    assert forbidden.status_code == 404
    approved = codex_env["client"].post(f"/api/integrations/codex/operations/{operation_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "succeeded"
    db = codex_env["Session"]()
    assert db.get(Component, 1).quantity == 17
    assert [(row.movement_type, row.quantity_delta) for row in db.query(StockMovement).all()] == [("loss", -3)]
    db.close()

    undo = codex_env["client"].post(
        f"/api/integrations/codex/v1/operations/{operation_id}/undo",
        headers=headers,
    )
    assert undo.status_code == 200, undo.text
    undo_id = undo.json()["id"]
    db = codex_env["Session"]()
    assert db.get(Component, 1).quantity == 17
    db.close()
    undone = codex_env["client"].post(f"/api/integrations/codex/operations/{undo_id}/approve")
    assert undone.status_code == 200, undone.text
    db = codex_env["Session"]()
    assert db.get(Component, 1).quantity == 20
    assert [row.quantity_delta for row in db.query(StockMovement).order_by(StockMovement.created_at).all()] == [-3, 3]
    original = db.get(IntegrationOperation, operation_id)
    assert original.status == "undone"
    assert original.undone_by_operation_id == undo_id
    db.close()


def test_idempotency_expiry_revoke_and_state_drift_are_safe(codex_env):
    raw_token, headers = create_machine_token(codex_env)
    body = {
        "idempotency_key": "component-update-0001",
        "actions": [
            {
                "action": "component.update",
                "target_id": "RES-00000001",
                "payload": {"location": "A-01"},
            }
        ],
    }
    first = codex_env["client"].post("/api/integrations/codex/v1/operations", headers=headers, json=body)
    second = codex_env["client"].post("/api/integrations/codex/v1/operations", headers=headers, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    db = codex_env["Session"]()
    component = db.get(Component, 1)
    component.location = "其他会话已修改"
    db.commit()
    db.close()
    stale = codex_env["client"].post(f"/api/integrations/codex/operations/{first.json()['id']}/approve")
    assert stale.status_code == 409
    db = codex_env["Session"]()
    assert db.get(Component, 1).location == "其他会话已修改"
    db.close()
    regenerated = codex_env["client"].post("/api/integrations/codex/v1/operations", headers=headers, json=body)
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["id"] != first.json()["id"]
    assert regenerated.json()["status"] == "pending_approval"
    db = codex_env["Session"]()
    regenerated_row = db.get(IntegrationOperation, regenerated.json()["id"])
    regenerated_row.approval_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()
    expired_status = codex_env["client"].get(
        f"/api/integrations/codex/v1/operations/{regenerated.json()['id']}",
        headers=headers,
    )
    assert expired_status.status_code == 200
    assert expired_status.json()["status"] == "expired"
    db = codex_env["Session"]()
    token = db.query(IntegrationAccessToken).one()
    token.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()
    assert codex_env["client"].get("/api/integrations/codex/v1/session", headers=headers).status_code == 401

    replacement = codex_env["client"].post(
        "/api/integrations/codex/tokens",
        json={"name": "撤销测试", "expires_in_days": 1},
    ).json()
    replacement_headers = {"Authorization": f"Bearer {replacement['token']}"}
    assert codex_env["client"].delete(f"/api/integrations/codex/tokens/{replacement['id']}").status_code == 200
    assert codex_env["client"].get("/api/integrations/codex/v1/session", headers=replacement_headers).status_code == 401
    assert raw_token not in codex_env["client"].get("/api/integrations/codex/tokens").text


def test_sliding_window_rate_limit():
    limiter = SlidingWindowLimiter()
    limiter.check("token", "read", 2)
    limiter.check("token", "read", 2)
    with pytest.raises(Exception) as error:
        limiter.check("token", "read", 2)
    assert getattr(error.value, "status_code", None) == 429


def test_atomic_project_bom_and_consumption_can_be_approved_then_reversed(codex_env):
    _, headers = create_machine_token(codex_env)
    proposal = codex_env["client"].post(
        "/api/integrations/codex/v1/operations",
        headers=headers,
        json={
            "idempotency_key": "project-bom-stock-atomic-0001",
            "reason": "Codex 接入验收",
            "actions": [
                {"action": "workspace.project.create", "payload": {"project_code": "PRJ-CODEX-TEST", "name": "Codex 接入验收"}},
                {
                    "action": "workspace.bom.upsert",
                    "payload": {"project_code": "PRJ-CODEX-TEST", "warehouse_code": "RES-00000001", "required_quantity": 4},
                },
                {
                    "action": "stock.adjust",
                    "target_id": "RES-00000001",
                    "payload": {"delta": -2, "movement_type": "manual_consume", "reason": "焊接验收板"},
                },
            ],
        },
    )
    assert proposal.status_code == 200, proposal.text
    operation_id = proposal.json()["id"]
    db = codex_env["Session"]()
    assert db.query(PersonalProjectV2).count() == 0
    assert db.query(PersonalProjectBomItemV2).count() == 0
    assert db.get(Component, 1).quantity == 20
    db.close()

    approved = codex_env["client"].post(f"/api/integrations/codex/operations/{operation_id}/approve")
    assert approved.status_code == 200, approved.text
    db = codex_env["Session"]()
    project = db.query(PersonalProjectV2).filter(PersonalProjectV2.project_code == "PRJ-CODEX-TEST").one()
    bom = db.query(PersonalProjectBomItemV2).filter(PersonalProjectBomItemV2.project_id == project.id).one()
    assert project.status == "planning"
    assert project.current_version_id is not None
    assert (bom.archived_at, bom.quantity_per_board) == (None, 4)
    assert db.get(Component, 1).quantity == 18
    db.close()

    undo = codex_env["client"].post(f"/api/integrations/codex/v1/operations/{operation_id}/undo", headers=headers)
    assert undo.status_code == 200, undo.text
    first_undo_id = undo.json()["id"]
    assert codex_env["client"].post(f"/api/integrations/codex/operations/{first_undo_id}/reject").status_code == 200
    retry_undo = codex_env["client"].post(f"/api/integrations/codex/v1/operations/{operation_id}/undo", headers=headers)
    assert retry_undo.status_code == 200, retry_undo.text
    assert retry_undo.json()["id"] != first_undo_id
    reversed_response = codex_env["client"].post(f"/api/integrations/codex/operations/{retry_undo.json()['id']}/approve")
    assert reversed_response.status_code == 200, reversed_response.text
    db = codex_env["Session"]()
    project = db.query(PersonalProjectV2).filter(PersonalProjectV2.project_code == "PRJ-CODEX-TEST").one()
    bom = db.query(PersonalProjectBomItemV2).filter(PersonalProjectBomItemV2.project_id == project.id).one()
    assert project.archived_at is not None
    assert bom.archived_at is not None
    assert db.get(Component, 1).quantity == 20
    assert db.get(IntegrationOperation, operation_id).preview_json
    db.close()


def test_project_lifecycle_versions_costs_and_expenses_remain_approval_only(codex_env):
    _, headers = create_machine_token(codex_env)
    created = codex_env["client"].post(
        "/api/integrations/codex/v1/operations",
        headers=headers,
        json={
            "idempotency_key": "project-lifecycle-create-0001",
            "actions": [
                {
                    "action": "workspace.project.create",
                    "payload": {
                        "project_code": "wxy-plugin-board", "name": "插件项目",
                        "start_date": "2026-07-20", "status": "pcb_design",
                        "lifecycle_dates": {
                            "planning": "2026-07-20",
                            "component_selection": "2026-07-21",
                            "schematic": "2026-07-22",
                            "pcb_design": "2026-07-23",
                        },
                    },
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    db = codex_env["Session"]()
    assert db.query(PersonalProjectV2).filter(PersonalProjectV2.project_code == "WXY-PLUGIN-BOARD").count() == 0
    db.close()
    assert codex_env["client"].post(f"/api/integrations/codex/operations/{created.json()['id']}/approve").status_code == 200

    changed = codex_env["client"].post(
        "/api/integrations/codex/v1/operations",
        headers=headers,
        json={
            "idempotency_key": "project-lifecycle-change-0001",
            "actions": [
                {"action": "workspace.project.status", "target_id": "WXY-PLUGIN-BOARD", "payload": {"status": "fabricating", "note": "进入打板"}},
            ],
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["risk_level"] == "normal"
    assert codex_env["client"].post(f"/api/integrations/codex/operations/{changed.json()['id']}/approve").status_code == 200

    project_context = codex_env["client"].get(
        "/api/integrations/codex/v1/projects/WXY-PLUGIN-BOARD",
        headers=headers,
    )
    assert project_context.status_code == 200
    assert project_context.json()["project_code"] == "WXY-PLUGIN-BOARD"
    assert project_context.json()["status"] == "fabricating"
    assert project_context.json()["period"]["start_week"] == "2026W30"
    assert [node["status"] for node in project_context.json()["lifecycle"]["nodes"][:5]] == [
        "planning", "component_selection", "schematic", "pcb_design", "fabricating",
    ]
    assert project_context.json()["lifecycle"]["nodes"][0]["occurred_on"] == "2026-07-20"
    assert project_context.json()["lifecycle"]["nodes"][3]["state"] == "completed"
    assert project_context.json()["lifecycle"]["nodes"][4]["state"] == "current"
    assert len(project_context.json()["status_history"]) == 5

    proposal = codex_env["client"].post(
        "/api/integrations/codex/v1/operations",
        headers=headers,
        json={
            "idempotency_key": "project-version-expense-0001",
            "actions": [
                {"action": "workspace.version.create", "target_id": "WXY-PLUGIN-BOARD", "payload": {"version_code": "V2", "change_summary": "修复接口"}},
                {"action": "workspace.expense.create", "target_id": "WXY-PLUGIN-BOARD", "payload": {"category": "pcb_fabrication", "amount": "88.50", "occurred_on": "2026-07-21", "vendor": "板厂"}},
            ],
        },
    )
    assert proposal.status_code == 200, proposal.text
    db = codex_env["Session"]()
    assert db.query(PersonalProjectVersionV2).count() == 1
    assert db.query(PersonalProjectExpenseV2).count() == 0
    db.close()
    assert codex_env["client"].post(f"/api/integrations/codex/operations/{proposal.json()['id']}/approve").status_code == 200

    versions = codex_env["client"].get(
        "/api/integrations/codex/v1/projects/WXY-PLUGIN-BOARD/versions",
        headers=headers,
    ).json()["items"]
    assert [row["version_code"] for row in versions] == ["V2", "V1"]
    costs = codex_env["client"].get(
        "/api/integrations/codex/v1/projects/WXY-PLUGIN-BOARD/costs",
        headers=headers,
    ).json()
    assert costs["direct_expense"] == 88.5
    assert costs["comprehensive_cost"] == 88.5
    dashboard = codex_env["client"].get("/api/integrations/codex/v1/projects/overview", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["items"][0]["current_version_code"] == "V2"
    assert dashboard.json()["items"][0]["unpriced_count"] == 0


def test_purchase_create_receive_and_receive_undo_are_ledger_based(codex_env):
    _, headers = create_machine_token(codex_env)
    create_order = codex_env["client"].post(
        "/api/integrations/codex/v1/operations",
        headers=headers,
        json={
            "idempotency_key": "purchase-create-0001",
            "actions": [
                {
                    "action": "purchase.create",
                    "payload": {
                        "order_number": "PO-CODEX-1",
                        "status": "ordered",
                        "lines": [
                            {"warehouse_code": "RES-00000001", "description": "10k 电阻", "ordered_quantity": 5}
                        ],
                    },
                }
            ],
        },
    )
    assert create_order.status_code == 200, create_order.text
    approved_order = codex_env["client"].post(f"/api/integrations/codex/operations/{create_order.json()['id']}/approve")
    assert approved_order.status_code == 200, approved_order.text
    db = codex_env["Session"]()
    line = db.query(PurchaseLine).one()
    line_id = line.id
    db.close()

    receive = codex_env["client"].post(
        "/api/integrations/codex/v1/operations",
        headers=headers,
        json={
            "idempotency_key": "purchase-receive-0001",
            "actions": [
                {"action": "purchase.receive", "target_id": line_id, "payload": {"quantity": 5, "location": "A-01"}}
            ],
        },
    )
    assert receive.status_code == 200, receive.text
    receive_id = receive.json()["id"]
    assert codex_env["client"].post(f"/api/integrations/codex/operations/{receive_id}/approve").status_code == 200
    db = codex_env["Session"]()
    assert db.get(Component, 1).quantity == 25
    assert db.get(PurchaseLine, line_id).received_quantity == 5
    assert db.query(PurchaseReceipt).count() == 1
    db.close()

    undo = codex_env["client"].post(f"/api/integrations/codex/v1/operations/{receive_id}/undo", headers=headers)
    assert undo.status_code == 200, undo.text
    assert codex_env["client"].post(f"/api/integrations/codex/operations/{undo.json()['id']}/approve").status_code == 200
    db = codex_env["Session"]()
    assert db.get(Component, 1).quantity == 20
    assert db.get(PurchaseLine, line_id).received_quantity == 0
    assert sorted(row.quantity for row in db.query(PurchaseReceipt).all()) == [-5, 5]
    movements = db.query(StockMovement).order_by(StockMovement.created_at).all()
    assert [(row.movement_type, row.quantity_delta) for row in movements] == [
        ("purchase_receipt", 5),
        ("purchase_receipt_reversal", -5),
    ]
    db.close()


def test_project_v2_shortage_context_is_per_board_and_purchases_stay_separate(codex_env):
    _, headers = create_machine_token(codex_env)
    db = codex_env["Session"]()
    current = PersonalProjectV2(
        id="project-current", owner_user_id=1, project_code="PRJ-CURRENT", name="当前项目",
        status="planning", start_date=datetime.utcnow().date(),
    )
    other = PersonalProjectV2(
        id="project-other", owner_user_id=1, project_code="PRJ-OTHER", name="其他项目",
        status="planning", start_date=datetime.utcnow().date(),
    )
    db.add_all([current, other])
    db.flush()
    current_version = PersonalProjectVersionV2(
        id="version-current", project_id=current.id, sequence_number=1, version_code="V1", status="designing"
    )
    other_version = PersonalProjectVersionV2(
        id="version-other", project_id=other.id, sequence_number=1, version_code="V1", status="designing"
    )
    db.add_all([current_version, other_version])
    db.flush()
    current.current_version_id = current_version.id
    other.current_version_id = other_version.id
    db.add_all(
        [
            PersonalProjectBomItemV2(
                id="bom-current", project_id=current.id, version_id=current_version.id,
                component_id=1, quantity_per_board=25, designators="R1",
            ),
            PersonalProjectBomItemV2(
                id="bom-other", project_id=other.id, version_id=other_version.id,
                component_id=1, quantity_per_board=18, designators="R1",
            ),
        ]
    )
    order = PurchaseOrder(
        id="order-context",
        scope_type="personal",
        owner_user_id=1,
        project_id=None,
        order_number="PO-CONTEXT",
        status="ordered",
        currency="CNY",
        created_by_user_id=1,
    )
    db.add(order)
    db.add(
        PurchaseLine(
            id="line-context",
            purchase_order_id=order.id,
            component_id=1,
            receiver_user_id=1,
            description="10k 电阻",
            ordered_quantity=10,
            received_quantity=2,
            purchase_url="https://example.test/part",
            status="partial",
        )
    )
    db.commit()
    db.close()

    project_response = codex_env["client"].get("/api/integrations/codex/v1/projects/PRJ-CURRENT", headers=headers)
    assert project_response.status_code == 200, project_response.text
    row = project_response.json()["bom"][0]
    assert row["warehouse_code"] == "RES-00000001"
    assert row["stock_quantity"] == 20
    assert row["available_quantity"] == 20
    assert row["quantity_per_board"] == 25
    assert row["shortage_quantity"] == 5
    assert row["enough"] is False
    assert row["average_unit_price"] == 0.125

    purchases = codex_env["client"].get("/api/integrations/codex/v1/purchases", headers=headers)
    assert purchases.status_code == 200, purchases.text
    purchase = purchases.json()["items"][0]
    assert purchase["project_code"] is None
    line = purchase["lines"][0]
    assert line["warehouse_code"] == "RES-00000001"
    assert line["outstanding_quantity"] == 8
    assert line["in_transit_quantity"] == 8
    assert line["counts_as_in_transit"] is True
    assert line["purchase_url"] == "https://example.test/part"

    risks_response = codex_env["client"].get("/api/integrations/codex/v1/risks", headers=headers)
    assert risks_response.status_code == 200, risks_response.text
    assert isinstance(risks_response.json()["items"], list)
