import base64
import hashlib
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytest.importorskip("mcp")

from jsonschema import Draft202012Validator
from starlette.testclient import TestClient

from app import codex_mcp
from app.database import Base
from app.models import ActivityLog, Category, Component, IntegrationOperation, PersonalProjectV2, User


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def _register(client: TestClient, redirect_uri: str = "https://chatgpt.com/connector/oauth/component-test") -> str:
    response = client.post(
        "/register",
        json={
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_name": "ChatGPT WXY LAB Hardware Test",
            "scope": "inventory:read operations:propose operations:execute",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


def _link(client: TestClient, client_id: str, scope: str = "inventory:read operations:execute") -> dict:
    redirect_uri = "https://chatgpt.com/connector/oauth/component-test"
    verifier = "component-warehouse-test-verifier-" + "x" * 48
    authorize = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": "state-value",
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "scope": scope,
            "resource": codex_mcp.MCP_RESOURCE_URL,
        },
        follow_redirects=False,
    )
    assert authorize.status_code == 302, authorize.text
    request_id = authorize.headers["location"].rstrip("/").split("/")[-1]
    preview = client.get(f"/approval/{request_id}")
    assert preview.status_code == 200, preview.text
    assert preview.json()["scopes"] == scope.split()
    approval = client.post(f"/approval/{request_id}", json={"decision": "approve"})
    assert approval.status_code == 200, approval.text
    callback = urlparse(approval.json()["redirect_url"])
    callback_query = parse_qs(callback.query)
    assert callback.netloc == "chatgpt.com"
    assert callback_query["state"] == ["state-value"]
    token = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": callback_query["code"][0],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "resource": codex_mcp.MCP_RESOURCE_URL,
        },
    )
    assert token.status_code == 200, token.text
    payload = token.json()
    payload["_authorization_code"] = callback_query["code"][0]
    payload["_code_verifier"] = verifier
    return payload


def _mcp_request(client: TestClient, access_token: str, method: str, params: dict | None = None):
    response = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _tool_payload(result: dict) -> dict:
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


def _assert_tool_output(tool_descriptors: dict[str, dict], tool_name: str, payload: dict) -> None:
    Draft202012Validator(tool_descriptors[tool_name]["outputSchema"]).validate(payload)


