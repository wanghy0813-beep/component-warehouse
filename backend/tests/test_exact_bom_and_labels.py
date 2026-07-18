from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.labels import render_component_label_sheet
from app.models import Category, Component, SupplierPart, User
from app.services.bom_match import BomRow, inspect_bom_fields, match_bom_rows, parse_bom_excel


def test_bom_matching_is_exact_only_and_passive_composite_must_be_unique(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bom.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    user = User(id=1, phone="13800000001", nickname="BOM 用户")
    resistor = Category(name="电阻", color="#eef2ff")
    db.add_all([user, resistor])
    db.flush()
    exact = Component(
        owner_user_id=1,
        name="精密电阻",
        model="RC0805FR-0710KL",
        normalized_spec="10kΩ",
        parameters="10kΩ 1%",
        package="0805",
        quantity=10,
        category_id=resistor.id,
    )
    fuzzy = Component(
        owner_user_id=1,
        name="相似型号但不是同一料",
        model="RC0805FR-0710KX",
        normalized_spec="10kΩ",
        parameters="10kΩ 1%",
        package="0805",
        quantity=20,
        category_id=resistor.id,
    )
    db.add_all([exact, fuzzy])
    db.flush()
    db.add(
        SupplierPart(
            id="supplier-1",
            scope_type="personal",
            owner_user_id=1,
            component_id=exact.id,
            supplier="LCSC",
            supplier_part_number="C123456",
            status="active",
        )
    )
    db.add(
        SupplierPart(
            id="supplier-foreign",
            scope_type="team",
            team_library_id=None,
            component_id=fuzzy.id,
            supplier="LCSC",
            supplier_part_number="C123456",
            status="active",
        )
    )
    db.add(
        SupplierPart(
            id="supplier-2",
            scope_type="personal",
            owner_user_id=1,
            component_id=fuzzy.id,
            supplier="Mouser",
            supplier_part_number="C123456",
            status="active",
        )
    )
    db.commit()

    supplier_row = BomRow(
        source_row=2,
        data={
            "required_quantity": 2,
            "supplier_part": "C123456",
            "supplier": "LCSC",
            "manufacturer_part": "",
            "value": "",
            "comment": "",
            "footprint": "0805",
            "designator": "R1,R2",
        },
    )
    result = match_bom_rows(
        db,
        [supplier_row],
        component_ids=[exact.id, fuzzy.id],
        supplier_scope_type="personal",
        supplier_owner_user_id=1,
    )[0]
    assert result["selected_component_id"] == exact.id
    assert result["status"] == "exact_lcsc"

    normalized_mpn_row = BomRow(
        source_row=3,
        data={
            "required_quantity": 1,
            "supplier_part": "",
            "manufacturer": "Texas Instruments",
            "manufacturer_part": "OPA-2333",
            "value": "",
            "comment": "",
            "footprint": "VSSOP-8",
            "designator": "U1",
        },
    )
    opamp = Component(
        owner_user_id=1,
        name="精密运放",
        manufacturer="Texas Instruments",
        model="OPA2333",
        package="VSSOP-8",
        quantity=4,
    )
    db.add(opamp)
    db.commit()
    result = match_bom_rows(db, [normalized_mpn_row], component_ids=[opamp.id])[0]
    assert result["selected_component_id"] == opamp.id
    assert result["status"] == "exact"

    fuzzy_row = BomRow(
        source_row=4,
        data={
            "required_quantity": 1,
            "supplier_part": "",
            "manufacturer_part": "RC0805FR-0710KZ",
            "value": "",
            "comment": "",
            "footprint": "0805",
            "designator": "R3",
        },
    )
    result = match_bom_rows(db, [fuzzy_row], component_ids=[exact.id, fuzzy.id])[0]
    assert result["selected_component_id"] is None

    passive_row = BomRow(
        source_row=5,
        data={
            "required_quantity": 1,
            "supplier_part": "",
            "manufacturer_part": "",
            "value": "10kΩ",
            "comment": "电阻",
            "footprint": "0805",
            "category": "电阻",
            "primary_category": "电阻",
            "designator": "R4",
        },
    )
    result = match_bom_rows(db, [passive_row], component_ids=[exact.id, fuzzy.id])[0]
    assert result["selected_component_id"] is None
    assert result["status"] == "review"

    result = match_bom_rows(db, [passive_row], component_ids=[exact.id])[0]
    assert result["selected_component_id"] == exact.id
    assert result["status"] == "exact"
    db.close()
    engine.dispose()


def test_bom_matching_filters_same_package_function_mismatches_and_net_labels(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'candidate-safety.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    user = User(id=1, phone="13800000001", nickname="候选安全测试")
    categories = {
        name: Category(name=name, color="#eef2ff")
        for name in ["电阻", "电容", "二极管", "传感器", "连接器"]
    }
    db.add(user)
    db.add_all(categories.values())
    db.flush()
    resistor = Component(
        owner_user_id=1,
        name="10kΩ 0805 电阻",
        model="R0805-10K",
        normalized_spec="10kΩ",
        parameters="10kΩ",
        package="0805",
        quantity=10,
        category_id=categories["电阻"].id,
    )
    capacitor = Component(
        owner_user_id=1,
        name="100nF 0805 电容",
        model="C0805-100N",
        normalized_spec="100nF",
        parameters="100nF",
        package="0805",
        quantity=10,
        category_id=categories["电容"].id,
    )
    switching_diode = Component(
        owner_user_id=1,
        name="1N4148W 开关二极管",
        model="1N4148W",
        parameters="高速开关二极管 100V",
        package="SOD-123",
        quantity=10,
        category_id=categories["二极管"].id,
    )
    sensor = Component(
        owner_user_id=1,
        name="SHT30 温湿度传感器模块",
        model="SHT30",
        parameters="I2C 温湿度传感器",
        package="模块",
        quantity=2,
        category_id=categories["传感器"].id,
    )
    connector = Component(
        owner_user_id=1,
        name="2.54mm 1x10P 排针",
        model="1x10P",
        parameters="单排 10P 2.54mm",
        package="直插",
        tags="连接器,排针,2.54mm,10P",
        quantity=5,
        category_id=categories["连接器"].id,
    )
    db.add_all([resistor, capacitor, switching_diode, sensor, connector])
    db.commit()

    rows = [
        BomRow(1, {"required_quantity": 1, "manufacturer_part": "BZT52C12", "comment": "12V 稳压二极管", "footprint": "SOD-123", "designator": "D1"}),
        BomRow(2, {"required_quantity": 1, "manufacturer_part": "DRV8876", "comment": "电荷泵电容", "footprint": "0805", "designator": "C1"}),
        BomRow(3, {"required_quantity": 1, "value": "RFREQ", "comment": "IC pin label", "footprint": "0805", "designator": "RFREQ"}),
        BomRow(4, {"required_quantity": 1, "value": "BEC", "comment": "power rail", "footprint": "模块", "designator": "BEC"}),
        BomRow(5, {"required_quantity": 1, "value": "1x10P 排针", "comment": "2.54mm 排针 1x10P", "footprint": "直插", "category": "连接器", "designator": "J1"}),
    ]
    results = match_bom_rows(
        db,
        rows,
        component_ids=[resistor.id, capacitor.id, switching_diode.id, sensor.id, connector.id],
    )
    assert [row["status"] for row in results[:4]] == ["missing", "missing", "missing", "missing"]
    assert all(not row["matches"] for row in results[:4])
    assert results[4]["status"] == "review"
    assert results[4]["selected_component_id"] is None
    assert [item["component"]["id"] for item in results[4]["matches"]] == [connector.id]

    db.close()
    engine.dispose()


def test_label_html_is_exact_a4_40_grid_with_calibration_and_offsets():
    html = render_component_label_sheet(
        [
            {
                "warehouse_code": "RES-00000001",
                "name": "10k 电阻",
                "normalized_spec": "10kΩ",
                "package": "0805",
                "category": {"name": "电阻"},
            }
        ],
        "https://example.test/component-warehouse/personal",
        start_slot=3,
        copies=2,
        offset_x_mm=0.4,
        offset_y_mm=-0.3,
    )
    assert "@page { size: A4 portrait; margin: 0; }" in html
    assert "grid-template-columns: repeat(4, 52.5mm)" in html
    assert "grid-template-rows: repeat(10, 29.7mm)" in html
    assert "translate(0.40mm, -0.30mm)" in html
    assert html.count("placeholder") >= 2
    assert html.count(">RES-00000001</strong>") == 2

    calibration = render_component_label_sheet([], "https://example.test", calibration=True)
    assert "校准格 1" in calibration
    assert "校准格 40" in calibration


def test_ad_bom_csv_import_supports_utf8_headers():
    rows = parse_bom_excel(
        "Designator,Quantity,Value,Footprint,Manufacturer,MPN,LCSC\nR1 R2,2,10k,0805,Yageo,RC0805FR-0710KL,C123456\n".encode("utf-8"),
        "ad-bom.csv",
    )
    assert len(rows) == 1
    assert rows[0].data["required_quantity"] == 2
    assert rows[0].data["manufacturer_part"] == "RC0805FR-0710KL"
    assert rows[0].data["supplier_part"] == "C123456"

    custom = "Ref,Count,PartNo,PCB Land\nC1,3,CL10B104KB8NNNC,C0805\n".encode("utf-8")
    inspection = inspect_bom_fields(custom, "custom.csv")
    assert inspection["headers"] == ["Ref", "Count", "PartNo", "PCB Land"]
    mapped = parse_bom_excel(
        custom,
        "custom.csv",
        {
            "__header_row": 1,
            "designator": "Ref",
            "quantity": "Count",
            "manufacturer_part": "PartNo",
            "footprint": "PCB Land",
        },
    )
    assert mapped[0].data["designator"] == "C1"
    assert mapped[0].data["required_quantity"] == 3
    assert mapped[0].data["manufacturer_part"] == "CL10B104KB8NNNC"
