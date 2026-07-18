from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import component_keyword_filters, component_out
from app.models import Category, Component
from app.services.component_search import find_unit_conversion_match, keyword_unit_variants


def test_capacitance_variants_include_equivalent_engineering_units():
    variants = keyword_unit_variants("0.1uF")

    assert variants[0] == "0.1uF"
    assert "100nF" in variants
    assert "100000pF" in variants
    assert "0.1µF" in variants


def test_inductance_and_resistance_variants_are_bidirectional():
    assert "100uH" in keyword_unit_variants("0.1mH")
    assert "0.1mH" in keyword_unit_variants("100uH")
    assert "1000Ω" in keyword_unit_variants("1kΩ")
    assert "1kΩ" in keyword_unit_variants("1000ohm")


def test_conversion_annotation_only_marks_converted_matches():
    converted = find_unit_conversion_match("0.1uF", ["100nF ±10% 50V"])

    assert converted == {
        "query_value": "0.1uF",
        "matched_value": "100nF",
        "dimension": "capacitance",
        "dimension_label": "电容",
        "label": "0.1uF = 100nF",
    }
    assert find_unit_conversion_match("0.1uF", ["0.1µF ±10% 50V"]) is None
    assert find_unit_conversion_match("0603", ["100nF 0603"]) is None


def test_component_query_matches_equivalent_value_and_marks_result(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'component-unit-search.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    category = Category(name="电容", color="#dcfce7")
    db.add(category)
    db.flush()
    db.add_all(
        [
            Component(
                id=1,
                owner_user_id=1,
                name="100nF 电容",
                normalized_spec="100nF ±10% 50V",
                package="0603",
                quantity=20,
                category_id=category.id,
            ),
            Component(
                id=2,
                owner_user_id=1,
                name="1uF 电容",
                normalized_spec="1uF ±10% 50V",
                package="0603",
                quantity=20,
                category_id=category.id,
            ),
        ]
    )
    db.commit()

    rows = db.query(Component).filter(or_(*component_keyword_filters("0.1uF"))).all()

    assert [row.id for row in rows] == [1]
    payload = component_out(rows[0], search_keyword="0.1uF")
    assert payload["search_unit_conversion"]["label"] == "0.1uF = 100nF"

    db.close()
    engine.dispose()
