from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext
from app.database import Base
from app.main import delete_component, filter_owner
from app.models import Component, ComponentIdentityRegistry


def test_component_remove_soft_deletes_and_keeps_ids_reserved(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'component-remove.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    auth = AuthContext(user_id=1, phone="13800000001", nickname="测试用户")
    component = Component(
        name="误添加器件",
        model="WRONG-001",
        lcsc_number="C999999",
        quantity=12,
        owner_user_id=1,
    )
    db.add(component)
    db.commit()
    component_id = component.id

    result = delete_component(component_id, auth, db)

    kept = db.get(Component, component_id)
    assert result["removed"] is True
    assert result["id_reserved"] is True
    assert kept is not None
    assert kept.revoked_at is not None
    assert kept.warehouse_code == result["warehouse_code"]
    assert filter_owner(db.query(Component), Component, auth).count() == 0

    identity = db.query(ComponentIdentityRegistry).filter_by(code=kept.warehouse_code).one()
    assert identity.status == "archived"
    assert identity.component_id is None

    db.close()
    engine.dispose()
