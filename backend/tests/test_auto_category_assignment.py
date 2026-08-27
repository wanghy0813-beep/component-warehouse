from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import normalize_for_inventory
from app.models import Category
from app.seed import seed_categories


def test_inventory_normalization_assigns_17_zone_category_and_location(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auto-category.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    seed_categories(db)

    values = normalize_for_inventory(db, {
        "name": "CH224A USB PD 受电协议芯片",
        "model": "CH224A",
        "package": "ESSOP-10",
        "quantity": 3,
    })
    category = db.get(Category, values["category_id"])
    assert category.name == "电源IC"
    assert values["location"] == "08 电源IC"
    assert "17区自动分类" in values["remark"]
    db.close()
    engine.dispose()
