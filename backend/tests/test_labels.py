from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.labels import (
    _draw_pdf_text,
    _server_font,
    _text_size,
    label_title,
    qr_svg_markup,
    render_component_label_sheet,
    render_custom_label_sheet,
    sanitize_svg_markup,
)
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
            "category": {"name": "电容", "color": "#DCFCE7"},
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
    assert 'style="background:#DBEAFE;border-color:#DBEAFE;color:#111827;"' in html
    assert 'style="background:#DCFCE7;border-color:#DCFCE7;color:#111827;"' in html
    assert "元器件" in html
    assert "/hardware/fonts/dingtalk/L1_" in html
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
    assert "padding: 2.15mm 2.15mm" in html
    assert ".label-card:nth-child(4n+1) { padding-left: 5.25mm; }" in html
    assert ".label-card:nth-child(4n) { padding-right: 4.8mm; }" in html
    assert ".label-card:nth-child(-n+4) { padding-top: 3.85mm; }" in html
    assert ".label-card:nth-last-child(-n+4) { padding-bottom: 3.4mm; }" in html
    assert ".label-card:nth-child(n+37) { padding-bottom: 4.0mm; }" in html
    assert ".label-card:nth-child(4n+2) { transform: translateX(-0.40mm); }" in html
    assert ".label-card:nth-child(4n+3) { transform: translateX(-0.80mm); }" in html
    assert ".label-card:nth-child(4n) { transform: translateX(-1.20mm); }" in html
    assert "grid-template-columns: 13.4mm minmax(0, 1fr)" in html
    assert "padding: 2.15mm 1.55mm 1.95mm 2.05mm" in html
    assert ".label-card:nth-child(4n+1) .component-frame" in html
    assert "padding-left: 2.6mm" in html
    assert "padding-right: 1.25mm" in html
    assert "padding: .65mm .15mm .6mm 0" in html
    assert 'class="label-copy-header"' in html
    assert ".label-copy-header { min-width: 0; display: grid; gap: .34mm; }" in html
    assert ".label-code { display: block; min-width: 0; width: 100%; overflow: visible;" in html
    assert "text-overflow: clip" in html
    assert 'class="label-code dingtalk-print-text"' in html
    assert 'aria-label="CAP-00000001"' in html
    assert ".dingtalk-print-text" in html
    assert '<b class="label-title">100nF</b>' in html
    assert "label-title-svg" not in html
    assert "aspect-ratio: 1 / 1" in html
    assert "15.45mm" not in html
    assert "border: .18mm solid #cbd5e1" in html
    assert "border-radius: 2mm" in html
    assert 'class="label-logo" src="/component-warehouse/api/assets/brand-logo-label.png?v=20260702b"' in html
    assert "RASTER_SCALE = 2.15" in html
    assert "window.__cwRasterizeLabels" in html
    assert 'className = \'raster-sheet\'' in html
    assert "label-logo-text" not in html
    assert 'class="label-print-meta"' in html
    assert "P:" in html
    assert "border: 0; border-radius: 0" not in html


def test_dingtalk_print_fields_render_as_text_not_inline_glyph_paths():
    html = render_component_label_sheet(
        [
            {
                "warehouse_code": "RES-000000100",
                "normalized_spec": "10kΩ",
                "category": {"name": "电阻"},
            }
        ],
        "https://example.com/component-warehouse/personal",
    )

    assert 'class="label-code dingtalk-print-text"' in html
    assert 'aria-label="RES-000000100"' in html
    assert ">RES-000000100</strong>" in html
    assert "label-code-svg" not in html
    assert "<path " not in html


def test_zero_ohm_resistor_title_is_normalized_for_print():
    assert label_title({"warehouse_code": "RES-00000003", "normalized_spec": "0", "category": {"name": "电阻"}}) == "0Ω"
    assert label_title({"warehouse_code": "RES-00000003", "normalized_spec": "０", "category": {"name": "电阻"}}) == "0Ω"
    assert label_title({"warehouse_code": "RES-00000003", "normalized_spec": "0R", "category": {"name": "电阻"}}) == "0Ω"
    assert label_title({"warehouse_code": "RES-00000003", "normalized_spec": "0 ohm", "category": {"name": "电阻"}}) == "0Ω"
    assert label_title({"warehouse_code": "CAP-00000003", "normalized_spec": "0", "category": {"name": "电容"}}) == "0"


