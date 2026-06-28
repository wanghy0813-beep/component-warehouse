from app.models import Component


def headers(user_id):
    return {"x-test-user": str(user_id)}


def test_mobile_scan_resolve_personal_and_ambiguity(team_env):
    client = team_env["client"]
    Session = team_env["Session"]
    db = Session()
    db.add(
        Component(
            name="移动扫码器件",
            warehouse_code="SEN-00000088",
            lcsc_number="C880088",
            quantity=9,
            owner_user_id=1,
        )
    )
    db.commit()
    db.close()

    resolved = client.post(
        "/api/mobile/v1/resolve",
        json={"value": "https://example.test/component-warehouse/personal/scan/SEN-00000088"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["component"]["id"] == "SEN-00000088"

    db = Session()
    db.add(
        Component(
            name="重复立创 ID",
            warehouse_code="SEN-00000089",
            lcsc_number="C880088",
            quantity=1,
            owner_user_id=2,
        )
    )
    db.commit()
    db.close()
    ambiguous = client.post("/api/mobile/v1/resolve", json={"value": "C880088"})
    assert ambiguous.status_code == 409
    assert ambiguous.json()["detail"]["code"] == "AMBIGUOUS_IDENTIFIER"


def test_mobile_team_link_requires_membership(team_env, created_library):
    client = team_env["client"]
    library_id = created_library["id"]
    parsed = client.post(
        "/api/mobile/v1/resolve",
        json={"value": f"https://example.test/component-warehouse/team/scan/{library_id}/item-id"},
    )
    assert parsed.status_code == 200
    assert parsed.json()["requires_auth"] is True
    assert parsed.json()["url"].startswith("/component-warehouse/team/scan/")
    denied = client.get(
        f"/api/mobile/v1/team/libraries/{library_id}/components/item-id",
        headers=headers(3),
    )
    assert denied.status_code == 404


def test_mobile_capabilities_are_public_and_versioned(team_env):
    response = team_env["client"].get("/api/mobile/v1/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["bridge_protocol"] == "1.0"
    assert data["application_root"] == "/component-warehouse"
    assert data["scan"]["batch_max"] == 50
    assert data["scan"]["supports_multiple_results"] is True
    assert "receiveNfc" in data["web_bridge"]["methods"]


def test_mobile_personal_batch_resolves_only_current_users_components(team_env):
    client = team_env["client"]
    Session = team_env["Session"]
    db = Session()
    db.add_all(
        [
            Component(
                name="用户一器件",
                warehouse_code="RES-00000101",
                lcsc_number="C101",
                quantity=4,
                owner_user_id=1,
            ),
            Component(
                name="用户二器件",
                warehouse_code="CAP-00000102",
                lcsc_number="C102",
                quantity=7,
                owner_user_id=2,
            ),
        ]
    )
    db.commit()
    db.close()

    response = client.post(
        "/api/mobile/v1/personal/resolve-batch",
        headers=headers(1),
        json={
            "values": [
                "https://example.test/component-warehouse/personal/scan/RES-00000101",
                "C102",
                "NOT-FOUND",
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["matched"] == 1
    assert [item["status"] for item in data["results"]] == [
        "matched",
        "not_found",
        "not_found",
    ]
    assert data["results"][0]["component"]["component_id"]


def test_mobile_team_batch_requires_membership_and_matches_current_library(
    team_env,
    created_library,
):
    client = team_env["client"]
    Session = team_env["Session"]
    library_id = created_library["id"]
    db = Session()
    component = Component(
        name="团队扫码器件",
        warehouse_code="SEN-00000103",
        lcsc_number="C103",
        quantity=8,
        owner_user_id=1,
    )
    db.add(component)
    db.commit()
    db.refresh(component)
    component_id = component.id
    db.close()

    created = client.post(
        f"/api/team/libraries/{library_id}/components",
        headers=headers(1),
        json={
            "cw_component_id": component_id,
            "name": component.name,
            "quantity": component.quantity,
        },
    )
    assert created.status_code == 200
    item = created.json()["item"]

    response = client.post(
        f"/api/mobile/v1/team/libraries/{library_id}/resolve-batch",
        headers=headers(1),
        json={
            "values": [
                "C103",
                (
                    "https://example.test/component-warehouse/team/scan/"
                    f"{library_id}/{item['id']}"
                ),
                "NOT-FOUND",
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["matched"] == 2
    assert data["results"][0]["component"]["id"] == item["id"]
    assert data["results"][1]["component"]["id"] == item["id"]
    assert data["results"][2]["status"] == "not_found"

    denied = client.post(
        f"/api/mobile/v1/team/libraries/{library_id}/resolve-batch",
        headers=headers(3),
        json={"values": ["C103"]},
    )
    assert denied.status_code == 404
