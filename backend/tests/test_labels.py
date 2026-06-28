from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.labels import qr_svg_markup, render_component_label_sheet, render_custom_label_sheet, sanitize_svg_markup
from app.models import Category, Component
from app.auth import AuthContext
from app.main import (
    archive_custom_label,
    create_custom_label,
    export_component_label_sheet,
    export_components_from_ids,
    export_custom_label_sheet,
    list_custom_labels,
    qr_svg_markup as public_qr_svg_markup,
    update_custom_label,
)
from app.schemas import ComponentExportCustomLabel, ComponentExportRequest, CustomLabelExportRequest, CustomLabelTemplateCreate, CustomLabelTemplateUpdate


class BadString:
    def __str__(self):
        raise RuntimeError("bad string")


def test_label_sheet_uses_safe_category_names_for_supported_shapes():
    records = [
        {
            "warehouse_code": "RES-00000018",
            "normalized_spec": "1kΩ",
            "model": "0805W8F1001T5E",
            "category": Category(name="电阻", code_prefix="RES"),
        },
        {
            "warehouse_code": "CAP-00000001",
            "normalized_spec": "100nF",
            "category": {"name": "电容"},
        },
        {
            "warehouse_code": "MOD-00000001",
            "name": "模块",
            "category": "功能模块",
        },
        {
            "warehouse_code": "UNK-00000001",
            "name": "未分类物料",
            "category": None,
        },
    ]

    html = render_component_label_sheet(records, "https://example.com/component-warehouse/personal")

    assert "电阻" in html
    assert "电容" in html
    assert "功能模块" in html
    assert "元器件" in html
    assert "&lt;app.models" not in html
    assert "<app.models" not in html


def test_label_sheet_tolerates_bad_optional_fields_without_failing_batch():
    html = render_component_label_sheet(
        [
            {
                "warehouse_code": "RES-00000018",
                "normalized_spec": BadString(),
                "model": BadString(),
                "name": "异常字段物料",
                "category": BadString(),
            },
            {
                "warehouse_code": "CAP-00000001",
                "normalized_spec": "100nF",
                "category": {"name": "电容"},
            },
        ],
        "https://example.com/component-warehouse/personal",
    )

    assert "RES-00000018" in html
    assert "CAP-00000001" in html
    assert "未命名器件" in html
    assert "Traceback" not in html
    assert 'class="label-frame component-frame' in html
    assert "padding: 1.22mm 1.32mm" in html
    assert "grid-template-columns: 17mm minmax(0, 1fr)" in html
    assert "padding: 1.9mm 2.2mm 1.9mm 3.7mm" in html
    assert ".label-card:nth-child(4n+1) .component-frame" in html
    assert "padding-left: 5.9mm" in html
    assert "padding-right: .95mm" in html
    assert "padding: 2.35mm .1mm 2.05mm 0" in html
    assert "aspect-ratio: 1 / 1" in html
    assert "15.45mm" not in html
    assert "border: .18mm solid #cbd5e1" in html
    assert "border-radius: 2mm" in html
    assert 'class="label-logo"' in html
    assert 'class="label-print-meta"' in html
    assert "P:" in html
    assert "border: 0; border-radius: 0" not in html


def test_custom_label_sheet_uses_shared_logo_time_border_and_sanitizes_svg():
    dirty_svg = '<svg onload="alert(1)" viewBox="0 0 10 10"><script>alert(1)</script><rect width="10" height="10" fill="#111" onclick="bad()" /></svg>'
    safe_svg = sanitize_svg_markup(dirty_svg)

    assert "<script" not in safe_svg
    assert "onload" not in safe_svg
    assert "onclick" not in safe_svg
    assert "<rect" in safe_svg

    html = render_custom_label_sheet(
        {
            "elements": [
                {"type": "text", "text": "临时标记", "x": 20, "y": 36, "width": 60, "height": 20, "font_size": 16},
                {"type": "svg", "svg": dirty_svg, "x": 34, "y": 10, "width": 32, "height": 20},
            ]
        },
        copies=2,
    )

    assert "临时标记" in html
    assert 'class="label-logo"' in html
    assert 'class="label-print-meta"' in html
    assert "P:" in html
    assert "script" not in html.lower()
    assert "onclick" not in html.lower()


def test_qr_svg_markup_is_inline_safe_and_stably_sized():
    svg = qr_svg_markup("https://example.com/component-warehouse/personal/scan/RES-00000018")

    assert svg.lstrip().startswith("<svg")
    assert "<?xml" not in svg
    assert "viewBox=" in svg
    assert 'preserveAspectRatio="xMidYMid meet"' in svg
    assert 'shape-rendering="crispEdges"' in svg


def test_public_project_qr_svg_uses_same_stable_svg_contract():
    svg = public_qr_svg_markup("https://example.com/component-warehouse/personal/public/projects/PJ-00000005")

    assert svg.lstrip().startswith("<svg")
    assert "<?xml" not in svg
    assert "viewBox=" in svg
    assert 'preserveAspectRatio="xMidYMid meet"' in svg