def test_pdf_title_renderer_keeps_ohm_symbol_visible_with_font_fallback():
    pil_image = pytest.importorskip("PIL.Image")
    pil_image_draw = pytest.importorskip("PIL.ImageDraw")

    image = pil_image.new("RGB", (240, 90), "white")
    draw = pil_image_draw.Draw(image)
    font = _server_font(36, bold=True)

    assert _text_size(draw, "0Ω", font)[0] > _text_size(draw, "0", font)[0]
    _draw_pdf_text(draw, (8, 8), "0Ω", font=font, fill="#000000")

    dark_pixels = 0
    for x in range(8, 120):
        for y in range(8, 70):
            if image.getpixel((x, y)) != (255, 255, 255):
                dark_pixels += 1
    assert dark_pixels > 80


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
                {"type": "text", "text": "临时标记", "x": 20, "y": 36, "width": 60, "height": 20, "font_size": 16, "align": "left"},
                {"type": "svg", "svg": dirty_svg, "x": 34, "y": 10, "width": 32, "height": 20},
            ]
        },
        copies=2,
    )

    assert "临时标记" in html
    assert 'class="label-logo" src="/component-warehouse/api/assets/brand-logo-label.png?v=20260702b"' in html
    assert "label-logo-text" not in html
    assert "text-align:left" in html
    assert "justify-content:flex-start" in html
    assert 'class="label-print-meta"' in html
    assert "P:" in html
    assert "<script>alert" not in html.lower()
    assert "onclick" not in html.lower()
    assert "window.__cwRasterizeLabels" in html

    no_logo = render_custom_label_sheet(
        {
            "show_logo": False,
            "elements": [
                {"type": "text", "text": "无品牌标签", "x_mm": 4, "y_mm": 8, "width_mm": 36, "height_mm": 8, "font_size": 14, "font_family": "misans", "align": "right"},
                {"type": "field", "field": "package", "prefix": "封装 ", "x_mm": 4, "y_mm": 18, "width_mm": 36, "height_mm": 4, "font_size": 9, "font_family": "dingtalk", "align": "center"},
            ],
        },
    )
    assert "无品牌标签" in no_logo
    assert "封装 0805" in no_logo
    assert 'class="label-logo"' not in no_logo
    assert "custom-label-card" in no_logo
    assert ".custom-label-card { padding: 2.15mm 2.15mm; }" in no_logo
    assert "custom-frame without-logo" in no_logo
    assert ".custom-canvas { position: absolute; inset: 0; width: 100%; height: 100%; overflow: hidden; padding: 0; }" in no_logo
    assert "left:4.000mm;top:8.000mm;width:36.000mm;height:8.000mm;" in no_logo
    assert "font-family:&quot;" not in no_logo
    assert 'font-family:"MiSans", "Microsoft YaHei", sans-serif' in no_logo
    assert 'font-family:"DingTalk JinBuTi", "钉钉进步体", "Microsoft YaHei", sans-serif' in no_logo
    assert "font-size:2.381mm" in no_logo
    assert "font-weight:800" in no_logo
    assert "/hardware/fonts/misans/MiSans." in no_logo
    assert "/hardware/fonts/dingtalk/L1_" in no_logo
    assert no_logo.index("@font-face") < no_logo.index("@page")
    assert "data:font/woff2;base64" not in no_logo
    assert "text-align:right" in no_logo
    assert "justify-content:flex-end" in no_logo


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
                    {"type": "text", "text": "电阻盒", "x": 20, "y": 35, "width": 60, "height": 20, "font_size": 16},
                    {"type": "field", "field": "print_date", "prefix": "打印 "},
                    {"type": "field", "field": "package", "prefix": "封装 ", "font_family": "deyi"},
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
        CustomLabelTemplateUpdate(
            name="纸盒分类 A",
            content={
                "elements": [
                    {"type": "text", "text": "RES"},
                    {"type": "field", "field": "print_date", "prefix": "打印 "},
                    {"type": "field", "field": "package", "prefix": "封装 ", "font_family": "deyi"},
                ]
            },
        ),
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
    assert "print_date" not in html
    assert "封装" in html
    assert 'class="label-logo" src="/component-warehouse/api/assets/brand-logo-label.png?v=20260702b"' in html
    assert "label-logo-text" not in html
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
    category = Category(name="电阻", color="#FEE2E2")
    db.add(category)
    db.flush()
    capacitor = Category(name="电容", color="#DCFCE7")
    db.add(capacitor)
    db.flush()
    db.add(Component(name="10k 电阻", normalized_spec="10kΩ", package="0805", quantity=10, warehouse_code="RES-00000001", category_id=category.id, owner_user_id=11))
    db.add(Component(name="1k 电阻", normalized_spec="1kΩ", package="1206", quantity=10, warehouse_code="RES-00000002", category_id=category.id, owner_user_id=11))
    db.add(Component(name="100nF 电容", normalized_spec="100nF", package="0603", quantity=20, warehouse_code="CAP-00000001", category_id=capacitor.id, owner_user_id=11))
    board_category = Category(name="开发板", color="#E5E7EB")
    db.add(board_category)
    db.flush()
    db.add(Component(name="ESP32 开发板", model="ESP32-S3-DevKitC-1", normalized_spec="ESP32-S3", package="", quantity=2, warehouse_code="DEV-00000001", category_id=board_category.id, owner_user_id=11))
    db.commit()
    custom = create_custom_label(
        CustomLabelTemplateCreate(
            name="纸盒",
            content={
                "kind": "standard_category_group",
                "active_style_id": "res",
                "styles": [
                    {"id": "res", "name": "电阻盒", "category_name": "电阻", "elements": [{"role": "category_title", "type": "text", "text": "电阻", "font_family": "dingtalk"}]},
                    {"id": "cap", "name": "电容盒", "category_name": "电容", "elements": [{"role": "category_title", "type": "text", "text": "电容", "font_family": "dingtalk"}]},
                    {"id": "ind", "name": "电感盒", "category_name": "电感", "elements": [{"role": "category_title", "type": "text", "text": "电感", "font_family": "dingtalk"}]},
                    {"id": "dev", "name": "开发板盒", "category_name": "开发板", "elements": [{"role": "category_title", "type": "text", "text": "开发板", "font_family": "dingtalk"}]},
                ],
                "elements": [{"type": "text", "text": "电阻"}],
            },
        ),
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
    assert html.index("RES-00000001") < html.index('aria-label="电阻"')
    assert html.index('aria-label="电阻"') < html.index('aria-label="电容"')
    assert html.count('aria-label="电阻"') == 2
    assert html.count('aria-label="电容"') == 2
    assert html.count('aria-label="开发板"') == 2
    assert 'aria-label="电感"' not in html
    assert "standard-category-title dingtalk-print-text" in html
    assert "standard-category-title-svg" not in html
    assert "<path " not in html
    assert ">电阻</strong>" in html
    assert html.count("封装 0805 / 1206") == 2
    assert html.count("封装 0603") == 2
    assert html.count("型号 ESP32-S3-DevKitC-1") == 2
    assert "standard-category-frame" in html
    assert "standard-category-kicker" in html
    assert "standard-category-title-band" in html
    assert "standard-category-meta" not in html
    assert 'font-family: "DingTalk JinBuTi", "钉钉进步体", "Microsoft YaHei", sans-serif; font-synthesis: none;' in html
    assert "/hardware/fonts/dingtalk/L1_" in html
    assert html.index("@font-face") < html.index("@page")
    assert 'style="background:#FEE2E2;border-color:#FEE2E2;color:#111827;"' in html

    calibration = export_component_label_sheet(
        ComponentExportRequest(all=True, calibration=True, custom_labels=[ComponentExportCustomLabel(template_id=custom["id"], copies=2)]),
        None,
        auth,
        db,
    ).body.decode("utf-8")
    assert "校准格 40" in calibration
    assert 'aria-label="电阻"' not in calibration
    assert "封装 0805 / 1206" not in calibration

    legacy = create_custom_label(
        CustomLabelTemplateCreate(
            name="旧版分类盒子",
            content={
                "active_style_id": "res-legacy",
                "styles": [
                    {
                        "id": "res-legacy",
                        "name": "电阻 分类标签",
                        "elements": [
                            {"type": "text", "text": "电阻", "font_family": "dingtalk"},
                            {"type": "text", "text": "料盒 / 分类 / 常用"},
                            {"type": "field", "field": "package", "prefix": "封装 "},
                        ],
                    },
                    {
                        "id": "cap-legacy",
                        "name": "电容 分类标签",
                        "elements": [
                            {"type": "text", "text": "电容", "font_family": "dingtalk"},
                            {"type": "text", "text": "料盒 / 分类 / 常用"},
                            {"type": "field", "field": "package", "prefix": "封装 "},
                        ],
                    },
                ],
                "elements": [{"type": "text", "text": "电阻"}],
            },
        ),
        auth,
        db,
    )
    legacy_html = export_component_label_sheet(
        ComponentExportRequest(
            all=True,
            custom_labels=[ComponentExportCustomLabel(template_id=legacy["id"], copies=1)],
        ),
        None,
        auth,
        db,
    ).body.decode("utf-8")
    assert legacy_html.count('class="label-frame standard-category-frame"') == 2
    assert "封装 0805 / 1206" in legacy_html
    assert "封装 0603" in legacy_html

    db.close()
    engine.dispose()
