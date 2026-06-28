from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Category, Component
from app.services.external_order_import import _parsed_ai_external_row
from app.services.category_governance import (
    ai_category_allowed,
    canonical_order_category_name,
    category_from_order_text,
)


def test_order_category_is_exact_and_takes_priority_over_ai(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'categories.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    resistor = Category(name="电阻")
    capacitor = Category(name="电容")
    db.add_all([resistor, capacitor])
    db.flush()
    assert category_from_order_text(db, "贴片电阻").name == "电阻"
    assert category_from_order_text(db, "电容").name == "电容"
    assert category_from_order_text(db, "电阻电容混合包") is None

    component = Component(name="10k", source="立创商城 Excel", category=resistor)
    assert ai_category_allowed(component, {"category": "电容", "confidence": "high"}) is False
    component.category = None
    assert ai_category_allowed(component, {"category": "电容", "confidence": "medium"}) is False
    assert ai_category_allowed(component, {"category": "电容", "confidence": "high"}) is True
    assert ai_category_allowed(component, {"category": "电容", "confidence": "high", "requires_confirmation": True}) is False
    db.close()
    engine.dispose()


def test_external_order_aliases_are_exact_and_canonical():
    names = {"电阻", "连接件", "其他"}
    assert canonical_order_category_name("电阻器", names) == "电阻"
    assert canonical_order_category_name("连接器", names) == "连接件"
    assert canonical_order_category_name("连接器插座", names) is None


def test_external_order_ai_category_requires_unambiguous_high_confidence():
    categories = {"电阻", "电容"}
    base = {
        "source_row": 2,
        "normalized_name": "10k 电阻",
        "category": "电阻",
        "confidence": "high",
    }
    assert _parsed_ai_external_row(base, "order.xlsx", categories).data["category_name"] == "电阻"
    needs_review = {**base, "requires_confirmation": True}
    assert _parsed_ai_external_row(needs_review, "order.xlsx", categories).data["category_name"] is None
    order_wins = {**needs_review, "order_category": "电容器"}
    assert _parsed_ai_external_row(order_wins, "order.xlsx", categories).data["category_name"] == "电容"
