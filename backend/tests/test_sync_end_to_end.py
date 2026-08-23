import json
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import desktop, sync
from app.auth import AuthContext, require_sync_read, require_sync_write
from app.database import Base, get_db
from app.models import Component, StockMovement, SyncTransaction, User
from app.services.desktop_bootstrap import import_desktop_bootstrap
from app.services.sync_bootstrap import create_personal_bootstrap
from app.services.sync_journal import register_sync_journal


def test_two_sqlite_databases_merge_offline_and_online_stock_events(tmp_path: Path, monkeypatch):
    register_sync_journal()
    monkeypatch.setenv("SYNC_ENABLED", "0")
    monkeypatch.setenv("DESKTOP_MODE", "0")

    server_root = tmp_path / "server"
    server_root.mkdir()
    server_engine = create_engine(
        f"sqlite:///{server_root / 'component_warehouse.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(server_engine)
    ServerSession = sessionmaker(server_engine, autocommit=False, autoflush=False)
    seed = ServerSession()
    seed.add(User(id=1, phone="13800000001", nickname="双库同步用户"))
    seed.add(Component(id=1, owner_user_id=1, name="双库同步电阻", quantity=10))
    seed.commit()
    package = create_personal_bootstrap(
        seed,
        owner_user_id=1,
        data_root=server_root,
        server_instance_id="server-e2e",
        cursor=0,
        output_dir=server_root,
    )
    seed.commit()
    seed.close()

    desktop_root = tmp_path / "desktop"
    desktop_root.mkdir()
    desktop_db = desktop_root / "component_warehouse.db"
    initial_engine = create_engine(f"sqlite:///{desktop_db}")
    Base.metadata.create_all(initial_engine)
    initial_engine.dispose()
    marker_path = desktop_root / "desktop-state.json"
    import_desktop_bootstrap(
        package,
        database_path=desktop_db,
        data_root=desktop_root,
        marker_path=marker_path,
    )
    local_engine = create_engine(
        f"sqlite:///{desktop_db}",
        connect_args={"check_same_thread": False},
    )
    LocalSession = sessionmaker(local_engine, autocommit=False, autoflush=False)

    server_app = FastAPI()
    server_app.include_router(sync.router)

    def server_db():
        session = ServerSession()
        try:
            yield session
        finally:
            session.close()

    def sync_auth():
        return AuthContext(user_id=1, phone="13800000001", nickname="双库同步用户", account_id="account-e2e")

    server_app.dependency_overrides[get_db] = server_db
    server_app.dependency_overrides[require_sync_read] = sync_auth
    server_app.dependency_overrides[require_sync_write] = sync_auth
    monkeypatch.setenv("SYNC_ENABLED", "1")
    monkeypatch.setenv("SYNC_ALLOWED_ACCOUNT_IDS", "1")
    monkeypatch.setattr(sync, "_server_instance_id", lambda: "server-e2e")
    registration_client = TestClient(server_app)
    device_id = registration_client.post(
        "/api/sync/v1/devices",
        json={"installation_id": "00000000-0000-0000-0000-000000000099", "name": "E2E PC"},
    ).json()["device_id"]
    registration_client.close()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker_path.write_text(json.dumps({**marker, "device_id": device_id}), encoding="utf-8")

    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("DESKTOP_DATA_ROOT", str(desktop_root))
    monkeypatch.setattr(desktop.httpx, "Client", lambda *args, **kwargs: TestClient(server_app))

    local = LocalSession()
    local_component = local.get(Component, 1)
    local_component.quantity += 2
    local.add(
        StockMovement(
            id=str(uuid.uuid4()),
            component_id=1,
            owner_user_id=1,
            movement_type="manual_restock",
            quantity_delta=2,
        )
    )
    local.commit()
    assert local.query(SyncTransaction).filter(SyncTransaction.status == "pending_upload").count() == 1
    first_sync = desktop.sync_now(
        {"remote_base": "https://server", "access_token": "e2e-token", "device_id": device_id},
        None,
        local,
    )
    assert first_sync["synced"] is True
    first_verify = ServerSession()
    assert first_verify.get(Component, 1).quantity == 12
    first_verify.close()

    monkeypatch.setenv("DESKTOP_MODE", "0")
    online = ServerSession()
    online_component = online.get(Component, 1)
    online_component.quantity += 3
    online.add(
        StockMovement(
            id=str(uuid.uuid4()),
            component_id=1,
            owner_user_id=1,
            movement_type="manual_restock",
            quantity_delta=3,
        )
    )
    online.commit()
    online.close()

    monkeypatch.setenv("DESKTOP_MODE", "1")
    local_component = local.get(Component, 1)
    local_component.quantity += 2
    local.add(
        StockMovement(
            id=str(uuid.uuid4()),
            component_id=1,
            owner_user_id=1,
            movement_type="manual_restock",
            quantity_delta=2,
        )
    )
    local.commit()
    second_sync = desktop.sync_now(
        {"remote_base": "https://server", "access_token": "e2e-token", "device_id": device_id},
        None,
        local,
    )
    assert second_sync["synced"] is True
    local.expire_all()
    assert local.get(Component, 1).quantity == 17
    server_verify = ServerSession()
    assert server_verify.get(Component, 1).quantity == 17
    server_verify.close()
    local.close()
    local_engine.dispose()
    server_engine.dispose()
