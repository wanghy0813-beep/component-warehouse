import asyncio
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext
from app.database import Base
from app.main import (
    commit_price_statement,
    dashboard,
    preview_price_statement,
    rollback_price_statement_batch,
)
from app.codex_integration import _execute_action, _prepare_action
from app.models import Component, ComponentPriceEntry, Project, ProjectBomItem, User
from app.services import excel_import
from app.services.price_import import parse_price_statement


HEADERS = [
    "订单编号",
    "订单状态",
    "下单时间",
    "商品编号",
    "商品名称",
    "商品型号",
    "订购数量",
    "单价（人民币含税）",
    "小计金额（人民币含税）",
]


def statement_bytes(c1_subtotal: str = "10.00") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["立创商城物料明细对账单"])
    sheet.append(HEADERS)
    sheet.append(["SO-A", "已发货", "2026/07/01 10:00", "C1", "器件一", "M1", 10, Decimal(c1_subtotal) / 10, Decimal(c1_subtotal)])
    sheet.append(["SO-A", "已发货", "2026/07/01 10:00", "C2", "器件二", "M2", 10, 3, 30])
    sheet.append([None, None, None, None, "价外费用（配送费）", None, None, None, 8])
    sheet.append(["SO-CANCEL", "已取消", "2026/07/02 10:00", "C1", "取消器件", "M1", 9, 11, 99])
    sheet.append([None, None, None, None, "价外费用（配送费）", None, None, None, 2])
    sheet.append(["SO-B", "已发货", "2026/07/03 10:00", "C1", "器件一", "M1", 5, 1, 5])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


class MemoryUpload:
    def __init__(self, content: bytes, filename: str):
        self.content = content
        self.filename = filename

    async def read(self) -> bytes:
        return self.content


def upload(content: bytes, filename: str = "statement.xlsx") -> MemoryUpload:
    return MemoryUpload(content, filename)


def test_parser_allocates_shipping_and_excludes_canceled_orders():
    statement = parse_price_statement(statement_bytes(), "statement.xlsx")
    assert statement.item_row_count == 4
    assert statement.shipped_item_row_count == 3
    assert statement.canceled_item_row_count == 1
    assert statement.shipping_row_count == 2
    assert statement.shipped_merchandise_total == Decimal("45.000000")
    assert statement.shipped_shipping_total == Decimal("8.000000")
    assert statement.shipped_landed_total == Decimal("53.000000")

    by_key = {row.key: row for row in statement.rows}
    assert by_key[("SO-A", "C1")].allocated_shipping == Decimal("2.000000")
    assert by_key[("SO-A", "C2")].allocated_shipping == Decimal("6.000000")
    assert by_key[("SO-CANCEL", "C1")].allocated_shipping == Decimal("0.000000")


def test_old_xls_signature_uses_xlrd_path(monkeypatch):
    sentinel = [(1, ["xls"])]
    monkeypatch.setattr(excel_import, "_all_rows_from_xls", lambda content: sentinel)
    assert excel_import._all_rows(b"\xd0\xcf\x11\xe0test", "statement.xls") == sentinel


