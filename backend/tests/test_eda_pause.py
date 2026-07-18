from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import risks
from app.codex_integration import prune_expired_operation_snapshots
from app.database import Base
from app.eda import router as eda_router
from app.models import Component, EdaComponentBinding, IntegrationOperation, User
from app.risks import RiskScope, list_risks_impl


def test_disabled_eda_routes_return_404_before_auth(monkeypatch):
    monkeypatch.setattr("app.features.FEATURE_EDA_ENABLED", False)
    app = FastAPI()
    app.include_router(eda_router)
    with TestClient(app) as client:
        for method, path in [
            ("get", "/api/eda/summary"),
            ("get", "/api/eda/sync-tokens"),
            ("get", "/api/team/libraries/example/eda/summary"),
            ("get", "/api/eda/sync/manifest"),
        ]:
            response = getattr(client, method)(path)
            assert response.status_code == 404, (path, response.text)


def test_disabled_eda_omits_eda_specific_risks_but_keeps_other_risks(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'eda-risk-pause.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add(User(id=1, phone="13800000001", nickname="用户"))
    component = Component(owner_user_id=1, warehouse_code="ICS-00000001", name="MCU", quantity=0, safety_quantity=5, is_common=True)
    db.add(component)
    db.flush()
    db.add(
        EdaComponentBinding(
            id="binding-1",
            scope_type="personal",
            owner_user_id=1,
            component_id=component.id,
            verification_status="raw",
            created_by_user_id=1,
        )
    )
    db.commit()
    monkeypatch.setattr(risks, "FEATURE_EDA_ENABLED", False)
    result = list_risks_impl(db, RiskScope("personal", 1, None))
    risk_types = {row["risk_type"] for row in result["items"]}
    assert "missing_datasheet" in risk_types
    assert "missing_supplier_part" in risk_types
    assert "low_stock" in risk_types
    assert not {"missing_symbol", "missing_footprint", "unverified_footprint"} & risk_types
    db.close()
    engine.dispose()


def test_expired_undo_snapshots_are_pruned_without_removing_audit_summary(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'operation-prune.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add(User(id=1, phone="13800000001", nickname="用户"))
    operation = IntegrationOperation(
        id="op-expired",
        owner_user_id=1,
        idempotency_key="expired-operation",
        status="succeeded",
        request_json='{"actions":[]}',
        preview_json='[{"label":"archived summary"}]',
        before_json='[{"secret":"snapshot"}]',
        after_json='[{"ok":true}]',
        inverse_json='[{"action":"project.restore"}]',
        precondition_hash="0" * 64,
        approval_expires_at=datetime.utcnow() - timedelta(days=31),
        undo_expires_at=datetime.utcnow() - timedelta(seconds=1),
        executed_at=datetime.utcnow() - timedelta(days=31),
    )
    db.add(operation)
    db.commit()
    assert prune_expired_operation_snapshots(db) == 1
    db.refresh(operation)
    assert operation.before_json is None
    assert operation.inverse_json is None
    assert operation.preview_json == '[{"label":"archived summary"}]'
    assert operation.after_json == '[{"ok":true}]'
    assert operation.status == "succeeded"
    db.close()
    engine.dispose()
