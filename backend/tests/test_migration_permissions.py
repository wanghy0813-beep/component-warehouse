import sqlite3

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext, require_admin
from app.database import Base
from app.main import (
    V04_ACCOUNT_MIGRATION,
    V04_LEGACY_COMPETITION_CLEANUP,
    V041_CONTEST_LIVE_INVENTORY,
    V070_EDA_ENGINEERING,
    V072_LCSC_SOURCE_NORMALIZATION,
    ensure_v04_migration_backup,
    ensure_v041_migration_backup,
    filter_owner,
    remove_legacy_component_lcsc_unique,
    run_v04_account_migration,
    run_v041_inventory_migration,
    run_v070_eda_migration,
    run_v072_lcsc_source_normalization,
    undo_latest_component_ai_change,
)
from app.models import (
    AppMigration,
    ActivityLog,
    CompetitionLibrary,
    CompetitionLibraryComponent,
    CompetitionLibraryMember,
    Component,
    InventoryLot,
    Project,
    ProjectBomItem,
    User,
)


def test_v04_migration_is_idempotent_and_isolates_owners(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(User(id=1, phone="legacy", nickname="旧镜像", password_hash="legacy", is_admin=True))
    db.add(User(id=2, phone="13800000002", nickname="其他人", is_admin=False))
    db.add(
        Component(
            name="库存 A",
            quantity=5,
            owner_user_id=2,
            competition_name="旧比赛",
            priority="P0",
            target_quantity=20,
        )
    )
    db.add(Project(name="项目 A", owner_user_id=2))
    db.commit()

    monkeypatch.setattr("app.main.DATABASE_URL", f"sqlite:///{path}")
    backup = ensure_v04_migration_backup()
    assert backup and backup.exists()

    run_v04_account_migration(db)
    run_v04_account_migration(db)
    assert db.get(AppMigration, V04_ACCOUNT_MIGRATION)
    assert db.get(AppMigration, V04_LEGACY_COMPETITION_CLEANUP)
    assert db.get(User, 1).password_hash is None
    assert db.get(User, 1).is_admin is False
    assert {row.owner_user_id for row in db.query(Component).all()} == {1}
    migrated_component = db.query(Component).one()
    assert migrated_component.competition_name is None
    assert migrated_component.priority is None
    assert migrated_component.target_quantity == 0
    assert {row.owner_user_id for row in db.query(Project).all()} == {1}
    assert filter_owner(db.query(Component), Component, AuthContext(2, "x", "x")).count() == 0

    connection = sqlite3.connect(path)
    try:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()
    assert "user_tokens" not in names
    assert "password_reset_codes" not in names
    db.close()
    engine.dispose()


def test_admin_permission_comes_only_from_verified_context():
    admin = AuthContext(1, "13800000001", "管理员", is_admin=True)
    member = AuthContext(2, "13800000002", "成员", is_admin=False)
    assert require_admin(admin) is admin
    try:
        require_admin(member)
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError("non-admin context must be rejected")


def test_v041_migration_restores_released_and_enables_live_inventory(tmp_path, monkeypatch):
    path = tmp_path / "v040.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(User(id=1, phone="13800000001", nickname="队长"))
    db.add(User(id=2, phone="13800000002", nickname="离队成员"))
    db.flush()
    live_component = Component(
        owner_user_id=1,
        warehouse_code="CW-00000001",
        name="实时物料",
        quantity=73,
    )
    frozen_component = Component(
        owner_user_id=2,
        warehouse_code="CW-00000002",
        name="离队物料",
        quantity=12,
    )
    project = Project(owner_user_id=1, name="旧项目")
    library = CompetitionLibrary(
        id="library-1",
        name="旧团队器件库",
        creator_user_id=1,
        status="active",
    )
    db.add_all([live_component, frozen_component, project, library])
    db.flush()
    db.add(
        CompetitionLibraryMember(
            library_id=library.id,
            user_id=1,
            role="captain",
            status="active",
        )
    )
    released = ProjectBomItem(
        project_id=project.id,
        component_id=live_component.id,
        required_quantity=1,
        status="released",
    )
    db.add(released)
    db.add_all(
        [
            CompetitionLibraryComponent(
                id="item-live",
                library_id=library.id,
                cw_component_id=live_component.id,
                name="旧实时名称",
                quantity=1,
                created_by_user_id=1,
                updated_by_user_id=1,
            ),
            CompetitionLibraryComponent(
                id="item-frozen",
                library_id=library.id,
                cw_component_id=frozen_component.id,
                name="旧离队名称",
                quantity=1,
                created_by_user_id=2,
                updated_by_user_id=2,
            ),
        ]
    )
    db.commit()

    monkeypatch.setattr("app.main.DATABASE_URL", f"sqlite:///{path}")
    backup = ensure_v041_migration_backup()
    assert backup and backup.exists()
    run_v041_inventory_migration(db)
    run_v041_inventory_migration(db)

    assert db.get(AppMigration, V041_CONTEST_LIVE_INVENTORY)
    assert db.get(ProjectBomItem, released.id).status == "reserved"
    live = db.get(CompetitionLibraryComponent, "item-live")
    assert live.source_user_id == 1
    assert live.sync_status == "live"
    assert live.cw_component_id == live_component.id
    assert live.quantity == 73
    frozen = db.get(CompetitionLibraryComponent, "item-frozen")
    assert frozen.source_user_id == 2
    assert frozen.sync_status == "frozen"
    assert frozen.cw_component_id is None
    assert frozen.quantity == 12
    assert frozen.warehouse_code_snapshot == "CW-00000002"
    assert '"quantity": 12' in frozen.frozen_snapshot_json
    db.close()
    engine.dispose()


def test_v072_lcsc_source_normalization_shortens_existing_sources(tmp_path):
    path = tmp_path / "v072.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add_all(
        [
            Component(name="立创长来源", source="立创商城 Excel", quantity=1),
            Component(name="LCSC 来源", source="LCSC order import", quantity=1),
            Component(name="淘宝来源", source="淘宝", quantity=1),
        ]
    )
    db.commit()

    run_v072_lcsc_source_normalization(db)
    run_v072_lcsc_source_normalization(db)

    sources = {row.name: row.source for row in db.query(Component).all()}
    assert sources["立创长来源"] == "立创"
    assert sources["LCSC 来源"] == "立创"
    assert sources["淘宝来源"] == "淘宝"
    assert db.get(AppMigration, V072_LCSC_SOURCE_NORMALIZATION)
    db.close()
    engine.dispose()


