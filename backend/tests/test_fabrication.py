import io
import json
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import AuthContext, require_access
from app.database import Base, get_db
from app.fabrication import process_revision, recover_interrupted_revisions, router
from app.models import (
    CompetitionLibrary,
    CompetitionLibraryComponent,
    CompetitionLibraryMember,
    Component,
    Project,
    ProjectAssemblyLossEvent,
    ProjectAssemblyOperation,
    ProjectBoard,
    ProjectBomItem,
    ProjectBomSolderPoint,
    ProjectFabricationRevision,
    User,
)
from app.services import eda_storage
from app.services import fabrication_parser
from app.services.fabrication_parser import (
    FabricationParseError,
    _sanitize_svg_markup,
    parse_fabrication_package,
)


def zip_bytes(files: dict[str, str | bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def manufacturing_zip(*, units: str = "mm", r1_model: str = "R-10K", r1_x: str | None = None) -> bytes:
    scale = r1_x or ("0.5in" if units == "inch" else "12.7mm")
    return zip_bytes(
        {
            "JLCPCB/BOM.csv": (
                "Designator,Comment,Footprint,MPN,DNP\n"
                f"R1,10K,0603,{r1_model},no\n"
                "R2,10K,0603,R-10K,no\n"
                "U1,MCU,QFN-32,MCU-1,yes\n"
                "J1,USB,USB-C,USB-C-1,no\n"
            ),
            "JLCPCB/PickAndPlace.csv": (
                "Designator,Mid X,Mid Y,Layer,Rotation\n"
                f"R1,{scale},25.4mm,Top,90\n"
                "R2,30,25,Bottom,180\n"
                "U1,20,40,Top,0\n"
            ),
            "Gerber/board.GKO": "%FSLAX46Y46*%\n%MOMM*%\nG04 synthetic outline*\nM02*\n",
        }
    )


@pytest.fixture()
def fabrication_env(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fabrication.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add_all(
        [
            User(id=1, phone="13800000001", nickname="所有者", is_admin=True),
            User(id=2, phone="13800000002", nickname="编辑者", is_admin=False),
            User(id=3, phone="13800000003", nickname="只读者", is_admin=False),
        ]
    )
    component = Component(id=1, owner_user_id=1, name="10K 电阻", model="R-10K", package="0603", quantity=10)
    project = Project(id=1, scope_type="personal", owner_user_id=1, project_code="PJ-GERBER", name="装配测试")
    board = ProjectBoard(id=1, project_id=1, board_index=1, name="第 1 板", status="active")
    item = ProjectBomItem(id=1, project_id=1, component_id=1, required_quantity=2, status="reserved", remark="BOM 位号: R1,R2；BOM 型号: R-10K；BOM 封装: 0603")
    db.add_all([component, project, board, item])
    db.flush()
    db.add_all(
        [
            ProjectBomSolderPoint(id=1, bom_item_id=1, board_id=1, designator="R1", designator_key="R1", active_for_assembly=True, state_version=1, bom_model="R-10K", bom_footprint="0603"),
            ProjectBomSolderPoint(id=2, bom_item_id=1, board_id=1, designator="R2", designator_key="R2", active_for_assembly=True, state_version=1, bom_model="R-10K", bom_footprint="0603"),
        ]
    )
    library = CompetitionLibrary(id="lib-1", name="团队库", creator_user_id=1, status="active")
    team_project = Project(id=2, scope_type="team", team_library_id="lib-1", project_code="TPJ-GERBER", name="团队装配")
    team_board = ProjectBoard(id=2, project_id=2, board_index=1, name="团队第 1 板", status="active")
    team_item = ProjectBomItem(id=2, project_id=2, component_id=1, required_quantity=1, status="reserved", remark="BOM 位号: R1；BOM 型号: R-10K；BOM 封装: 0603")
    db.add_all([library, team_project, team_board, team_item])
    db.flush()
    db.add_all(
        [
            CompetitionLibraryMember(library_id="lib-1", user_id=1, role="captain", status="active"),
            CompetitionLibraryMember(library_id="lib-1", user_id=2, role="editor", status="active"),
            CompetitionLibraryMember(library_id="lib-1", user_id=3, role="viewer", status="active"),
            CompetitionLibraryComponent(
                id="team-component-1",
                library_id="lib-1",
                cw_component_id=1,
                source_user_id=1,
                sync_status="live",
                name="10K 电阻",
                model="R-10K",
                quantity=10,
                created_by_user_id=1,
                updated_by_user_id=1,
            ),
            ProjectBomSolderPoint(id=3, bom_item_id=2, board_id=2, designator="R1", designator_key="R1", active_for_assembly=True, state_version=1, bom_model="R-10K", bom_footprint="0603"),
        ]
    )
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(router)

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
            return AuthContext(user_id=user.id, phone=user.phone, nickname=user.nickname or "用户", is_admin=bool(user.is_admin))
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_access] = override_auth
    monkeypatch.setattr(eda_storage, "EDA_STORAGE_ROOT", tmp_path / "eda")
    monkeypatch.setattr(eda_storage, "MIN_FREE_BYTES", 0)
    monkeypatch.setattr(eda_storage, "MIN_FREE_RATIO", 0.01)
    client = TestClient(app)
    yield {"client": client, "Session": Session, "tmp_path": tmp_path}
    client.close()
    engine.dispose()


def parse_queued_revision(env, revision_id: str) -> ProjectFabricationRevision:
    db = env["Session"]()
    revision = db.get(ProjectFabricationRevision, revision_id)
    process_revision(db, revision)
    db.refresh(revision)
    assert revision.status == "review", revision.error_message
    db.expunge(revision)
    db.close()
    return revision


def upload_parse_activate(env, project_id: int = 1, prefix: str = "/api/projects") -> dict:
    client = env["client"]
    response = client.post(
        f"{prefix}/{project_id}/fabrication-revisions",
        files={"file": ("manufacturing.zip", manufacturing_zip(), "application/zip")},
    )
    assert response.status_code == 200, response.text
    revision_id = response.json()["id"]
    parse_queued_revision(env, revision_id)
    preview = client.get(f"{prefix}/{project_id}/fabrication-revisions/{revision_id}")
    assert preview.status_code == 200
    assert preview.json()["summary"]["placement_count"] == 4
    activate = client.post(f"{prefix}/{project_id}/fabrication-revisions/{revision_id}/commit", json={})
    assert activate.status_code == 200, activate.text
    return activate.json()


def test_deterministic_parser_handles_jlc_units_sides_dnp_and_unpositioned(tmp_path: Path):
    package = tmp_path / "manufacturing.zip"
    package.write_bytes(manufacturing_zip(units="inch"))
    result = parse_fabrication_package(package, allow_ai=False)
    assert result["profile"] == "jlc-easyeda"
    assert result["mapping_required"] is False
    assert result["summary"] == {
        "file_count": 3,
        "layer_count": 1,
        "placement_count": 4,
        "positioned_count": 3,
        "unpositioned_count": 1,
        "dnp_count": 1,
        "bom_only_count": 1,
        "cpl_only_count": 0,
    }
    rows = {row["designator"]: row for row in result["placements"]}
    assert rows["R1"]["x_mm"] == pytest.approx(12.7)
    assert rows["R2"]["board_side"] == "bottom"
    assert rows["U1"]["dnp"] is True
    assert rows["J1"]["positioned"] is False


@pytest.mark.parametrize(
    "filename,profile",
    [
        ("jlc-easyeda-v1.zip", "jlc-easyeda"),
        ("kicad-v1.zip", "kicad"),
        ("altium-v1.zip", "altium"),
    ],
)
def test_redistributable_adapter_fixtures_parse(filename: str, profile: str):
    package = Path(__file__).parent / "fixtures" / "fabrication" / filename
    result = parse_fabrication_package(package, allow_ai=False)
    assert result["profile"] == profile
    assert result["summary"]["layer_count"] >= 1
    assert result["summary"]["positioned_count"] >= 3
    if profile == "altium":
        assert any("重复位号" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    "files, message",
    [
        ({"../escape.csv": "x"}, "不安全路径"),
        ({"nested.zip": b"PK\x05\x06" + b"\x00" * 18}, "嵌套压缩包"),
    ],
)
def test_zip_security_rejects_traversal_and_nested_archives(tmp_path: Path, files, message):
    package = tmp_path / "unsafe.zip"
    package.write_bytes(zip_bytes(files))
    with pytest.raises(FabricationParseError, match=message):
        parse_fabrication_package(package, allow_ai=False)


def test_zip_security_rejects_symlink_depth_ratio_count_and_expanded_limits(tmp_path: Path, monkeypatch):
    symlink = zipfile.ZipInfo("Gerber/link.gbr")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    package = tmp_path / "symlink.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(symlink, "target.gbr")
    with pytest.raises(FabricationParseError, match="符号链接"):
        parse_fabrication_package(package, allow_ai=False)

    package.write_bytes(zip_bytes({"a/b/c/d/e/f/g/h/i/BOM.csv": "Designator,Value\nR1,10K"}))
    with pytest.raises(FabricationParseError, match="目录层级"):
        parse_fabrication_package(package, allow_ai=False)

    package.write_bytes(zip_bytes({"BOM.csv": "A" * 50_000}))
    with pytest.raises(FabricationParseError, match="压缩比异常"):
        parse_fabrication_package(package, allow_ai=False)

    monkeypatch.setattr(fabrication_parser, "MAX_ENTRIES", 2)
    package.write_bytes(zip_bytes({"a.csv": "a", "b.csv": "b", "c.csv": "c"}))
    with pytest.raises(FabricationParseError, match="文件数"):
        parse_fabrication_package(package, allow_ai=False)

    monkeypatch.setattr(fabrication_parser, "MAX_ENTRIES", 500)
    monkeypatch.setattr(fabrication_parser, "MAX_RATIO", 10_000)
    monkeypatch.setattr(fabrication_parser, "MAX_EXPANDED_BYTES", 10)
    package.write_bytes(zip_bytes({"BOM.csv": "Designator,Value\nR1,10K"}))
    with pytest.raises(FabricationParseError, match="展开后"):
        parse_fabrication_package(package, allow_ai=False)


def test_svg_sanitizer_removes_active_and_external_content():
    markup = """<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)" viewBox="0 0 10 10">
      <defs><path id="safe" d="M0 0L1 1" /></defs>
      <script>alert(1)</script><foreignObject><div>bad</div></foreignObject>
      <use href="#safe"/><use href="https://evil.example/x.svg#p"/>
      <a href="javascript:alert(1)"><rect width="5" height="5" /></a>
      <path d="M1 1L2 2" style="background:url(https://evil.example/x)" onclick="alert(2)"/>
    </svg>"""
    cleaned, bounds, warning = _sanitize_svg_markup("hostile.svg", markup)
    assert warning is None and cleaned and bounds["view_box"] == "0 0 10 10"
    assert "script" not in cleaned
    assert "foreignObject" not in cleaned
    assert "https:" not in cleaned
    assert "javascript:" not in cleaned
    assert "onload" not in cleaned and "onclick" not in cleaned and "style=" not in cleaned
    assert 'href="#safe"' in cleaned


def test_nc_drill_text_is_not_sent_to_ai_as_bom_or_cpl(tmp_path: Path, monkeypatch):
    package = tmp_path / "gerber-only.zip"
    package.write_bytes(zip_bytes({"PCB1-RoundHoles.TXT": "T1F00S00C0.300\nX100Y100", "PCB1.GM1": "%FSLAX46Y46*%\n%MOMM*%\nM02*%"}))
    called = False

    def unexpected_ai(_tables):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(fabrication_parser, "_ai_mapping", unexpected_ai)
    result = parse_fabrication_package(package, allow_ai=True)
    assert called is False
    assert result["mapping_required"] is True
    assert any("普通 Gerber" in warning for warning in result["warnings"])


def test_preview_is_non_mutating_then_activation_links_exact_designators(fabrication_env):
    client = fabrication_env["client"]
    response = client.post(
        "/api/projects/1/fabrication-revisions",
        files={"file": ("manufacturing.zip", manufacturing_zip(), "application/zip")},
    )
    assert response.status_code == 200
    revision_id = response.json()["id"]
    parse_queued_revision(fabrication_env, revision_id)
    db = fabrication_env["Session"]()
    assert db.get(Project, 1).active_fabrication_revision_id is None
    assert db.get(Component, 1).quantity == 10
    assert db.query(ProjectBomSolderPoint).filter(ProjectBomSolderPoint.bom_item_id == 1).count() == 2
    db.close()
    activated = client.post(f"/api/projects/1/fabrication-revisions/{revision_id}/commit", json={})
    assert activated.status_code == 200, activated.text
    assert activated.json()["result"]["linked_points"] == 2
    db = fabrication_env["Session"]()
    assert db.get(Project, 1).active_fabrication_revision_id == revision_id
    assert db.get(Component, 1).quantity == 10
    points = db.query(ProjectBomSolderPoint).filter(ProjectBomSolderPoint.bom_item_id == 1).all()
    assert {(point.designator_key, point.board_side) for point in points if point.active_for_assembly} == {("R1", "top"), ("R2", "bottom")}
    db.close()


def test_interrupted_parser_jobs_are_requeued_after_restart(fabrication_env):
    upload = fabrication_env["client"].post(
        "/api/projects/1/fabrication-revisions",
        files={"file": ("manufacturing.zip", manufacturing_zip(), "application/zip")},
    )
    assert upload.status_code == 200
    db = fabrication_env["Session"]()
    revision = db.get(ProjectFabricationRevision, upload.json()["id"])
    revision.status = "parsing"
    db.commit()
    assert recover_interrupted_revisions(db) == 1
    db.refresh(revision)
    assert revision.status == "queued"
    assert recover_interrupted_revisions(db) == 0
    db.close()


def test_personal_project_scope_isolated(fabrication_env):
    response = fabrication_env["client"].get(
        "/api/projects/1/fabrication-revisions",
        headers={"x-test-user": "2"},
    )
    assert response.status_code in {403, 404}


def test_manual_placement_side_change_updates_linked_point_and_resets(fabrication_env):
    upload_parse_activate(fabrication_env)
    client = fabrication_env["client"]
    view = client.get("/api/projects/1/assembly-view", params={"board_id": 1, "side": "top"}).json()
    r1 = next(item for item in view["placements"] if item["designator"] == "R1")
    changed = client.patch(
        f"/api/projects/1/fabrication-revisions/{view['revision']['id']}/placements/{r1['id']}",
        json={"x_mm": 18.2, "y_mm": 22.5, "board_side": "bottom", "rotation_deg": 135},
    )
    assert changed.status_code == 200, changed.text
    db = fabrication_env["Session"]()
    point = db.get(ProjectBomSolderPoint, r1["point_id"])
    assert point.board_side == "bottom" and point.state_version == r1["state_version"] + 1
    db.close()
    reset = client.patch(
        f"/api/projects/1/fabrication-revisions/{view['revision']['id']}/placements/{r1['id']}",
        json={"reset": True},
    )
    assert reset.status_code == 200
    assert reset.json()["board_side"] == "top"
    assert reset.json()["x_mm"] == pytest.approx(r1["source_x_mm"])
    assert reset.json()["rotation_deg"] == pytest.approx(r1["source_rotation_deg"])
    db = fabrication_env["Session"]()
    assert db.get(ProjectBomSolderPoint, r1["point_id"]).board_side == "top"
    db.close()


def test_version_move_preserves_history_and_identity_change_requires_confirmation(fabrication_env):
    upload_parse_activate(fabrication_env)
    client = fabrication_env["client"]
    view = client.get("/api/projects/1/assembly-view", params={"board_id": 1, "side": "top"}).json()
    first_revision_id = view["revision"]["id"]
    r1 = next(item for item in view["placements"] if item["designator"] == "R1")
    solder = client.post(
        "/api/projects/1/assembly-actions",
        json={"board_id": 1, "action": "solder", "point_ids": [r1["point_id"]], "versions": {str(r1["point_id"]): r1["state_version"]}, "idempotency_key": "version-history-solder"},
    )
    assert solder.status_code == 200

    moved_upload = client.post(
        "/api/projects/1/fabrication-revisions",
        files={"file": ("moved.zip", manufacturing_zip(r1_x="18.5mm"), "application/zip")},
    )
    moved_id = moved_upload.json()["id"]
    parse_queued_revision(fabrication_env, moved_id)
    moved_diff = client.get(f"/api/projects/1/fabrication-revisions/{moved_id}/diff").json()
    assert moved_diff["summary"]["moved"] >= 1 and moved_diff["summary"]["conflicts"] == 0
    assert client.post(f"/api/projects/1/fabrication-revisions/{moved_id}/commit", json={}).status_code == 200
    moved_view = client.get("/api/projects/1/assembly-view", params={"board_id": 1, "side": "top"}).json()
    moved_r1 = next(item for item in moved_view["placements"] if item["designator"] == "R1")
    assert moved_r1["soldered"] is True and moved_r1["point_id"] == r1["point_id"]

    changed_upload = client.post(
        "/api/projects/1/fabrication-revisions",
        files={"file": ("changed.zip", manufacturing_zip(r1_model="R-10K-NEW"), "application/zip")},
    )
    changed_id = changed_upload.json()["id"]
    parse_queued_revision(fabrication_env, changed_id)
    rejected = client.post(f"/api/projects/1/fabrication-revisions/{changed_id}/commit", json={})
    assert rejected.status_code == 409
    accepted = client.post(
        f"/api/projects/1/fabrication-revisions/{changed_id}/commit",
        json={"accept_conflicts": True},
    )
    assert accepted.status_code == 200, accepted.text
    db = fabrication_env["Session"]()
    old_point = db.get(ProjectBomSolderPoint, r1["point_id"])
    active_r1 = db.query(ProjectBomSolderPoint).filter(
        ProjectBomSolderPoint.board_id == 1,
        ProjectBomSolderPoint.designator_key == "R1",
        ProjectBomSolderPoint.active_for_assembly.is_(True),
    ).one()
    assert old_point.soldered is True and old_point.active_for_assembly is False
    assert active_r1.id != old_point.id and active_r1.soldered is False
    assert db.get(Component, 1).quantity == 9
    db.close()
    assert client.post(f"/api/projects/1/fabrication-revisions/{first_revision_id}/commit", json={}).status_code == 409
    switched_back = client.post(
        f"/api/projects/1/fabrication-revisions/{first_revision_id}/commit",
        json={"accept_conflicts": True},
    )
    assert switched_back.status_code == 200
    restored_view = client.get("/api/projects/1/assembly-view", params={"board_id": 1, "side": "top"}).json()
    restored_r1 = next(item for item in restored_view["placements"] if item["designator"] == "R1")
    assert restored_r1["point_id"] == r1["point_id"] and restored_r1["soldered"] is True


def test_assembly_actions_are_idempotent_cumulative_atomic_and_undoable(fabrication_env):
    upload_parse_activate(fabrication_env)
    client = fabrication_env["client"]
    view = client.get("/api/projects/1/assembly-view", params={"board_id": 1, "side": "top"}).json()
    r1 = next(item for item in view["placements"] if item["designator"] == "R1")
    solder_payload = {
        "board_id": 1,
        "action": "solder",
        "point_ids": [r1["point_id"]],
        "versions": {str(r1["point_id"]): r1["state_version"]},
        "idempotency_key": "solder-r1",
    }
    solder = client.post("/api/projects/1/assembly-actions", json=solder_payload)
    assert solder.status_code == 200, solder.text
    assert solder.json()["inventory_changes"][0]["delta"] == -1
    replay = client.post("/api/projects/1/assembly-actions", json=solder_payload)
    assert replay.status_code == 200 and replay.json()["idempotent_replay"] is True
    db = fabrication_env["Session"]()
    assert db.get(Component, 1).quantity == 9
    db.close()

    refreshed = client.get("/api/projects/1/assembly-view", params={"board_id": 1, "side": "top"}).json()
    r1 = next(item for item in refreshed["placements"] if item["designator"] == "R1")
    loss = client.post(
        "/api/projects/1/assembly-actions",
        json={"board_id": 1, "action": "loss", "point_ids": [r1["point_id"]], "versions": {str(r1["point_id"]): r1["state_version"]}, "idempotency_key": "loss-r1-1"},
    )
    assert loss.status_code == 200, loss.text
    assert loss.json()["inventory_changes"] == []
    db = fabrication_env["Session"]()
    assert db.get(Component, 1).quantity == 9
    point = db.get(ProjectBomSolderPoint, r1["point_id"])
    assert point.soldered is False and point.lost is True
    assert db.query(ProjectAssemblyLossEvent).filter(ProjectAssemblyLossEvent.solder_point_id == point.id, ProjectAssemblyLossEvent.reversed_at.is_(None)).count() == 1
    db.close()

    refreshed = client.get("/api/projects/1/assembly-view", params={"board_id": 1, "side": "top"}).json()
    r1 = next(item for item in refreshed["placements"] if item["designator"] == "R1")
    replacement = client.post(
        "/api/projects/1/assembly-actions",
        json={"board_id": 1, "action": "solder", "point_ids": [r1["point_id"]], "versions": {str(r1["point_id"]): r1["state_version"]}, "idempotency_key": "replacement-r1"},
    )
    assert replacement.status_code == 200
    refreshed = client.get("/api/projects/1/assembly-view", params={"board_id": 1, "side": "top"}).json()
    r1 = next(item for item in refreshed["placements"] if item["designator"] == "R1")
    second_loss = client.post(
        "/api/projects/1/assembly-actions",
        json={"board_id": 1, "action": "loss", "point_ids": [r1["point_id"]], "versions": {str(r1["point_id"]): r1["state_version"]}, "idempotency_key": "loss-r1-2"},
    )
    assert second_loss.status_code == 200
    db = fabrication_env["Session"]()
    assert db.get(Component, 1).quantity == 8
    assert db.query(ProjectAssemblyLossEvent).filter(ProjectAssemblyLossEvent.solder_point_id == r1["point_id"], ProjectAssemblyLossEvent.reversed_at.is_(None)).count() == 2
    db.close()
    undo = client.post(
        f"/api/projects/1/assembly-actions/{second_loss.json()['operation_id']}/undo",
        json={"idempotency_key": "undo-loss-r1-2"},
    )
    assert undo.status_code == 200, undo.text
    db = fabrication_env["Session"]()
    assert db.get(Component, 1).quantity == 8
    point = db.get(ProjectBomSolderPoint, r1["point_id"])
    assert point.soldered is True
    assert db.query(ProjectAssemblyLossEvent).filter(ProjectAssemblyLossEvent.solder_point_id == point.id, ProjectAssemblyLossEvent.reversed_at.is_(None)).count() == 1
    db.close()


def test_batch_shortage_and_stale_version_roll_back_entire_action(fabrication_env):
    upload_parse_activate(fabrication_env)
    client = fabrication_env["client"]
    db = fabrication_env["Session"]()
    component = db.get(Component, 1)
    component.quantity = 1
    points = db.query(ProjectBomSolderPoint).filter(ProjectBomSolderPoint.board_id == 1, ProjectBomSolderPoint.active_for_assembly.is_(True)).all()
    db.commit()
    versions = {str(point.id): point.state_version for point in points}
    point_ids = [point.id for point in points]
    db.close()
    shortage = client.post(
        "/api/projects/1/assembly-actions",
        json={"board_id": 1, "action": "solder", "point_ids": point_ids, "versions": versions, "idempotency_key": "shortage-batch"},
    )
    assert shortage.status_code == 409
    db = fabrication_env["Session"]()
    assert db.get(Component, 1).quantity == 1
    assert all(not db.get(ProjectBomSolderPoint, point_id).soldered for point_id in point_ids)
    db.close()
    stale = client.post(
        "/api/projects/1/assembly-actions",
        json={"board_id": 1, "action": "solder", "point_ids": [point_ids[0]], "versions": {str(point_ids[0]): 999}, "idempotency_key": "stale"},
    )
    assert stale.status_code == 409
    missing_version = client.post(
        "/api/projects/1/assembly-actions",
        json={"board_id": 1, "action": "solder", "point_ids": [point_ids[0]], "versions": {}, "idempotency_key": "missing-version"},
    )
    assert missing_version.status_code == 409


def test_team_editor_can_use_linked_member_stock_viewer_cannot(fabrication_env):
    db = fabrication_env["Session"]()
    db.query(ProjectBomSolderPoint).filter(ProjectBomSolderPoint.bom_item_id == 2).delete()
    db.commit()
    db.close()
    upload_parse_activate(fabrication_env, project_id=2, prefix="/api/team/libraries/lib-1/projects")
    client = fabrication_env["client"]
    view = client.get(
        "/api/team/libraries/lib-1/projects/2/assembly-view",
        params={"board_id": 2, "side": "top"},
        headers={"x-test-user": "2"},
    )
    assert view.status_code == 200 and view.json()["can_edit"] is True
    point = next(item for item in view.json()["placements"] if item["point_id"])
    viewer = client.post(
        "/api/team/libraries/lib-1/projects/2/assembly-actions",
        headers={"x-test-user": "3"},
        json={"board_id": 2, "action": "solder", "point_ids": [point["point_id"]], "versions": {str(point["point_id"]): point["state_version"]}, "idempotency_key": "viewer-denied"},
    )
    assert viewer.status_code == 403
    editor = client.post(
        "/api/team/libraries/lib-1/projects/2/assembly-actions",
        headers={"x-test-user": "2"},
        json={"board_id": 2, "action": "solder", "point_ids": [point["point_id"]], "versions": {str(point["point_id"]): point["state_version"]}, "idempotency_key": "editor-solder"},
    )
    assert editor.status_code == 200, editor.text
    db = fabrication_env["Session"]()
    operation = db.query(ProjectAssemblyOperation).filter(ProjectAssemblyOperation.id == editor.json()["operation_id"]).one()
    assert json.loads(operation.inventory_source_user_ids_json) == [1]
    assert db.get(Component, 1).quantity == 9
    db.close()


def test_public_assembly_is_opt_in_and_minimized(fabrication_env):
    upload_parse_activate(fabrication_env)
    client = fabrication_env["client"]
    closed = client.get("/api/public/projects/PJ-GERBER/assembly-view")
    assert closed.status_code == 404
    enabled = client.patch("/api/projects/1/assembly-public-setting", json={"enabled": True})
    assert enabled.status_code == 200
    public = client.get("/api/public/projects/PJ-GERBER/assembly-view")
    assert public.status_code == 200
    text = public.text
    assert "source_sha256" not in text
    assert '"mapping"' not in text
    assert "stock_quantity" not in text
    assert "stock_owner_user_id" not in text
    assert "source_name" not in text
    assert '"source_x_mm"' not in text
    assert '"bom_item_id"' not in text
    assert '"state_version"' not in text
    assert '"point_id"' not in text
