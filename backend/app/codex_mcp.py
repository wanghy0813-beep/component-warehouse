import hashlib
import calendar
import json
import os
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.types import Tool, ToolAnnotations
from pydantic import AnyHttpUrl
from sqlalchemy import or_
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import auth as auth_module
from .auth import AuthContext, extract_bearer_token, no_auth_context, verify_local_access, verify_remote_token
from .codex_integration import (
    READ_RATE_LIMIT,
    SERVICE_VERSION,
    CodexPrincipal,
    MatchItem,
    MatchRequest,
    OperationAction,
    OperationCreate,
    _limiter,
    codex_session,
    create_operation,
    get_component,
    get_operation_status,
    get_project,
    get_purchases,
    get_risks,
    get_workspace_catalog,
    list_projects,
    match_components,
    read_workspace_dataset as read_codex_workspace_dataset,
    request_operation_undo,
    search_components,
)
from .codex_mcp_models import McpOAuthAuthorization, McpOAuthClient, McpOAuthGrant, McpOAuthRefreshReplay
from .database import Base, SessionLocal, engine
from .models import IntegrationAccessToken, User


READ_SCOPE = "inventory:read"
PROPOSE_SCOPE = "operations:propose"
SUPPORTED_SCOPES = (READ_SCOPE, PROPOSE_SCOPE)
PUBLIC_ORIGIN = os.getenv("COMPONENT_WAREHOUSE_PUBLIC_ORIGIN", "https://wxylab.ltd").rstrip("/")
MCP_RESOURCE_URL = os.getenv(
    "COMPONENT_WAREHOUSE_MCP_RESOURCE_URL",
    f"{PUBLIC_ORIGIN}/hardware/mcp",
).rstrip("/")
MCP_ISSUER_URL = os.getenv(
    "COMPONENT_WAREHOUSE_MCP_ISSUER_URL",
    f"{PUBLIC_ORIGIN}/hardware/oauth",
).rstrip("/")
MCP_LEGACY_RESOURCE_URLS = {
    value.strip().rstrip("/")
    for value in os.getenv(
        "COMPONENT_WAREHOUSE_MCP_LEGACY_RESOURCE_URLS",
        f"{PUBLIC_ORIGIN}/component-warehouse/mcp",
    ).split(",")
    if value.strip()
}
MCP_ACCEPTED_RESOURCE_URLS = {MCP_RESOURCE_URL, *MCP_LEGACY_RESOURCE_URLS}
MCP_CONSENT_URL = os.getenv(
    "COMPONENT_WAREHOUSE_MCP_CONSENT_URL",
    f"{PUBLIC_ORIGIN}/hardware/integrations/codex/oauth",
).rstrip("/")
ACCESS_TOKEN_MINUTES = max(5, int(os.getenv("COMPONENT_WAREHOUSE_MCP_ACCESS_TOKEN_MINUTES", "60")))
REFRESH_TOKEN_DAYS = max(1, int(os.getenv("COMPONENT_WAREHOUSE_MCP_REFRESH_TOKEN_DAYS", "30")))
AUTHORIZATION_TTL_MINUTES = max(
    2,
    int(os.getenv("COMPONENT_WAREHOUSE_MCP_AUTHORIZATION_TTL_MINUTES", "10")),
)
AUTH_CODE_TTL_MINUTES = 5
ALLOWED_REDIRECT_ORIGINS = {
    value.strip().rstrip("/")
    for value in os.getenv(
        "COMPONENT_WAREHOUSE_MCP_ALLOWED_REDIRECT_ORIGINS",
        "https://chatgpt.com",
    ).split(",")
    if value.strip()
}
ALLOW_LOCAL_REDIRECTS = os.getenv("COMPONENT_WAREHOUSE_MCP_ALLOW_LOCAL_REDIRECTS", "0") == "1"
_STORAGE_LOCK = threading.Lock()
_STORAGE_BINDS: set[int] = set()
_STORAGE_TABLES = [
    User.__table__,
    IntegrationAccessToken.__table__,
    McpOAuthClient.__table__,
    McpOAuthAuthorization.__table__,
    McpOAuthGrant.__table__,
    McpOAuthRefreshReplay.__table__,
]

_MATCH_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reference": {"type": "string", "description": "原始位号文本，例如 R1,R2"},
        "designator": {"type": "string", "description": "单个位号，例如 R1"},
        "quantity": {"type": "integer", "minimum": 1, "default": 1},
        "required_quantity": {"type": "integer", "minimum": 1},
        "manufacturer_part": {"type": "string", "description": "制造商型号"},
        "manufacturer": {"type": "string", "description": "制造商"},
        "supplier_part": {"type": "string", "description": "供应商料号，例如立创编号"},
        "supplier": {"type": "string", "description": "供应商"},
        "parameters": {"type": "string", "description": "电气参数和规格"},
        "value": {"type": "string", "description": "标称值，例如 10kΩ"},
        "footprint": {"type": "string", "description": "封装"},
        "category": {"type": "string", "description": "器件分类"},
    },
}

_OPERATION_ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "component.create",
                "component.update",
                "component.archive",
                "component.restore",
                "stock.adjust",
                "workspace.project.create",
                "workspace.project.update",
                "workspace.project.archive",
                "workspace.project.restore",
                "workspace.project.status",
                "workspace.version.create",
                "workspace.version.status",
                "workspace.expense.create",
                "workspace.expense.archive",
                "workspace.expense.restore",
                "workspace.bom.upsert",
                "workspace.bom.archive",
                "workspace.bom.restore",
                "purchase.create",
                "purchase.update",
                "purchase.cancel",
                "purchase.receive",
                "purchase.reverse_receive",
            ],
        },
        "target_id": {
            "anyOf": [{"type": "string"}, {"type": "integer"}],
            "description": "稳定仓库编号、项目编号或数字 ID；创建操作可省略",
        },
        "payload": {
            "type": "object",
            "additionalProperties": True,
            "description": "操作字段；服务端会再次严格校验并只生成审批预览",
        },
    },
    "required": ["action"],
}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
    additional_properties: bool | dict[str, Any] = False,
    title: str | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = list(required)
    if title:
        schema["title"] = title
    return schema


