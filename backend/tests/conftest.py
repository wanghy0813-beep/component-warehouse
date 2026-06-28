from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import team
from app.auth import AuthContext, require_access
from app.team import router
from app.mobile import router as mobile_router
from app.purchases import router as purchase_router
from app.team_projects import router as team_projects_router
from app.database import Base, get_db
from app.models import User


@pytest.fixture()
def team_env(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'contest-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add_all(
        [
            User(id=1, phone="13800000001", nickname="队长", is_admin=True),
            User(id=2, phone="13800000002", nickname="成员", is_admin=False),
            User(id=3, phone="13800000003", nickname="外部用户", is_admin=False),
        ]
    )
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(router)
    app.include_router(mobile_router)
    app.include_router(team_projects_router)
    app.include_router(purchase_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_auth(x_test_user: int = Header(default=1)) -> AuthContext:
        session = Session()
        try:
            user = session.get(User, x_test_user)
            assert user
            return AuthContext(
                user_id=user.id,
                phone=user.phone,
                nickname=user.nickname or "用户",
                is_admin=bool(user.is_admin),
            )
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_access] = override_auth
    monkeypatch.setattr(team, "TEAM_MEDIA_ROOT", tmp_path / "media")
    monkeypatch.setattr(team, "TEAM_SECRET_FILE", tmp_path / ".invite-secret")
    monkeypatch.setattr(team, "INVITE_SECRET", "")
    monkeypatch.setattr(team, "PUBLIC_TEAM_BASE_URL", "https://example.test/team")
    client = TestClient(app)
    yield {"client": client, "Session": Session, "engine": engine, "tmp_path": tmp_path}
    client.close()
    engine.dispose()


@pytest.fixture()
def created_library(team_env):
    client = team_env["client"]
    response = client.post(
        "/api/team/libraries",
        json={
            "name": "电赛一队",
            "competition_type": "电子设计竞赛",
            "description": "测试库",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()
