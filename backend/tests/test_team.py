import io

from openpyxl import Workbook
from sqlalchemy import event

from app import team
from app.models import (
    ActivityLog,
    Category,
    CompetitionActivityLog,
    CompetitionComponentMarker,
    CompetitionLibraryComponent,
    Component,
)


def headers(user_id):
    return {"x-test-user": str(user_id)}


def test_invite_join_remove_unblock_and_reset(team_env, created_library):
    client = team_env["client"]
    library_id = created_library["id"]
    invite = client.get(f"/api/team/libraries/{library_id}/invite").json()
    old_token = invite["token"]

    preview = client.get(f"/api/team/invites/{old_token}")
    assert preview.status_code == 200
    assert set(preview.json()["library"]) == {"id", "name"}

    joined = client.post(f"/api/team/invites/{old_token}/join", headers=headers(2))
    assert joined.status_code == 200
    assert joined.json()["library"]["role"] == "editor"

    removed = client.delete(
        f"/api/team/libraries/{library_id}/members/2",
        headers=headers(1),
    )
    assert removed.status_code == 200
    blocked = client.post(f"/api/team/invites/{old_token}/join", headers=headers(2))
    assert blocked.status_code == 403

    assert client.post(
        f"/api/team/libraries/{library_id}/members/2/unblock",
        headers=headers(1),
    ).status_code == 200
    assert client.post(f"/api/team/invites/{old_token}/join", headers=headers(2)).status_code == 403

    reset = client.post(
        f"/api/team/libraries/{library_id}/invite/reset",
        headers=headers(1),
    )
    assert reset.status_code == 200
    assert client.get(f"/api/team/invites/{old_token}").status_code == 404
    assert client.get(f"/api/team/invites/{reset.json()['token']}").status_code == 200
    assert client.post(
        f"/api/team/invites/{reset.json()['token']}/join",
        headers=headers(2),
    ).status_code == 200


def test_team_usage_event_writes_library_log(team_env, created_library):
    client = team_env["client"]
    Session = team_env["Session"]
    library_id = created_library["id"]
    response = client.post(
        f"/api/team/libraries/{library_id}/usage-events",
        headers=headers(1),
        json={
            "event": "ui.nav.click",
            "page": f"/library/{library_id}/components",
            "entry": "components",
            "target_type": "team_library",
            "target_id": library_id,
            "viewport_width": 1280,
        },
    )
    assert response.status_code == 200, response.text
    db = Session()
    try:
        log = db.query(CompetitionActivityLog).filter_by(library_id=library_id, action="ui.nav.click").one()
        assert log.entity_type == "team_library"
        assert log.entity_id == library_id
        assert "viewport_width" in log.after_json
    finally:
        db.close()