def test_legacy_global_lcsc_unique_constraint_is_removed(tmp_path, monkeypatch):
    path = tmp_path / "legacy-lcsc.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE components (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            quantity INTEGER NOT NULL,
            status VARCHAR(40) NOT NULL,
            lcsc_number VARCHAR(120),
            owner_user_id INTEGER,
            CONSTRAINT uq_components_lcsc_number UNIQUE (lcsc_number)
        );
        CREATE INDEX ix_components_name ON components(name);
        INSERT INTO components (id, name, quantity, status, lcsc_number, owner_user_id)
        VALUES (1, '账号一物料', 1, 'in_stock', 'C123456', 1);
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr("app.main.DATABASE_URL", f"sqlite:///{path}")

    assert remove_legacy_component_lcsc_unique() is True
    assert remove_legacy_component_lcsc_unique() is False

    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO components (id, name, quantity, status, lcsc_number, owner_user_id) "
        "VALUES (2, '账号二同料号', 2, 'in_stock', 'C123456', 2)"
    )
    connection.commit()
    assert connection.execute("SELECT COUNT(*) FROM components").fetchone()[0] == 2
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='ix_components_name'"
    ).fetchone()
    connection.close()


def test_v070_migration_adds_legacy_lots_roles_and_clears_orphan_project_links(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'v070.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(id=1, phone="13800000001", nickname="用户")
    library = CompetitionLibrary(id="team-1", name="团队", creator_user_id=1, status="active")
    component = Component(owner_user_id=1, name="旧库存", quantity=7, location=None)
    db.add_all([user, library, component])
    db.flush()
    db.add(CompetitionLibraryMember(library_id=library.id, user_id=1, role="member", status="active"))
    log = ActivityLog(
        owner_user_id=1,
        action="project.delete",
        entity_type="project",
        project_id=999,
        summary="删除旧项目",
    )
    db.add(log)
    db.commit()

    run_v070_eda_migration(db)
    run_v070_eda_migration(db)

    assert db.get(AppMigration, V070_EDA_ENGINEERING)
    assert db.query(CompetitionLibraryMember).one().role == "editor"
    lot = db.query(InventoryLot).one()
    assert lot.source_type == "legacy"
    assert lot.remaining_quantity == 7
    assert lot.location is None
    assert db.get(ActivityLog, log.id).project_id is None
    db.close()
    engine.dispose()


def test_ai_component_changes_can_be_undone_with_before_snapshot(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ai-undo.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(id=1, phone="13800000001", nickname="用户")
    component = Component(owner_user_id=1, name="AI 修改后名称", tags="new", quantity=1)
    db.add_all([user, component])
    db.flush()
    db.add(
        ActivityLog(
            owner_user_id=1,
            action="ai.component.organize",
            entity_type="component",
            entity_id=component.id,
            component_id=component.id,
            summary="AI 规范化",
            detail='{"before":{"name":"原名称","tags":"old"},"after":{"name":"AI 修改后名称","tags":"new"}}',
        )
    )
    db.commit()
    result = undo_latest_component_ai_change(
        component.id,
        AuthContext(1, "13800000001", "用户"),
        db,
    )
    assert result["name"] == "原名称"
    assert result["tags"] == "old"
    assert db.get(Component, component.id).ai_status == "stale"
    original_log = db.query(ActivityLog).filter(ActivityLog.action == "ai.component.organize").one()
    assert "undone_at" in original_log.detail
    db.close()
    engine.dispose()