def test_price_import_is_idempotent_revisable_isolated_and_reversible(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'price.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add_all(
        [
            User(id=1, phone="13800000001", nickname="用户一"),
            User(id=2, phone="13800000002", nickname="用户二"),
            Component(id=1, owner_user_id=1, warehouse_code="RES-00000001", name="器件一", lcsc_number="C1", quantity=10, average_unit_price=Decimal("9")),
            Component(id=2, owner_user_id=1, warehouse_code="RES-00000002", name="器件二", lcsc_number="C2", quantity=20),
            Component(id=3, owner_user_id=2, warehouse_code="RES-00000003", name="他人器件", lcsc_number="C1", quantity=99, average_unit_price=Decimal("7")),
        ]
    )
    db.commit()
    auth = AuthContext(1, "13800000001", "用户一")

    preview = asyncio.run(preview_price_statement(auth, upload(statement_bytes()), db))
    assert preview["summary"]["matched_count"] == 2
    assert preview["summary"]["unmatched_count"] == 0
    assert preview["summary"]["shipped_landed_total"] == 53.0
    assert {row["warehouse_code"] for row in preview["rows"]} == {"RES-00000001", "RES-00000002"}

    first = asyncio.run(commit_price_statement(auth, upload(statement_bytes()), db))["batch"]
    assert first["created_count"] == 4
    assert first["updated_count"] == 0
    assert db.get(Component, 1).quantity == 10
    assert db.get(Component, 2).quantity == 20
    assert db.get(Component, 1).average_unit_price == Decimal("1.133333")
    assert db.get(Component, 2).average_unit_price == Decimal("3.600000")
    assert db.get(Component, 3).average_unit_price == Decimal("7.000000")
    assert db.query(ComponentPriceEntry).filter(ComponentPriceEntry.owner_user_id == 1).count() == 4
    assert db.query(ComponentPriceEntry).filter(ComponentPriceEntry.order_status == "已取消").count() == 1

    duplicate = asyncio.run(commit_price_statement(auth, upload(statement_bytes(), "overlap.xlsx"), db))["batch"]
    assert duplicate["created_count"] == 0
    assert duplicate["updated_count"] == 0
    assert duplicate["unchanged_count"] == 4
    assert db.get(Component, 1).average_unit_price == Decimal("1.133333")

    revision = asyncio.run(commit_price_statement(auth, upload(statement_bytes("20.00"), "revision.xlsx"), db))["batch"]
    assert revision["updated_count"] == 2
    assert db.get(Component, 1).average_unit_price == Decimal("1.880000")
    assert db.get(Component, 2).average_unit_price == Decimal("3.480000")

    rolled_revision = rollback_price_statement_batch(revision["id"], auth, db)
    assert rolled_revision["status"] == "rolled_back"
    assert db.get(Component, 1).average_unit_price == Decimal("1.133333")
    assert db.get(Component, 2).average_unit_price == Decimal("3.600000")
    rollback_price_statement_batch(duplicate["id"], auth, db)
    rolled_first = rollback_price_statement_batch(first["id"], auth, db)
    assert rolled_first["status"] == "rolled_back"
    assert db.get(Component, 1).average_unit_price == Decimal("9.000000")
    assert db.get(Component, 2).average_unit_price is None
    assert db.get(Component, 1).quantity == 10
    assert db.query(ComponentPriceEntry).filter(ComponentPriceEntry.active == True).count() == 0
    db.close()
    engine.dispose()


def test_dashboard_values_full_and_available_inventory_without_zero_price_masking(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add(User(id=1, phone="13800000001", nickname="用户一"))
    db.add_all(
        [
            Component(id=1, owner_user_id=1, name="已计价", quantity=10, average_unit_price=Decimal("1.25")),
            Component(id=2, owner_user_id=1, name="未计价", quantity=50, average_unit_price=None),
        ]
    )
    db.add(Project(id=1, owner_user_id=1, name="项目", status="active"))
    db.add(ProjectBomItem(project_id=1, component_id=1, required_quantity=2, status="reserved"))
    db.commit()

    result = dashboard(AuthContext(1, "13800000001", "用户一"), db)
    assert result["inventory_value_total"] == Decimal("12.50")
    assert result["available_inventory_value_total"] == Decimal("10.00")
    assert result["priced_component_count"] == 1
    assert result["unpriced_component_count"] == 1
    assert result["currency"] == "CNY"
    db.close()
    engine.dispose()


def test_codex_price_update_is_validated_and_uses_stable_component_code(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'codex-price.db'}")
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add(User(id=1, phone="13800000001", nickname="用户一"))
    db.add(Component(id=1, owner_user_id=1, warehouse_code="MOD-00000001", name="模块", quantity=1))
    db.commit()

    action, _ = _prepare_action(
        db,
        1,
        {"action": "component.update", "target_id": "MOD-00000001", "payload": {"average_unit_price": 12.3456789}},
    )
    assert action["target_id"] == "MOD-00000001"
    assert action["payload"]["average_unit_price"] == Decimal("12.345679")
    _execute_action(db, 1, action)
    db.commit()
    assert db.get(Component, 1).average_unit_price == Decimal("12.345679")

    with pytest.raises(HTTPException, match="器件均价超出允许范围"):
        _prepare_action(
            db,
            1,
            {"action": "component.update", "target_id": "MOD-00000001", "payload": {"average_unit_price": -1}},
        )
    db.close()
    engine.dispose()
