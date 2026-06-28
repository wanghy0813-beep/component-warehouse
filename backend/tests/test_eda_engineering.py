import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import eda
from app.auth import AuthContext, require_access
from app.database import Base, get_db
from app.eda import router as eda_router
from app.models import (
    Category,
    Component,
    EdaAsset,
    EdaComponentBinding,
    InventoryLot,
    Project,
    ProjectBomItem,
    PurchaseLine,
    StockMovement,
    User,
)
from app.purchases import router as purchase_router
from app.risks import router as risk_router
from app.services.eda_storage import public_http_target, resolve_asset_path, stage_upload


def test_eda_two_phase_upload_binding_verification_purchase_and_risks(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.features.FEATURE_EDA_ENABLED", True)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'engineering.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    user = User(id=1, phone="13800000001", nickname="工程用户")
    other_user = User(id=2, phone="13800000002", nickname="其他工程用户")
    category = Category(name="芯片", color="#eef2ff")
    db.add_all([user, other_user, category])
    db.flush()
    component = Component(
        owner_user_id=1,
        warehouse_code="ICX-00000001",
        name="精密运放",
        manufacturer="Texas Instruments",
        model="OPA2333",
        package="VSSOP-8",
        quantity=2,
        safety_quantity=6,
        is_common=True,
        category_id=category.id,
    )
    db.add(component)
    db.commit()
    component_id = component.id
    db.close()

    monkeypatch.setattr("app.services.eda_storage.EDA_STORAGE_ROOT", tmp_path / "eda")
    monkeypatch.setattr("app.services.eda_storage.PERSONAL_QUOTA_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr("app.services.eda_storage.MIN_FREE_BYTES", 0)
    monkeypatch.setattr("app.services.eda_storage.MIN_FREE_RATIO", 0.01)

    app = FastAPI()
    app.include_router(eda_router)
    app.include_router(purchase_router)
    app.include_router(risk_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_auth(x_test_user: int = Header(default=1)) -> AuthContext:
        return AuthContext(x_test_user, "13800000001", "工程用户")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_access] = override_auth
    client = TestClient(app)

    library = client.post("/api/eda/libraries", json={"name": "正式器件库", "category": "IC"}).json()
    version = client.post(
        f"/api/eda/libraries/{library['id']}/versions",
        json={"version": "1.0.0", "change_note": "首版"},
    ).json()
    symbol = client.post(
        f"/api/eda/versions/{version['id']}/symbols",
        json={"name": "OPA2333"},
    ).json()
    footprint = client.post(
        f"/api/eda/versions/{version['id']}/footprints",
        json={"name": "VSSOP-8"},
    ).json()

    staged = client.post(
        "/api/eda/uploads/stage",
        files={"file": ("OPA2333.pdf", b"%PDF-1.7\nengineering", "application/pdf")},
    )
    assert staged.status_code == 200, staged.text
    asset = client.post(
        "/api/eda/assets",
        json={
            "upload_token": staged.json()["token"],
            "library_version_id": version["id"],
            "verification_status": "raw",
        },
    )
    assert asset.status_code == 200, asset.text
    asset_id = asset.json()["id"]
    assert client.get(f"/api/eda/assets/{asset_id}/download").content.startswith(b"%PDF-")
    assert client.post(
        "/api/eda/uploads/stage",
        files={"file": ("fake.pdf", b"not-a-pdf", "application/pdf")},
    ).status_code == 400
    assert client.post(
        "/api/eda/uploads/stage",
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    ).status_code == 400

    binding = client.post(
        "/api/eda/bindings",
        json={
            "component_id": component_id,
            "library_version_id": version["id"],
            "symbol_id": symbol["id"],
            "footprint_id": footprint["id"],
            "datasheet_asset_id": asset_id,
            "source": "自建",
        },
    )
    assert binding.status_code == 200, binding.text
    binding_id = binding.json()["id"]
    incomplete = client.post(
        f"/api/eda/bindings/{binding_id}/verify",
        json={"status": "verified", "checklist": {}, "note": "缺少检查项"},
    )
    assert incomplete.status_code == 400
    verified = client.post(
        f"/api/eda/bindings/{binding_id}/verify",
        json={
            "status": "verified",
            "checklist": {
                "datasheet_checked": True,
                "symbol_checked": True,
                "footprint_checked": True,
            },
            "note": "已按数据手册复核引脚与焊盘",
        },
    )
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"
    workspace = client.post("/api/eda/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["version"]["id"] == version["id"]
    assert client.post("/api/eda/workspace").json()["version"]["id"] == version["id"]
    component_options = client.get("/api/eda/component-options", params={"q": "OPA2333"}).json()
    assert component_options[0]["id"] == component_id
    changed_binding = client.post(
        "/api/eda/quick-bindings",
        json={
            "component_id": component_id,
            "library_version_id": version["id"],
            "symbol_name": "OPA2333",
            "footprint_name": "VSSOP-8-REV",
            "datasheet_asset_id": asset_id,
            "source": "快速模式",
        },
    )
    assert changed_binding.status_code == 200, changed_binding.text
    assert changed_binding.json()["verification_status"] == "raw"
    assert client.post(
        f"/api/eda/bindings/{binding_id}/verify",
        json={
            "status": "verified",
            "checklist": {
                "datasheet_checked": True,
                "symbol_checked": True,
                "footprint_checked": True,
            },
            "note": "修改后重新复核",
        },
    ).status_code == 200

    supplier = client.post(
        "/api/eda/supplier-parts",
        json={
            "component_id": component_id,
            "supplier": "LCSC",
            "supplier_part_number": "C123456",
            "is_preferred": True,
        },
    )
    assert supplier.status_code == 200

    order = client.post("/api/purchases", json={"platform": "LCSC", "status": "ordered"}).json()
    order = client.post(
        f"/api/purchases/{order['id']}/lines",
        json={
            "component_id": component_id,
            "description": "OPA2333 VSSOP-8",
            "ordered_quantity": 5,
            "unit_price": 3.5,
        },
    ).json()
    line_id = order["lines"][0]["id"]
    received = client.post(
        f"/api/purchases/lines/{line_id}/receive",
        json={"quantity": 3, "location": "", "note": "第一批到货"},
    )
    assert received.status_code == 200, received.text
    assert received.json()["lines"][0]["received_quantity"] == 3

    risks = client.get("/api/risks").json()
    assert any(item["risk_type"] == "low_stock" for item in risks["items"])
    assert not any(item["risk_type"] == "missing_footprint" for item in risks["items"])
    manual_issue = client.post(
        "/api/risks",
        json={
            "component_id": component_id,
            "risk_type": "purchase_issue",
            "severity": "warning",
            "title": "供应商批次丝印异常",
            "detail": "需要复核到货批次",
        },
    )
    assert manual_issue.status_code == 200
    issue_id = manual_issue.json()["id"]
    assert any(item["id"] == issue_id for item in client.get("/api/risks").json()["items"])
    assert client.patch(f"/api/risks/{issue_id}", json={"status": "resolved"}).status_code == 200
    assert not any(item["id"] == issue_id for item in client.get("/api/risks").json()["items"])

    token = client.post("/api/eda/sync-tokens", json={"name": "测试工作站", "expires_in_days": 30}).json()
    assert token["token"].startswith("eda_")
    assert any(item["id"] == token["id"] for item in client.get("/api/eda/sync-tokens").json())
    assert client.delete(f"/api/eda/sync-tokens/{token['id']}").status_code == 200

    project_db = Session()
    project = Project(owner_user_id=1, scope_type="personal", name="运放测试板", status="designing")
    project_db.add(project)
    project_db.flush()
    project_db.add(ProjectBomItem(project_id=project.id, component_id=component_id, required_quantity=8, status="reserved"))
    project_db.commit()
    project_id = project.id
    project_db.close()
    generated = client.post(f"/api/purchases/from-project/{project_id}", json={"platform": "LCSC"})
    assert generated.status_code == 200, generated.text
    assert generated.json()["project_id"] == project_id
    assert generated.json()["lines"][0]["ordered_quantity"] == 9

    duplicate_stage = client.post(
        "/api/eda/uploads/stage",
        files={"file": ("OPA2333-copy.pdf", b"%PDF-1.7\nengineering", "application/pdf")},
    ).json()
    assert client.post(
        "/api/eda/assets",
        headers={"X-Test-User": "2"},
        json={"upload_token": duplicate_stage["token"], "verification_status": "raw"},
    ).status_code == 403
    duplicate_asset = client.post(
        "/api/eda/assets",
        json={"upload_token": duplicate_stage["token"], "verification_status": "raw"},
    ).json()
    assert client.delete(f"/api/eda/assets/{asset_id}", params={"confirm": "永久删除"}).status_code == 409
    assert client.post(f"/api/eda/assets/{asset_id}/archive").json()["status"] == "trash"
    assert client.delete(f"/api/eda/assets/{asset_id}", params={"confirm": "永久删除"}).status_code == 200

    check = Session()
    assets = check.query(EdaAsset).all()
    assert len(assets) == 2
    assert len({item.storage_path for item in assets}) == 1
    object_path = tmp_path / "eda" / duplicate_asset["sha256"][:2]
    assert len(list((tmp_path / "eda" / "objects").rglob(f"{duplicate_asset['sha256']}*"))) == 1
    binding_row = check.query(EdaComponentBinding).one()
    assert binding_row.verification_status == "verified"
    assert binding_row.datasheet_asset_id is None
    assert check.query(PurchaseLine).filter(PurchaseLine.received_quantity == 3).one()
    assert check.get(Component, component_id).quantity == 5
    assert check.query(InventoryLot).count() == 1
    assert check.query(StockMovement).filter(StockMovement.movement_type == "purchase_receipt").count() == 1
    check.close()
    assert object_path.parent.exists()
    assert client.post(f"/api/eda/assets/{duplicate_asset['id']}/archive").status_code == 200
    assert client.delete(
        f"/api/eda/assets/{duplicate_asset['id']}",
        params={"confirm": "永久删除"},
    ).status_code == 200
    assert not list((tmp_path / "eda" / "objects").rglob(f"{duplicate_asset['sha256']}*"))
    empty_publish = client.post(f"/api/eda/versions/{version['id']}/publish")
    assert empty_publish.status_code == 400
    library_stage = client.post(
        "/api/eda/uploads/stage",
        files={"file": ("Example.SchLib", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1library", "application/octet-stream")},
    ).json()
    assert client.post(
        "/api/eda/assets",
        json={
            "upload_token": library_stage["token"],
            "library_version_id": version["id"],
            "verification_status": "raw",
        },
    ).status_code == 200
    publish_check = client.get(f"/api/eda/versions/{version['id']}/publish-check").json()
    assert publish_check["can_publish"] is True
    assert publish_check["risk_count"] > 0
    assert client.post(f"/api/eda/versions/{version['id']}/publish").status_code == 409
    assert client.post(
        f"/api/eda/versions/{version['id']}/publish",
        params={"confirm_risks": "true"},
    ).status_code == 200
    assert client.post(
        f"/api/eda/versions/{version['id']}/symbols",
        json={"name": "MUTATION_BLOCKED"},
    ).status_code == 409
    immutable_stage = client.post(
        "/api/eda/uploads/stage",
        files={"file": ("immutable.pdf", b"%PDF-1.7\nimmutable", "application/pdf")},
    ).json()
    assert client.post(
        "/api/eda/assets",
        json={
            "upload_token": immutable_stage["token"],
            "library_version_id": version["id"],
            "verification_status": "raw",
        },
    ).status_code == 409
    assert client.post(
        "/api/eda/assets",
        json={"upload_token": immutable_stage["token"], "verification_status": "raw"},
    ).status_code == 200

    foreign_library = client.post(
        "/api/eda/libraries",
        headers={"X-Test-User": "2"},
        json={"name": "其他用户库"},
    ).json()
    foreign_version = client.post(
        f"/api/eda/libraries/{foreign_library['id']}/versions",
        headers={"X-Test-User": "2"},
        json={"version": "1.0.0"},
    ).json()
    foreign_symbol = client.post(
        f"/api/eda/versions/{foreign_version['id']}/symbols",
        headers={"X-Test-User": "2"},
        json={"name": "FOREIGN_SYMBOL"},
    ).json()
    assert client.post(
        "/api/eda/bindings",
        json={"component_id": component_id, "symbol_id": foreign_symbol["id"]},
    ).status_code == 404
    foreign_stage = client.post(
        "/api/eda/uploads/stage",
        headers={"X-Test-User": "2"},
        files={"file": ("FOREIGN.SchLib", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1foreign", "application/octet-stream")},
    ).json()
    assert client.post(
        "/api/eda/assets",
        headers={"X-Test-User": "2"},
        json={
            "upload_token": foreign_stage["token"],
            "library_version_id": foreign_version["id"],
            "verification_status": "raw",
        },
    ).status_code == 200
    assert client.post(
        f"/api/eda/versions/{foreign_version['id']}/publish",
        headers={"X-Test-User": "2"},
        params={"confirm_risks": "true"},
    ).status_code == 200
    active_token = client.post(
        "/api/eda/sync-tokens",
        json={"name": "作用域测试", "expires_in_days": 30},
    ).json()["token"]
    manifest = client.get(
        "/api/eda/sync/manifest",
        headers={"X-EDA-Sync-Token": active_token},
    )
    assert manifest.status_code == 200
    assert {item["name"] for item in manifest.json()["libraries"]} == {"正式器件库"}
    draft = client.post(
        "/api/eda/sync/drafts",
        headers={"X-EDA-Sync-Token": active_token},
        json={"base_version_id": version["id"]},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["status"] == "raw"
    assert draft.json()["asset_count"] == 1
    client.close()
    engine.dispose()


def test_eda_storage_rejects_paths_ssrf_quota_and_cleans_interrupted_stage(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'security.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    monkeypatch.setattr("app.services.eda_storage.EDA_STORAGE_ROOT", tmp_path / "eda")
    monkeypatch.setattr("app.services.eda_storage.MIN_FREE_BYTES", 0)
    monkeypatch.setattr("app.services.eda_storage.MIN_FREE_RATIO", 0.01)
    monkeypatch.setattr("app.services.eda_storage.PERSONAL_QUOTA_BYTES", 4)

    with pytest.raises(Exception) as quota_error:
        asyncio.run(
            stage_upload(
                db,
                InterruptedUpload(),
                scope_type="personal",
                owner_user_id=1,
                team_library_id=None,
            )
        )
    assert getattr(quota_error.value, "status_code", None) == 413

    monkeypatch.setattr("app.services.eda_storage.PERSONAL_QUOTA_BYTES", 1024)
    before = set((tmp_path / "eda").rglob("*"))
    with pytest.raises(OSError):
        asyncio.run(
            stage_upload(
                db,
                InterruptedUpload(fail_after_first=True),
                scope_type="personal",
                owner_user_id=1,
                team_library_id=None,
            )
        )
    after = set((tmp_path / "eda").rglob("*"))
    assert not [path for path in after - before if path.is_file()]

    with pytest.raises(Exception) as path_error:
        resolve_asset_path("../../etc/passwd")
    assert getattr(path_error.value, "status_code", None) == 400
    with pytest.raises(Exception) as ssrf_error:
        public_http_target("http://127.0.0.1/private.pdf")
    assert getattr(ssrf_error.value, "status_code", None) == 400
    db.close()
    engine.dispose()


class InterruptedUpload:
    filename = "interrupted.pdf"
    content_type = "application/pdf"

    def __init__(self, fail_after_first: bool = False):
        self.calls = 0
        self.fail_after_first = fail_after_first

    async def read(self, _: int) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"%PDF-1.7\npayload"
        if self.fail_after_first:
            raise OSError("connection interrupted")
        return b""