def test_oauth_mcp_flow_is_scoped_rotated_and_browser_approved(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'component-mcp.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    with Session() as db:
        db.add_all(
            [
                User(id=1, phone="13800000001", nickname="库主"),
                User(id=2, phone="13800000002", nickname="其他用户"),
                Category(id=1, name="电阻", color="#fff", code_prefix="RES", code_prefix_locked=True),
                Component(
                    id=1,
                    owner_user_id=1,
                    warehouse_code="RES-00000001",
                    name="10k 电阻",
                    model="RC0603FR-0710KL",
                    normalized_spec="10kΩ",
                    parameters="10kΩ 1%",
                    package="0603",
                    quantity=20,
                    category_id=1,
                ),
                Component(
                    id=2,
                    owner_user_id=2,
                    warehouse_code="RES-00000002",
                    name="其他用户私有器件",
                    model="PRIVATE-ONLY",
                    package="0603",
                    quantity=500,
                    category_id=1,
                ),
                PersonalProjectV2(
                    id="11111111-1111-4111-8111-111111111111",
                    owner_user_id=1,
                    project_code="PRJ-MCP-SEED",
                    name="MCP 现有项目",
                    status="active",
                    start_date=date(2026, 1, 1),
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(codex_mcp, "SessionLocal", Session)
    monkeypatch.setattr(codex_mcp.auth_module, "AUTH_MODE", "account-v1")
    monkeypatch.setattr(codex_mcp.auth_module, "NO_AUTH_USER_ID", 1)

    with TestClient(codex_mcp.app, base_url="https://wxylab.ltd") as client:
        authorization_metadata = client.get("/.well-known/oauth-authorization-server")
        assert authorization_metadata.status_code == 200
        assert authorization_metadata.json()["token_endpoint_auth_methods_supported"] == ["none"]
        protected_metadata = client.get("/.well-known/oauth-protected-resource/hardware/mcp")
        assert protected_metadata.status_code == 200
        assert protected_metadata.json()["resource"] == codex_mcp.MCP_RESOURCE_URL
        assert codex_mcp.MCP_RESOURCE_URL.endswith("/hardware/mcp")
        assert any(value.endswith("/component-warehouse/mcp") for value in codex_mcp.MCP_LEGACY_RESOURCE_URLS)

        auth_client_id = _register(client)
        protected_authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": auth_client_id,
                "redirect_uri": "https://chatgpt.com/connector/oauth/component-test",
                "state": "protected-state",
                "code_challenge": _pkce_challenge("protected-verifier-" + "x" * 48),
                "code_challenge_method": "S256",
                "scope": "inventory:read operations:propose",
                "resource": codex_mcp.MCP_RESOURCE_URL,
            },
            follow_redirects=False,
        )
        protected_request_id = protected_authorize.headers["location"].rstrip("/").split("/")[-1]
        assert client.get(f"/approval/{protected_request_id}").status_code == 401
        monkeypatch.setattr(codex_mcp.auth_module, "AUTH_MODE", "none")

        invalid_registration = client.post(
            "/register",
            json={
                "redirect_uris": ["https://attacker.example/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert invalid_registration.status_code == 400

        client_id = _register(client)
        tokens = _link(client, client_id)
        assert tokens["access_token"].startswith("cw_mcp_at_")
        assert tokens["refresh_token"].startswith("cw_mcp_rt_")
        reused_code = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": tokens["_authorization_code"],
                "redirect_uri": "https://chatgpt.com/connector/oauth/component-test",
                "code_verifier": tokens["_code_verifier"],
                "resource": codex_mcp.MCP_RESOURCE_URL,
            },
        )
        assert reused_code.status_code == 400
        assert reused_code.json()["error"] == "invalid_grant"

        tools = _mcp_request(client, tokens["access_token"], "tools/list")["tools"]
        tool_descriptors = {tool["name"]: tool for tool in tools}
        assert set(tool_descriptors) == {
            "warehouse_session",
            "list_workspace_datasets",
            "read_workspace_dataset",
            "list_inventory_categories",
            "search_inventory",
            "get_inventory_component",
            "match_inventory",
            "list_inventory_projects",
            "get_inventory_project",
            "list_inventory_risks",
            "list_inventory_purchases",
            "execute_reversible_operation",
            "undo_reversible_operation",
            "propose_operation",
            "get_operation_state",
            "propose_operation_undo",
        }
        for descriptor in tool_descriptors.values():
            assert descriptor.get("outputSchema")
            Draft202012Validator.check_schema(descriptor["outputSchema"])
        search_descriptor = tool_descriptors["search_inventory"]
        match_descriptor = tool_descriptors["match_inventory"]
        proposal_descriptor = tool_descriptors["propose_operation"]
        execute_descriptor = tool_descriptors["execute_reversible_operation"]
        assert search_descriptor["securitySchemes"] == [{"type": "oauth2", "scopes": ["inventory:read"]}]
        assert proposal_descriptor["securitySchemes"] == [{"type": "oauth2", "scopes": ["inventory:read"]}]
        assert execute_descriptor["securitySchemes"] == [
            {"type": "oauth2", "scopes": ["inventory:read", "operations:execute"]}
        ]
        assert execute_descriptor["annotations"]["destructiveHint"] is False
        match_item_schema = match_descriptor["inputSchema"]["properties"]["items"]["items"]
        action_schema = proposal_descriptor["inputSchema"]["properties"]["actions"]["items"]
        assert match_item_schema.get("additionalProperties") is not True
        assert action_schema.get("additionalProperties") is not True
        assert "manufacturer_part" in match_item_schema.get("properties", {})
        assert {"action", "payload"}.issubset(action_schema.get("properties", {}))

        session_payload = _tool_payload(
            _mcp_request(client, tokens["access_token"], "tools/call", {"name": "warehouse_session"})
        )
        _assert_tool_output(tool_descriptors, "warehouse_session", session_payload)
        assert session_payload["service_name"] == "WXY LAB Hardware"
        assert session_payload["read_mode"] == "full_personal_workspace"
        assert session_payload["write_mode"] == "chatgpt_risk_direct_with_undo"
        assert session_payload["direct_write"] is True

        workspace_payload = _tool_payload(
            _mcp_request(client, tokens["access_token"], "tools/call", {"name": "list_workspace_datasets"})
        )
        _assert_tool_output(tool_descriptors, "list_workspace_datasets", workspace_payload)
        assert workspace_payload["service_name"] == "WXY LAB Hardware"
        assert workspace_payload["complete_personal_read"] is True
        assert "users" not in {row["dataset"] for row in workspace_payload["datasets"]}

        category_payload = _tool_payload(
            _mcp_request(client, tokens["access_token"], "tools/call", {"name": "list_inventory_categories"})
        )
        _assert_tool_output(tool_descriptors, "list_inventory_categories", category_payload)
        assert category_payload["classification_standard"] == "WXY LAB Hardware 17-zone"

        workspace_components = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "read_workspace_dataset", "arguments": {"dataset": "components", "limit": 1}},
            )
        )
        _assert_tool_output(tool_descriptors, "read_workspace_dataset", workspace_components)
        assert workspace_components["total"] == 1
        assert workspace_components["items"][0]["warehouse_code"] == "RES-00000001"
        assert "owner_user_id" not in workspace_components["items"][0]

        own_search = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "search_inventory", "arguments": {"query": "10k", "stock": "available"}},
            )
        )
        _assert_tool_output(tool_descriptors, "search_inventory", own_search)
        assert [row["warehouse_code"] for row in own_search["items"]] == ["RES-00000001"]
        private_search = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "search_inventory", "arguments": {"query": "PRIVATE-ONLY"}},
            )
        )
        assert private_search["items"] == []

        component_detail = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "get_inventory_component", "arguments": {"warehouse_code": "RES-00000001"}},
            )
        )
        _assert_tool_output(tool_descriptors, "get_inventory_component", component_detail)

        match_payload = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {
                    "name": "match_inventory",
                    "arguments": {
                        "items": [
                            {
                                "designator": "R1",
                                "quantity": 2,
                                "manufacturer_part": "RC0603FR-0710KL",
                                "value": "10kΩ",
                                "footprint": "0603",
                            }
                        ]
                    },
                },
            )
        )
        _assert_tool_output(tool_descriptors, "match_inventory", match_payload)

        projects_payload = _tool_payload(
            _mcp_request(client, tokens["access_token"], "tools/call", {"name": "list_inventory_projects"})
        )
        _assert_tool_output(tool_descriptors, "list_inventory_projects", projects_payload)
        project_payload = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "get_inventory_project", "arguments": {"project_id": "PRJ-MCP-SEED"}},
            )
        )
        _assert_tool_output(tool_descriptors, "get_inventory_project", project_payload)

        risks_payload = _tool_payload(
            _mcp_request(client, tokens["access_token"], "tools/call", {"name": "list_inventory_risks"})
        )
        _assert_tool_output(tool_descriptors, "list_inventory_risks", risks_payload)
        purchases_payload = _tool_payload(
            _mcp_request(client, tokens["access_token"], "tools/call", {"name": "list_inventory_purchases"})
        )
        _assert_tool_output(tool_descriptors, "list_inventory_purchases", purchases_payload)

        proposal = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {
                    "name": "propose_operation",
                    "arguments": {
                        "idempotency_key": "mcp-project-proposal-001",
                        "reason": "MCP test proposal",
                        "actions": [
                            {
                                "action": "workspace.project.create",
                                "payload": {"project_code": "PRJ-MCP-TEST", "name": "MCP 测试项目"},
                            }
                        ],
                    },
                },
            )
        )
        _assert_tool_output(tool_descriptors, "propose_operation", proposal)
        assert proposal["status"] == "pending_approval"
        assert proposal["approval_url"].startswith(
            "https://wxylab.ltd/hardware/integrations/codex/operations/"
        )
        with Session() as db:
            assert db.query(PersonalProjectV2).filter(PersonalProjectV2.project_code == "PRJ-MCP-TEST").count() == 0
            assert db.query(IntegrationOperation).filter(IntegrationOperation.status == "pending_approval").count() == 1

        direct_arguments = {
            "idempotency_key": "mcp-project-direct-001",
            "reason": "MCP direct reversible test",
            "actions": [
                {
                    "action": "workspace.project.create",
                    "payload": {"project_code": "PRJ-MCP-DIRECT", "name": "MCP 直接执行测试项目"},
                }
            ],
        }
        direct = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "execute_reversible_operation", "arguments": direct_arguments},
            )
        )
        _assert_tool_output(tool_descriptors, "execute_reversible_operation", direct)
        assert direct["status"] == "succeeded"
        assert direct["undo_expires_at"]
        replay = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "execute_reversible_operation", "arguments": direct_arguments},
            )
        )
        assert replay["id"] == direct["id"]
        with Session() as db:
            assert db.query(PersonalProjectV2).filter(PersonalProjectV2.project_code == "PRJ-MCP-DIRECT").count() == 1
            assert db.query(ActivityLog).filter(ActivityLog.action == "chatgpt_operation_executed").count() == 1

        undone = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "undo_reversible_operation", "arguments": {"operation_id": direct["id"]}},
            )
        )
        _assert_tool_output(tool_descriptors, "undo_reversible_operation", undone)
        assert undone["status"] == "succeeded"
        with Session() as db:
            original = db.get(IntegrationOperation, direct["id"])
            project = db.query(PersonalProjectV2).filter(PersonalProjectV2.project_code == "PRJ-MCP-DIRECT").one()
            assert original.status == "undone"
            assert project.archived_at is not None
            assert db.query(ActivityLog).filter(ActivityLog.action == "chatgpt_operation_undone").count() == 1

        operation_state = _tool_payload(
            _mcp_request(
                client,
                tokens["access_token"],
                "tools/call",
                {"name": "get_operation_state", "arguments": {"operation_id": proposal["id"]}},
            )
        )
        _assert_tool_output(tool_descriptors, "get_operation_state", operation_state)

        refreshed = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": tokens["refresh_token"],
                "resource": codex_mcp.MCP_RESOURCE_URL,
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["refresh_token"] != tokens["refresh_token"]

        replay = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": tokens["refresh_token"],
                "resource": codex_mcp.MCP_RESOURCE_URL,
            },
        )
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"
        revoked_access = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {refreshed.json()['access_token']}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
        )
        assert revoked_access.status_code == 401
        assert "resource_metadata=" in revoked_access.headers["www-authenticate"]

    engine.dispose()