def _array_schema(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


_NULLABLE_STRING = _nullable({"type": "string"})
_NULLABLE_INTEGER = _nullable({"type": "integer"})
_NULLABLE_NUMBER = _nullable({"type": "number"})

_COMPONENT_OUTPUT_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "warehouse_code": {"type": "string"},
        "name": {"type": "string"},
        "model": _NULLABLE_STRING,
        "manufacturer": _NULLABLE_STRING,
        "description": _NULLABLE_STRING,
        "category": _NULLABLE_STRING,
        "parameters": _NULLABLE_STRING,
        "normalized_spec": _NULLABLE_STRING,
        "package": _NULLABLE_STRING,
        "lcsc_number": _NULLABLE_STRING,
        "quantity": {"type": "integer"},
        "average_unit_price": _NULLABLE_NUMBER,
        "price_currency": {"type": "string", "const": "CNY"},
        "reserved_quantity": {"type": "integer"},
        "occupied_quantity": {"type": "integer"},
        "available_quantity": {"type": "integer"},
        "stock_status": {"type": "string"},
        "location": _NULLABLE_STRING,
        "location_code": _NULLABLE_STRING,
        "datasheet_url": _NULLABLE_STRING,
        "buy_url": _NULLABLE_STRING,
        "tags": _NULLABLE_STRING,
        "safety_quantity": _NULLABLE_INTEGER,
        "target_quantity": _NULLABLE_INTEGER,
        "ai_summary": _NULLABLE_STRING,
        "ai_usage": {},
        "ai_risk_notes": {},
        "ai_substitutes": {},
        "updated_at": _NULLABLE_STRING,
        "search_unit_conversion": {},
    },
    required=(
        "id",
        "warehouse_code",
        "name",
        "quantity",
        "average_unit_price",
        "price_currency",
        "reserved_quantity",
        "occupied_quantity",
        "available_quantity",
        "stock_status",
    ),
    title="InventoryComponent",
)

_SUPPLIER_PART_OUTPUT_SCHEMA = _object_schema(
    {
        "supplier": _NULLABLE_STRING,
        "supplier_part_number": _NULLABLE_STRING,
        "purchase_url": _NULLABLE_STRING,
        "unit_price": _NULLABLE_NUMBER,
        "currency": _NULLABLE_STRING,
        "is_preferred": {"type": "boolean"},
    },
    required=("supplier", "supplier_part_number", "is_preferred"),
    title="SupplierPart",
)

_INVENTORY_LOT_OUTPUT_SCHEMA = _object_schema(
    {
        "id": {"type": "string"},
        "source_type": _NULLABLE_STRING,
        "source_reference": _NULLABLE_STRING,
        "location": _NULLABLE_STRING,
        "initial_quantity": {"type": "integer"},
        "remaining_quantity": {"type": "integer"},
        "received_at": _NULLABLE_STRING,
    },
    required=("id", "initial_quantity", "remaining_quantity"),
    title="InventoryLot",
)

_STOCK_MOVEMENT_OUTPUT_SCHEMA = _object_schema(
    {
        "id": {"type": "string"},
        "movement_type": {"type": "string"},
        "quantity_delta": {"type": "integer"},
        "reason": _NULLABLE_STRING,
        "created_at": _NULLABLE_STRING,
    },
    required=("id", "movement_type", "quantity_delta"),
    title="StockMovement",
)

_COMPONENT_DETAIL_OUTPUT_SCHEMA = _object_schema(
    {
        **_COMPONENT_OUTPUT_SCHEMA["properties"],
        "supplier_parts": _array_schema(_SUPPLIER_PART_OUTPUT_SCHEMA),
        "lots": _array_schema(_INVENTORY_LOT_OUTPUT_SCHEMA),
        "recent_movements": _array_schema(_STOCK_MOVEMENT_OUTPUT_SCHEMA),
    },
    required=tuple(_COMPONENT_OUTPUT_SCHEMA["required"])
    + ("supplier_parts", "lots", "recent_movements"),
    title="InventoryComponentDetail",
)

_MATCH_CANDIDATE_COMPONENT_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "warehouse_code": {"type": "string"},
        "name": {"type": "string"},
        "model": _NULLABLE_STRING,
        "manufacturer": _NULLABLE_STRING,
        "parameters": _NULLABLE_STRING,
        "package": _NULLABLE_STRING,
        "lcsc_number": _NULLABLE_STRING,
        "quantity": {"type": "integer"},
    },
    required=("id", "warehouse_code", "name"),
    additional_properties=True,
    title="MatchCandidateComponent",
)

_MATCH_CANDIDATE_SCHEMA = _object_schema(
    {
        "component": _MATCH_CANDIDATE_COMPONENT_SCHEMA,
        "score": {"type": "number"},
        "match_type": {"type": "string", "enum": ["exact", "candidate"]},
        "reason": {"type": "string"},
        "flags": _array_schema({"type": "string"}),
        "available_quantity": {"type": "integer"},
        "shortage_quantity": {"type": "integer"},
        "enough": {"type": "boolean"},
    },
    required=(
        "component",
        "score",
        "match_type",
        "reason",
        "flags",
        "available_quantity",
        "shortage_quantity",
        "enough",
    ),
    title="MatchCandidate",
)

_MISSING_SUGGESTION_SCHEMA = _nullable(
    _object_schema(
        {
            "description": {"type": "string"},
            "reason": {"type": "string"},
            "lcsc_search_keyword": {"type": "string"},
            "lcsc_search_url": {"type": "string"},
            "alternatives": _array_schema(
                _object_schema(
                    {"description": {"type": "string"}, "reason": {"type": "string"}},
                    required=("description", "reason"),
                )
            ),
        },
        required=("description", "reason", "lcsc_search_keyword", "lcsc_search_url"),
        title="MissingSuggestion",
    )
)

_MATCH_RESULT_SCHEMA = _object_schema(
    {
        "reference": _NULLABLE_STRING,
        "designator": _NULLABLE_STRING,
        "quantity": {"type": "integer"},
        "required_quantity": {"type": "integer"},
        "manufacturer_part": _NULLABLE_STRING,
        "manufacturer": _NULLABLE_STRING,
        "supplier_part": _NULLABLE_STRING,
        "supplier": _NULLABLE_STRING,
        "parameters": _NULLABLE_STRING,
        "comment": _NULLABLE_STRING,
        "value": _NULLABLE_STRING,
        "footprint": _NULLABLE_STRING,
        "category": _NULLABLE_STRING,
        "status": {"type": "string"},
        "classification": {"type": "string", "enum": ["exact", "candidate", "missing", "shortage"]},
        "auto_selected": {"type": "boolean"},
        "selected_component_id": _NULLABLE_INTEGER,
        "match_confidence": {"type": "number"},
        "matches": _array_schema(_MATCH_CANDIDATE_SCHEMA),
        "role": {"type": "string"},
        "missing_suggestion": _MISSING_SUGGESTION_SCHEMA,
        "ignored_input": {"type": "boolean"},
        "ignored_reason": _NULLABLE_STRING,
        "lcsc_search_url": _NULLABLE_STRING,
        "ai_reason": {"type": "string"},
    },
    required=(
        "required_quantity",
        "status",
        "classification",
        "auto_selected",
        "selected_component_id",
        "match_confidence",
        "matches",
        "ignored_input",
    ),
    title="BomMatchResult",
)

