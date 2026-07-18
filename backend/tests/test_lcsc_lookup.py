import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main as main_app
from app.auth import AuthContext
from app.database import Base
from app.models import Category, Component, User
from app.schemas import ComponentCreate, LcscPreviewRequest, LcscPreviewResponse
from app.services.lcsc_lookup import (
    LcscLookupError,
    LcscProductNotFound,
    extract_product_json_ld,
    fetch_lcsc_product,
    normalize_lcsc_number,
    parse_lcsc_copy_text,
)


SAMPLE_PRODUCT = {
    "@context": "http://schema.org",
    "@type": "Product",
    "name": "TI LP5907MFX-3.3/NOPB",
    "sku": "C80670",
    "mpn": "LP5907MFX-3.3/NOPB",
    "brand": {"@type": "Brand", "name": "TI"},
    "description": "Linear Voltage Regulator IC Positive Fixed 1 Output 250mA SOT-23-5",
    "category": "Power Management (PMIC)/Voltage Regulators - Linear, Low Drop Out (LDO) Regulators",
    "offers": {"url": "https://www.lcsc.com/product-detail/C80670.html"},
    "additionalProperty": [
        {"@type": "PropertyValue", "name": "Package", "value": "SOT-23-5"},
        {"@type": "PropertyValue", "name": "Output Voltage", "value": "3.3V"},
        {"@type": "PropertyValue", "name": "Operating Voltage", "value": "5.5V"},
        {"@type": "PropertyValue", "name": "Output Current", "value": "250mA"},
    ],
    "subjectOf": {
        "@type": "DigitalDocument",
        "name": "Datasheet",
        "url": "https://datasheet.lcsc.com/datasheet/pdf/example.pdf?productCode=C80670",
    },
}


@pytest.fixture()
def preview_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lcsc-preview.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(User(id=7, phone="13800000007", nickname="测试用户"))
    db.add_all([
        Category(name="芯片", code_prefix="ICS"),
        Category(name="电源", code_prefix="PWR"),
        Category(name="其他", code_prefix="OTH"),
    ])
    db.commit()
    yield db
    db.close()
    engine.dispose()


def auth_context():
    return AuthContext(user_id=7, phone="13800000007", nickname="测试用户")


def sample_text():
    return "名称：3.3V 250mA 5.5V\n型号：LP5907MFX-3.3/NOPB\n品牌：TI(德州仪器)\n封装：SOT-23-5\n编号：C80670“"


def test_parse_copy_text_and_normalize_number():
    parsed = parse_lcsc_copy_text(sample_text())
    assert parsed == {
        "copied_name": "3.3V 250mA 5.5V",
        "model": "LP5907MFX-3.3/NOPB",
        "manufacturer": "TI(德州仪器)",
        "package": "SOT-23-5",
        "lcsc_number": "C80670",
    }
    assert normalize_lcsc_number("编号：c 80670。") == "C80670"


def test_extract_product_json_ld_requires_exact_sku():
    html = f'<script type="application/ld+json">{json.dumps(SAMPLE_PRODUCT)}</script>'
    assert extract_product_json_ld(html, "c80670")["mpn"] == "LP5907MFX-3.3/NOPB"
    with pytest.raises(LcscLookupError, match="编号不一致"):
        extract_product_json_ld(html, "C99999")
    with pytest.raises(LcscProductNotFound):
        extract_product_json_ld("<html></html>", "C80670")


def test_fetch_lcsc_product_handles_404_and_timeout():
    not_found = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404, request=request)))
    with pytest.raises(LcscProductNotFound):
        fetch_lcsc_product("C80670", not_found)
    not_found.close()

    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    timed_out = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(LcscLookupError, match="查询失败"):
        fetch_lcsc_product("C80670", timed_out)
    timed_out.close()


