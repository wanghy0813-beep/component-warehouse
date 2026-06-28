from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext
from app.database import Base
from app.main import admin_usage_dashboard
from app.models import ActivityLog, Category, Component, Project, ProjectBomItem, User
from app.services.substitutions import substitution_suggestions_for_bom_items


def make_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'substitutions.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    return engine, Session()


def test_shortage_bom_item_suggests_same_category_package_value_without_replacing(tmp_path):
    engine, db = make_db(tmp_path)
    user = User(id=1, phone="admin-user", nickname="管理员", is_admin=True)
    capacitor = Category(name="电容", color="#eef2ff")
    db.add_all([user, capacitor])
    db.flush()

    source = Component(
        owner_user_id=1,
        name="CL21B106KAYQNNE 10uF 25V MLCC",
        model="CL21B106KAYQNNE",
        normalized_spec="10uF",
        parameters="10uF 25V X5R",
        package="0805",
        quantity=0,
        category_id=capacitor.id,
    )
    same_voltage = Component(
        owner_user_id=1,
        name="CL21B106KAYONNE 10uF 25V MLCC",
        model="CL21B106KAYONNE",
        normalized_spec="10uF",
        parameters="10uF 25V X5R",
        package="C0805",
        quantity=12,
        category_id=capacitor.id,
    )
    lower_voltage = Component(
        owner_user_id=1,
        name="CL21A106KOQNNNE 10uF 16V MLCC",
        model="CL21A106KOQNNNE",
        normalized_spec="10uF",
        parameters="10uF 16V X5R",
        package="0805",
        quantity=40,
        category_id=capacitor.id,
    )
    wrong_value = Component(
        owner_user_id=1,
        name="CL21B105KAFNNNE 1uF 25V MLCC",
        model="CL21B105KAFNNNE",
        normalized_spec="1uF",
        parameters="1uF 25V X5R",
        package="0805",
        quantity=50,
        category_id=capacitor.id,
    )
    wrong_package = Component(
        owner_user_id=1,
        name="10uF 25V 0603",
        model="CL10B106KP8NNNC",
        normalized_spec="10uF",
        parameters="10uF 25V",
        package="0603",
        quantity=50,
        category_id=capacitor.id,
    )
    project = Project(owner_user_id=1, project_code="PJ-00000001", name="替代料测试")
    db.add_all([source, same_voltage, lower_voltage, wrong_value, wrong_package, project])
    db.flush()
    item = ProjectBomItem(project_id=project.id, component_id=source.id, required_quantity=1, status="reserved")
    db.add(item)
    db.commit()
    db.refresh(item)

    suggestions = substitution_suggestions_for_bom_items(db, [item], {source.id: 0})[item.id]
    suggested_ids = {row["component"]["id"] for row in suggestions}

    assert same_voltage.id in suggested_ids
    assert lower_voltage.id in suggested_ids
    assert wrong_value.id not in suggested_ids
    assert wrong_package.id not in suggested_ids
    assert all(row["auto_replace"] is False for row in suggestions)
    lower = next(row for row in suggestions if row["component"]["id"] == lower_voltage.id)
    assert any("耐压更低" in warning for warning in lower["warnings"])

    db.close()
    engine.dispose()


def test_admin_usage_dashboard_aggregates_ui_events_lightly(tmp_path):
    engine, db = make_db(tmp_path)
    admin = User(id=1, phone="admin-user", nickname="管理员", is_admin=True, last_login_at=datetime.utcnow())
    user = User(id=2, phone="13800000001", nickname="普通用户", last_login_at=datetime.utcnow() - timedelta(days=1))
    db.add_all([admin, user])
    db.flush()
    db.add_all(
        [
            ActivityLog(owner_user_id=1, action="ui.nav.click", entity_type="ui", summary="导航", detail='{"page":"/components","entry":"components"}'),
            ActivityLog(owner_user_id=1, action="ui.components.detail_open", entity_type="component", entity_id=3, summary="详情", detail='{"page":"/components","entry":"card"}'),
            ActivityLog(owner_user_id=2, action="ui.components.detail_open", entity_type="component", entity_id=4, summary="详情", detail='{"page":"/components","entry":"card"}'),
            ActivityLog(owner_user_id=2, action="component.create", entity_type="component", summary="非 UI 操作"),
        ]
    )
    db.commit()

    result = admin_usage_dashboard(AuthContext(1, admin.phone, admin.nickname, is_admin=True), db)

    assert result["registered_users"] == 2
    assert result["monthly_active_users"] == 2
    assert result["ui_events_30d"] == 3
    assert result["top_features"][0]["action"] == "ui.components.detail_open"
    assert result["recent_users"][0]["event_count_30d"] >= 1

    db.close()
    engine.dispose()