_PROJECT_BOM_ITEM_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "component_id": {"type": "integer"},
        "warehouse_code": {"type": "string"},
        "name": {"type": "string"},
        "model": _NULLABLE_STRING,
        "required_quantity": {"type": "integer"},
        "own_reserved_quantity": {"type": "integer"},
        "reserved_quantity": {"type": "integer"},
        "reserved_by_other_projects_quantity": {"type": "integer"},
        "stock_quantity": {"type": "integer"},
        "free_quantity": {"type": "integer"},
        "available_for_project_quantity": {"type": "integer"},
        "physical_shortage_quantity": {"type": "integer"},
        "reservation_shortage_quantity": {"type": "integer"},
        "shortage_quantity": {"type": "integer"},
        "enough": {"type": "boolean"},
        "status": {"type": "string"},
        "remark": _NULLABLE_STRING,
    },
    required=(
        "id",
        "component_id",
        "warehouse_code",
        "required_quantity",
        "stock_quantity",
        "shortage_quantity",
        "enough",
        "status",
    ),
    title="ProjectBomItem",
)

_PROJECT_OUTPUT_SCHEMA = _object_schema(
    {},
    additional_properties=True,
    title="PersonalProjectWorkspaceV2",
)

_RISK_ITEM_SCHEMA = _object_schema(
    {
        "id": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        "component_id": _NULLABLE_INTEGER,
        "project_id": _NULLABLE_INTEGER,
        "warehouse_code": _NULLABLE_STRING,
        "component_name": _NULLABLE_STRING,
        "project_code": _NULLABLE_STRING,
        "project_name": _NULLABLE_STRING,
        "risk_type": {"type": "string"},
        "title": {"type": "string"},
        "detail": _NULLABLE_STRING,
        "severity": {"type": "string"},
        "status": {"type": "string"},
        "source": {"type": "string"},
        "verification_status": _NULLABLE_STRING,
    },
    required=("id", "risk_type", "title", "severity", "status", "source"),
    title="InventoryRisk",
)

_PURCHASE_LINE_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "component_id": _NULLABLE_INTEGER,
        "warehouse_code": _NULLABLE_STRING,
        "description": _NULLABLE_STRING,
        "ordered_quantity": {"type": "integer"},
        "received_quantity": {"type": "integer"},
        "outstanding_quantity": {"type": "integer"},
        "unit_price": _NULLABLE_NUMBER,
        "purchase_url": _NULLABLE_STRING,
        "status": {"type": "string"},
        "note": _NULLABLE_STRING,
        "counts_as_in_transit": {"type": "boolean"},
        "in_transit_quantity": {"type": "integer"},
    },
    required=(
        "id",
        "ordered_quantity",
        "received_quantity",
        "outstanding_quantity",
        "status",
        "counts_as_in_transit",
        "in_transit_quantity",
    ),
    title="PurchaseLine",
)

_PURCHASE_ORDER_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "project_id": _NULLABLE_INTEGER,
        "project_code": _NULLABLE_STRING,
        "order_number": _NULLABLE_STRING,
        "platform": _NULLABLE_STRING,
        "status": {"type": "string"},
        "currency": _NULLABLE_STRING,
        "note": _NULLABLE_STRING,
        "lines": _array_schema(_PURCHASE_LINE_SCHEMA),
    },
    required=("id", "status", "lines"),
    title="PurchaseOrder",
)

_OPERATION_OUTPUT_SCHEMA = _object_schema(
    {
        "id": {"type": "string"},
        "status": {"type": "string"},
        "risk_level": {"type": "string"},
        "reason": _NULLABLE_STRING,
        "preview": _array_schema({}),
        "approval_expires_at": {"type": "string"},
        "undo_expires_at": _NULLABLE_STRING,
        "undo_of_operation_id": _NULLABLE_STRING,
        "undone_by_operation_id": _NULLABLE_STRING,
        "approved_at": _NULLABLE_STRING,
        "executed_at": _NULLABLE_STRING,
        "failure_message": _NULLABLE_STRING,
        "created_at": {"type": "string"},
        "approval_url": {"type": "string"},
    },
    required=(
        "id",
        "status",
        "risk_level",
        "preview",
        "approval_expires_at",
        "created_at",
        "approval_url",
    ),
    title="BrowserApprovalOperation",
)

_PERSONAL_COMPONENT_LIST_SCHEMA = _object_schema(
    {
        "items": _array_schema(_COMPONENT_OUTPUT_SCHEMA),
        "count": {"type": "integer"},
        "scope": {"type": "string", "const": "personal"},
    },
    required=("items", "count", "scope"),
    title="PersonalComponentList",
)

