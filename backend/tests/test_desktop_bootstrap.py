import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Category, Component, CompetitionLibrary, CustomLabelAsset, CustomLabelTemplate, User
from app.services.desktop_bootstrap import import_desktop_bootstrap
from app.services.sync_bootstrap import create_personal_bootstrap


def test_personal_bootstrap_excludes_team_and_imports_files(tmp_path):
    server_root = tmp_path / "server"
    server_root.mkdir()
    server_db = server_root / "component_warehouse.db"
    server_engine = create_engine(f"sqlite:///{server_db}")
    Base.metadata.create_all(server_engine)
    ServerSession = sessionmaker(server_engine)
    session = ServerSession()
    session.add(User(id=1, phone="13800000001", nickname="个人用户", is_admin=True))
    session.add(Category(id=1, name="电阻"))
    session.add(Component(id=1, owner_user_id=1, category_id=1, name="10k 电阻", quantity=100))
    session.add(CompetitionLibrary(id="00000000-0000-0000-0000-000000000010", name="团队库", creator_user_id=1))
    template = CustomLabelTemplate(
        id="00000000-0000-0000-0000-000000000020",
        scope_type="personal",
        owner_user_id=1,
        name="标签",
        content_json="{}",
        created_by_user_id=1,
    )
    session.add(template)
    file_path = server_root / "custom-labels" / "personal" / "1" / "asset.svg"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("<svg>offline</svg>", encoding="utf-8")
    session.add(
        CustomLabelAsset(
            id="00000000-0000-0000-0000-000000000021",
            template_id=template.id,
            file_name="asset.svg",
            storage_path=str(file_path),
            mime_type="image/svg+xml",
            sha256=hashlib.sha256(file_path.read_bytes()).hexdigest(),
            size_bytes=file_path.stat().st_size,
        )
    )
    session.commit()

    package = create_personal_bootstrap(
        session,
        owner_user_id=1,
        data_root=server_root,
        server_instance_id="server-one",
        cursor=7,
        output_dir=server_root,
    )
    session.commit()
    session.close()

    desktop_root = tmp_path / "desktop"
    desktop_root.mkdir()
    desktop_db = desktop_root / "component_warehouse.db"
    desktop_engine = create_engine(f"sqlite:///{desktop_db}")
    Base.metadata.create_all(desktop_engine)
    desktop_engine.dispose()
    marker_path = desktop_root / "desktop-state.json"
    result = import_desktop_bootstrap(
        package,
        database_path=desktop_db,
        data_root=desktop_root,
        marker_path=marker_path,
    )
    assert result["cursor"] == 7
    assert json.loads(marker_path.read_text(encoding="utf-8"))["server_instance_id"] == "server-one"

    verify_engine = create_engine(f"sqlite:///{desktop_db}")
    VerifySession = sessionmaker(verify_engine)
    verify = VerifySession()
    assert verify.query(Component).one().name == "10k 电阻"
    assert verify.query(CompetitionLibrary).count() == 0
    asset = verify.query(CustomLabelAsset).one()
    assert Path(asset.storage_path).read_text(encoding="utf-8") == "<svg>offline</svg>"
    verify.close()
    verify_engine.dispose()
    server_engine.dispose()
