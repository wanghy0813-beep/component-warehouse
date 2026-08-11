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
    create_component_lot,
    decrement_component_quantity,
    delete_bom_item,
    delete_component_lot,
    increment_component_quantity,
    list_component_lots,
    list_component_cards_page,
    record_usage_event,
    sync_bom_solder_points,
    update_equipment_occupancy,
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
    StockMovement,
    User,
)
from app.services.stock_ledger import record_stock_delta
from app.schemas import ComponentConsumeRequest, EquipmentOccupancyRequest, InventoryLotCreate, UsageEventRequest
from app.services.inventory import (
    is_durable_equipment,
    normalize_inventory_location,
    normalize_inventory_status,
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


def test_component_card_page_is_compact_and_pages_by_category(inventory_env):
    db = inventory_env["db"]
    capacitor = Category(name="电容", color="#ecfeff")
    db.add(capacitor)
    db.flush()
    db.add_all([
        Component(
            owner_user_id=1,
            name="100nF 电容",
            normalized_spec="100nF",
            category_id=capacitor.id,
            quantity=10,
            warehouse_code="CAP-00000001",
            description="卡片流不应携带详情正文",
        ),
        Component(
            owner_user_id=1,
            name="1uF 电容",
            normalized_spec="1uF",
            category_id=capacitor.id,
            quantity=8,
            warehouse_code="CAP-00000002",
        ),
    ])
    db.commit()

    common = {
        "auth": inventory_env["auth"],
        "db": db,
        "page_size": 1,
        "keyword": None,
        "category_id": None,
        "status": None,
        "ai_status": None,
        "stock": None,
    }
    first = list_component_cards_page(page=1, **common)
    second = list_component_cards_page(page=2, **common)

    assert first["total"] == 3
    assert first["category_total"] == 2
    assert first["has_more"] is True
    assert first["groups"][0]["category"].name == "电阻"
    assert second["groups"][0]["category"].name == "电容"
    assert len(second["groups"][0]["items"]) == 2
    assert "description" not in second["groups"][0]["items"][0]
    assert "ai_usage" not in second["groups"][0]["items"][0]
    assert "card_chips" in second["groups"][0]["items"][0]
    assert "card_usage" in second["groups"][0]["items"][0]


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


def test_equipment_occupancy_keeps_asset_count_and_only_loss_reduces_inventory(inventory_env):
    db = inventory_env["db"]
    auth = inventory_env["auth"]
    equipment_category = Category(name="设备", color="#e2e8f0")
    db.add(equipment_category)
    db.flush()
    equipment = Component(
        owner_user_id=auth.user_id,
        name="实验室调试器",
        category=equipment_category,
        warehouse_code="EQP-00000999",
        quantity=1,
        status="in_transit",
        location="运输中",
    )
    db.add(equipment)
    db.commit()

    assert is_durable_equipment(equipment) is True
    assert normalize_inventory_location(" 运输中 ") is None
    assert normalize_inventory_status("in_transit") == "in_stock"
    assert component_out(equipment)["location"] is None
    assert component_out(equipment)["status"] == "in_stock"

    occupied = update_equipment_occupancy(
        equipment.id,
        EquipmentOccupancyRequest(action="occupy", quantity=1, remark="实验台使用"),
        auth,
        db,
    )
    assert occupied["quantity"] == 1
    assert occupied["occupied_quantity"] == 1
    assert occupied["available_quantity"] == 0
    assert db.query(ActivityLog).filter_by(component_id=equipment.id, action="component.occupy").one()

    released = update_equipment_occupancy(
        equipment.id,
        EquipmentOccupancyRequest(action="release", quantity=1, remark="实验完成"),
        auth,
        db,
    )
    assert released["quantity"] == 1
    assert released["occupied_quantity"] == 0
    assert released["available_quantity"] == 1
    assert db.query(ActivityLog).filter_by(component_id=equipment.id, action="component.release").one()

    with pytest.raises(HTTPException) as error:
        decrement_component_quantity(equipment.id, auth, db, ComponentConsumeRequest(quantity=1))
    assert error.value.status_code == 400
    assert "正常使用不扣库存" in error.value.detail
    assert equipment.quantity == 1

    update_equipment_occupancy(
        equipment.id,
        EquipmentOccupancyRequest(action="occupy", quantity=1),
        auth,
        db,
    )

    result = decrement_component_quantity(
        equipment.id,
        auth,
        db,
        ComponentConsumeRequest(quantity=1, reason_type="loss", remark="外壳损坏"),
    )
    assert result["quantity"] == 0
    assert result["occupied_quantity"] == 0
    assert result["status"] == "damaged"
    assert db.query(ActivityLog).filter_by(component_id=equipment.id, action="component.loss").one()
    assert db.query(StockMovement).filter_by(component_id=equipment.id, movement_type="manual_loss").one()

    restored = increment_component_quantity(
        equipment.id,
        auth,
        db,
        ComponentConsumeRequest(quantity=1, remark="维修后重新入库"),
    )
    assert restored["quantity"] == 1
    assert restored["status"] == "in_stock"


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


def test_old_lots_refresh_immediately_and_unused_manual_lot_can_be_deleted(inventory_env):
    db = inventory_env["db"]
    component = inventory_env["component"]
    auth = inventory_env["auth"]

    initial_lots = list_component_lots(component.id, auth, db)
    assert len(initial_lots) == 1
    assert initial_lots[0]["source_type"] == "legacy"
    assert initial_lots[0]["remaining_quantity"] == 5
    assert initial_lots[0]["can_delete"] is False

    created = create_component_lot(
        component.id,
        InventoryLotCreate(quantity=3, source_type="taobao", source_reference="WRONG-ORDER"),
        auth,
        db,
    )
    assert created["remaining_quantity"] == 3
    assert created["can_delete"] is True
    assert component.quantity == 8

    result = delete_component_lot(component.id, created["id"], auth, db)
    assert result["deleted"] is True
    assert result["removed_quantity"] == 3
    assert result["component"]["quantity"] == 5
    assert db.get(InventoryLot, created["id"]).status == "deleted"
    assert [row["source_type"] for row in list_component_lots(component.id, auth, db)] == ["legacy"]
    assert [
        (movement.movement_type, movement.quantity_delta)
        for movement in db.query(StockMovement).filter(StockMovement.lot_id == created["id"]).order_by(StockMovement.created_at.asc()).all()
    ] == [("manual_lot_create", 3), ("manual_lot_delete", -3)]


@pytest.mark.parametrize("movement_type", ["component_create", "team_component_create"])
def test_unused_initial_inventory_lot_can_be_deleted(inventory_env, movement_type):
    db = inventory_env["db"]
    auth = inventory_env["auth"]
    component = Component(
        owner_user_id=1,
        name=f"{movement_type} 初始库存测试",
        quantity=4,
        warehouse_code=f"CW-{movement_type}",
    )
    db.add(component)
    db.flush()
    movements = record_stock_delta(
        db,
        component,
        4,
        movement_type=movement_type,
        reason="新增元器件初始库存",
        actor_user_id=1,
    )
    lot_id = movements[0].lot_id
    db.commit()

    lots = list_component_lots(component.id, auth, db)
    assert len(lots) == 1
    assert lots[0]["source_type"] == movement_type
    assert lots[0]["can_delete"] is True

    result = delete_component_lot(component.id, lot_id, auth, db)
    assert result["deleted"] is True
    assert result["removed_quantity"] == 4
    assert result["component"]["quantity"] == 0
    assert db.get(InventoryLot, lot_id).status == "deleted"
    assert [
        (movement.movement_type, movement.quantity_delta)
        for movement in db.query(StockMovement).filter(StockMovement.lot_id == lot_id).order_by(StockMovement.created_at.asc()).all()
    ] == [(movement_type, 4), ("manual_lot_delete", -4)]


def test_used_initial_inventory_lot_cannot_be_deleted(inventory_env):
    db = inventory_env["db"]
    auth = inventory_env["auth"]
    component = Component(
        owner_user_id=1,
        name="已扣减初始库存测试",
        quantity=3,
        warehouse_code="CW-USED-INITIAL",
    )
    db.add(component)
    db.flush()
    movements = record_stock_delta(
        db,
        component,
        3,
        movement_type="component_create",
        reason="新增元器件初始库存",
        actor_user_id=1,
    )
    lot_id = movements[0].lot_id
    component.quantity -= 1
    record_stock_delta(db, component, -1, movement_type="manual_consume", lot_id=lot_id)
    db.commit()

    lots = list_component_lots(component.id, auth, db)
    assert lots[0]["can_delete"] is False
    assert "已经发生扣减" in lots[0]["delete_block_reason"]
    with pytest.raises(HTTPException) as error:
        delete_component_lot(component.id, lot_id, auth, db)
    assert error.value.status_code == 400
    assert "已经发生扣减" in error.value.detail
    assert db.get(InventoryLot, lot_id).status == "active"


def test_used_manual_lot_cannot_be_deleted(inventory_env):
    db = inventory_env["db"]
    component = inventory_env["component"]
    auth = inventory_env["auth"]
    created = create_component_lot(
        component.id,
        InventoryLotCreate(quantity=2, source_type="manual", source_reference="USED-LOT"),
        auth,
        db,
    )
    component.quantity -= 1
    record_stock_delta(db, component, -1, movement_type="manual_consume", lot_id=created["id"])
    db.commit()

    with pytest.raises(HTTPException) as error:
        delete_component_lot(component.id, created["id"], auth, db)

    assert error.value.status_code == 400
    assert "已经发生扣减" in error.value.detail
    assert db.get(InventoryLot, created["id"]).status == "active"


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