def test_team_lcsc_create_preserves_full_personal_component_and_reuses_duplicate(team_env, created_library):
    client = team_env["client"]
    Session = team_env["Session"]
    library_id = created_library["id"]
    db = Session()
    db.add(Category(name="电源", code_prefix="PWR"))
    db.commit()
    db.close()

    payload = {
        "name": "LP5907MFX-3.3/NOPB 3.3V 250mA LDO",
        "model": "LP5907MFX-3.3/NOPB",
        "manufacturer": "TI",
        "description": "250mA low-noise LDO",
        "lcsc_number": "c80670",
        "quantity": 0,
        "category": "电源",
        "package": "SOT-23-5",
        "parameters": "Output Voltage 3.3V；Output Current 250mA",
        "datasheet_url": "https://datasheet.lcsc.com/datasheet/pdf/example.pdf?productCode=C80670",
        "buy_url": "https://www.lcsc.com/product-detail/C80670.html",
        "source": "立创",
        "source_title": "TI LP5907MFX-3.3/NOPB",
        "tags": "低噪声,低静态电流",
    }
    first = client.post(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(1),
        json=payload,
    )
    assert first.status_code == 200, first.text
    item = first.json()["item"]
    assert item["manufacturer"] == "TI"
    assert item["description"] == "250mA low-noise LDO"
    assert item["buy_url"].endswith("/C80670.html")
    assert item["datasheet_url"].endswith("productCode=C80670")

    db = Session()
    component = db.query(Component).filter_by(owner_user_id=1, lcsc_number="C80670").one()
    assert component.category.name == "电源"
    assert component.source == "立创"
    assert component.source_title == "TI LP5907MFX-3.3/NOPB"
    component_id = component.id
    db.close()

    duplicate = client.post(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(1),
        json={**payload, "name": "不应创建的新名称"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["merged"] is True
    assert duplicate.json()["item"]["cw_component_id"] == component_id
    db = Session()
    assert db.query(Component).filter_by(owner_user_id=1, lcsc_number="C80670").count() == 1
    db.close()


def test_member_edit_captain_permissions_link_merge_and_logs(team_env, created_library):
    client = team_env["client"]
    Session = team_env["Session"]
    library_id = created_library["id"]
    token = client.get(f"/api/team/libraries/{library_id}/invite").json()["token"]
    client.post(f"/api/team/invites/{token}/join", headers=headers(2))

    db = Session()
    cw = Component(
        name="精密运放",
        model="OPA2333",
        lcsc_number="C123456",
        quantity=10,
        warehouse_code="CW-00000001",
        owner_user_id=2,
    )
    captain_cw = Component(
        name="队长的精密运放",
        model="OPA2333",
        lcsc_number="C654321",
        quantity=6,
        warehouse_code="CW-00000002",
        owner_user_id=1,
    )
    db.add_all([cw, captain_cw])
    db.commit()
    db.refresh(cw)
    cw_id = cw.id
    captain_cw_id = captain_cw.id
    db.close()

    first = client.post(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(2),
        json={"name": "OPA2333", "lcsc_number": "C123456", "quantity": 2},
    )
    assert first.status_code == 200
    assert first.json()["item"]["cw_component_id"] == cw_id
    assert first.json()["item"]["source_user_id"] == 2
    assert first.json()["item"]["sync_status"] == "live"
    assert first.json()["item"]["quantity"] == 10

    merged = client.post(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(2),
        json={"name": "同一物料", "lcsc_number": "C123456", "quantity": 3, "remark": "第二批"},
    )
    assert merged.json()["merged"] is True
    assert merged.json()["item"]["quantity"] == 10

    loose = client.post(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(2),
        json={"name": "待关联运放", "quantity": 4, "remark": "手工录入"},
    ).json()["item"]
    link = client.post(
        f"/api/team/libraries/{library_id}/components/{loose['id']}/link",
        headers=headers(2),
        json={"cw_component_id": cw_id},
    )
    assert link.json()["merged"] is True
    assert link.json()["item"]["quantity"] == 10

    db = Session()
    db.get(Component, cw_id).quantity = 17
    db.commit()
    db.close()
    live = client.get(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(2),
    ).json()["items"][0]
    assert live["quantity"] == 17
    assert live["available_quantity"] == 17

    forbidden = client.delete(
        f"/api/team/libraries/{library_id}/members/1",
        headers=headers(2),
    )
    assert forbidden.status_code == 403

    removed = client.delete(
        f"/api/team/libraries/{library_id}/members/2",
        headers=headers(1),
    )
    assert removed.status_code == 200
    frozen = client.get(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(1),
    ).json()["items"][0]
    assert frozen["sync_status"] == "frozen"
    assert frozen["cw_component_id"] is None
    assert frozen["quantity"] == 17

    db = Session()
    db.get(Component, cw_id).quantity = 99
    db.commit()
    db.close()
    still_frozen = client.get(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(1),
    ).json()["items"][0]
    assert still_frozen["quantity"] == 17

    rebound = client.post(
        f"/api/team/libraries/{library_id}/components/{frozen['id']}/rebind",
        headers=headers(1),
        json={"cw_component_id": captain_cw_id},
    )
    assert rebound.status_code == 200
    assert rebound.json()["item"]["sync_status"] == "live"
    assert rebound.json()["item"]["source_user_id"] == 1
    assert rebound.json()["item"]["quantity"] == 6

    db = Session()
    actions = {
        row.action
        for row in db.query(CompetitionActivityLog)
        .filter(CompetitionActivityLog.library_id == library_id)
        .all()
    }
    assert {
        "member.join",
        "member.remove",
        "component.create",
        "component.merge",
        "component.link_merge",
        "component.link",
    } <= actions
    assert db.query(CompetitionLibraryComponent).filter_by(library_id=library_id).count() == 1
    db.close()


def test_quantity_sync_permissions_and_shared_markers(team_env, created_library):
    client = team_env["client"]
    Session = team_env["Session"]
    library_id = created_library["id"]
    invite = client.get(f"/api/team/libraries/{library_id}/invite").json()["token"]
    assert client.post(f"/api/team/invites/{invite}/join", headers=headers(2)).status_code == 200
    assert client.post(f"/api/team/invites/{invite}/join", headers=headers(3)).status_code == 200

    db = Session()
    component = Component(
        name="同步测试器件",
        quantity=5,
        warehouse_code="MN-00000999",
        owner_user_id=2,
    )
    db.add(component)
    db.commit()
    db.refresh(component)
    component_id = component.id
    db.close()

    item = client.post(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(2),
        json={"cw_component_id": component_id, "name": component.name, "quantity": 5},
    ).json()["item"]

    forbidden = client.patch(
        f"/api/team/libraries/{library_id}/components/{item['id']}/quantity",
        headers=headers(3),
        json={"quantity": 8},
    )
    assert forbidden.status_code == 403

    updated = client.patch(
        f"/api/team/libraries/{library_id}/components/{item['id']}/quantity",
        headers=headers(1),
        json={"quantity": 12, "remark": "队长盘点"},
    )
    assert updated.status_code == 200
    assert updated.json()["quantity"] == 12

    marker = client.post(
        f"/api/team/libraries/{library_id}/components/{item['id']}/markers",
        headers=headers(3),
        json={"category": "需复核", "color": "#F97316", "flagged": True, "note": "检查封装"},
    )
    assert marker.status_code == 200
    marker_id = marker.json()["id"]
    edited = client.put(
        f"/api/team/libraries/{library_id}/components/{item['id']}/markers/{marker_id}",
        headers=headers(2),
        json={"category": "已复核", "color": "#22C55E", "flagged": False},
    )
    assert edited.status_code == 200
    filtered = client.get(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(1),
        params={"marker_category": "已复核", "marker_color": "#22C55E", "flagged": False},
    ).json()
    assert filtered["total"] == 1

    invalid_color = client.post(
        f"/api/team/libraries/{library_id}/components/{item['id']}/markers",
        headers=headers(3),
        json={"category": "非法颜色", "color": "#123456", "flagged": False},
    )
    assert invalid_color.status_code == 422

    db = Session()
    assert db.get(Component, component_id).quantity == 12
    assert db.query(ActivityLog).filter_by(component_id=component_id).count() == 1
    assert db.query(CompetitionActivityLog).filter_by(
        library_id=library_id,
        action="component.quantity.update",
    ).count() == 1
    assert db.query(CompetitionComponentMarker).filter_by(id=marker_id).count() == 1
    db.close()


def test_import_all_my_components_endpoint_is_removed(team_env, created_library):
    client = team_env["client"]
    library_id = created_library["id"]
    response = client.post(
        f"/api/team/libraries/{library_id}/components/import-all-mine",
        headers=headers(1),
    )
    assert response.status_code == 410


def test_team_category_paging_never_truncates_a_loaded_category(team_env, created_library):
    client = team_env["client"]
    Session = team_env["Session"]
    library_id = created_library["id"]
    db = Session()
    first_category = Category(name="完整类别甲", code_prefix="X91")
    second_category = Category(name="完整类别乙", code_prefix="X92")
    db.add_all([first_category, second_category])
    db.flush()
    components = [
        Component(
            name=f"甲-{index}",
            warehouse_code=f"X91-{index + 1:08d}",
            quantity=index + 1,
            category=first_category,
            owner_user_id=1,
        )
        for index in range(7)
    ] + [
        Component(
            name="乙-1",
            warehouse_code="X92-00000008",
            quantity=1,
            category=second_category,
            owner_user_id=1,
        )
    ]
    db.add_all(components)
    db.flush()
    db.add_all([
        CompetitionLibraryComponent(
            id=f"complete-category-{index}",
            library_id=library_id,
            cw_component_id=component.id,
            source_user_id=1,
            sync_status="live",
            warehouse_code_snapshot=component.warehouse_code,
            name=component.name,
            quantity=component.quantity,
            created_by_user_id=1,
            updated_by_user_id=1,
        )
        for index, component in enumerate(components)
    ])
    db.commit()
    db.close()

    select_count = 0

    def count_selects(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(team_env["engine"], "before_cursor_execute", count_selects)
    try:
        first_page = client.get(
            f"/api/team/libraries/{library_id}/components",
            headers=headers(1),
            params={"page": 1, "page_size": 1},
        ).json()
    finally:
        event.remove(team_env["engine"], "before_cursor_execute", count_selects)
    assert first_page["category_total"] == 2
    assert first_page["has_more"] is True
    assert len(first_page["groups"]) == 1
    expected_count = {"完整类别甲": 7, "完整类别乙": 1}[first_page["groups"][0]["name"]]
    assert len(first_page["groups"][0]["items"]) == expected_count
    assert len(first_page["items"]) == len(first_page["groups"][0]["items"])
    assert select_count <= 9

    captain_export = client.post(
        f"/api/team/libraries/{library_id}/components/export/label-sheet",
        headers=headers(1),
    )
    assert captain_export.status_code == 200
    assert "A4 直角 40 格" in captain_export.text
    assert "grid-template-columns: repeat(4, 52.5mm)" in captain_export.text
    assert "grid-template-rows: repeat(10, 29.7mm)" in captain_export.text

    category_filtered_export = client.post(
        f"/api/team/libraries/{library_id}/components/export/label-sheet",
        headers=headers(1),
        json={"excluded_categories": ["完整类别甲"]},
    )
    assert category_filtered_export.status_code == 200
    assert "甲-0" not in category_filtered_export.text
    assert "X91-00000001" not in category_filtered_export.text
    assert "乙-1" in category_filtered_export.text
    assert "X92-00000008" in category_filtered_export.text

    date_filtered_export = client.post(
        f"/api/team/libraries/{library_id}/components/export/label-sheet",
        headers=headers(1),
        json={"imported_from": "2999-01-01", "imported_to": "2999-01-01"},
    )
    assert date_filtered_export.status_code == 200
    assert "甲-0" not in date_filtered_export.text
    assert "X91-00000001" not in date_filtered_export.text

    custom_label = client.post(
        f"/api/team/libraries/{library_id}/custom-labels",
        headers=headers(1),
        json={"name": "团队纸盒", "content": {"elements": [{"type": "text", "text": "团队自定义标签"}]}},
    )
    assert custom_label.status_code == 200
    appended_export = client.post(
        f"/api/team/libraries/{library_id}/components/export/label-sheet",
        headers=headers(1),
        json={"custom_labels": [{"template_id": custom_label.json()["id"], "copies": 2}]},
    )
    assert appended_export.status_code == 200
    assert appended_export.text.index("X91-00000001") < appended_export.text.index("团队自定义标签")
    assert appended_export.text.count("团队自定义标签") == 2

    invite = client.get(f"/api/team/libraries/{library_id}/invite").json()["token"]
    client.post(f"/api/team/invites/{invite}/join", headers=headers(2))
    member_export = client.post(
        f"/api/team/libraries/{library_id}/components/export/label-sheet",
        headers=headers(2),
    )
    assert member_export.status_code == 403


def test_csv_xlsx_import_pcb_image_permission_and_ai_cache(team_env, created_library, monkeypatch):
    client = team_env["client"]
    library_id = created_library["id"]
    token = client.get(f"/api/team/libraries/{library_id}/invite").json()["token"]
    client.post(f"/api/team/invites/{token}/join", headers=headers(2))

    csv_content = "名称,型号,立创 ID,数量,位置,分类,标签,备注\n电阻,10k,,20,A盒,阻容,常用,测试\n".encode("utf-8-sig")
    imported = client.post(
        f"/api/team/libraries/{library_id}/components/import",
        headers=headers(2),
        files={"file": ("team.csv", csv_content, "text/csv")},
    )
    assert imported.status_code == 200
    assert imported.json()["created"] == 1

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["名称", "型号", "立创 ID", "数量", "位置", "分类", "标签", "备注"])
    sheet.append(["陶瓷电容", "100nF", "", 12, "B盒", "阻容", "常用", "XLSX 导入"])
    xlsx_content = io.BytesIO()
    workbook.save(xlsx_content)
    imported_xlsx = client.post(
        f"/api/team/libraries/{library_id}/components/import",
        headers=headers(2),
        files={
            "file": (
                "team.xlsx",
                xlsx_content.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert imported_xlsx.status_code == 200
    assert imported_xlsx.json()["created"] == 1

    pcb = client.post(
        f"/api/team/libraries/{library_id}/pcbs",
        headers=headers(2),
        json={"name": "主控板", "status": "可用", "quantity": 1},
    ).json()
    image = client.post(
        f"/api/team/libraries/{library_id}/pcbs/{pcb['id']}/images/front",
        headers=headers(2),
        files={"file": ("front.png", b"\x89PNG\r\n\x1a\nsmall", "image/png")},
    )
    assert image.status_code == 200
    assert client.get(
        f"/api/team/libraries/{library_id}/pcbs/{pcb['id']}/images/front",
        headers=headers(3),
    ).status_code == 404
    oversized = client.post(
        f"/api/team/libraries/{library_id}/pcbs/{pcb['id']}/images/back",
        headers=headers(2),
        files={"file": ("back.png", b"x" * (team.MAX_PCB_IMAGE_BYTES + 1), "image/png")},
    )
    assert oversized.status_code == 413

    calls = {"count": 0}

    def fake_ai(*args, **kwargs):
        calls["count"] += 1
        return {
            "answer": "优先使用库内 10k 电阻",
            "component_matches": [],
            "pcb_matches": [],
            "next_steps": [],
            "requires_confirmation": True,
        }

    monkeypatch.setattr(team, "contest_library_assist", fake_ai)
    payload = {"query_type": "find_components", "prompt": "找一个 10k 电阻"}
    first = client.post(
        f"/api/team/libraries/{library_id}/ai",
        headers=headers(2),
        json=payload,
    )
    second = client.post(
        f"/api/team/libraries/{library_id}/ai",
        headers=headers(2),
        json=payload,
    )
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert calls["count"] == 1


def test_team_projects_roles_usage_purchase_and_receipt(team_env, created_library):
    client = team_env["client"]
    Session = team_env["Session"]
    library_id = created_library["id"]
    invite = client.get(f"/api/team/libraries/{library_id}/invite").json()["token"]
    assert client.post(f"/api/team/invites/{invite}/join", headers=headers(2)).status_code == 200
    assert client.put(
        f"/api/team/libraries/{library_id}/members/2/role",
        headers=headers(1),
        json={"role": "viewer"},
    ).status_code == 200
    assert client.post(
        f"/api/team/libraries/{library_id}/projects",
        headers=headers(2),
        json={"name": "只读用户不能创建"},
    ).status_code == 403
    assert client.get(f"/api/team/libraries/{library_id}/projects", headers=headers(2)).status_code == 200
    assert client.put(
        f"/api/team/libraries/{library_id}/members/2/role",
        headers=headers(1),
        json={"role": "editor"},
    ).status_code == 200

    db = Session()
    component = Component(
        name="团队项目芯片",
        model="TEAM-IC-1",
        quantity=1,
        safety_quantity=3,
        warehouse_code="TEAM-00000001",
        owner_user_id=2,
    )
    db.add(component)
    db.commit()
    component_id = component.id
    component_name = component.name
    db.close()
    team_item = client.post(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(2),
        json={"cw_component_id": component_id, "name": component_name, "quantity": 1},
    ).json()["item"]
    project = client.post(
        f"/api/team/libraries/{library_id}/projects",
        headers=headers(2),
        json={"name": "团队测试板", "status": "designing"},
    ).json()
    added = client.post(
        f"/api/team/libraries/{library_id}/projects/{project['id']}/bom",
        headers=headers(2),
        json={"component_id": component_id, "required_quantity": 5, "remark": "U1,U2,U3,U4,U5"},
    )
    assert added.status_code == 200
    usage = client.get(
        f"/api/team/libraries/{library_id}/components/{team_item['id']}/usage-records",
        headers=headers(1),
    ).json()
    assert usage[0]["project_name"] == "团队测试板"
    assert usage[0]["designators"] == ["U1", "U2", "U3", "U4", "U5"]

    order = client.post(
        f"/api/team/libraries/{library_id}/purchases/from-project/{project['id']}",
        headers=headers(2),
        json={"platform": "LCSC"},
    )
    assert order.status_code == 200, order.text
    line = order.json()["lines"][0]
    assert line["ordered_quantity"] == 7
    assert line["receiver_user_id"] == 2
    receipt = client.post(
        f"/api/team/libraries/{library_id}/purchases/lines/{line['id']}/receive",
        headers=headers(1),
        json={"quantity": 2, "location": "A1", "note": "部分到货"},
    )
    assert receipt.status_code == 200
    db = Session()
    assert db.get(Component, component_id).quantity == 3
    db.close()