_TOOL_OUTPUT_SCHEMAS = {
    "warehouse_session": _object_schema(
        {
            "service_name": {"type": "string", "const": "WXY LAB Hardware"},
            "owner_user_id": {"type": "integer"},
            "scopes": _array_schema({"type": "string"}),
            "expires_at": _NULLABLE_STRING,
            "service_version": {"type": "string"},
            "read_mode": {"type": "string", "const": "full_personal_workspace"},
            "workspace_catalog": {"type": "string"},
            "excluded_boundaries": _array_schema({"type": "string"}),
            "write_mode": {"type": "string", "const": "browser_approval_only"},
            "limits": _object_schema(
                {
                    "read_per_minute": {"type": "integer"},
                    "workspace_read_per_minute": {"type": "integer"},
                    "workspace_page_size": {"type": "integer"},
                    "proposals_per_minute": {"type": "integer"},
                },
                required=(
                    "read_per_minute",
                    "workspace_read_per_minute",
                    "workspace_page_size",
                    "proposals_per_minute",
                ),
            ),
        },
        required=(
            "service_name",
            "owner_user_id",
            "scopes",
            "service_version",
            "read_mode",
            "workspace_catalog",
            "excluded_boundaries",
            "write_mode",
            "limits",
        ),
        title="WarehouseSession",
    ),
    "list_workspace_datasets": _object_schema(
        {
            "service_name": {"type": "string", "const": "WXY LAB Hardware"},
            "scope": {"type": "string", "const": "personal"},
            "read_mode": {"type": "string", "const": "full_personal_workspace"},
            "complete_personal_read": {"type": "boolean", "const": True},
            "datasets": _array_schema(
                _object_schema(
                    {
                        "dataset": {"type": "string"},
                        "primary_key": {"type": "string"},
                        "fields": _array_schema({"type": "string"}),
                        "count": {"type": "integer"},
                    },
                    required=("dataset", "primary_key", "fields", "count"),
                )
            ),
            "dataset_count": {"type": "integer"},
            "record_count": {"type": "integer"},
            "excluded_boundaries": _array_schema({"type": "string"}),
        },
        required=(
            "service_name",
            "scope",
            "read_mode",
            "complete_personal_read",
            "datasets",
            "dataset_count",
            "record_count",
            "excluded_boundaries",
        ),
        title="PersonalWorkspaceCatalog",
    ),
    "read_workspace_dataset": _object_schema(
        {
            "service_name": {"type": "string", "const": "WXY LAB Hardware"},
            "scope": {"type": "string", "const": "personal"},
            "dataset": {"type": "string"},
            "primary_key": {"type": "string"},
            "items": _array_schema(_object_schema({}, additional_properties=True)),
            "count": {"type": "integer"},
            "total": {"type": "integer"},
            "next_cursor": _NULLABLE_STRING,
            "complete": {"type": "boolean"},
        },
        required=(
            "service_name",
            "scope",
            "dataset",
            "primary_key",
            "items",
            "count",
            "total",
            "next_cursor",
            "complete",
        ),
        title="PersonalWorkspaceDatasetPage",
    ),
    "search_inventory": _PERSONAL_COMPONENT_LIST_SCHEMA,
    "get_inventory_component": _COMPONENT_DETAIL_OUTPUT_SCHEMA,
    "match_inventory": _object_schema(
        {
            "items": _array_schema(_MATCH_RESULT_SCHEMA),
            "count": {"type": "integer"},
            "scope": {"type": "string", "const": "personal"},
        },
        required=("items", "count", "scope"),
        title="PersonalBomMatchList",
    ),
    "list_inventory_projects": _object_schema(
        {
            "items": _array_schema(_PROJECT_OUTPUT_SCHEMA),
            "count": {"type": "integer"},
            "scope": {"type": "string", "const": "personal"},
            "schema_version": {"type": "string", "const": "project-workspace-v2"},
        },
        required=("items", "count", "scope", "schema_version"),
        title="PersonalProjectList",
    ),
    "get_inventory_project": _PROJECT_OUTPUT_SCHEMA,
    "list_inventory_risks": _object_schema(
        {
            "items": _array_schema(_RISK_ITEM_SCHEMA),
            "total": {"type": "integer"},
            "count": {"type": "integer"},
            "counts": _object_schema({}, additional_properties={"type": "integer"}),
            "scope": {"type": "string", "const": "personal"},
        },
        required=("items", "total", "count", "counts", "scope"),
        title="PersonalRiskList",
    ),
    "list_inventory_purchases": _object_schema(
        {
            "items": _array_schema(_PURCHASE_ORDER_SCHEMA),
            "count": {"type": "integer"},
            "scope": {"type": "string", "const": "personal"},
        },
        required=("items", "count", "scope"),
        title="PersonalPurchaseList",
    ),
    "propose_operation": _OPERATION_OUTPUT_SCHEMA,
    "get_operation_state": _OPERATION_OUTPUT_SCHEMA,
    "propose_operation_undo": _OPERATION_OUTPUT_SCHEMA,
}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_timestamp(value: datetime) -> int:
    return calendar.timegm(value.utctimetuple())


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def ensure_mcp_storage() -> None:
    bind = SessionLocal.kw.get("bind") or engine
    bind_key = id(bind)
    if bind_key in _STORAGE_BINDS:
        return
    with _STORAGE_LOCK:
        if bind_key in _STORAGE_BINDS:
            return
        Base.metadata.create_all(bind=bind, tables=_STORAGE_TABLES)
        _STORAGE_BINDS.add(bind_key)


def _redirect_allowed(value: str) -> bool:
    parsed = urlparse(value)
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if origin in ALLOWED_REDIRECT_ORIGINS:
        if origin == "https://chatgpt.com":
            return parsed.path.startswith("/connector/oauth/") or parsed.path == "/connector_platform_oauth_redirect"
        return True
    return ALLOW_LOCAL_REDIRECTS and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


def _client_from_row(row: McpOAuthClient) -> OAuthClientInformationFull:
    return OAuthClientInformationFull.model_validate(_load(row.metadata_json, {}))


def _authorization_code(row: McpOAuthAuthorization, raw_code: str) -> AuthorizationCode:
    return AuthorizationCode(
        code=raw_code,
        scopes=list(_load(row.scopes_json, [])),
        expires_at=_utc_timestamp(row.code_expires_at or row.expires_at),
        client_id=row.client_id,
        code_challenge=row.code_challenge,
        redirect_uri=row.redirect_uri,
        redirect_uri_provided_explicitly=bool(row.redirect_uri_provided_explicitly),
        resource=row.resource,
        subject=str(row.owner_user_id) if row.owner_user_id is not None else None,
    )


def _linked_access_token(db, grant: McpOAuthGrant) -> IntegrationAccessToken | None:
    token = db.get(IntegrationAccessToken, grant.id)
    if not token or token.status != "active" or token.revoked_at is not None:
        return None
    return token


class ComponentWarehouseOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        ensure_mcp_storage()
        with SessionLocal() as db:
            row = db.get(McpOAuthClient, client_id)
            if not row:
                return None
            row.last_used_at = _utcnow()
            db.commit()
            return _client_from_row(row)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        ensure_mcp_storage()
        if not client_info.client_id:
            raise RegistrationError("invalid_client_metadata", "client_id is required")
        if client_info.token_endpoint_auth_method != "none" or client_info.client_secret:
            raise RegistrationError(
                "invalid_client_metadata",
                "WXY LAB Hardware accepts public PKCE clients without a client secret",
            )
        redirect_uris = [str(value) for value in client_info.redirect_uris or []]
        if not redirect_uris or any(not _redirect_allowed(value) for value in redirect_uris):
            raise RegistrationError(
                "invalid_redirect_uri",
                "Only registered ChatGPT connector callbacks are accepted",
            )
        if not {"authorization_code", "refresh_token"}.issubset(set(client_info.grant_types or [])):
            raise RegistrationError("invalid_client_metadata", "authorization_code and refresh_token are required")
        if "code" not in set(client_info.response_types or []):
            raise RegistrationError("invalid_client_metadata", "code response type is required")
        metadata = client_info.model_dump(mode="json", exclude_none=True)
        with SessionLocal() as db:
            existing = db.get(McpOAuthClient, client_info.client_id)
            if existing:
                if existing.metadata_json != _dump(metadata):
                    raise RegistrationError("invalid_client_metadata", "client_id is already registered")
                return
            db.add(McpOAuthClient(client_id=client_info.client_id, metadata_json=_dump(metadata)))
            db.commit()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        ensure_mcp_storage()
        if params.resource not in MCP_ACCEPTED_RESOURCE_URLS:
            raise AuthorizeError("invalid_request", "resource must identify the WXY LAB Hardware MCP server")
        scopes = list(params.scopes or [])
        if READ_SCOPE not in scopes or any(scope not in SUPPORTED_SCOPES for scope in scopes):
            raise AuthorizeError("invalid_scope", "inventory:read is required and only documented scopes are allowed")
        request_id = secrets.token_urlsafe(32)
        with SessionLocal() as db:
            db.add(
                McpOAuthAuthorization(
                    request_id=request_id,
                    client_id=str(client.client_id),
                    redirect_uri=str(params.redirect_uri),
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    state=params.state,
                    scopes_json=_dump(scopes),
                    code_challenge=params.code_challenge,
                    resource=params.resource,
                    status="pending",
                    expires_at=_utcnow() + timedelta(minutes=AUTHORIZATION_TTL_MINUTES),
                )
            )
            db.commit()
        return f"{MCP_CONSENT_URL}/{request_id}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        ensure_mcp_storage()
        with SessionLocal() as db:
            row = (
                db.query(McpOAuthAuthorization)
                .filter(McpOAuthAuthorization.code_hash == _hash_token(authorization_code))
                .first()
            )
            now = _utcnow()
            if (
                not row
                or row.client_id != client.client_id
                or row.status != "approved"
                or not row.owner_user_id
                or not row.code_expires_at
                or row.code_expires_at <= now
            ):
                return None
            return _authorization_code(row, authorization_code)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        ensure_mcp_storage()
        now = _utcnow()
        access_expires = now + timedelta(minutes=ACCESS_TOKEN_MINUTES)
        refresh_expires = now + timedelta(days=REFRESH_TOKEN_DAYS)
        raw_access = _new_token("cw_mcp_at_")
        raw_refresh = _new_token("cw_mcp_rt_")
        grant_id = str(uuid4())
        with SessionLocal() as db:
            reserved = (
                db.query(McpOAuthAuthorization)
                .filter(
                    McpOAuthAuthorization.code_hash == _hash_token(authorization_code.code),
                    McpOAuthAuthorization.client_id == client.client_id,
                    McpOAuthAuthorization.status == "approved",
                    McpOAuthAuthorization.owner_user_id.is_not(None),
                    McpOAuthAuthorization.code_expires_at > now,
                )
                .update({McpOAuthAuthorization.status: "exchanging"}, synchronize_session=False)
            )
            if reserved != 1:
                db.rollback()
                raise TokenError("invalid_grant", "authorization code is invalid, expired, or already used")
            row = (
                db.query(McpOAuthAuthorization)
                .filter(McpOAuthAuthorization.code_hash == _hash_token(authorization_code.code))
                .first()
            )
            if not row or not row.owner_user_id:
                db.rollback()
                raise TokenError("invalid_grant", "authorization code owner is missing")
            scopes = list(_load(row.scopes_json, []))
            db.add(
                IntegrationAccessToken(
                    id=grant_id,
                    owner_user_id=row.owner_user_id,
                    name="ChatGPT Work 模式",
                    token_hash=_hash_token(raw_access),
                    token_prefix=raw_access[:18],
                    scopes=" ".join(scopes),
                    status="active",
                    expires_at=refresh_expires,
                )
            )
            db.add(
                McpOAuthGrant(
                    id=grant_id,
                    client_id=row.client_id,
                    owner_user_id=row.owner_user_id,
                    access_token_hash=_hash_token(raw_access),
                    refresh_token_hash=_hash_token(raw_refresh),
                    scopes_json=_dump(scopes),
                    resource=row.resource,
                    access_expires_at=access_expires,
                    refresh_expires_at=refresh_expires,
                )
            )
            row.status = "exchanged"
            row.exchanged_at = now
            db.commit()
        return OAuthToken(
            access_token=raw_access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_MINUTES * 60,
            refresh_token=raw_refresh,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        ensure_mcp_storage()
        with SessionLocal() as db:
            digest = _hash_token(refresh_token)
            grant = (
                db.query(McpOAuthGrant)
                .filter(McpOAuthGrant.refresh_token_hash == digest)
                .first()
            )
            if not grant:
                replay = db.get(McpOAuthRefreshReplay, digest)
                replayed_grant = db.get(McpOAuthGrant, replay.grant_id) if replay else None
                if replayed_grant and replayed_grant.revoked_at is None:
                    now = _utcnow()
                    replayed_grant.revoked_at = now
                    linked = db.get(IntegrationAccessToken, replayed_grant.id)
                    if linked and linked.status == "active":
                        linked.status = "revoked"
                        linked.revoked_at = now
                    db.commit()
                return None
            if (
                grant.client_id != client.client_id
                or grant.revoked_at is not None
                or grant.refresh_expires_at <= _utcnow()
                or not _linked_access_token(db, grant)
            ):
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=grant.client_id,
                scopes=list(_load(grant.scopes_json, [])),
                expires_at=_utc_timestamp(grant.refresh_expires_at),
                subject=str(grant.owner_user_id),
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        ensure_mcp_storage()
        now = _utcnow()
        raw_access = _new_token("cw_mcp_at_")
        raw_refresh = _new_token("cw_mcp_rt_")
        with SessionLocal() as db:
            grant = (
                db.query(McpOAuthGrant)
                .filter(McpOAuthGrant.refresh_token_hash == _hash_token(refresh_token.token))
                .first()
            )
            linked = _linked_access_token(db, grant) if grant else None
            if (
                not grant
                or not linked
                or grant.client_id != client.client_id
                or grant.revoked_at is not None
                or grant.refresh_expires_at <= now
                or grant.resource not in MCP_ACCEPTED_RESOURCE_URLS
                or any(scope not in _load(grant.scopes_json, []) for scope in scopes)
            ):
                raise TokenError("invalid_grant", "refresh token is invalid, expired, reused, or revoked")
            previous_refresh_hash = grant.refresh_token_hash
            rotated = (
                db.query(McpOAuthGrant)
                .filter(
                    McpOAuthGrant.id == grant.id,
                    McpOAuthGrant.refresh_token_hash == previous_refresh_hash,
                    McpOAuthGrant.revoked_at.is_(None),
                    McpOAuthGrant.refresh_expires_at > now,
                )
                .update(
                    {
                        McpOAuthGrant.access_token_hash: _hash_token(raw_access),
                        McpOAuthGrant.refresh_token_hash: _hash_token(raw_refresh),
                        McpOAuthGrant.access_expires_at: now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
                        McpOAuthGrant.last_used_at: now,
                        McpOAuthGrant.rotation_counter: int(grant.rotation_counter or 0) + 1,
                    },
                    synchronize_session=False,
                )
            )
            if rotated != 1:
                db.rollback()
                raise TokenError("invalid_grant", "refresh token was already rotated")
            db.add(
                McpOAuthRefreshReplay(
                    token_hash=previous_refresh_hash,
                    grant_id=grant.id,
                    expires_at=grant.refresh_expires_at,
                )
            )
            linked.token_hash = _hash_token(raw_access)
            linked.token_prefix = raw_access[:18]
            linked.last_used_at = now
            db.commit()
            return OAuthToken(
                access_token=raw_access,
                token_type="Bearer",
                expires_in=ACCESS_TOKEN_MINUTES * 60,
                refresh_token=raw_refresh,
                scope=" ".join(scopes),
            )

    async def load_access_token(self, token: str) -> AccessToken | None:
        ensure_mcp_storage()
        with SessionLocal() as db:
            grant = (
                db.query(McpOAuthGrant)
                .filter(McpOAuthGrant.access_token_hash == _hash_token(token))
                .first()
            )
            now = _utcnow()
            linked = _linked_access_token(db, grant) if grant else None
            if (
                not grant
                or not linked
                or grant.revoked_at is not None
                or grant.access_expires_at <= now
                or grant.resource not in MCP_ACCEPTED_RESOURCE_URLS
            ):
                return None
            grant.last_used_at = now
            linked.last_used_at = now
            db.commit()
            return AccessToken(
                token=token,
                client_id=grant.client_id,
                scopes=list(_load(grant.scopes_json, [])),
                expires_at=_utc_timestamp(grant.access_expires_at),
                resource=grant.resource,
                subject=str(grant.owner_user_id),
                claims={"grant_id": grant.id, "owner_user_id": grant.owner_user_id},
            )

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.load_access_token(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        ensure_mcp_storage()
        digest = _hash_token(token.token)
        with SessionLocal() as db:
            grant = (
                db.query(McpOAuthGrant)
                .filter(
                    or_(
                        McpOAuthGrant.access_token_hash == digest,
                        McpOAuthGrant.refresh_token_hash == digest,
                    )
                )
                .first()
            )
            if not grant:
                return
            now = _utcnow()
            grant.revoked_at = grant.revoked_at or now
            linked = db.get(IntegrationAccessToken, grant.id)
            if linked and linked.status == "active":
                linked.status = "revoked"
                linked.revoked_at = now
            db.commit()


class AppsFastMCP(FastMCP):
    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema["additionalProperties"] = False
            output_schema = _TOOL_OUTPUT_SCHEMAS.get(tool.name)
            if output_schema is None:
                raise RuntimeError(f"MCP 工具 {tool.name} 缺少 outputSchema")
            tool.outputSchema = deepcopy(output_schema)
            if tool.name == "match_inventory":
                tool.inputSchema.pop("$defs", None)
                item_list = tool.inputSchema["properties"]["items"]
                item_list.update({"items": _MATCH_ITEM_SCHEMA, "minItems": 1, "maxItems": 200})
                tool.inputSchema["properties"]["top_n"].update({"minimum": 1, "maximum": 10})
            elif tool.name == "propose_operation":
                tool.inputSchema.pop("$defs", None)
                action_list = tool.inputSchema["properties"]["actions"]
                action_list.update({"items": _OPERATION_ACTION_SCHEMA, "minItems": 1, "maxItems": 100})
                tool.inputSchema["properties"]["idempotency_key"].update(
                    {"minLength": 8, "maxLength": 120}
                )
            # Operation tools only create a short-lived browser approval draft.
            # They cannot approve or execute changes, so the same personal-library
            # read grant is sufficient and ChatGPT does not need a second OAuth
            # round trip while validating the connector.
            schemes = [{"type": "oauth2", "scopes": [READ_SCOPE]}]
            setattr(tool, "securitySchemes", schemes)
            tool.meta = {**(tool.meta or {}), "securitySchemes": schemes}
        return tools


provider = ComponentWarehouseOAuthProvider()
resource_host = urlparse(MCP_RESOURCE_URL).netloc
mcp = AppsFastMCP(
    name="WXY LAB Hardware",
    instructions=(
        "Read the authenticated user's complete personal WXY LAB Hardware business workspace. "
        "Never expose team data, other users, credentials, tokens, audit logs, AI cache, sync internals, binary contents, or server paths. "
        "Never treat package-only similarity as electrical compatibility. "
        "Write tools create browser approval proposals and never approve changes."
    ),
    website_url=f"{PUBLIC_ORIGIN}/hardware/",
    token_verifier=provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(MCP_ISSUER_URL),
        service_documentation_url=AnyHttpUrl(f"{PUBLIC_ORIGIN}/hardware/manual"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=list(SUPPORTED_SCOPES),
            default_scopes=list(SUPPORTED_SCOPES),
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[READ_SCOPE],
        resource_server_url=AnyHttpUrl(MCP_RESOURCE_URL),
    ),
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[resource_host, "localhost:*", "127.0.0.1:*"],
        allowed_origins=[PUBLIC_ORIGIN, "https://chatgpt.com"],
    ),
)

client_registration_options = ClientRegistrationOptions(
    enabled=True,
    valid_scopes=list(SUPPORTED_SCOPES),
    default_scopes=list(SUPPORTED_SCOPES),
)
revocation_options = RevocationOptions(enabled=True)
client_authenticator = ClientAuthenticator(provider)


def _principal(required_scope: str = READ_SCOPE) -> CodexPrincipal:
    token = get_access_token()
    if not token or not token.subject:
        raise ValueError("需要先连接 WXY LAB Hardware 账号")
    if required_scope not in token.scopes:
        raise ValueError(f"当前连接缺少 {required_scope} 权限")
    claims = token.claims or {}
    grant_id = str(claims.get("grant_id") or "")
    if not grant_id:
        raise ValueError("WXY LAB Hardware OAuth 授权状态无效")
    expires_at = datetime.utcfromtimestamp(token.expires_at) if token.expires_at else None
    principal = CodexPrincipal(grant_id, int(token.subject), tuple(token.scopes), expires_at)
    _limiter.check(grant_id, "read", READ_RATE_LIMIT)
    return principal


def _tool_result(value: Any) -> Any:
    result = jsonable_encoder(value)
    if isinstance(result, dict):
        approval_url = result.get("approval_url")
        if isinstance(approval_url, str) and approval_url.startswith("/hardware/"):
            result["approval_url"] = f"{PUBLIC_ORIGIN}{approval_url}"
        elif isinstance(approval_url, str) and approval_url.startswith("/personal/"):
            result["approval_url"] = f"{PUBLIC_ORIGIN}/component-warehouse{approval_url}"
    return result


def _call_with_db(callback):
    try:
        with SessionLocal() as db:
            return _tool_result(callback(db))
    except HTTPException as error:
        raise ValueError(str(error.detail)) from error


def _oauth_rate_limit(request: Request, bucket: str, limit: int) -> JSONResponse | None:
    client_host = request.client.host if request.client else "unknown"
    try:
        _limiter.check(f"oauth:{client_host}", bucket, limit)
    except HTTPException as error:
        return JSONResponse(
            {"error": "temporarily_unavailable", "error_description": str(error.detail)},
            status_code=error.status_code,
            headers={"Cache-Control": "no-store", "Retry-After": "60"},
        )
    return None


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
PROPOSAL_ONLY = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@mcp.tool(
    title="检查 WXY LAB Hardware 连接",
    description="返回当前授权用户、权限、服务版本和审批模式，不返回令牌。",
    annotations=READ_ONLY,
)
def warehouse_session() -> dict[str, Any]:
    principal = _principal()
    return _tool_result(codex_session(principal=principal))


@mcp.tool(
    title="列出完整个人业务库",
    description="列出当前账号可读取的全部个人业务数据集、安全字段和记录数。",
    annotations=READ_ONLY,
)
def list_workspace_datasets() -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(lambda db: get_workspace_catalog(principal=principal, db=db))


@mcp.tool(
    title="分页读取个人业务数据集",
    description="按完整个人库目录中的数据集名称分页读取；持续使用 next_cursor 直到为空。",
    annotations=READ_ONLY,
)
def read_workspace_dataset(
    dataset: str,
    cursor: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(
        lambda db: read_codex_workspace_dataset(
            dataset=dataset,
            cursor=cursor.strip() or None,
            limit=max(1, min(int(limit), 200)),
            principal=principal,
            db=db,
        )
    )


@mcp.tool(
    title="搜索个人元器件库存",
    description="按名称、型号、参数、封装、立创编号和库存状态查询当前用户个人库。",
    annotations=READ_ONLY,
)
def search_inventory(
    query: str = "",
    category: str = "",
    package: str = "",
    stock: str = "all",
    limit: int = 30,
) -> dict[str, Any]:
    principal = _principal()
    if stock not in {"available", "shortage", "all"}:
        raise ValueError("stock 必须是 available、shortage 或 all")
    limit = max(1, min(int(limit), 50))
    return _call_with_db(
        lambda db: search_components(
            q=query.strip() or None,
            category=category.strip() or None,
            package=package.strip() or None,
            stock=stock,
            limit=limit,
            principal=principal,
            db=db,
        )
    )


@mcp.tool(
    title="读取元器件详情",
    description="按稳定仓库编号读取个人元器件、库存批次、供应商和近期流水。",
    annotations=READ_ONLY,
)
def get_inventory_component(warehouse_code: str) -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(lambda db: get_component(warehouse_code, principal=principal, db=db))


@mcp.tool(
    title="批量匹配板卡或 BOM",
    description=(
        "把最多 200 条结构化器件需求匹配到个人库存，返回 exact、candidate、missing 或 shortage。"
        "只会自动选择唯一高置信精确项。"
    ),
    annotations=READ_ONLY,
)
def match_inventory(items: list[MatchItem], top_n: int = 5) -> dict[str, Any]:
    principal = _principal()
    payload = MatchRequest(items=items, top_n=top_n)
    return _call_with_db(lambda db: match_components(payload, principal=principal, db=db))


@mcp.tool(
    title="列出个人项目",
    description="读取当前用户的个人项目及其 BOM、预留和缺料上下文。",
    annotations=READ_ONLY,
)
def list_inventory_projects() -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(lambda db: list_projects(principal=principal, db=db))


@mcp.tool(
    title="读取个人项目",
    description="按稳定项目编号或数字 ID 读取项目、BOM、预留和缺料详情。",
    annotations=READ_ONLY,
)
def get_inventory_project(project_id: str) -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(lambda db: get_project(project_id, principal=principal, db=db))


@mcp.tool(
    title="读取个人库存风险",
    description="读取库存、数据手册、BOM、采购和人工维护的个人库风险。",
    annotations=READ_ONLY,
)
def list_inventory_risks() -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(lambda db: get_risks(principal=principal, db=db))


@mcp.tool(
    title="读取个人采购",
    description="读取个人采购单、未到货数量和可靠的在途上下文。",
    annotations=READ_ONLY,
)
def list_inventory_purchases() -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(lambda db: get_purchases(principal=principal, db=db))


@mcp.tool(
    title="生成 WXY LAB Hardware 写操作审批单",
    description="校验操作并生成 10 分钟有效的网页审批单；不会直接修改库存、项目、BOM 或采购。",
    annotations=PROPOSAL_ONLY,
)
def propose_operation(
    idempotency_key: str,
    actions: list[OperationAction],
    reason: str = "",
) -> dict[str, Any]:
    principal = _principal()
    payload = OperationCreate(
        idempotency_key=idempotency_key,
        reason=reason.strip() or None,
        actions=actions,
    )
    return _call_with_db(lambda db: create_operation(payload, principal=principal, db=db))


@mcp.tool(
    title="查询 WXY LAB Hardware 审批状态",
    description="查询由当前 ChatGPT 授权创建的操作是否待审批、已执行、已拒绝、过期或失败。",
    annotations=READ_ONLY,
)
def get_operation_state(operation_id: str) -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(lambda db: get_operation_status(operation_id, principal=principal, db=db))


@mcp.tool(
    title="生成撤销审批单",
    description="为 30 天撤销窗口内的成功操作生成新的网页审批单；不会直接执行撤销。",
    annotations=PROPOSAL_ONLY,
)
def propose_operation_undo(operation_id: str) -> dict[str, Any]:
    principal = _principal()
    return _call_with_db(lambda db: request_operation_undo(operation_id, principal=principal, db=db))


def _browser_auth(request: Request, db) -> AuthContext:
    raw_token = extract_bearer_token(request.headers.get("authorization"))
    if not auth_module.auth_required():
        return no_auth_context(db)
    if not raw_token:
        raise HTTPException(status_code=401, detail="请先登录 WXY LAB Hardware")
    if auth_module.AUTH_MODE == "local-password":
        return verify_local_access(db, raw_token)
    return verify_remote_token(db, raw_token)


def _approval_payload(row: McpOAuthAuthorization, client: McpOAuthClient) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "client_name": _client_from_row(client).client_name or "ChatGPT",
        "client_id": row.client_id,
        "scopes": list(_load(row.scopes_json, [])),
        "resource": row.resource,
        "status": row.status,
        "expires_at": row.expires_at,
        "permissions": {
            READ_SCOPE: "完整读取你的个人库存、流水、项目、采购、EDA、标签及文件元数据",
            PROPOSE_SCOPE: "生成需要你在网页逐单批准的变更草案，不可自行批准或执行",
        },
    }


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def oauth_authorization_metadata(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "issuer": MCP_ISSUER_URL,
            "authorization_endpoint": f"{MCP_ISSUER_URL}/authorize",
            "token_endpoint": f"{MCP_ISSUER_URL}/token",
            "registration_endpoint": f"{MCP_ISSUER_URL}/register",
            "revocation_endpoint": f"{MCP_ISSUER_URL}/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": list(SUPPORTED_SCOPES),
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@mcp.custom_route("/authorize", methods=["GET", "POST"])
async def oauth_authorize(request: Request):
    limited = _oauth_rate_limit(request, "authorize", 120)
    if limited:
        return limited
    return await AuthorizationHandler(provider).handle(request)


@mcp.custom_route("/token", methods=["POST"])
async def oauth_token(request: Request):
    limited = _oauth_rate_limit(request, "token", 240)
    if limited:
        return limited
    return await TokenHandler(provider, client_authenticator).handle(request)


@mcp.custom_route("/register", methods=["POST"])
async def oauth_register(request: Request):
    limited = _oauth_rate_limit(request, "register", 30)
    if limited:
        return limited
    return await RegistrationHandler(provider, options=client_registration_options).handle(request)


@mcp.custom_route("/revoke", methods=["POST"])
async def oauth_revoke(request: Request):
    return await RevocationHandler(provider, client_authenticator).handle(request)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    ensure_mcp_storage()
    return JSONResponse(
        {
            "status": "ok",
            "service": "WXY LAB Hardware",
            "version": SERVICE_VERSION,
            "resource": MCP_RESOURCE_URL,
            "tool_count": 13,
        }
    )


@mcp.custom_route("/approval/{request_id}", methods=["GET"])
async def get_approval(request: Request) -> JSONResponse:
    try:
        ensure_mcp_storage()
        with SessionLocal() as db:
            _browser_auth(request, db)
            row = db.get(McpOAuthAuthorization, request.path_params["request_id"])
            if not row:
                raise HTTPException(status_code=404, detail="授权请求不存在")
            if row.status == "pending" and row.expires_at <= _utcnow():
                row.status = "expired"
                db.commit()
            client = db.get(McpOAuthClient, row.client_id)
            if not client:
                raise HTTPException(status_code=404, detail="OAuth 客户端不存在")
            return JSONResponse(jsonable_encoder(_approval_payload(row, client)), headers={"Cache-Control": "no-store"})
    except HTTPException as error:
        return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers={"Cache-Control": "no-store"})


@mcp.custom_route("/approval/{request_id}", methods=["POST"])
async def decide_approval(request: Request) -> JSONResponse:
    try:
        ensure_mcp_storage()
        body = await request.json()
        decision = str(body.get("decision") or "").strip().lower()
        if decision not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail="decision 必须为 approve 或 reject")
        with SessionLocal() as db:
            auth = _browser_auth(request, db)
            row = db.get(McpOAuthAuthorization, request.path_params["request_id"])
            if not row:
                raise HTTPException(status_code=404, detail="授权请求不存在")
            now = _utcnow()
            if row.status != "pending":
                raise HTTPException(status_code=409, detail="该授权请求已经处理或失效")
            if row.expires_at <= now:
                row.status = "expired"
                db.commit()
                raise HTTPException(status_code=410, detail="授权请求已过期，请从 ChatGPT 重新连接")
            if decision == "reject":
                row.status = "denied"
                row.owner_user_id = auth.user_id
                row.denied_at = now
                redirect_url = construct_redirect_uri(
                    row.redirect_uri,
                    error="access_denied",
                    error_description="The user rejected WXY LAB Hardware access",
                    state=row.state,
                )
            else:
                raw_code = _new_token("cw_mcp_code_")
                row.status = "approved"
                row.owner_user_id = auth.user_id
                row.code_hash = _hash_token(raw_code)
                row.code_expires_at = now + timedelta(minutes=AUTH_CODE_TTL_MINUTES)
                row.approved_at = now
                redirect_url = construct_redirect_uri(row.redirect_uri, code=raw_code, state=row.state)
            db.commit()
            return JSONResponse(
                {"ok": True, "decision": decision, "redirect_url": redirect_url},
                headers={"Cache-Control": "no-store"},
            )
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"detail": "请求格式无效"}, status_code=400, headers={"Cache-Control": "no-store"})
    except HTTPException as error:
        return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers={"Cache-Control": "no-store"})


app = mcp.streamable_http_app()
