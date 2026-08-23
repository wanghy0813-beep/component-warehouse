from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import sync
from app.auth import AuthContext, require_sync_read, require_sync_write
from app.database import Base, get_db
from app.models import Component, PersonalProjectV2, StockMovement, SyncChange, SyncEntity, SyncTransaction, User
from app.services.sync_core import iso_utc, loads, stable_entity_uid
from app.services.sync_journal import register_sync_journal


def test_business_commit_writes_sync_change_in_same_transaction(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    register_sync_journal()
    engine = create_engine(f"sqlite:///{tmp_path / 'journal.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, autocommit=False, autoflush=False)
    db = Session()
    db.add(User(id=1, phone="13800000001", nickname="离线用户"))
    db.commit()
    component = Component(owner_user_id=1, name="离线器件", quantity=5)
    db.add(component)
    db.flush()
    db.add(
        StockMovement(
            id="00000000-0000-0000-0003-000000000001",
            component_id=component.id,
            owner_user_id=1,
            movement_type="component_create",
            quantity_delta=5,
        )
    )
    db.commit()
    assert db.query(SyncTransaction).filter(SyncTransaction.status == "pending_upload").count() == 1
    assert db.query(SyncChange).count() == 2
    change = db.query(SyncChange).filter(SyncChange.entity_type == "components").one()
    assert change.entity_type == "components"
    assert loads(change.fields_json, {})["name"] == "离线器件"
    entity = db.query(SyncEntity).filter(
        SyncEntity.entity_type == "components",
        SyncEntity.local_id == str(component.id),
    ).one()
    assert entity.entity_uid != stable_entity_uid(1, "components", component.id)
    movement = db.query(SyncChange).filter(SyncChange.entity_type == "stock_movements_v2").one()
    assert loads(movement.refs_json, {})["component_id"] == entity.entity_uid
    db.close()
    engine.dispose()


def test_sync_push_is_idempotent_and_creates_conflict(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'sync.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, autocommit=False, autoflush=False)
    db = Session()
    db.add(User(id=1, phone="13800000001", nickname="同步用户"))
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(sync.router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_auth():
        return AuthContext(user_id=1, phone="13800000001", nickname="同步用户", account_id="account-1")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_sync_read] = override_auth
    app.dependency_overrides[require_sync_write] = override_auth
    monkeypatch.setenv("SYNC_ENABLED", "1")
    monkeypatch.setenv("SYNC_ALLOWED_ACCOUNT_IDS", "1")
    monkeypatch.setattr(sync, "_server_instance_id", lambda: "sync-test-server")
    client = TestClient(app)

    registration = client.post(
        "/api/sync/v1/devices",
        json={"installation_id": "00000000-0000-0000-0000-000000000001", "name": "测试 PC"},
    )
    assert registration.status_code == 200, registration.text
    device_id = registration.json()["device_id"]
    entity_uid = "00000000-0000-0000-0000-000000000100"
    transaction = {
        "transaction_id": "00000000-0000-0000-0000-000000000200",
        "event_id": "desktop-event-1",
        "base_cursor": 0,
        "created_at": "2026-08-24T00:00:00Z",
        "changes": [
            {
                "entity_uid": entity_uid,
                "entity_type": "personal_projects_v2",
                "operation": "upsert",
                "base_version": 0,
                "fields": {
                    "project_code": "PJ-OFFLINE",
                    "name": "离线项目",
                    "status": "planning",
                    "start_date": date.today().isoformat(),
                },
                "field_times": {"name": "2026-08-24T00:00:00Z"},
                "occurred_at": "2026-08-24T00:00:00Z",
            }
        ],
    }
    first = client.post("/api/sync/v1/push", json={"device_id": device_id, "transactions": [transaction]})
    assert first.status_code == 200, first.text
    assert first.json()["items"][0]["status"] == "accepted"
    duplicate = client.post("/api/sync/v1/push", json={"device_id": device_id, "transactions": [transaction]})
    assert duplicate.status_code == 200
    assert duplicate.json()["items"][0]["idempotent"] is True

    verify = Session()
    assert verify.query(PersonalProjectV2).one().name == "离线项目"
    entity = verify.get(SyncEntity, entity_uid)
    entity.version = 2
    entity.field_times_json = '{"name":"2026-08-24T00:01:00Z"}'
    verify.commit()
    verify.close()

    conflict_transaction = {
        **transaction,
        "transaction_id": "00000000-0000-0000-0000-000000000201",
        "event_id": "desktop-event-2",
        "changes": [{
            **transaction["changes"][0],
            "base_version": 1,
            "fields": {"name": "并发离线名称"},
            "field_times": {"name": "2026-08-24T00:02:00Z"},
            "occurred_at": "2026-08-24T00:02:00Z",
        }],
    }
    conflict = client.post(
        "/api/sync/v1/push",
        json={"device_id": device_id, "transactions": [conflict_transaction]},
    )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["items"][0]["status"] == "conflict"
    open_conflicts = client.get("/api/sync/v1/conflicts").json()["items"]
    assert open_conflicts[0]["reason"] in {"clock_drift", "same_field_window"}

    pulled = client.get("/api/sync/v1/pull", params={"device_id": device_id, "after": 0})
    assert pulled.status_code == 200
    assert pulled.json()["next_cursor"] >= 1
    cursor_before_resolution = pulled.json()["next_cursor"]
    resolved = client.post(
        f"/api/sync/v1/conflicts/{open_conflicts[0]['id']}/resolve",
        json={"resolution": "server"},
    )
    assert resolved.status_code == 200, resolved.text
    resolution_pull = client.get(
        "/api/sync/v1/pull",
        params={"device_id": device_id, "after": cursor_before_resolution},
    )
    assert any(item["event_id"].startswith("resolution:") for item in resolution_pull.json()["items"])
    assert client.get("/api/sync/v1/conflicts").json()["items"] == []
    client.close()
    engine.dispose()


def test_concurrent_stock_deltas_merge_and_absolute_adjustment_conflicts(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'stock-sync.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, autocommit=False, autoflush=False)
    seed = Session()
    seed.info["sync_apply"] = True
    seed.add(User(id=1, phone="13800000001", nickname="库存同步用户"))
    component = Component(owner_user_id=1, name="同步电阻", quantity=10)
    seed.add(component)
    seed.flush()
    component_uid = stable_entity_uid(1, "components", component.id)
    seed.add(
        SyncEntity(
            entity_uid=component_uid,
            owner_user_id=1,
            entity_type="components",
            local_id=str(component.id),
            version=1,
            field_times_json="{}",
            tombstone=False,
        )
    )
    seed.commit()
    seed.info.pop("sync_apply", None)
    seed.close()

    app = FastAPI()
    app.include_router(sync.router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_auth():
        return AuthContext(user_id=1, phone="13800000001", nickname="库存同步用户", account_id="account-1")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_sync_read] = override_auth
    app.dependency_overrides[require_sync_write] = override_auth
    monkeypatch.setenv("SYNC_ENABLED", "1")
    monkeypatch.setenv("SYNC_ALLOWED_ACCOUNT_IDS", "1")
    monkeypatch.setattr(sync, "_server_instance_id", lambda: "stock-sync-test")
    client = TestClient(app)
    device_id = client.post(
        "/api/sync/v1/devices",
        json={"installation_id": "00000000-0000-0000-0000-000000000010", "name": "库存测试 PC"},
    ).json()["device_id"]

    def stock_transaction(suffix: int, delta: int, movement_type: str, base_version: int, absolute: int):
        occurred_at = iso_utc()
        return {
            "transaction_id": f"00000000-0000-0000-0001-{suffix:012d}",
            "event_id": f"stock-event-{suffix}",
            "base_cursor": 0,
            "created_at": occurred_at,
            "changes": [
                {
                    "entity_uid": component_uid,
                    "entity_type": "components",
                    "operation": "upsert",
                    "base_version": base_version,
                    "fields": {"quantity": absolute},
                    "field_times": {"quantity": occurred_at},
                    "occurred_at": occurred_at,
                },
                {
                    "entity_uid": f"00000000-0000-0000-0002-{suffix:012d}",
                    "entity_type": "stock_movements_v2",
                    "operation": "upsert",
                    "base_version": 0,
                    "fields": {
                        "movement_type": movement_type,
                        "quantity_delta": delta,
                        "reason": "并发库存测试",
                    },
                    "refs": {"component_id": component_uid},
                    "field_times": {"quantity_delta": occurred_at},
                    "occurred_at": occurred_at,
                },
            ],
        }

    first = stock_transaction(1, 2, "manual_restock", 1, 12)
    second = stock_transaction(2, 3, "manual_restock", 1, 13)
    assert client.post("/api/sync/v1/push", json={"device_id": device_id, "transactions": [first]}).json()["items"][0]["status"] == "accepted"
    second_result = client.post("/api/sync/v1/push", json={"device_id": device_id, "transactions": [second]})
    assert second_result.status_code == 200, second_result.text
    assert second_result.json()["items"][0]["status"] == "accepted"

    verify = Session()
    assert verify.query(Component).one().quantity == 15
    delta_change = verify.query(SyncChange).filter(SyncChange.event_id == "stock-event-2:0").one()
    delta_fields = loads(delta_change.fields_json, {})
    assert delta_fields["__inventory_delta__"] == 3
    assert "quantity" not in delta_fields
    verify.close()

    absolute = stock_transaction(3, 5, "manual_adjustment", 1, 20)
    conflict = client.post("/api/sync/v1/push", json={"device_id": device_id, "transactions": [absolute]})
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["items"][0]["status"] == "conflict"
    assert client.get("/api/sync/v1/conflicts").json()["items"][0]["reason"] == "absolute_inventory"
    verify = Session()
    assert verify.query(Component).one().quantity == 15
    verify.close()
    client.close()
    engine.dispose()