def test_preview_uses_official_fields_and_returns_existing(preview_db, monkeypatch):
    existing = Component(
        owner_user_id=7,
        name="已有 LP5907",
        model="LP5907MFX-3.3/NOPB",
        lcsc_number="c80670",
        quantity=3,
    )
    preview_db.add(existing)
    preview_db.commit()
    monkeypatch.setattr(main_app, "fetch_lcsc_product", lambda code: SAMPLE_PRODUCT)
    monkeypatch.setattr(
        main_app,
        "organize_lcsc_draft",
        lambda draft, categories: {
            "name": "LP5907MFX-3.3/NOPB 3.3V 250mA LDO",
            "category": "电源",
            "tags": ["低噪声", "低静态电流"],
            "confidence": "high",
        },
    )

    result = main_app.preview_lcsc_component(LcscPreviewRequest(raw_text=sample_text()), auth_context(), preview_db)
    LcscPreviewResponse.model_validate(result).model_dump_json()
    draft = result["draft"]
    assert result["status"] == "official"
    assert result["existing_component"]["id"] == existing.id
    assert draft["name"] == "LP5907MFX-3.3/NOPB 3.3V 250mA LDO"
    assert draft["manufacturer"] == "TI"
    assert draft["package"] == "SOT-23-5"
    assert draft["category_name"] == "电源"
    assert draft["category_id"]
    assert "Output Current 250mA" in draft["parameters"]
    assert draft["datasheet_url"].endswith("example.pdf?productCode=C80670")
    assert draft["buy_url"] == "https://www.lcsc.com/product-detail/C80670.html"
    assert draft["quantity"] == 0


def test_preview_ai_fallback_requires_exact_lcsc_source(preview_db, monkeypatch):
    monkeypatch.setattr(main_app, "fetch_lcsc_product", lambda code: (_ for _ in ()).throw(LcscLookupError("offline")))
    monkeypatch.setattr(
        main_app,
        "lookup_lcsc_fallback",
        lambda parsed, categories: {
            "lcsc_number": "C80670",
            "exact_lcsc_match": True,
            "model": "LP5907MFX-3.3/NOPB",
            "manufacturer": "TI",
            "package": "SOT-23-5",
            "parameters": [{"name": "Output Current", "value": "250mA"}],
            "datasheet_url": "https://www.ti.com/lit/ds/lp5907.pdf",
            "product_url": "https://www.lcsc.com/product-detail/C80670.html",
            "name": "LP5907MFX-3.3/NOPB 3.3V 250mA LDO",
            "category": "电源",
            "tags": ["低噪声"],
            "sources": [{"title": "C80670", "url": "https://www.lcsc.com/product-detail/C80670.html"}],
        },
    )
    result = main_app.preview_lcsc_component(LcscPreviewRequest(raw_text=sample_text()), auth_context(), preview_db)
    assert result["status"] == "ai_fallback"
    assert result["draft"]["manufacturer"] == "TI(德州仪器)"
    assert result["draft"]["parameters"] == "Output Current 250mA"
    assert any("不等同于直接读取" in warning for warning in result["warnings"])


def test_preview_double_failure_keeps_parsed_draft(preview_db, monkeypatch):
    monkeypatch.setattr(main_app, "fetch_lcsc_product", lambda code: (_ for _ in ()).throw(LcscLookupError("offline")))
    monkeypatch.setattr(main_app, "lookup_lcsc_fallback", lambda parsed, categories: (_ for _ in ()).throw(RuntimeError("ai down")))
    result = main_app.preview_lcsc_component(LcscPreviewRequest(raw_text=sample_text()), auth_context(), preview_db)
    assert result["status"] == "parsed_only"
    assert result["draft"]["model"] == "LP5907MFX-3.3/NOPB"
    assert result["draft"]["manufacturer"] == "TI(德州仪器)"
    assert result["draft"]["buy_url"].endswith("/C80670.html")
    assert any("当前仅保留" in warning for warning in result["warnings"])


def test_personal_create_normalizes_duplicate_and_returns_complete_fields(preview_db):
    category = preview_db.query(Category).filter_by(name="电源").one()
    payload = ComponentCreate(
        name="LP5907MFX-3.3/NOPB 3.3V 250mA LDO",
        model="LP5907MFX-3.3/NOPB",
        manufacturer="TI",
        description="250mA low-noise LDO",
        category_id=category.id,
        parameters="Output Voltage 3.3V；Output Current 250mA",
        package="SOT-23-5",
        lcsc_number="c80670",
        source="立创",
        datasheet_url="https://datasheet.lcsc.com/datasheet/pdf/example.pdf?productCode=C80670",
        buy_url="https://www.lcsc.com/product-detail/C80670.html",
    )
    result = main_app.create_component(payload, auth_context(), preview_db)
    assert result["lcsc_number"] == "C80670"
    assert result["manufacturer"] == "TI"
    assert result["description"] == "250mA low-noise LDO"
    assert result["buy_url"].endswith("/C80670.html")
    assert result["datasheet_url"].endswith("productCode=C80670")

    with pytest.raises(HTTPException) as error:
        main_app.create_component(payload, auth_context(), preview_db)
    assert error.value.status_code == 409
    assert "已存在" in str(error.value.detail)