def test_label_export_filters_by_imported_date(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'labels.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    resistor = Category(name="电阻")
    dev_board = Category(name="开发板")
    connector = Category(name="连接件")
    db.add_all([resistor, dev_board, connector])
    db.flush()
    db.add_all(
        [
            Component(name="当天导入", quantity=10, category_id=resistor.id, first_stocked_at=datetime(2026, 6, 25, 9, 30), created_at=datetime(2026, 6, 25, 9, 0)),
            Component(name="旧导入", quantity=10, first_stocked_at=datetime(2026, 6, 20, 9, 30), created_at=datetime(2026, 6, 20, 9, 0)),
            Component(name="旧数据兜底", quantity=1, first_stocked_at=None, created_at=datetime(2026, 6, 25, 10, 0)),
            Component(name="当天开发板", quantity=2, category_id=dev_board.id, first_stocked_at=datetime(2026, 6, 25, 11, 0), created_at=datetime(2026, 6, 25, 11, 0)),
            Component(name="当天连接件", quantity=3, category_id=connector.id, first_stocked_at=datetime(2026, 6, 25, 12, 0), created_at=datetime(2026, 6, 25, 12, 0)),
        ]
    )
    db.commit()

    rows = export_components_from_ids(db, [], None, True, imported_from="2026-06-25", imported_to="2026-06-25")
    assert [row.name for row in rows] == ["当天导入", "旧数据兜底", "当天开发板", "当天连接件"]

    rows = export_components_from_ids(
        db,
        [],
        None,
        True,
        imported_from="2026-06-25",
        imported_to="2026-06-25",
        excluded_categories=["开发板", "连接件"],
    )
    assert [row.name for row in rows] == ["当天导入", "旧数据兜底"]

    rows = export_components_from_ids(
        db,
        [],
        None,
        True,
        imported_from="2026-06-25",
        imported_to="2026-06-25",
        excluded_categories=["未分类"],
    )
    assert "旧数据兜底" not in [row.name for row in rows]

    with pytest.raises(HTTPException):
        export_components_from_ids(db, [], None, True, imported_from="2026-06-26", imported_to="2026-06-25")

    db.close()
    engine.dispose()


def test_custom_label_template_crud_and_export_keeps_personal_scope(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'custom-labels.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    auth = AuthContext(user_id=11, phone="13800000011", nickname="标签用户")

    created = create_custom_label(
        CustomLabelTemplateCreate(
            name="纸盒分类",
            content={
                "elements": [
                    {"type": "text", "text": "电阻盒", "x": 20, "y": 35, "width": 60, "height": 20, "font_size": 16}
                ]
            },
        ),
        auth,
        db,
    )
    assert created["name"] == "纸盒分类"
    assert created["status"] == "active"
    assert created["assets"] == []

    updated = update_custom_label(
        created["id"],
        CustomLabelTemplateUpdate(name="纸盒分类 A", content={"elements": [{"type": "text", "text": "RES"}]}),
        auth,
        db,
    )
    assert updated["name"] == "纸盒分类 A"
    assert list_custom_labels(auth, db)[0]["id"] == created["id"]

    response = export_custom_label_sheet(
        CustomLabelExportRequest(template_id=created["id"], start_slot=2, copies=1),
        auth,
        db,
    )
    html = response.body.decode("utf-8")
    assert "RES" in html
    assert 'class="label-logo"' in html
    assert 'class="label-print-meta"' in html

    assert archive_custom_label(created["id"], auth, db) == {"archived": True}
    assert list_custom_labels(auth, db) == []

    db.close()
    engine.dispose()


def test_component_label_export_appends_custom_labels_after_components(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'component-with-custom-labels.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    auth = AuthContext(user_id=11, phone="13800000011", nickname="标签用户")
    category = Category(name="电阻")
    db.add(category)
    db.flush()
    db.add(Component(name="10k 电阻", normalized_spec="10kΩ", quantity=10, warehouse_code="RES-00000001", category_id=category.id, owner_user_id=11))
    db.commit()
    custom = create_custom_label(
        CustomLabelTemplateCreate(name="纸盒", content={"elements": [{"type": "text", "text": "纸盒分类"}]}),
        auth,
        db,
    )

    response = export_component_label_sheet(
        ComponentExportRequest(
            all=True,
            custom_labels=[ComponentExportCustomLabel(template_id=custom["id"], copies=2)],
        ),
        None,
        auth,
        db,
    )
    html = response.body.decode("utf-8")
    assert html.index("RES-00000001") < html.index("纸盒分类")
    assert html.count("纸盒分类") == 2

    calibration = export_component_label_sheet(
        ComponentExportRequest(all=True, calibration=True, custom_labels=[ComponentExportCustomLabel(template_id=custom["id"], copies=2)]),
        None,
        auth,
        db,
    ).body.decode("utf-8")
    assert "校准格 40" in calibration
    assert "纸盒分类" not in calibration

    db.close()
    engine.dispose()
