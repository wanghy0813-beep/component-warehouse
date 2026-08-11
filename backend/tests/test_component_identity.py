from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.component_identity import (
    V060_COMPONENT_IDENTITIES,
    allocate_component_identity,
    archive_component_identity,
    identity_by_code,
    public_identity_out,
    run_component_identity_migration,
)
from app.database import Base
from app.models import AppMigration, Category, Component, ComponentIdentityRegistry
from app.seed import DEFAULT_CATEGORIES


def test_v060_identity_migration_uses_global_non_reusable_sequence(tmp_path):
    assert "设备" in DEFAULT_CATEGORIES
    engine = create_engine(f"sqlite:///{tmp_path / 'identity.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    resistor = Category(name="电阻")
    capacitor = Category(name="电容")
    db.add_all([resistor, capacitor])
    db.flush()
    first = Component(name="10k", category=resistor, warehouse_code="LC-00000009", quantity=2)
    second = Component(name="100nF", category=capacitor, warehouse_code="EX-00000002", quantity=0)
    db.add_all([first, second])
    db.commit()

    assert run_component_identity_migration(db) == 2
    assert run_component_identity_migration(db) == 0
    assert db.get(AppMigration, V060_COMPONENT_IDENTITIES)
    assert first.warehouse_code == "RES-00000001"
    assert second.warehouse_code == "CAP-00000002"
    assert [row.legacy_code for row in db.query(ComponentIdentityRegistry).order_by(ComponentIdentityRegistry.sequence_number)] == [
        "LC-00000009",
        "EX-00000002",
    ]
    assert identity_by_code(db, "LC-00000009") is None
    public = public_identity_out(identity_by_code(db, "RES-00000001"), first)
    assert {"quantity", "location", "owner_user_id", "remark"}.isdisjoint(public)

    first.category = capacitor
    assert allocate_component_identity(db, first).code == "RES-00000001"
    archive_component_identity(db, first)
    db.delete(first)
    db.commit()

    replacement = Component(name="1k", category=resistor, quantity=1)
    db.add(replacement)
    db.flush()
    assert allocate_component_identity(db, replacement).code == "RES-00000003"
    db.commit()
    assert db.query(ComponentIdentityRegistry).filter_by(code="RES-00000001", status="archived").one()
    equipment = Category(name="设备")
    db.add(equipment)
    db.flush()
    equipment_component = Component(name="实验室设备", category=equipment, quantity=1)
    db.add(equipment_component)
    db.flush()
    assert allocate_component_identity(db, equipment_component).prefix == "EQP"
    custom = Category(name="特殊执行器")
    db.add(custom)
    db.flush()
    custom_component = Component(name="执行器", category=custom, quantity=1)
    db.add(custom_component)
    db.flush()
    custom_identity = allocate_component_identity(db, custom_component)
    assert len(custom_identity.prefix) == 3
    assert custom_identity.prefix.startswith("X")
    assert custom.code_prefix == custom_identity.prefix
    assert custom.code_prefix_locked is True
    db.close()
    engine.dispose()
