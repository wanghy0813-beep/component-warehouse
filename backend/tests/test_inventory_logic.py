from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext
from app.database import Base
from app.main import (
    apply_component_organize_result,
    apply_loss_inventory_change,
    apply_solder_inventory_change,
    component_usage_records,
    component_out,
    delete_bom_item,
    record_usage_event,
    sync_bom_solder_points,
)
from app.models import (
    ActivityLog,
    Category,
    Component,
    InventoryLot,
    Project,
    ProjectBoard,
    ProjectBomItem,
    ProjectBomSolderPoint,
    User,
)
from app.services.stock_ledger import record_stock_delta
from app.schemas import UsageEventRequest
from app.services.inventory import (
    parse_passive_si_value,
    reserved_quantities,
    sort_components_by_value,
)


@pytest.fixture()
def inventory_env(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'inventory.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    user = User(id=1, phone="13800000001", nickname="库存用户")
    category = Category(name="电阻", color="#eef2ff")
    db.add_all([user, category])
    db.flush()
    component = Component(
        owner_user_id=1,
        name="10k 电阻",
        normalized_spec="10kΩ",
        category_id=category.id,
        quantity=5,
        warehouse_code="CW-00000001",
    )
    project = Project(owner_user_id=1, project_code="PJ-00000001", name="焊接测试")
    db.add_all([component, project])
    db.flush()
    board = ProjectBoard(project_id=project.id, board_index=1, name="第 1 板")
    item = ProjectBomItem(
        project_id=project.id,
        component_id=component.id,
        required_quantity=2,
        status="reserved",
        remark="R1,R2",
    )
    db.add_all([board, item])
    db.flush()
    points = [
        ProjectBomSolderPoint(
            bom_item_id=item.id,
            board_id=board.id,
            designator=designator,
        )
        for designator in ["R1", "R2"]
    ]
    db.add_all(points)
    db.commit()
    db.refresh(item)
    yield {
        "db": db,
        "component": component,
        "project": project,
        "item": item,
        "points": points,
        "auth": AuthContext(1, user.phone, user.nickname),
    }
    db.close()
    engine.dispose()


def test_solder_loss_inventory_identity_and_usage_records(inventory_env):
    db = inventory_env["db"]
    component = inventory_env["component"]
    project = inventory_env["project"]
    item = inventory_env["item"]
    first, second = inventory_env["points"]
    auth = inventory_env["auth"]

    assert reserved_quantities(db, [component.id])[component.id] == 2
    apply_solder_inventory_change(db, item, [first], True, project.id, auth)
    first.soldered = True
    db.commit()
    assert component.quantity == 4
    assert reserved_quantities(db, [component.id])[component.id] == 1

    apply_solder_inventory_change(db, item, [first], True, project.id, auth)
    db.commit()
    assert component.quantity == 4

    apply_solder_inventory_change(db, item, [first], False, project.id, auth)
    first.soldered = False
    db.commit()
    assert component.quantity == 5
    assert reserved_quantities(db, [component.id])[component.id] == 2

    apply_loss_inventory_change(db, item, [second], True, project.id, auth)
    second.lost = True
    db.commit()
    assert component.quantity == 4
    assert reserved_quantities(db, [component.id])[component.id] == 2

    apply_solder_inventory_change(db, item, [second], True, project.id, auth)
    second.soldered = True
    db.commit()
    assert component.quantity == 3
    assert reserved_quantities(db, [component.id])[component.id] == 1

    records = component_usage_records(component.id, auth, db, limit=100)
    assert [row["action"] for row in records[:2]] == ["component.consume", "component.loss"]
    assert records[0]["project_name"] == "焊接测试"
    assert records[0]["project_code"] == "PJ-00000001"
    assert records[0]["designators"] == ["R2"]


def test_usage_event_writes_owner_scoped_activity_log(inventory_env):
    db = inventory_env["db"]
    auth = inventory_env["auth"]
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    result = record_usage_event(
        UsageEventRequest(
            event="ui.components.detail_open",
            page="/components",
            target_type="component",
            target_id=inventory_env["component"].id,
            entry="card",
            detail={"source": "test"},
            viewport_width=390,
        ),
        request,
        auth,
        db,
    )

    assert result == {"ok": True}
    log = db.query(ActivityLog).filter(ActivityLog.action == "ui.components.detail_open").one()
    assert log.owner_user_id == auth.user_id
    assert log.entity_type == "component"
    assert log.entity_id == inventory_env["component"].id
    assert '"viewport_width": 390' in log.detail


def test_full_solder_shortage_rolls_back_and_delete_requires_undo(inventory_env):
    db = inventory_env["db"]
    component = inventory_env["component"]
    project = inventory_env["project"]
    item = inventory_env["item"]
    points = inventory_env["points"]
    auth = inventory_env["auth"]
    component.quantity = 1
    db.commit()

    with pytest.raises(HTTPException) as error:
        apply_solder_inventory_change(db, item, points, True, project.id, auth)
    assert error.value.status_code == 400
    assert "需要 2" in error.value.detail
    assert "现有 1" in error.value.detail
    assert "缺少 1" in error.value.detail
    assert component.quantity == 1
    assert not any(point.stock_applied for point in points)

    component.quantity = 2
    apply_solder_inventory_change(db, item, points, True, project.id, auth)
    for point in points:
        point.soldered = True
    db.commit()
    assert component.quantity == 0

    apply_solder_inventory_change(db, item, points, True, project.id, auth)
    db.commit()
    assert component.quantity == 0

    with pytest.raises(HTTPException) as delete_error:
        delete_bom_item(project.id, item.id, auth, db)
    assert "请先逐项撤销" in delete_error.value.detail


def test_passive_value_sorting_uses_si_units():
    category = SimpleNamespace(name="电阻")
    values = [
        SimpleNamespace(id=1, category=category, category_id=1, normalized_spec="1MΩ", parameters=None, model=None, name="1M"),
        SimpleNamespace(id=2, category=category, category_id=1, normalized_spec="0Ω", parameters=None, model=None, name="0"),
        SimpleNamespace(id=3, category=category, category_id=1, normalized_spec="10kΩ", parameters=None, model=None, name="10k"),
        SimpleNamespace(id=4, category=category, category_id=1, normalized_spec=None, parameters=None, model="未知", name="未知"),
    ]
    assert parse_passive_si_value(values[0]) == 1_000_000
    assert [item.id for item in sort_components_by_value(values)] == [2, 3, 1, 4]


def test_component_sorting_prioritizes_rlc_then_standard_custom_other_and_uncategorized():
    def item(identifier, category_name, category_id, spec="1"):
        category = SimpleNamespace(name=category_name) if category_name else None
        return SimpleNamespace(
            id=identifier,
            category=category,
            category_id=category_id,
            normalized_spec=spec,
            parameters=None,
            model=str(identifier),
            name=str(identifier),
        )

    values = [
        item(1, "自定义类别", 1),
        item(2, "其他", 2),
        item(3, None, None),
        item(4, "电容", 20, "100nF"),
        item(5, "电阻", 99, "10kΩ"),
        item(6, "电感", 3, "10µH"),
        item(7, "二极管", 2),
    ]
    assert [row.id for row in sort_components_by_value(values)] == [5, 4, 6, 7, 1, 2, 3]


def test_low_stock_warning_requires_common_and_respects_exemption(inventory_env):
    component = inventory_env["component"]
    component.is_common = True
    component.safety_quantity = 5
    assert component_out(component, 1)["low_stock_warning"] is True
    component.low_stock_exempt = True
    assert component_out(component, 1)["low_stock_warning"] is False
    component.low_stock_exempt = False
    component.is_common = False
    assert component_out(component, 1)["low_stock_warning"] is False


def test_inventory_lots_track_channel_and_support_specific_lot_decrement(inventory_env):
    db = inventory_env["db"]
    component = inventory_env["component"]

    movements = record_stock_delta(
        db,
        component,
        3,
        movement_type="manual_restock",
        source_type="taobao",
        source_reference="TB-ORDER-1",
        location="A1",
    )
    db.flush()
    lot = db.get(InventoryLot, movements[0].lot_id)
    assert lot.source_type == "taobao"
    assert lot.source_reference == "TB-ORDER-1"
    assert lot.remaining_quantity == 3

    record_stock_delta(db, component, -2, movement_type="manual_consume", lot_id=lot.id)
    db.flush()
    assert lot.remaining_quantity == 1

    with pytest.raises(ValueError):
        record_stock_delta(db, component, -2, movement_type="manual_consume", lot_id=lot.id)


def test_ai_package_only_fills_empty_package_and_never_overwrites_manual_value(inventory_env):
    db = inventory_env["db"]
    component = inventory_env["component"]

    component.package = "0805"
    apply_component_organize_result(db, component, {"package": "0603", "confidence": "high"}, source="test")
    assert component.package == "0805"

    component.package = None
    apply_component_organize_result(db, component, {"package": "0603", "confidence": "low"}, source="test")
    assert component.package is None

    apply_component_organize_result(db, component, {"package": "0603", "confidence": "high"}, source="test")
    assert component.package == "0603"


def test_bom_without_designators_generates_quantity_solder_points(inventory_env):
    db = inventory_env["db"]
    component = inventory_env["component"]
    project = inventory_env["project"]

    item = ProjectBomItem(
        project_id=project.id,
        component_id=component.id,
        required_quantity=3,
        status="reserved",
        remark="",
    )
    db.add(item)
    db.flush()

    sync_bom_solder_points(db, item)
    db.flush()
    points = (
        db.query(ProjectBomSolderPoint)
        .filter(ProjectBomSolderPoint.bom_item_id == item.id)
        .order_by(ProjectBomSolderPoint.designator.asc())
        .all()
    )
    assert [point.designator for point in points] == ["用量1", "用量2", "用量3"]
