import hashlib
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from .auth import AuthContext, require_access
from .component_identity import (
    allocate_component_identity,
    archive_component_identity,
    identity_by_code,
    refresh_identity_snapshot,
)
from .database import Base, get_db
from .models import (
    ActivityLog,
    Category,
    Component,
    ComponentIdentityRegistry,
    IntegrationAccessToken,
    IntegrationOperation,
    InventoryLot,
    PersonalProjectBomItemV2,
    PersonalProjectExpenseV2,
    PersonalProjectRiskV2,
    PersonalProjectStatusEventV2,
    PersonalProjectV2,
    PersonalProjectVersionV2,
    Project,
    ProjectBoard,
    ProjectBomItem,
    ProjectCodeAlias,
    ProjectExpense,
    ProjectPcbVersion,
    ProjectStatusEvent,
    PurchaseLine,
    PurchaseOrder,
    PurchaseReceipt,
    StockMovement,
    SupplierPart,
)
from .services.bom_match import BomRow, match_bom_rows
from .services.inventory import (
    component_available_quantity,
    equipment_occupied_quantity,
    is_durable_equipment,
    normalize_inventory_location,
    normalize_inventory_status,
    reserved_quantities,
)
from .services.component_search import find_unit_conversion_match, keyword_unit_variants
from .services.stock_ledger import record_stock_delta
from .services.sync_bootstrap import collect_personal_rows
from .services.sync_core import EXCLUDED_SYNC_FIELDS, json_value as sync_json_value, primary_key_column
from .services.project_tracking import (
    EXPENSE_CATEGORY_LABELS,
    PCB_VERSION_STATUS_LABELS,
    PROJECT_STATUS_LABELS,
    active_version as active_project_version,
    assert_project_code_available,
    cost_summary as project_cost_summary,
    create_initial_version,
    create_version as create_project_version,
    expense_out,
    normalize_project_code,
    normalize_version_code,
    project_by_code_or_alias,
    project_period,
    shanghai_today,
    version_stats,
)
from .risks import RiskScope, list_risks_impl
from .personal_projects_v2 import (
    EXPENSE_CATEGORIES as WORKSPACE_EXPENSE_CATEGORIES,
    PROJECT_STATUSES as WORKSPACE_PROJECT_STATUSES,
    VERSION_STATUSES as WORKSPACE_VERSION_STATUSES,
    add_actual_timeline_events as add_workspace_actual_timeline_events,
    add_initial_timeline_events as add_workspace_initial_timeline_events,
    cost_summary as workspace_cost_summary,
    lifecycle_out as workspace_lifecycle_out,
    normalize_code as normalize_workspace_code,
    normalize_version as normalize_workspace_version,
    normalized_actual_lifecycle_dates as normalize_workspace_actual_lifecycle_dates,
    period_out as workspace_period_out,
    project_out as workspace_project_summary,
    status_history_out as workspace_status_history_out,
    today as workspace_today,
    version_out as workspace_version_out,
)


router = APIRouter(tags=["codex-integration"])
SERVICE_NAME = "WXY LAB Hardware"
SERVICE_VERSION = "2026-08-27-full-personal-read"
TOKEN_PREFIX = "cw_codex_"
READ_SCOPE = "inventory:read"
APPROVAL_TTL = timedelta(minutes=10)
UNDO_TTL = timedelta(days=30)
MAX_ACTIONS = 100
MAX_MATCH_ROWS = 200
READ_RATE_LIMIT = 120
PROPOSAL_RATE_LIMIT = 20
WORKSPACE_READ_RATE_LIMIT = 30
WORKSPACE_PAGE_LIMIT = 200
WORKSPACE_EXCLUDED_DATASETS = {"users"}
WORKSPACE_PERSONAL_EXTRA_DATASETS = {
    "import_records",
    "order_import_batches",
    "order_import_lines",
    "price_import_batches",
    "price_import_lines",
}
WORKSPACE_EXCLUDED_FIELDS = set(EXCLUDED_SYNC_FIELDS) | {
    "password_hash",
    "previous_component",
    "raw_data",
    "row_data",
    "source_file",
    "storage_path",
    "team_library_id",
}
WORKSPACE_EXCLUDED_BOUNDARIES = [
    "team data",
    "other users",
    "account credentials",
    "integration and EDA tokens",
    "audit logs",
    "AI cache",
    "sync internals",
    "binary file contents",
    "server storage paths",
]


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int = Field(default=365, ge=1, le=3650)


class MatchItem(BaseModel):
    reference: str | None = None
    designator: str | None = None
    quantity: int = Field(default=1, ge=1)
    required_quantity: int | None = Field(default=None, ge=1)
    manufacturer_part: str | None = None
    manufacturer: str | None = None
    supplier_part: str | None = None
    supplier: str | None = None
    parameters: str | None = None
    value: str | None = None
    footprint: str | None = None
    category: str | None = None


class MatchRequest(BaseModel):
    items: list[MatchItem] = Field(min_length=1, max_length=MAX_MATCH_ROWS)
    top_n: int = Field(default=5, ge=1, le=10)


class OperationAction(BaseModel):
    action: str = Field(min_length=3, max_length=80)
    target_id: str | int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class OperationCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    reason: str | None = Field(default=None, max_length=1000)
    actions: list[OperationAction] = Field(min_length=1, max_length=MAX_ACTIONS)


@dataclass(frozen=True)
class CodexPrincipal:
    token_id: str
    owner_user_id: int
    scopes: tuple[str, ...]
    expires_at: datetime | None


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, token_id: str, bucket: str, limit: int) -> None:
        now = time.monotonic()
        key = (token_id, bucket)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
            events.append(now)


_limiter = SlidingWindowLimiter()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _date_value(value: Any, default: date | None = None) -> date | None:
    if value in {None, ""}:
        return default
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="日期必须使用 YYYY-MM-DD 格式") from error


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"不能序列化 {type(value).__name__}")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _load(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


def _hash(value: Any) -> str:
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _token_out(token: IntegrationAccessToken) -> dict[str, Any]:
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.token_prefix,
        "scopes": token.scopes.split(),
        "status": token.status,
        "expires_at": token.expires_at,
        "last_used_at": token.last_used_at,
        "created_at": token.created_at,
    }


def _operation_out(operation: IntegrationOperation, include_sensitive: bool = False) -> dict[str, Any]:
    data = {
        "id": operation.id,
        "status": operation.status,
        "risk_level": operation.risk_level,
        "reason": operation.reason,
        "preview": _load(operation.preview_json, []),
        "approval_expires_at": operation.approval_expires_at,
        "undo_expires_at": operation.undo_expires_at,
        "undo_of_operation_id": operation.undo_of_operation_id,
        "undone_by_operation_id": operation.undone_by_operation_id,
        "approved_at": operation.approved_at,
        "executed_at": operation.executed_at,
        "failure_message": operation.failure_message,
        "created_at": operation.created_at,
        "approval_url": f"/hardware/integrations/codex/operations/{operation.id}",
    }
    if include_sensitive:
        data.update(
            {
                "request": _load(operation.request_json, {}),
                "before": _load(operation.before_json, []),
                "after": _load(operation.after_json, []),
                "can_approve": operation.status == "pending_approval" and operation.approval_expires_at > _utcnow(),
                "can_undo": (
                    operation.status == "succeeded"
                    and operation.undo_expires_at is not None
                    and operation.undo_expires_at > _utcnow()
                    and not operation.undone_by_operation_id
                ),
            }
        )
    return data


def _expire_if_needed(operation: IntegrationOperation, now: datetime | None = None) -> bool:
    if operation.status == "pending_approval" and operation.approval_expires_at <= (now or _utcnow()):
        operation.status = "expired"
        operation.failure_message = operation.failure_message or "审批链接已过期，未产生写入"
        return True
    return False


def _extract_machine_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value.startswith(TOKEN_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Codex 集成令牌无效")
    return value.strip()


def require_codex_token(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CodexPrincipal:
    raw_token = _extract_machine_token(authorization)
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    token = db.query(IntegrationAccessToken).filter(IntegrationAccessToken.token_hash == digest).first()
    now = _utcnow()
    if not token or token.status != "active" or token.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Codex 集成令牌已撤销或不存在")
    if token.expires_at and token.expires_at <= now:
        token.status = "expired"
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Codex 集成令牌已过期")
    scopes = tuple(item for item in token.scopes.split() if item)
    if READ_SCOPE not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="令牌没有个人库存读取权限")
    _limiter.check(token.id, "read", READ_RATE_LIMIT)
    token.last_used_at = now
    db.commit()
    return CodexPrincipal(token.id, token.owner_user_id, scopes, token.expires_at)


def _require_owner(auth: AuthContext, owner_user_id: int) -> None:
    if auth.user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="操作不存在")


@router.get("/api/integrations/codex/tokens")
def list_tokens(auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    rows = (
        db.query(IntegrationAccessToken)
        .filter(IntegrationAccessToken.owner_user_id == auth.user_id)
        .order_by(IntegrationAccessToken.created_at.desc())
        .all()
    )
    return [_token_out(row) for row in rows]


@router.post("/api/integrations/codex/tokens")
def create_token(payload: TokenCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = IntegrationAccessToken(
        id=str(uuid4()),
        owner_user_id=auth.user_id,
        name=payload.name.strip(),
        token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        token_prefix=raw[:18],
        scopes=READ_SCOPE,
        status="active",
        expires_at=_utcnow() + timedelta(days=payload.expires_in_days),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return {**_token_out(token), "token": raw, "shown_once": True}


@router.delete("/api/integrations/codex/tokens/{token_id}")
def revoke_token(token_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    token = db.get(IntegrationAccessToken, token_id)
    if not token or token.owner_user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="令牌不存在")
    if token.status == "active":
        token.status = "revoked"
        token.revoked_at = _utcnow()
        db.commit()
    return _token_out(token)


def _component_query(db: Session, owner_user_id: int):
    return (
        db.query(Component)
        .options(joinedload(Component.category))
        .filter(Component.owner_user_id == owner_user_id, Component.revoked_at.is_(None))
    )


def _component_out(
    db: Session,
    component: Component,
    reserved: dict[int, int] | None = None,
    search_keyword: str | None = None,
) -> dict[str, Any]:
    reserved = reserved if reserved is not None else reserved_quantities(db, [component.id])
    held = int(reserved.get(component.id, 0))
    quantity = int(component.quantity or 0)
    occupied = equipment_occupied_quantity(component)
    available = component_available_quantity(component, held)
    return {
        "id": component.id,
        "warehouse_code": component.warehouse_code,
        "name": component.name,
        "model": component.model,
        "manufacturer": component.manufacturer,
        "description": component.description,
        "category": component.category.name if component.category else None,
        "parameters": component.parameters,
        "normalized_spec": component.normalized_spec,
        "package": component.package,
        "lcsc_number": component.lcsc_number,
        "quantity": quantity,
        "average_unit_price": component.average_unit_price,
        "price_currency": "CNY",
        "reserved_quantity": held,
        "occupied_quantity": occupied,
        "available_quantity": available,
        "stock_status": "shortage" if quantity - held - occupied < 0 else normalize_inventory_status(component.status, location=component.location),
        "location": normalize_inventory_location(component.location),
        "location_code": component.location_code,
        "datasheet_url": component.datasheet_url,
        "buy_url": component.buy_url,
        "tags": component.tags,
        "safety_quantity": component.safety_quantity,
        "target_quantity": component.target_quantity,
        "ai_summary": component.ai_summary,
        "ai_usage": _load(component.ai_usage, component.ai_usage),
        "ai_risk_notes": _load(component.ai_risk_notes, component.ai_risk_notes),
        "ai_substitutes": _load(component.ai_substitutes, component.ai_substitutes),
        "updated_at": component.updated_at,
        "search_unit_conversion": find_unit_conversion_match(
            search_keyword,
            (
                component.warehouse_code,
                component.name,
                component.model,
                component.manufacturer,
                component.parameters,
                component.normalized_spec,
                component.package,
                component.lcsc_number,
                component.tags,
            ),
        ),
    }


def _workspace_dataset_rows(db: Session, owner_user_id: int) -> dict[str, list[dict[str, Any]]]:
    selected = collect_personal_rows(db, owner_user_id)
    for name in WORKSPACE_PERSONAL_EXTRA_DATASETS:
        table = Base.metadata.tables.get(name)
        if table is None or "owner_user_id" not in table.c:
            continue
        primary = primary_key_column(table)
        statement = select(table).where(table.c.owner_user_id == owner_user_id).order_by(primary.asc())
        selected[name] = [dict(row) for row in db.execute(statement).mappings().all()]
    return {
        name: rows
        for name, rows in selected.items()
        if name not in WORKSPACE_EXCLUDED_DATASETS and name in Base.metadata.tables
    }


def _workspace_field_visible(name: str) -> bool:
    lowered = name.lower()
    return (
        name not in WORKSPACE_EXCLUDED_FIELDS
        and "user_id" not in lowered
        and "password" not in lowered
        and "token" not in lowered
        and not lowered.endswith("_path")
    )


def _workspace_value(name: str, value: Any) -> Any:
    if isinstance(value, str) and name.endswith("_json"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return sync_json_value(value)


def _workspace_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        name: _workspace_value(name, value)
        for name, value in row.items()
        if _workspace_field_visible(name)
    }


def _workspace_dataset_catalog(selected: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    datasets = []
    for name in sorted(selected):
        table = Base.metadata.tables[name]
        datasets.append(
            {
                "dataset": name,
                "primary_key": primary_key_column(table).name,
                "fields": [column.name for column in table.columns if _workspace_field_visible(column.name)],
                "count": len(selected[name]),
            }
        )
    return datasets


@router.get("/api/integrations/codex/v1/session")
def codex_session(principal: CodexPrincipal = Depends(require_codex_token)):
    return {
        "service_name": SERVICE_NAME,
        "owner_user_id": principal.owner_user_id,
        "scopes": principal.scopes,
        "expires_at": principal.expires_at,
        "service_version": SERVICE_VERSION,
        "read_mode": "full_personal_workspace",
        "workspace_catalog": "/api/integrations/codex/v1/workspace",
        "excluded_boundaries": WORKSPACE_EXCLUDED_BOUNDARIES,
        "write_mode": "browser_approval_only",
        "limits": {
            "read_per_minute": READ_RATE_LIMIT,
            "workspace_read_per_minute": WORKSPACE_READ_RATE_LIMIT,
            "workspace_page_size": WORKSPACE_PAGE_LIMIT,
            "proposals_per_minute": PROPOSAL_RATE_LIMIT,
        },
    }


@router.get("/api/integrations/codex/v1/workspace")
def get_workspace_catalog(
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    _limiter.check(principal.token_id, "workspace-read", WORKSPACE_READ_RATE_LIMIT)
    selected = _workspace_dataset_rows(db, principal.owner_user_id)
    datasets = _workspace_dataset_catalog(selected)
    return {
        "service_name": SERVICE_NAME,
        "scope": "personal",
        "read_mode": "full_personal_workspace",
        "complete_personal_read": True,
        "datasets": datasets,
        "dataset_count": len(datasets),
        "record_count": sum(item["count"] for item in datasets),
        "excluded_boundaries": WORKSPACE_EXCLUDED_BOUNDARIES,
    }


@router.get("/api/integrations/codex/v1/workspace/{dataset}")
def read_workspace_dataset(
    dataset: str,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=WORKSPACE_PAGE_LIMIT),
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    _limiter.check(principal.token_id, "workspace-read", WORKSPACE_READ_RATE_LIMIT)
    selected = _workspace_dataset_rows(db, principal.owner_user_id)
    if dataset not in selected:
        raise HTTPException(status_code=404, detail="该数据集不在个人业务库只读范围内")
    rows = selected[dataset]
    primary_name = primary_key_column(Base.metadata.tables[dataset]).name
    start = 0
    if cursor:
        identifiers = [str(row.get(primary_name)) for row in rows]
        try:
            start = identifiers.index(cursor) + 1
        except ValueError as error:
            raise HTTPException(status_code=422, detail="分页游标无效，请重新读取数据集目录") from error
    page = rows[start : start + limit]
    has_more = start + len(page) < len(rows)
    next_cursor = str(page[-1].get(primary_name)) if page and has_more else None
    return {
        "service_name": SERVICE_NAME,
        "scope": "personal",
        "dataset": dataset,
        "primary_key": primary_name,
        "items": [_workspace_row(row) for row in page],
        "count": len(page),
        "total": len(rows),
        "next_cursor": next_cursor,
        "complete": next_cursor is None,
    }


@router.get("/api/integrations/codex/v1/categories")
def codex_categories(
    _principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    rows = db.query(Category).order_by(Category.id.asc()).all()
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "color": row.color,
                "code_prefix": row.code_prefix,
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.get("/api/integrations/codex/v1/components/search")
def search_components(
    q: str | None = None,
    category: str | None = None,
    package: str | None = None,
    stock: str | None = Query(default=None, pattern="^(available|shortage|all)$"),
    limit: int = Query(default=30, ge=1, le=50),
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    query = _component_query(db, principal.owner_user_id)
    if q and q.strip():
        filters = []
        for variant in keyword_unit_variants(q):
            pattern = f"%{variant}%"
            filters.extend(
                [
                    Component.warehouse_code.ilike(pattern),
                    Component.name.ilike(pattern),
                    Component.model.ilike(pattern),
                    Component.manufacturer.ilike(pattern),
                    Component.parameters.ilike(pattern),
                    Component.normalized_spec.ilike(pattern),
                    Component.package.ilike(pattern),
                    Component.lcsc_number.ilike(pattern),
                    Component.tags.ilike(pattern),
                ]
            )
        query = query.filter(or_(*filters))
    if category:
        query = query.join(Category).filter(Category.name == category)
    if package:
        query = query.filter(Component.package.ilike(f"%{package.strip()}%"))
    rows = query.order_by(Component.updated_at.desc(), Component.id.asc()).limit(200).all()
    reserved = reserved_quantities(db, [row.id for row in rows])
    result = [_component_out(db, row, reserved, q) for row in rows]
    if stock == "available":
        result = [row for row in result if row["available_quantity"] > 0]
    elif stock == "shortage":
        result = [row for row in result if row["available_quantity"] <= 0]
    return {"items": result[:limit], "count": min(len(result), limit), "scope": "personal"}


def _owned_component_by_code(db: Session, owner_user_id: int, code_or_id: str | int, include_archived: bool = False) -> Component:
    query = db.query(Component).options(joinedload(Component.category)).filter(Component.owner_user_id == owner_user_id)
    if not include_archived:
        query = query.filter(Component.revoked_at.is_(None))
    text = str(code_or_id or "").strip()
    component = query.filter(Component.warehouse_code == text.upper()).first()
    if not component and text.isdigit():
        component = query.filter(Component.id == int(text)).first()
    if not component:
        raise HTTPException(status_code=404, detail="个人库中没有该元器件")
    return component


@router.get("/api/integrations/codex/v1/components/{warehouse_code}")
def get_component(
    warehouse_code: str,
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    component = _owned_component_by_code(db, principal.owner_user_id, warehouse_code)
    suppliers = (
        db.query(SupplierPart)
        .filter(
            SupplierPart.scope_type == "personal",
            SupplierPart.owner_user_id == principal.owner_user_id,
            SupplierPart.component_id == component.id,
            SupplierPart.status == "active",
        )
        .all()
    )
    lots = (
        db.query(InventoryLot)
        .filter(InventoryLot.owner_user_id == principal.owner_user_id, InventoryLot.component_id == component.id)
        .order_by(InventoryLot.received_at.desc())
        .limit(50)
        .all()
    )
    movements = (
        db.query(StockMovement)
        .filter(StockMovement.owner_user_id == principal.owner_user_id, StockMovement.component_id == component.id)
        .order_by(StockMovement.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        **_component_out(db, component),
        "supplier_parts": [
            {
                "supplier": row.supplier,
                "supplier_part_number": row.supplier_part_number,
                "purchase_url": row.purchase_url,
                "unit_price": row.unit_price,
                "currency": row.currency,
                "is_preferred": row.is_preferred,
            }
            for row in suppliers
        ],
        "lots": [
            {
                "id": row.id,
                "source_type": row.source_type,
                "source_reference": row.source_reference,
                "location": row.location,
                "initial_quantity": row.initial_quantity,
                "remaining_quantity": row.remaining_quantity,
                "received_at": row.received_at,
            }
            for row in lots
        ],
        "recent_movements": [
            {
                "id": row.id,
                "movement_type": row.movement_type,
                "quantity_delta": row.quantity_delta,
                "reason": row.reason,
                "created_at": row.created_at,
            }
            for row in movements
        ],
    }


@router.post("/api/integrations/codex/v1/components/match")
def match_components(
    payload: MatchRequest,
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    component_ids = [row.id for row in _component_query(db, principal.owner_user_id).all()]
    rows: list[BomRow] = []
    for index, item in enumerate(payload.items, start=1):
        data = item.model_dump()
        data["required_quantity"] = item.required_quantity or item.quantity
        data["comment"] = item.parameters
        rows.append(BomRow(index, data))
    matches = match_bom_rows(
        db,
        rows,
        top_n=payload.top_n,
        component_ids=component_ids,
        supplier_scope_type="personal",
        supplier_owner_user_id=principal.owner_user_id,
    )
    price_by_component_id = {
        component.id: component.average_unit_price
        for component in _component_query(db, principal.owner_user_id)
        .filter(Component.id.in_(component_ids or [0]))
        .all()
    }
    output = []
    for row in matches:
        for match in row.get("matches") or []:
            component_data = match.get("component") or {}
            component_id = component_data.get("id")
            component_data["average_unit_price"] = price_by_component_id.get(component_id)
            component_data["price_currency"] = "CNY"
        best = row.get("matches", [None])[0] if row.get("matches") else None
        if row["status"] in {"exact", "exact_lcsc"} and best and not best.get("enough"):
            classification = "shortage"
        elif row["status"] in {"exact", "exact_lcsc"}:
            classification = "exact"
        elif row.get("matches"):
            classification = "candidate"
        else:
            classification = "missing"
        if classification == "shortage":
            row["selected_component_id"] = None
        output.append({**row, "classification": classification, "auto_selected": classification == "exact" and row.get("selected_component_id") is not None})
    return {"items": output, "count": len(output), "scope": "personal"}


def _project_out(db: Session, project: Project) -> dict[str, Any]:
    version = active_project_version(db, project)
    bom_rows = (
        db.query(ProjectBomItem)
        .options(joinedload(ProjectBomItem.component))
        .join(Component, Component.id == ProjectBomItem.component_id)
        .filter(ProjectBomItem.project_id == project.id, ProjectBomItem.status != "archived")
        .filter(ProjectBomItem.pcb_version_id == version.id if version else ProjectBomItem.pcb_version_id.is_(None))
        .filter(Component.owner_user_id == project.owner_user_id, Component.revoked_at.is_(None))
        .order_by(ProjectBomItem.id.asc())
        .all()
    )
    total_reserved = reserved_quantities(db, [row.component_id for row in bom_rows])
    bom = []
    for row in bom_rows:
        points = list(getattr(row, "solder_points", []) or [])
        pending_points = sum(1 for point in points if not point.soldered)
        own_reserved = (
            pending_points
            if points and row.status == "reserved"
            else int(row.required_quantity or 0)
            if row.status == "reserved"
            else 0
        )
        reserved_all_projects = int(total_reserved.get(row.component_id, 0))
        reserved_by_others = max(0, reserved_all_projects - own_reserved)
        stock_quantity = int(row.component.quantity or 0)
        available_for_project = max(0, stock_quantity - reserved_by_others)
        free_quantity = max(0, stock_quantity - reserved_all_projects)
        physical_shortage = max(0, own_reserved - stock_quantity)
        total_shortage = max(0, own_reserved - available_for_project)
        reservation_shortage = max(0, total_shortage - physical_shortage)
        bom.append(
            {
                "id": row.id,
                "pcb_version_id": row.pcb_version_id,
                "component_id": row.component_id,
                "warehouse_code": row.component.warehouse_code,
                "name": row.component.name,
                "model": row.component.model,
                "required_quantity": row.required_quantity,
                "own_reserved_quantity": own_reserved,
                "reserved_quantity": reserved_all_projects,
                "reserved_by_other_projects_quantity": reserved_by_others,
                "stock_quantity": stock_quantity,
                "free_quantity": free_quantity,
                "available_for_project_quantity": available_for_project,
                "physical_shortage_quantity": physical_shortage,
                "reservation_shortage_quantity": reservation_shortage,
                "shortage_quantity": total_shortage,
                "enough": total_shortage == 0,
                "status": row.status,
                "remark": row.remark,
            }
        )
    versions = db.query(ProjectPcbVersion).filter(ProjectPcbVersion.project_id == project.id).order_by(
        ProjectPcbVersion.sequence_number.desc()
    ).all()
    return {
        "id": project.id,
        "project_code": project.project_code,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "status_label": PROJECT_STATUS_LABELS.get(project.status, project.status),
        "start_date": project.start_date,
        "end_date": project.end_date,
        "period": project_period(project),
        "archived": project.archived_at is not None,
        "current_version_id": version.id if version else None,
        "current_version_code": version.version_code if version else None,
        "versions": [version_stats(db, project, item) for item in versions],
        "cost_summary": project_cost_summary(db, project),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "bom": bom,
    }


def _owned_project(db: Session, owner_user_id: int, project_id: str | int, include_archived: bool = False) -> Project:
    query = db.query(Project).filter(Project.scope_type == "personal", Project.owner_user_id == owner_user_id)
    if not include_archived:
        query = query.filter(Project.archived_at.is_(None))
    text = str(project_id or "").strip()
    project = query.filter(Project.project_code == text.upper()).first()
    if not project:
        alias = db.query(ProjectCodeAlias).filter(ProjectCodeAlias.old_code == text.upper()).first()
        if alias:
            project = query.filter(Project.id == alias.project_id).first()
    if not project and text.isdigit():
        project = query.filter(Project.id == int(text)).first()
    if not project:
        raise HTTPException(status_code=404, detail="个人项目不存在")
    return project


def _workspace_owned_project(
    db: Session,
    owner_user_id: int,
    project_reference: str,
    include_archived: bool = False,
) -> PersonalProjectV2:
    query = db.query(PersonalProjectV2).filter(PersonalProjectV2.owner_user_id == owner_user_id)
    if not include_archived:
        query = query.filter(PersonalProjectV2.archived_at.is_(None))
    reference = str(project_reference or "").strip()
    project = query.filter(
        or_(PersonalProjectV2.id == reference, PersonalProjectV2.project_code == reference.upper())
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="个人 Project V2 项目不存在")
    return project


def _workspace_project_out(db: Session, project: PersonalProjectV2) -> dict[str, Any]:
    result = workspace_project_summary(db, project)
    history = db.query(PersonalProjectStatusEventV2).filter(
        PersonalProjectStatusEventV2.project_id == project.id
    ).order_by(PersonalProjectStatusEventV2.created_at.desc()).limit(100).all()
    versions = db.query(PersonalProjectVersionV2).filter(
        PersonalProjectVersionV2.project_id == project.id
    ).order_by(PersonalProjectVersionV2.sequence_number.desc()).all()
    bom = []
    if project.current_version_id:
        rows = db.query(PersonalProjectBomItemV2, Component).join(
            Component, Component.id == PersonalProjectBomItemV2.component_id
        ).filter(
            PersonalProjectBomItemV2.version_id == project.current_version_id,
            PersonalProjectBomItemV2.archived_at.is_(None),
            Component.owner_user_id == project.owner_user_id,
            Component.revoked_at.is_(None),
        ).order_by(PersonalProjectBomItemV2.created_at.asc()).all()
        for item, component in rows:
            required = int(item.quantity_per_board or 0)
            available = component_available_quantity(component, 0)
            bom.append({
                "id": item.id,
                "version_id": item.version_id,
                "component_id": component.id,
                "warehouse_code": component.warehouse_code,
                "name": component.name,
                "model": component.model,
                "quantity_per_board": required,
                "designators": [part for part in str(item.designators or "").split(",") if part],
                "stock_quantity": int(component.quantity or 0),
                "available_quantity": available,
                "shortage_quantity": max(0, required - available),
                "enough": available >= required,
                "average_unit_price": component.average_unit_price,
                "price_currency": "CNY",
                "unpriced": component.average_unit_price is None,
                "note": item.note,
            })
    return {
        **result,
        "schema_version": "project-workspace-v2",
        "current_version_id": project.current_version_id,
        "current_version_code": result.get("current_version", {}).get("version_code") if result.get("current_version") else None,
        "versions": [workspace_version_out(db, row) for row in versions],
        "cost_summary": result["cost"],
        "lifecycle": workspace_lifecycle_out(project, history),
        "status_history": workspace_status_history_out(history),
        "bom": bom,
    }


@router.get("/api/integrations/codex/v1/projects")
def list_projects(
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(PersonalProjectV2)
        .filter(
            PersonalProjectV2.owner_user_id == principal.owner_user_id,
            PersonalProjectV2.archived_at.is_(None),
        )
        .order_by(PersonalProjectV2.updated_at.desc())
        .all()
    )
    return {"items": [_workspace_project_out(db, row) for row in rows], "count": len(rows), "scope": "personal", "schema_version": "project-workspace-v2"}


@router.get("/api/integrations/codex/v1/projects/overview")
def get_projects_overview(
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    rows = db.query(PersonalProjectV2).filter(
        PersonalProjectV2.owner_user_id == principal.owner_user_id,
        PersonalProjectV2.archived_at.is_(None),
    ).order_by(PersonalProjectV2.updated_at.desc()).all()
    projects = []
    for project in rows:
        version = db.get(PersonalProjectVersionV2, project.current_version_id) if project.current_version_id else None
        costs = workspace_cost_summary(db, project)
        projects.append(
            {
                "id": project.id,
                "project_code": project.project_code,
                "name": project.name,
                "status": project.status,
                "status_label": WORKSPACE_PROJECT_STATUSES.get(project.status, project.status),
                "period": workspace_period_out(project),
                "current_version_id": version.id if version else None,
                "current_version_code": version.version_code if version else None,
                "actual_material_cost": costs["actual_material_cost"],
                "direct_expense": costs["direct_expense"],
                "comprehensive_cost": costs["comprehensive_cost"],
                "unpriced_count": costs["unpriced_count"],
                "updated_at": project.updated_at,
            }
        )
    return {
        "items": projects,
        "count": len(projects),
        "currency": "CNY",
        "cost_definition": "comprehensive_cost = actual_material_cost + direct_expense; purchases are excluded",
        "unpriced_policy": "missing average prices are reported as unpriced and never treated as zero",
        "schema_version": "project-workspace-v2",
    }


@router.get("/api/integrations/codex/v1/projects/{project_id}/versions")
def get_project_versions(
    project_id: str,
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    project = _workspace_owned_project(db, principal.owner_user_id, project_id)
    rows = db.query(PersonalProjectVersionV2).filter(PersonalProjectVersionV2.project_id == project.id).order_by(
        PersonalProjectVersionV2.sequence_number.desc()
    ).all()
    return {"project_code": project.project_code, "schema_version": "project-workspace-v2", "items": [workspace_version_out(db, row) for row in rows]}


@router.get("/api/integrations/codex/v1/projects/{project_id}/costs")
def get_project_costs(
    project_id: str,
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    project = _workspace_owned_project(db, principal.owner_user_id, project_id)
    return workspace_cost_summary(db, project) | {
        "currency": "CNY",
        "cost_definition": "comprehensive_cost = actual_material_cost + direct_expense; purchases are excluded",
        "schema_version": "project-workspace-v2",
    }


@router.get("/api/integrations/codex/v1/projects/{project_id}")
def get_project(
    project_id: str,
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    return _workspace_project_out(db, _workspace_owned_project(db, principal.owner_user_id, project_id))


@router.get("/api/integrations/codex/v1/risks")
def get_risks(
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    result = list_risks_impl(db, RiskScope("personal", principal.owner_user_id, None))
    project_ids = {
        row.id: row.project_code
        for row in db.query(PersonalProjectV2).filter(PersonalProjectV2.owner_user_id == principal.owner_user_id).all()
    }
    workspace_risks = db.query(PersonalProjectRiskV2).filter(
        PersonalProjectRiskV2.project_id.in_(list(project_ids) or [""])
    ).order_by(PersonalProjectRiskV2.status.asc(), PersonalProjectRiskV2.created_at.desc()).all()
    result["items"] = [
        {
            "risk_code": f"PV2-{row.id[:8].upper()}",
            "source": "project-workspace-v2",
            "project_id": row.project_id,
            "project_code": project_ids.get(row.project_id),
            "severity": row.severity,
            "status": row.status,
            "title": row.title,
            "detail": row.detail,
            "created_at": row.created_at,
        }
        for row in workspace_risks
    ] + result["items"]
    result["count"] = len(result["items"])
    for row in result["items"]:
        if row.get("component_id") and not row.get("warehouse_code"):
            component = db.get(Component, row["component_id"])
            if component and component.owner_user_id == principal.owner_user_id:
                row["warehouse_code"] = component.warehouse_code
        if row.get("project_id"):
            project = db.get(Project, row["project_id"])
            if project and project.owner_user_id == principal.owner_user_id:
                row["project_code"] = project.project_code
    return {**result, "count": result["total"], "scope": "personal"}


def _order_out(db: Session, order: PurchaseOrder) -> dict[str, Any]:
    lines = db.query(PurchaseLine).filter(PurchaseLine.purchase_order_id == order.id).order_by(PurchaseLine.created_at).all()
    project = db.get(Project, order.project_id) if order.project_id else None
    components = {
        component.id: component
        for component in db.query(Component).filter(Component.id.in_([row.component_id for row in lines if row.component_id] or [0])).all()
        if component.owner_user_id == order.owner_user_id
    }
    return {
        "id": order.id,
        "project_id": order.project_id,
        "project_code": project.project_code if project and project.owner_user_id == order.owner_user_id else None,
        "order_number": order.order_number,
        "platform": order.platform,
        "status": order.status,
        "currency": order.currency,
        "note": order.note,
        "lines": [
            ({
                "id": row.id,
                "component_id": row.component_id,
                "warehouse_code": components[row.component_id].warehouse_code if row.component_id in components else None,
                "description": row.description,
                "ordered_quantity": row.ordered_quantity,
                "received_quantity": row.received_quantity,
                "outstanding_quantity": max(0, int(row.ordered_quantity or 0) - int(row.received_quantity or 0)),
                "unit_price": row.unit_price,
                "purchase_url": row.purchase_url,
                "status": row.status,
                "note": row.note,
                "counts_as_in_transit": order.status in {"ordered", "partial"} and row.status in {"ordered", "partial"},
                "in_transit_quantity": (
                    max(0, int(row.ordered_quantity or 0) - int(row.received_quantity or 0))
                    if order.status in {"ordered", "partial"} and row.status in {"ordered", "partial"}
                    else 0
                ),
            })
            for row in lines
        ],
    }


@router.get("/api/integrations/codex/v1/purchases")
def get_purchases(
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.scope_type == "personal", PurchaseOrder.owner_user_id == principal.owner_user_id)
        .order_by(PurchaseOrder.updated_at.desc())
        .all()
    )
    return {"items": [_order_out(db, row) for row in rows], "count": len(rows), "scope": "personal"}


COMPONENT_FIELDS = {
    "name",
    "model",
    "manufacturer",
    "description",
    "category_id",
    "parameters",
    "package",
    "average_unit_price",
    "source",
    "lcsc_number",
    "tags",
    "normalized_spec",
    "status",
    "location",
    "remark",
    "datasheet_url",
    "buy_url",
    "target_quantity",
    "safety_quantity",
    "low_stock_exempt",
}
PROJECT_FIELDS = {"name", "description", "start_date", "end_date"}
ORDER_FIELDS = {"order_number", "platform", "status", "currency", "note"}
SUPPORTED_ACTIONS = {
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
}


def _normalize_average_unit_price(payload: dict[str, Any]) -> None:
    if "average_unit_price" not in payload or payload["average_unit_price"] is None:
        return
    try:
        average_unit_price = Decimal(str(payload["average_unit_price"]))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="器件均价必须是有效数字") from error
    if average_unit_price < 0 or average_unit_price > Decimal("99999999.999999"):
        raise HTTPException(status_code=422, detail="器件均价超出允许范围")
    payload["average_unit_price"] = average_unit_price.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _snapshot_component(component: Component) -> dict[str, Any]:
    return {field: getattr(component, field) for field in sorted(COMPONENT_FIELDS)} | {
        "id": component.id,
        "warehouse_code": component.warehouse_code,
        "quantity": component.quantity,
        "occupied_quantity": equipment_occupied_quantity(component),
        "revoked_at": component.revoked_at,
        "updated_at": component.updated_at,
    }


def _snapshot_project(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "project_code": project.project_code,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "start_date": project.start_date,
        "end_date": project.end_date,
        "archived_at": project.archived_at,
        "active_pcb_version_id": project.active_pcb_version_id,
        "updated_at": project.updated_at,
    }


def _owned_version(db: Session, owner_user_id: int, version_id: str | int) -> tuple[Project, ProjectPcbVersion]:
    text = str(version_id or "").strip()
    if not text.isdigit():
        raise HTTPException(status_code=422, detail="PCB 版本目标必须是数字 ID")
    version = db.get(ProjectPcbVersion, int(text))
    project = db.get(Project, version.project_id) if version else None
    if not version or not project or project.scope_type != "personal" or project.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="个人项目中没有该 PCB 版本")
    return project, version


def _snapshot_version(version: ProjectPcbVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_code": version.version_code,
        "status": version.status,
        "change_summary": version.change_summary,
        "archived_at": version.archived_at,
    }


def _owned_expense(db: Session, owner_user_id: int, expense_id: str) -> tuple[Project, ProjectExpense]:
    expense = db.get(ProjectExpense, str(expense_id))
    project = db.get(Project, expense.project_id) if expense else None
    if not expense or not project or project.scope_type != "personal" or project.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="个人项目中没有该费用记录")
    return project, expense


def _snapshot_expense(expense: ProjectExpense) -> dict[str, Any]:
    return {
        "id": expense.id,
        "project_id": expense.project_id,
        "pcb_version_id": expense.pcb_version_id,
        "category": expense.category,
        "amount": expense.amount,
        "occurred_on": expense.occurred_on,
        "vendor": expense.vendor,
        "note": expense.note,
        "attachment_asset_id": expense.attachment_asset_id,
        "archived_at": expense.archived_at,
    }


def _snapshot_workspace_project(project: PersonalProjectV2) -> dict[str, Any]:
    return {
        "id": project.id,
        "project_code": project.project_code,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "start_date": project.start_date,
        "end_date": project.end_date,
        "archived_at": project.archived_at,
        "current_version_id": project.current_version_id,
        "updated_at": project.updated_at,
        "schema_version": "project-workspace-v2",
    }


def _workspace_owned_version(
    db: Session, owner_user_id: int, version_id: str
) -> tuple[PersonalProjectV2, PersonalProjectVersionV2]:
    version = db.get(PersonalProjectVersionV2, str(version_id))
    project = db.get(PersonalProjectV2, version.project_id) if version else None
    if not version or not project or project.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Project V2 中没有该 PCB 版本")
    return project, version


def _snapshot_workspace_version(version: PersonalProjectVersionV2) -> dict[str, Any]:
    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_code": version.version_code,
        "status": version.status,
        "change_summary": version.change_summary,
    }


def _workspace_owned_expense(
    db: Session, owner_user_id: int, expense_id: str
) -> tuple[PersonalProjectV2, PersonalProjectExpenseV2]:
    expense = db.get(PersonalProjectExpenseV2, str(expense_id))
    project = db.get(PersonalProjectV2, expense.project_id) if expense else None
    if not expense or not project or project.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Project V2 中没有该费用")
    return project, expense


def _snapshot_workspace_expense(expense: PersonalProjectExpenseV2) -> dict[str, Any]:
    return {
        "id": expense.id,
        "project_id": expense.project_id,
        "version_id": expense.version_id,
        "category": expense.category,
        "amount": expense.amount,
        "occurred_on": expense.occurred_on,
        "vendor": expense.vendor,
        "note": expense.note,
        "archived_at": expense.archived_at,
    }


def _workspace_owned_bom(db: Session, owner_user_id: int, bom_id: str) -> PersonalProjectBomItemV2:
    row = db.get(PersonalProjectBomItemV2, str(bom_id))
    project = db.get(PersonalProjectV2, row.project_id) if row else None
    if not row or not project or project.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Project V2 中没有该 BOM 行")
    return row


def _owned_bom(db: Session, owner_user_id: int, bom_id: str | int) -> ProjectBomItem:
    text = str(bom_id or "")
    if not text.isdigit():
        raise HTTPException(status_code=422, detail="BOM 目标必须是数字 ID")
    row = (
        db.query(ProjectBomItem)
        .join(Project, Project.id == ProjectBomItem.project_id)
        .filter(ProjectBomItem.id == int(text), Project.scope_type == "personal", Project.owner_user_id == owner_user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="个人项目中没有该 BOM 行")
    return row


def _owned_order(db: Session, owner_user_id: int, order_id: str) -> PurchaseOrder:
    row = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.id == str(order_id), PurchaseOrder.scope_type == "personal", PurchaseOrder.owner_user_id == owner_user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="个人采购单不存在")
    return row


def _owned_line(db: Session, owner_user_id: int, line_id: str) -> tuple[PurchaseOrder, PurchaseLine]:
    line = db.get(PurchaseLine, str(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="采购行不存在")
    return _owned_order(db, owner_user_id, line.purchase_order_id), line


def _prepare_action(
    db: Session,
    owner_user_id: int,
    action: dict[str, Any],
    pending_project_codes: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    action_name = str(action.get("action") or "")
    if action_name not in SUPPORTED_ACTIONS:
        raise HTTPException(status_code=422, detail=f"不支持的操作：{action_name}")
    target_id = action.get("target_id")
    payload = dict(action.get("payload") or {})
    before: Any = None
    label = action_name
    risk = "normal"
    if action_name == "component.create":
        if not str(payload.get("name") or "").strip():
            raise HTTPException(status_code=422, detail="新建元器件必须提供 name")
        payload = {key: value for key, value in payload.items() if key in COMPONENT_FIELDS or key == "quantity"}
        original_location = payload.get("location")
        if "location" in payload:
            payload["location"] = normalize_inventory_location(original_location)
        payload["status"] = normalize_inventory_status(payload.get("status"), location=original_location)
        _normalize_average_unit_price(payload)
        if payload.get("category_id") is not None and not db.get(Category, int(payload["category_id"])):
            raise HTTPException(status_code=404, detail="元器件类别不存在")
        before = {"name": payload.get("name"), "model": payload.get("model"), "exists": False}
        label = f"新建元器件 {payload['name']}"
    elif action_name.startswith("component.") or action_name == "stock.adjust":
        component = _owned_component_by_code(db, owner_user_id, target_id, include_archived=action_name == "component.restore")
        before = _snapshot_component(component)
        target_id = component.warehouse_code or component.id
        label = f"{action_name} {component.warehouse_code or component.id} {component.name}"
        if action_name == "component.update":
            payload = {key: value for key, value in payload.items() if key in COMPONENT_FIELDS}
            if not payload:
                raise HTTPException(status_code=422, detail="元器件更新没有有效字段")
            original_location = payload.get("location")
            if "location" in payload:
                payload["location"] = normalize_inventory_location(original_location)
            if "status" in payload or original_location:
                payload["status"] = normalize_inventory_status(payload.get("status") or component.status, location=original_location)
            _normalize_average_unit_price(payload)
        elif action_name == "stock.adjust":
            delta = int(payload.get("delta") or 0)
            if not delta:
                raise HTTPException(status_code=422, detail="库存变更量不能为 0")
            if delta < 0 and abs(delta) > int(component.quantity or 0):
                raise HTTPException(status_code=409, detail="库存扣减或报损不能超过当前库存")
            movement_type = str(payload.get("movement_type") or "codex_adjustment")
            if movement_type not in {"codex_adjustment", "manual_consume", "loss", "purchase_receipt", "manual_receipt", "codex_undo"}:
                raise HTTPException(status_code=422, detail="库存流水类型无效")
            payload = {**payload, "delta": delta, "movement_type": movement_type}
            risk = "high" if delta < 0 else "normal"
        elif action_name in {"component.archive", "component.restore"}:
            risk = "high"
    elif action_name == "workspace.project.create":
        if not str(payload.get("name") or "").strip():
            raise HTTPException(status_code=422, detail="新建 Project V2 项目必须提供 name")
        code = normalize_workspace_code(payload.get("project_code"))
        if db.query(PersonalProjectV2.id).filter(PersonalProjectV2.project_code == code).first():
            raise HTTPException(status_code=409, detail="项目编号已存在")
        status_value = str(payload.get("status") or "planning")
        if status_value not in WORKSPACE_PROJECT_STATUSES:
            raise HTTPException(status_code=422, detail="不支持的 Project V2 状态")
        start_date_value = _date_value(payload.get("start_date"), workspace_today())
        if start_date_value > workspace_today():
            raise HTTPException(status_code=422, detail="开始日期不能晚于今天")
        lifecycle_dates = payload.get("lifecycle_dates")
        normalized_dates = None
        if lifecycle_dates is not None:
            if not isinstance(lifecycle_dates, dict):
                raise HTTPException(status_code=422, detail="lifecycle_dates 必须是阶段与日期的映射")
            normalized_dates = {
                key: _date_value(value).isoformat() for key, value in lifecycle_dates.items()
            }
            normalize_workspace_actual_lifecycle_dates(
                status_value,
                start_date_value,
                {key: _date_value(value) for key, value in normalized_dates.items()},
            )
        payload = {
            "project_code": code,
            "name": str(payload["name"]).strip()[:200],
            "description": str(payload.get("description") or "")[:5000] or None,
            "status": status_value,
            "start_date": start_date_value.isoformat(),
            "lifecycle_dates": normalized_dates,
        }
        before = {"project_code": code, "exists": False, "schema_version": "project-workspace-v2"}
        label = f"新建 Project V2 项目 {code} · {payload['name']}"
    elif action_name.startswith("workspace.project."):
        project = _workspace_owned_project(
            db, owner_user_id, target_id, include_archived=action_name == "workspace.project.restore"
        )
        before = _snapshot_workspace_project(project)
        target_id = project.project_code
        label = f"{action_name} {project.project_code} · {project.name}"
        if action_name == "workspace.project.update":
            payload = {key: value for key, value in payload.items() if key in PROJECT_FIELDS}
            if not payload:
                raise HTTPException(status_code=422, detail="项目更新没有有效字段")
        elif action_name == "workspace.project.status":
            status_value = str(payload.get("status") or "")
            if status_value not in WORKSPACE_PROJECT_STATUSES:
                raise HTTPException(status_code=422, detail="不支持的 Project V2 状态")
            payload = {
                "status": status_value,
                "note": str(payload.get("note") or "")[:1000] or None,
                "clear_end_date": bool(payload.get("clear_end_date")),
                "restore_end_date": payload.get("restore_end_date"),
            }
        else:
            payload = {}
            risk = "high"
    elif action_name == "workspace.version.create":
        reference = str(target_id or "").strip().upper()
        project = None
        try:
            project = _workspace_owned_project(db, owner_user_id, reference)
        except HTTPException:
            if reference not in (pending_project_codes or set()):
                raise
        sequence = (
            (db.query(PersonalProjectVersionV2.id).filter(PersonalProjectVersionV2.project_id == project.id).count() + 1)
            if project else 2
        )
        version_code = normalize_workspace_version(payload.get("version_code") or f"V{sequence}")
        change_summary = str(payload.get("change_summary") or "").strip() or None
        if sequence > 1 and not change_summary:
            raise HTTPException(status_code=422, detail="V2 及后续版本必须填写变更说明")
        payload = {"version_code": version_code, "change_summary": change_summary}
        before = {"project_code": reference, "exists": False, "schema_version": "project-workspace-v2"}
        label = f"为 {reference} 建立 PCB {version_code}"
    elif action_name == "workspace.version.status":
        project, version = _workspace_owned_version(db, owner_user_id, str(target_id))
        before = _snapshot_workspace_version(version)
        status_value = str(payload.get("status") or "")
        if status_value not in WORKSPACE_VERSION_STATUSES:
            raise HTTPException(status_code=422, detail="不支持的 PCB 版本状态")
        payload = {"status": status_value}
        label = f"更新 {project.project_code}/{version.version_code} 状态"
    elif action_name == "workspace.expense.create":
        reference = str(target_id or "").strip().upper()
        project = None
        try:
            project = _workspace_owned_project(db, owner_user_id, reference)
        except HTTPException:
            if reference not in (pending_project_codes or set()):
                raise
        category = str(payload.get("category") or "")
        if category not in WORKSPACE_EXPENSE_CATEGORIES:
            raise HTTPException(status_code=422, detail="不支持的费用分类")
        try:
            amount = Decimal(str(payload.get("amount"))).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="费用金额必须是有效数字") from error
        if amount <= 0:
            raise HTTPException(status_code=422, detail="费用金额必须大于 0")
        version_id = payload.get("version_id")
        if version_id and project:
            version_project, _ = _workspace_owned_version(db, owner_user_id, str(version_id))
            if version_project.id != project.id:
                raise HTTPException(status_code=422, detail="费用关联版本不属于目标项目")
        payload = {
            "version_id": version_id,
            "category": category,
            "amount": amount,
            "occurred_on": payload.get("occurred_on"),
            "vendor": str(payload.get("vendor") or "")[:200] or None,
            "note": str(payload.get("note") or "")[:2000] or None,
        }
        before = {"project_code": reference, "exists": False, "schema_version": "project-workspace-v2"}
        label = f"为 {reference} 记录 {amount} CNY 费用"
    elif action_name in {"workspace.expense.archive", "workspace.expense.restore"}:
        project, expense = _workspace_owned_expense(db, owner_user_id, str(target_id))
        before = _snapshot_workspace_expense(expense)
        payload = {}
        label = f"{action_name} {project.project_code}/{expense.id}"
        risk = "high"
    elif action_name == "workspace.bom.upsert":
        if target_id is None:
            reference = str(payload.get("project_code") or payload.get("project_id") or "").strip().upper()
            project = None
            try:
                project = _workspace_owned_project(db, owner_user_id, reference)
            except HTTPException:
                if reference not in (pending_project_codes or set()):
                    raise
            component = _owned_component_by_code(db, owner_user_id, payload.get("warehouse_code") or payload.get("component_id"))
            quantity = max(1, int(payload.get("quantity_per_board") or payload.get("required_quantity") or 1))
            version_id = payload.get("version_id")
            if version_id and project:
                version_project, _ = _workspace_owned_version(db, owner_user_id, str(version_id))
                if version_project.id != project.id:
                    raise HTTPException(status_code=422, detail="BOM 版本不属于目标项目")
            payload = {
                "project_code": reference,
                "component_id": component.id,
                "version_id": version_id,
                "quantity_per_board": quantity,
                "designators": str(payload.get("designators") or "")[:10000] or None,
                "note": str(payload.get("note") or payload.get("remark") or "")[:2000] or None,
            }
            before = {"exists": False, "project_code": reference, "component_id": component.id}
            label = f"向 {reference} BOM 添加 {component.warehouse_code}"
        else:
            bom = _workspace_owned_bom(db, owner_user_id, str(target_id))
            before = {
                "id": bom.id, "quantity_per_board": bom.quantity_per_board,
                "designators": bom.designators, "note": bom.note,
            }
            payload = {
                key: value for key, value in payload.items()
                if key in {"quantity_per_board", "designators", "note", "archived_at"}
            }
            label = f"更新 Project V2 BOM {bom.id}"
    elif action_name in {"workspace.bom.archive", "workspace.bom.restore"}:
        bom = _workspace_owned_bom(db, owner_user_id, str(target_id))
        before = {
            "id": bom.id, "project_id": bom.project_id, "version_id": bom.version_id,
            "component_id": bom.component_id, "archived_at": bom.archived_at,
        }
        payload = {}
        label = f"{action_name} {bom.id}"
        risk = "high"
    elif action_name == "project.create":
        if not str(payload.get("name") or "").strip():
            raise HTTPException(status_code=422, detail="新建项目必须提供 name")
        try:
            project_code = normalize_project_code(payload.get("project_code"))
            assert_project_code_available(db, project_code)
        except ValueError as error:
            raise HTTPException(status_code=409 if "存在" in str(error) else 422, detail=str(error)) from error
        payload["project_code"] = project_code
        status_value = str(payload.get("status") or "planning")
        if status_value not in PROJECT_STATUS_LABELS or status_value in {"active", "completed", "archived"}:
            raise HTTPException(status_code=422, detail="不支持的项目状态")
        payload["status"] = status_value
        before = {"project_code": project_code, "exists": False}
        label = f"新建项目 {payload['name']}"
    elif action_name.startswith("project."):
        project = _owned_project(db, owner_user_id, target_id, include_archived=action_name == "project.restore")
        before = _snapshot_project(project)
        target_id = project.project_code or project.id
        label = f"{action_name} {project.project_code or project.id} {project.name}"
        if action_name == "project.update":
            payload = {key: value for key, value in payload.items() if key in PROJECT_FIELDS}
            if not payload:
                raise HTTPException(status_code=422, detail="项目更新没有有效字段")
        elif action_name == "project.status":
            status_value = str(payload.get("status") or "")
            if status_value not in PROJECT_STATUS_LABELS or status_value == "archived":
                raise HTTPException(status_code=422, detail="不支持的项目状态")
            payload = {
                "status": status_value,
                "note": str(payload.get("note") or "")[:1000] or None,
                "clear_end_date": bool(payload.get("clear_end_date")),
                "restore_end_date": payload.get("restore_end_date"),
            }
        elif action_name == "project.code_change":
            try:
                new_code = normalize_project_code(payload.get("project_code"))
                assert_project_code_available(db, new_code, project.id)
            except ValueError as error:
                raise HTTPException(status_code=409 if "存在" in str(error) else 422, detail=str(error)) from error
            payload = {"project_code": new_code}
            risk = "high"
        else:
            risk = "high"
    elif action_name == "version.create":
        project = _owned_project(db, owner_user_id, target_id)
        before = {"project_id": project.id, "project_code": project.project_code, "exists": False}
        status_value = str(payload.get("status") or "designing")
        if status_value not in PCB_VERSION_STATUS_LABELS:
            raise HTTPException(status_code=422, detail="不支持的 PCB 版本状态")
        payload = {
            "version_code": payload.get("version_code"),
            "status": status_value,
            "change_summary": str(payload.get("change_summary") or "").strip() or None,
            "copy_from_version_id": payload.get("copy_from_version_id"),
        }
        label = f"为 {project.project_code} 新建 PCB 版本"
    elif action_name.startswith("version."):
        project, version = _owned_version(db, owner_user_id, target_id)
        before = _snapshot_version(version)
        before["project_active_pcb_version_id"] = project.active_pcb_version_id
        target_id = version.id
        label = f"{action_name} {project.project_code}/{version.version_code}"
        if action_name == "version.update":
            payload = {key: value for key, value in payload.items() if key in {"version_code", "change_summary", "make_active"}}
            if "version_code" in payload:
                try:
                    payload["version_code"] = normalize_version_code(payload["version_code"])
                except ValueError as error:
                    raise HTTPException(status_code=422, detail=str(error)) from error
        elif action_name == "version.status":
            status_value = str(payload.get("status") or "")
            if status_value not in PCB_VERSION_STATUS_LABELS:
                raise HTTPException(status_code=422, detail="不支持的 PCB 版本状态")
            payload = {"status": status_value}
        elif action_name == "version.retire":
            payload = {}
            risk = "high"
        else:
            payload = {
                "status": str(payload.get("status") or "designing"),
                "archived_at": payload.get("archived_at"),
            }
            risk = "high"
    elif action_name == "expense.create":
        project = _owned_project(db, owner_user_id, target_id)
        before = {"project_id": project.id, "project_code": project.project_code, "exists": False}
        category = str(payload.get("category") or "")
        if category not in EXPENSE_CATEGORY_LABELS:
            raise HTTPException(status_code=422, detail="不支持的费用分类")
        try:
            amount = Decimal(str(payload.get("amount")))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="费用金额必须是有效数字") from error
        if amount <= 0:
            raise HTTPException(status_code=422, detail="费用金额必须大于 0")
        version_id = payload.get("pcb_version_id")
        if version_id is not None:
            version_project, _ = _owned_version(db, owner_user_id, version_id)
            if version_project.id != project.id:
                raise HTTPException(status_code=422, detail="费用关联版本不属于目标项目")
        payload = {
            "pcb_version_id": version_id,
            "category": category,
            "amount": amount.quantize(Decimal("0.01")),
            "occurred_on": payload.get("occurred_on"),
            "vendor": str(payload.get("vendor") or "")[:200] or None,
            "note": str(payload.get("note") or "")[:2000] or None,
        }
        label = f"为 {project.project_code} 新增费用 {amount} CNY"
    elif action_name.startswith("expense."):
        project, expense = _owned_expense(db, owner_user_id, str(target_id))
        before = _snapshot_expense(expense)
        label = f"{action_name} {project.project_code}/{expense.id}"
        if action_name == "expense.update":
            payload = {key: value for key, value in payload.items() if key in {"pcb_version_id", "category", "amount", "occurred_on", "vendor", "note"}}
            if "category" in payload and payload["category"] not in EXPENSE_CATEGORY_LABELS:
                raise HTTPException(status_code=422, detail="不支持的费用分类")
            if "amount" in payload:
                try:
                    payload["amount"] = Decimal(str(payload["amount"])).quantize(Decimal("0.01"))
                except (InvalidOperation, TypeError, ValueError) as error:
                    raise HTTPException(status_code=422, detail="费用金额必须是有效数字") from error
                if payload["amount"] <= 0:
                    raise HTTPException(status_code=422, detail="费用金额必须大于 0")
            if payload.get("pcb_version_id") is not None:
                version_project, _ = _owned_version(db, owner_user_id, payload["pcb_version_id"])
                if version_project.id != project.id:
                    raise HTTPException(status_code=422, detail="费用关联版本不属于目标项目")
        else:
            payload = {}
            risk = "high"
    elif action_name == "bom.upsert" and target_id is None:
        project_reference = payload.get("project_id") or payload.get("project_code")
        project = None
        try:
            project = _owned_project(db, owner_user_id, project_reference)
        except HTTPException:
            if str(project_reference or "") not in (pending_project_codes or set()):
                raise
        component = _owned_component_by_code(db, owner_user_id, payload.get("component_id") or payload.get("warehouse_code"))
        before = {"exists": False, "project_id": project.id if project else None, "project_code": project_reference, "component_id": component.id}
        payload.update({"component_id": component.id})
        if project:
            payload["project_id"] = project.id
            if payload.get("pcb_version_id") is not None:
                version_project, version = _owned_version(db, owner_user_id, payload["pcb_version_id"])
                if version_project.id != project.id:
                    raise HTTPException(status_code=422, detail="BOM 版本不属于目标项目")
                payload["pcb_version_id"] = version.id
            else:
                version = active_project_version(db, project, create_if_missing=True)
                payload["pcb_version_id"] = version.id
        else:
            payload.pop("project_id", None)
            payload["project_code"] = str(project_reference)
        label = f"新增 BOM：{project.name if project else project_reference} / {component.name}"
    elif action_name.startswith("bom."):
        bom = _owned_bom(db, owner_user_id, target_id)
        before = {
            "id": bom.id,
            "project_id": bom.project_id,
            "component_id": bom.component_id,
            "required_quantity": bom.required_quantity,
            "status": bom.status,
            "remark": bom.remark,
        }
        target_id = bom.id
        label = f"{action_name} BOM #{bom.id}"
        if action_name in {"bom.archive", "bom.restore"}:
            risk = "high"
    elif action_name == "purchase.create":
        if payload.get("project_id") is not None:
            project_reference = payload["project_id"]
            try:
                payload["project_id"] = _owned_project(db, owner_user_id, project_reference).id
            except HTTPException:
                if str(project_reference or "") not in (pending_project_codes or set()):
                    raise
                payload.pop("project_id", None)
                payload["project_code"] = str(project_reference)
        lines = payload.get("lines") or []
        if not isinstance(lines, list) or not lines:
            raise HTTPException(status_code=422, detail="新建采购单至少包含一行")
        for line in lines:
            component = _owned_component_by_code(db, owner_user_id, line.get("component_id") or line.get("warehouse_code"))
            line["component_id"] = component.id
            if int(line.get("ordered_quantity") or 0) <= 0:
                raise HTTPException(status_code=422, detail="采购数量必须大于 0")
        before = {"order_number": payload.get("order_number"), "exists": False}
        label = f"新建采购单 {payload.get('order_number') or '未编号'}"
    elif action_name.startswith("purchase."):
        if action_name in {"purchase.receive", "purchase.reverse_receive"}:
            if action_name == "purchase.receive":
                order, line = _owned_line(db, owner_user_id, str(target_id))
                component = _owned_component_by_code(db, owner_user_id, line.component_id)
                before = {
                    "order": _order_out(db, order),
                    "line_id": line.id,
                    "component": _snapshot_component(component),
                }
                quantity = int(payload.get("quantity") or 0)
                remaining = int(line.ordered_quantity or 0) - int(line.received_quantity or 0)
                if quantity <= 0 or quantity > remaining:
                    raise HTTPException(status_code=422, detail=f"到货数量必须为 1 到 {max(0, remaining)}")
                payload["quantity"] = quantity
            else:
                receipt = db.get(PurchaseReceipt, str(target_id))
                if not receipt:
                    raise HTTPException(status_code=404, detail="到货记录不存在")
                order, line = _owned_line(db, owner_user_id, receipt.purchase_line_id)
                component = _owned_component_by_code(db, owner_user_id, line.component_id)
                before = {
                    "order": _order_out(db, order),
                    "receipt_id": receipt.id,
                    "receipt_quantity": receipt.quantity,
                    "component": _snapshot_component(component),
                }
            risk = "high"
        else:
            order = _owned_order(db, owner_user_id, str(target_id))
            before = _order_out(db, order)
            if action_name == "purchase.update":
                payload = {key: value for key, value in payload.items() if key in ORDER_FIELDS}
                if not payload:
                    raise HTTPException(status_code=422, detail="采购单更新没有有效字段")
            else:
                risk = "high"
        label = f"{action_name} {target_id}"
    normalized = {"action": action_name, "target_id": target_id, "payload": payload}
    preview = {"action": action_name, "target_id": target_id, "label": label, "risk_level": risk, "before": before, "after": payload}
    return normalized | {"preview": preview}, before


def _prepare_actions(db: Session, owner_user_id: int, actions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[Any], str]:
    pending_project_codes: set[str] = set()
    for action in actions:
        if action.get("action") != "workspace.project.create":
            continue
        payload = action.setdefault("payload", {})
        code = normalize_workspace_code(payload.get("project_code"))
        payload["project_code"] = code
        pending_project_codes.add(code)
    normalized = []
    before = []
    risk = "normal"
    for action in actions:
        prepared, snapshot = _prepare_action(db, owner_user_id, action, pending_project_codes)
        preview = prepared.pop("preview")
        normalized.append(prepared | {"preview": preview})
        before.append(snapshot)
        if preview["risk_level"] == "high":
            risk = "high"
    return normalized, before, risk


def _restore_component_identity(db: Session, component: Component) -> None:
    identity = identity_by_code(db, component.warehouse_code or "")
    if not identity:
        allocate_component_identity(db, component)
        return
    if identity.owner_user_id not in {None, component.owner_user_id}:
        raise HTTPException(status_code=409, detail="器件编号归属冲突，不能恢复")
    if identity.component_id not in {None, component.id}:
        raise HTTPException(status_code=409, detail="器件编号已被占用，不能恢复")
    identity.component_id = component.id
    identity.status = "active"
    identity.archived_at = None
    refresh_identity_snapshot(identity, component)


def _execute_action(db: Session, owner_user_id: int, action: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    name = action["action"]
    target_id = action.get("target_id")
    payload = action.get("payload") or {}
    now = _utcnow()
    inverse: dict[str, Any]
    if name == "component.create":
        quantity = max(0, int(payload.get("quantity") or 0))
        values = {key: value for key, value in payload.items() if key in COMPONENT_FIELDS}
        values["name"] = str(values["name"]).strip()
        component = Component(owner_user_id=owner_user_id, quantity=0, **values)
        db.add(component)
        db.flush()
        allocate_component_identity(db, component)
        if quantity:
            component.quantity = quantity
            record_stock_delta(db, component, quantity, movement_type="codex_initial_stock", reason="Codex 审批新建器件", actor_user_id=owner_user_id)
        inverse = {"action": "component.archive", "target_id": component.warehouse_code, "payload": {}}
        result = _snapshot_component(component)
    elif name in {"component.update", "component.archive", "component.restore", "stock.adjust"}:
        component = _owned_component_by_code(db, owner_user_id, target_id, include_archived=name == "component.restore")
        before = _snapshot_component(component)
        if name == "component.update":
            for key, value in payload.items():
                setattr(component, key, value)
            identity = db.query(ComponentIdentityRegistry).filter(ComponentIdentityRegistry.component_id == component.id).first()
            if identity:
                refresh_identity_snapshot(identity, component)
            inverse = {"action": "component.update", "target_id": component.warehouse_code, "payload": {key: before[key] for key in payload}}
        elif name == "component.archive":
            archive_component_identity(db, component)
            component.revoked_at = now
            inverse = {"action": "component.restore", "target_id": component.warehouse_code, "payload": {}}
        elif name == "component.restore":
            component.revoked_at = None
            _restore_component_identity(db, component)
            inverse = {"action": "component.archive", "target_id": component.warehouse_code, "payload": {}}
        else:
            delta = int(payload["delta"])
            component.quantity = int(component.quantity or 0) + delta
            if component.quantity < 0:
                raise HTTPException(status_code=409, detail="库存不足，操作未执行")
            if is_durable_equipment(component):
                component.occupied_quantity = min(equipment_occupied_quantity(component), component.quantity)
            record_stock_delta(
                db,
                component,
                delta,
                movement_type=payload.get("movement_type") or "codex_adjustment",
                reason=payload.get("reason") or "Codex 审批库存变更",
                actor_user_id=owner_user_id,
                location=payload.get("location"),
            )
            inverse = {
                "action": "stock.adjust",
                "target_id": component.warehouse_code,
                "payload": {"delta": -delta, "movement_type": "codex_undo", "reason": "撤销 Codex 库存变更"},
            }
        db.flush()
        result = _snapshot_component(component)
    elif name == "workspace.project.create":
        code = normalize_workspace_code(payload.get("project_code"))
        if db.query(PersonalProjectV2.id).filter(PersonalProjectV2.project_code == code).first():
            raise HTTPException(status_code=409, detail="项目编号已存在")
        project = PersonalProjectV2(
            id=str(uuid4()), owner_user_id=owner_user_id, project_code=code,
            name=str(payload["name"]).strip(), description=payload.get("description"),
            status=payload.get("status") or "planning",
            start_date=_date_value(payload.get("start_date"), workspace_today()),
        )
        db.add(project)
        db.flush()
        version = PersonalProjectVersionV2(
            id=str(uuid4()), project_id=project.id, sequence_number=1,
            version_code="V1", status="designing",
        )
        db.add(version)
        db.flush()
        project.current_version_id = version.id
        if payload.get("lifecycle_dates"):
            add_workspace_actual_timeline_events(
                db,
                project,
                owner_user_id,
                {key: _date_value(value) for key, value in payload["lifecycle_dates"].items()},
            )
        else:
            add_workspace_initial_timeline_events(
                db, project, owner_user_id, source="chatgpt_approval"
            )
        inverse = {"action": "workspace.project.archive", "target_id": code, "payload": {}}
        result = _snapshot_workspace_project(project)
    elif name in {
        "workspace.project.update", "workspace.project.archive", "workspace.project.restore", "workspace.project.status"
    }:
        project = _workspace_owned_project(
            db, owner_user_id, target_id, include_archived=name == "workspace.project.restore"
        )
        before = _snapshot_workspace_project(project)
        if name == "workspace.project.update":
            for key, value in payload.items():
                setattr(project, key, _date_value(value) if key in {"start_date", "end_date"} else value)
            inverse = {"action": name, "target_id": project.project_code, "payload": {key: before[key] for key in payload}}
        elif name == "workspace.project.archive":
            project.archived_at = now
            inverse = {"action": "workspace.project.restore", "target_id": project.project_code, "payload": {}}
        elif name == "workspace.project.restore":
            project.archived_at = None
            inverse = {"action": "workspace.project.archive", "target_id": project.project_code, "payload": {}}
        else:
            previous = project.status
            previous_end = project.end_date
            project.status = payload["status"]
            if project.status == "validated" and not project.end_date:
                project.end_date = workspace_today()
            elif payload.get("clear_end_date"):
                project.end_date = None
            if payload.get("restore_end_date"):
                project.end_date = _date_value(payload["restore_end_date"])
            db.add(PersonalProjectStatusEventV2(
                id=str(uuid4()), project_id=project.id, from_status=previous, to_status=project.status,
                note=payload.get("note"), source="chatgpt_approval", created_by_user_id=owner_user_id,
            ))
            inverse = {
                "action": "workspace.project.status", "target_id": project.project_code,
                "payload": {"status": previous, "clear_end_date": previous_end is None, "restore_end_date": previous_end, "note": "撤销状态变更"},
            }
        db.flush()
        result = _snapshot_workspace_project(project)
    elif name == "workspace.version.create":
        project = _workspace_owned_project(db, owner_user_id, target_id)
        sequence = (db.query(PersonalProjectVersionV2.id).filter(PersonalProjectVersionV2.project_id == project.id).count() + 1)
        code = normalize_workspace_version(payload.get("version_code") or f"V{sequence}")
        version = PersonalProjectVersionV2(
            id=str(uuid4()), project_id=project.id, sequence_number=sequence,
            version_code=code, status="designing", change_summary=payload.get("change_summary"),
        )
        db.add(version)
        db.flush()
        if project.current_version_id:
            source_rows = db.query(PersonalProjectBomItemV2).filter(
                PersonalProjectBomItemV2.version_id == project.current_version_id,
                PersonalProjectBomItemV2.archived_at.is_(None),
            ).all()
            for row in source_rows:
                db.add(PersonalProjectBomItemV2(
                    id=str(uuid4()), project_id=project.id, version_id=version.id,
                    component_id=row.component_id, quantity_per_board=row.quantity_per_board,
                    designators=row.designators, note=row.note,
                ))
        project.current_version_id = version.id
        inverse = {"action": "workspace.version.status", "target_id": version.id, "payload": {"status": "retired"}}
        result = workspace_version_out(db, version)
    elif name == "workspace.version.status":
        project, version = _workspace_owned_version(db, owner_user_id, str(target_id))
        previous = version.status
        version.status = payload["status"]
        project.current_version_id = version.id if version.status != "retired" else project.current_version_id
        inverse = {"action": name, "target_id": version.id, "payload": {"status": previous}}
        db.flush()
        result = workspace_version_out(db, version)
    elif name == "workspace.expense.create":
        project = _workspace_owned_project(db, owner_user_id, target_id)
        expense = PersonalProjectExpenseV2(
            id=str(uuid4()), project_id=project.id, version_id=payload.get("version_id"),
            category=payload["category"], amount=payload["amount"],
            occurred_on=_date_value(payload.get("occurred_on"), workspace_today()),
            vendor=payload.get("vendor"), note=payload.get("note"), created_by_user_id=owner_user_id,
        )
        db.add(expense)
        db.flush()
        inverse = {"action": "workspace.expense.archive", "target_id": expense.id, "payload": {}}
        result = _snapshot_workspace_expense(expense)
    elif name in {"workspace.expense.archive", "workspace.expense.restore"}:
        _, expense = _workspace_owned_expense(db, owner_user_id, str(target_id))
        expense.archived_at = now if name.endswith("archive") else None
        inverse = {
            "action": "workspace.expense.restore" if name.endswith("archive") else "workspace.expense.archive",
            "target_id": expense.id, "payload": {},
        }
        result = _snapshot_workspace_expense(expense)
    elif name == "workspace.bom.upsert":
        if target_id is None:
            project = _workspace_owned_project(db, owner_user_id, payload["project_code"])
            component = _owned_component_by_code(db, owner_user_id, payload["component_id"])
            version = (
                _workspace_owned_version(db, owner_user_id, str(payload["version_id"]))[1]
                if payload.get("version_id") else db.get(PersonalProjectVersionV2, project.current_version_id)
            )
            if not version or version.project_id != project.id:
                raise HTTPException(status_code=422, detail="BOM 版本不属于目标项目")
            existing = db.query(PersonalProjectBomItemV2).filter(
                PersonalProjectBomItemV2.version_id == version.id,
                PersonalProjectBomItemV2.component_id == component.id,
            ).first()
            if existing:
                bom = existing
                previous = {"quantity_per_board": bom.quantity_per_board, "designators": bom.designators, "note": bom.note, "archived_at": bom.archived_at}
                bom.quantity_per_board = payload["quantity_per_board"]
                bom.designators = payload.get("designators")
                bom.note = payload.get("note")
                bom.archived_at = None
                inverse = {"action": "workspace.bom.upsert", "target_id": bom.id, "payload": previous}
            else:
                bom = PersonalProjectBomItemV2(
                    id=str(uuid4()), project_id=project.id, version_id=version.id,
                    component_id=component.id, quantity_per_board=payload["quantity_per_board"],
                    designators=payload.get("designators"), note=payload.get("note"),
                )
                db.add(bom)
                db.flush()
                inverse = {"action": "workspace.bom.archive", "target_id": bom.id, "payload": {}}
        else:
            bom = _workspace_owned_bom(db, owner_user_id, str(target_id))
            previous = {key: getattr(bom, key) for key in payload}
            for key, value in payload.items():
                setattr(bom, key, value)
            inverse = {"action": name, "target_id": bom.id, "payload": previous}
        result = {
            "id": bom.id, "project_id": bom.project_id, "version_id": bom.version_id,
            "component_id": bom.component_id, "quantity_per_board": bom.quantity_per_board,
            "designators": bom.designators, "note": bom.note, "archived_at": bom.archived_at,
        }
    elif name in {"workspace.bom.archive", "workspace.bom.restore"}:
        bom = _workspace_owned_bom(db, owner_user_id, str(target_id))
        bom.archived_at = now if name.endswith("archive") else None
        inverse = {
            "action": "workspace.bom.restore" if name.endswith("archive") else "workspace.bom.archive",
            "target_id": bom.id, "payload": {},
        }
        result = {"id": bom.id, "archived_at": bom.archived_at}
    elif name == "project.create":
        code = normalize_project_code(payload.get("project_code"))
        try:
            assert_project_code_available(db, code)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        project = Project(
            scope_type="personal",
            owner_user_id=owner_user_id,
            project_code=code,
            name=str(payload["name"]).strip(),
            description=payload.get("description"),
            status=payload.get("status") or "planning",
            start_date=_date_value(payload.get("start_date"), shanghai_today()),
            end_date=_date_value(payload.get("end_date")),
        )
        db.add(project)
        db.flush()
        create_initial_version(db, project, owner_user_id)
        db.add(
            ProjectStatusEvent(
                id=str(uuid4()),
                project_id=project.id,
                from_status=None,
                to_status=project.status,
                note="通过 ChatGPT 网页审批创建项目",
                source="chatgpt_approval",
                created_by_user_id=owner_user_id,
            )
        )
        inverse = {"action": "project.archive", "target_id": code, "payload": {}}
        result = _snapshot_project(project)
    elif name in {"project.update", "project.archive", "project.restore", "project.status", "project.code_change"}:
        project = _owned_project(db, owner_user_id, target_id, include_archived=name == "project.restore")
        before = _snapshot_project(project)
        if name == "project.update":
            for key, value in payload.items():
                setattr(project, key, _date_value(value) if key in {"start_date", "end_date"} else value)
            inverse = {"action": "project.update", "target_id": project.project_code or project.id, "payload": {key: before[key] for key in payload}}
        elif name == "project.archive":
            project.archived_at = now
            inverse = {"action": "project.restore", "target_id": project.project_code or project.id, "payload": {}}
        elif name == "project.restore":
            project.archived_at = None
            inverse = {"action": "project.archive", "target_id": project.project_code or project.id, "payload": {}}
        elif name == "project.status":
            previous = project.status
            previous_end_date = project.end_date
            project.status = payload["status"]
            if project.status == "validated" and not project.end_date:
                project.end_date = shanghai_today()
            elif payload.get("clear_end_date"):
                project.end_date = None
            if payload.get("restore_end_date"):
                project.end_date = _date_value(payload["restore_end_date"])
            db.add(
                ProjectStatusEvent(
                    id=str(uuid4()),
                    project_id=project.id,
                    from_status=previous,
                    to_status=project.status,
                    note=payload.get("note"),
                    source="chatgpt_approval",
                    created_by_user_id=owner_user_id,
                )
            )
            inverse = {
                "action": "project.status",
                "target_id": project.project_code or project.id,
                "payload": {
                    "status": previous,
                    "clear_end_date": previous_end_date is None,
                    "restore_end_date": previous_end_date,
                    "note": "撤销状态变更",
                },
            }
        else:
            old_code = project.project_code
            new_code = normalize_project_code(payload["project_code"])
            if not db.query(ProjectCodeAlias.id).filter(ProjectCodeAlias.old_code == old_code).first():
                db.add(ProjectCodeAlias(project_id=project.id, old_code=old_code, created_by_user_id=owner_user_id))
            project.project_code = new_code
            inverse = {"action": "project.code_change", "target_id": new_code, "payload": {"project_code": old_code}}
        db.flush()
        result = _snapshot_project(project)
    elif name == "version.create":
        project = _owned_project(db, owner_user_id, target_id)
        try:
            version = create_project_version(
                db,
                project,
                owner_user_id,
                version_code=payload.get("version_code"),
                status=payload.get("status") or "designing",
                change_summary=payload.get("change_summary"),
                copy_from_version_id=payload.get("copy_from_version_id"),
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        inverse = {"action": "version.retire", "target_id": version.id, "payload": {}}
        result = version_stats(db, project, version)
    elif name in {"version.update", "version.status", "version.retire", "version.restore"}:
        project, version = _owned_version(db, owner_user_id, target_id)
        before = _snapshot_version(version)
        if name == "version.update":
            previous_active_version_id = project.active_pcb_version_id
            if "version_code" in payload:
                version.version_code = normalize_version_code(payload["version_code"])
            if "change_summary" in payload:
                version.change_summary = str(payload.get("change_summary") or "").strip() or None
            if payload.get("make_active"):
                project.active_pcb_version_id = version.id
                project.active_fabrication_revision_id = version.active_fabrication_revision_id
            inverse_payload = {key: before[key] for key in payload if key in before}
            if payload.get("make_active"):
                inverse_payload = {"make_active": True}
            inverse = {
                "action": "version.update",
                "target_id": previous_active_version_id if payload.get("make_active") and previous_active_version_id else version.id,
                "payload": inverse_payload,
            }
        elif name == "version.status":
            previous = version.status
            version.status = payload["status"]
            version.validated_at = now if version.status == "passed" else version.validated_at
            version.archived_at = now if version.status == "retired" else None
            inverse = {"action": "version.status", "target_id": version.id, "payload": {"status": previous}}
        elif name == "version.retire":
            version.status = "retired"
            version.archived_at = now
            if project.active_pcb_version_id == version.id:
                raise HTTPException(status_code=409, detail="当前 PCB 版本不能停用，请先切换版本")
            inverse = {"action": "version.restore", "target_id": version.id, "payload": {"status": before["status"], "archived_at": before["archived_at"]}}
        else:
            version.status = payload.get("status") or "designing"
            version.archived_at = None
            inverse = {"action": "version.retire", "target_id": version.id, "payload": {}}
        db.flush()
        result = version_stats(db, project, version)
    elif name == "expense.create":
        project = _owned_project(db, owner_user_id, target_id)
        expense = ProjectExpense(
            id=str(uuid4()),
            project_id=project.id,
            pcb_version_id=payload.get("pcb_version_id"),
            category=payload["category"],
            amount=payload["amount"],
            currency="CNY",
            occurred_on=_date_value(payload.get("occurred_on"), shanghai_today()),
            vendor=payload.get("vendor"),
            note=payload.get("note"),
            created_by_user_id=owner_user_id,
        )
        db.add(expense)
        db.flush()
        inverse = {"action": "expense.archive", "target_id": expense.id, "payload": {}}
        result = expense_out(expense, db.get(ProjectPcbVersion, expense.pcb_version_id) if expense.pcb_version_id else None)
    elif name in {"expense.update", "expense.archive", "expense.restore"}:
        project, expense = _owned_expense(db, owner_user_id, str(target_id))
        before = _snapshot_expense(expense)
        if name == "expense.update":
            for key, value in payload.items():
                setattr(expense, key, _date_value(value) if key == "occurred_on" else value)
            inverse = {"action": "expense.update", "target_id": expense.id, "payload": {key: before[key] for key in payload}}
        elif name == "expense.archive":
            expense.archived_at = now
            inverse = {"action": "expense.restore", "target_id": expense.id, "payload": {}}
        else:
            expense.archived_at = None
            inverse = {"action": "expense.archive", "target_id": expense.id, "payload": {}}
        db.flush()
        result = expense_out(expense, db.get(ProjectPcbVersion, expense.pcb_version_id) if expense.pcb_version_id else None)
    elif name == "bom.upsert":
        if target_id is None:
            project = _owned_project(db, owner_user_id, payload.get("project_id") or payload.get("project_code"))
            component = _owned_component_by_code(db, owner_user_id, payload["component_id"])
            version = (
                _owned_version(db, owner_user_id, payload["pcb_version_id"])[1]
                if payload.get("pcb_version_id") is not None
                else active_project_version(db, project, create_if_missing=True)
            )
            if version.project_id != project.id:
                raise HTTPException(status_code=422, detail="BOM 版本不属于目标项目")
            bom = ProjectBomItem(
                project_id=project.id,
                pcb_version_id=version.id,
                component_id=component.id,
                required_quantity=max(1, int(payload.get("required_quantity") or 1)),
                status=payload.get("status") or "reserved",
                remark=payload.get("remark"),
            )
            db.add(bom)
            db.flush()
            inverse = {"action": "bom.archive", "target_id": bom.id, "payload": {}}
        else:
            bom = _owned_bom(db, owner_user_id, target_id)
            previous = {"required_quantity": bom.required_quantity, "status": bom.status, "remark": bom.remark}
            for key in ["required_quantity", "status", "remark"]:
                if key in payload:
                    setattr(bom, key, payload[key])
            inverse = {"action": "bom.upsert", "target_id": bom.id, "payload": previous}
        result = {"id": bom.id, "project_id": bom.project_id, "component_id": bom.component_id, "required_quantity": bom.required_quantity, "status": bom.status, "remark": bom.remark}
    elif name in {"bom.archive", "bom.restore"}:
        bom = _owned_bom(db, owner_user_id, target_id)
        previous = bom.status
        bom.status = "archived" if name == "bom.archive" else payload.get("status") or "reserved"
        inverse = {
            "action": "bom.restore" if name == "bom.archive" else "bom.archive",
            "target_id": bom.id,
            "payload": {"status": previous},
        }
        result = {"id": bom.id, "status": bom.status}
    elif name == "purchase.create":
        project_id = None
        if payload.get("project_id") is not None or payload.get("project_code"):
            project_id = _owned_project(db, owner_user_id, payload.get("project_id") or payload.get("project_code")).id
        order = PurchaseOrder(
            id=str(uuid4()),
            scope_type="personal",
            owner_user_id=owner_user_id,
            project_id=project_id,
            order_number=payload.get("order_number"),
            platform=payload.get("platform"),
            status=payload.get("status") or "planned",
            currency=str(payload.get("currency") or "CNY").upper()[:8],
            note=payload.get("note"),
            created_by_user_id=owner_user_id,
        )
        db.add(order)
        db.flush()
        for raw_line in payload["lines"]:
            component = _owned_component_by_code(db, owner_user_id, raw_line["component_id"])
            db.add(
                PurchaseLine(
                    id=str(uuid4()),
                    purchase_order_id=order.id,
                    component_id=component.id,
                    receiver_user_id=owner_user_id,
                    description=str(raw_line.get("description") or component.name)[:300],
                    ordered_quantity=int(raw_line["ordered_quantity"]),
                    received_quantity=0,
                    unit_price=raw_line.get("unit_price"),
                    purchase_url=raw_line.get("purchase_url"),
                    status="planned" if order.status == "planned" else "ordered",
                    note=raw_line.get("note"),
                )
            )
        db.flush()
        inverse = {"action": "purchase.cancel", "target_id": order.id, "payload": {}}
        result = _order_out(db, order)
    elif name in {"purchase.update", "purchase.cancel"}:
        order = _owned_order(db, owner_user_id, str(target_id))
        before = _order_out(db, order)
        if name == "purchase.update":
            for key, value in payload.items():
                setattr(order, key, value)
            inverse = {"action": "purchase.update", "target_id": order.id, "payload": {key: before[key] for key in payload}}
        else:
            previous = order.status
            order.status = "cancelled"
            inverse = {"action": "purchase.update", "target_id": order.id, "payload": {"status": previous}}
        db.flush()
        result = _order_out(db, order)
    elif name == "purchase.receive":
        order, line = _owned_line(db, owner_user_id, str(target_id))
        component = _owned_component_by_code(db, owner_user_id, line.component_id)
        quantity = int(payload["quantity"])
        component.quantity = int(component.quantity or 0) + quantity
        component.first_stocked_at = component.first_stocked_at or now
        component.last_stocked_at = now
        if payload.get("location") and not component.location:
            component.location = payload["location"]
        movements = record_stock_delta(
            db,
            component,
            quantity,
            movement_type="purchase_receipt",
            reason=payload.get("note") or f"Codex 审批采购到货 {order.order_number or order.id}",
            purchase_line_id=line.id,
            actor_user_id=owner_user_id,
            location=payload.get("location"),
            unit_cost=line.unit_price,
            source_reference=order.order_number or order.id,
        )
        db.flush()
        receipt = PurchaseReceipt(
            id=str(uuid4()),
            purchase_line_id=line.id,
            inventory_lot_id=movements[0].lot_id if movements else None,
            quantity=quantity,
            location=payload.get("location"),
            received_by_user_id=owner_user_id,
            note=payload.get("note"),
        )
        db.add(receipt)
        line.received_quantity = int(line.received_quantity or 0) + quantity
        line.status = "received" if line.received_quantity >= line.ordered_quantity else "partial"
        order.status = "received" if all(row.status == "received" for row in db.query(PurchaseLine).filter(PurchaseLine.purchase_order_id == order.id).all()) else "partial"
        inverse = {"action": "purchase.reverse_receive", "target_id": receipt.id, "payload": {}}
        result = {"receipt_id": receipt.id, "quantity": quantity, "order": _order_out(db, order)}
    else:
        receipt = db.get(PurchaseReceipt, str(target_id))
        if not receipt:
            raise HTTPException(status_code=404, detail="到货记录不存在")
        order, line = _owned_line(db, owner_user_id, receipt.purchase_line_id)
        component = _owned_component_by_code(db, owner_user_id, line.component_id)
        quantity = abs(int(receipt.quantity or 0))
        if quantity <= 0 or component.quantity < quantity:
            raise HTTPException(status_code=409, detail="当前库存不足，不能撤销该次到货")
        component.quantity -= quantity
        movements = record_stock_delta(
            db,
            component,
            -quantity,
            movement_type="purchase_receipt_reversal",
            reason=f"撤销到货 {receipt.id}",
            purchase_line_id=line.id,
            actor_user_id=owner_user_id,
            lot_id=receipt.inventory_lot_id,
        )
        reversal = PurchaseReceipt(
            id=str(uuid4()),
            purchase_line_id=line.id,
            inventory_lot_id=movements[0].lot_id if movements else receipt.inventory_lot_id,
            quantity=-quantity,
            location=receipt.location,
            received_by_user_id=owner_user_id,
            note=f"撤销到货记录 {receipt.id}",
        )
        db.add(reversal)
        line.received_quantity = max(0, int(line.received_quantity or 0) - quantity)
        line.status = "partial" if line.received_quantity else "ordered"
        order.status = "partial" if line.received_quantity else "ordered"
        inverse = {
            "action": "purchase.receive",
            "target_id": line.id,
            "payload": {"quantity": quantity, "location": receipt.location, "note": f"重做到货 {receipt.id}"},
        }
        result = {"reversal_receipt_id": reversal.id, "quantity": -quantity, "order": _order_out(db, order)}
    db.flush()
    return result, inverse


def _execute_actions(db: Session, owner_user_id: int, actions: list[dict[str, Any]]) -> tuple[list[Any], list[dict[str, Any]]]:
    results = []
    inverse = []
    for action in actions:
        result, undo_action = _execute_action(db, owner_user_id, action)
        results.append(result)
        inverse.insert(0, undo_action)
    return results, inverse


@router.post("/api/integrations/codex/v1/operations")
def create_operation(
    payload: OperationCreate,
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    _limiter.check(principal.token_id, "proposal", PROPOSAL_RATE_LIMIT)
    existing = (
        db.query(IntegrationOperation)
        .filter(
            IntegrationOperation.access_token_id == principal.token_id,
            IntegrationOperation.idempotency_key == payload.idempotency_key,
        )
        .first()
    )
    if existing:
        if _expire_if_needed(existing):
            db.commit()
        if existing.status not in {"rejected", "expired", "stale", "failed"}:
            return _operation_out(existing)
    raw_actions = [row.model_dump() for row in payload.actions]
    if any(row["action"] == "purchase.reverse_receive" for row in raw_actions):
        raise HTTPException(status_code=422, detail="到货反向流水只能由撤销流程生成")
    prepared, before, risk = _prepare_actions(db, principal.owner_user_id, raw_actions)
    normalized = [{key: value for key, value in row.items() if key != "preview"} for row in prepared]
    previews = [row["preview"] for row in prepared]
    operation = IntegrationOperation(
        id=str(uuid4()),
        owner_user_id=principal.owner_user_id,
        access_token_id=principal.token_id,
        idempotency_key=(
            payload.idempotency_key
            if not existing
            else f"{payload.idempotency_key}:retry:{uuid4().hex[:8]}"
        ),
        status="pending_approval",
        risk_level=risk,
        reason=payload.reason,
        request_json=_dump({"actions": normalized}),
        preview_json=_dump(previews),
        before_json=_dump(before),
        precondition_hash=_hash(before),
        approval_expires_at=_utcnow() + APPROVAL_TTL,
    )
    db.add(operation)
    db.commit()
    db.refresh(operation)
    return _operation_out(operation)


@router.get("/api/integrations/codex/v1/operations/{operation_id}")
def get_operation_status(
    operation_id: str,
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    operation = db.get(IntegrationOperation, operation_id)
    if not operation or operation.owner_user_id != principal.owner_user_id or operation.access_token_id != principal.token_id:
        raise HTTPException(status_code=404, detail="操作不存在")
    if _expire_if_needed(operation):
        db.commit()
    return _operation_out(operation)


def _make_undo_operation(db: Session, operation: IntegrationOperation, token_id: str) -> IntegrationOperation:
    now = _utcnow()
    if operation.status != "succeeded" or operation.undone_by_operation_id:
        raise HTTPException(status_code=409, detail="该操作当前不能撤销")
    if not operation.undo_expires_at or operation.undo_expires_at <= now or not operation.inverse_json:
        raise HTTPException(status_code=410, detail="撤销窗口已结束")
    existing_rows = (
        db.query(IntegrationOperation)
        .filter(IntegrationOperation.undo_of_operation_id == operation.id)
        .order_by(IntegrationOperation.created_at.desc())
        .all()
    )
    for existing in existing_rows:
        if _expire_if_needed(existing, now):
            continue
        if existing.status == "pending_approval":
            db.commit()
            return existing
    if existing_rows:
        db.commit()
    inverse = _load(operation.inverse_json, [])
    prepared, before, risk = _prepare_actions(db, operation.owner_user_id, inverse)
    normalized = [{key: value for key, value in row.items() if key != "preview"} for row in prepared]
    undo = IntegrationOperation(
        id=str(uuid4()),
        owner_user_id=operation.owner_user_id,
        access_token_id=token_id,
        idempotency_key=f"undo:{operation.id}:{uuid4().hex[:8]}",
        status="pending_approval",
        risk_level="high" if risk == "high" else "normal",
        reason=f"撤销 Codex 操作 {operation.id}",
        request_json=_dump({"actions": normalized}),
        preview_json=_dump([row["preview"] for row in prepared]),
        before_json=_dump(before),
        precondition_hash=_hash(before),
        approval_expires_at=now + APPROVAL_TTL,
        undo_of_operation_id=operation.id,
    )
    db.add(undo)
    db.commit()
    db.refresh(undo)
    return undo


@router.post("/api/integrations/codex/v1/operations/{operation_id}/undo")
def request_operation_undo(
    operation_id: str,
    principal: CodexPrincipal = Depends(require_codex_token),
    db: Session = Depends(get_db),
):
    operation = db.get(IntegrationOperation, operation_id)
    if not operation or operation.owner_user_id != principal.owner_user_id or operation.access_token_id != principal.token_id:
        raise HTTPException(status_code=404, detail="操作不存在")
    return _operation_out(_make_undo_operation(db, operation, principal.token_id))


@router.get("/api/integrations/codex/operations")
def browser_list_operations(auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    rows = (
        db.query(IntegrationOperation)
        .filter(IntegrationOperation.owner_user_id == auth.user_id)
        .order_by(IntegrationOperation.created_at.desc())
        .limit(100)
        .all()
    )
    expired_changed = False
    for row in rows:
        expired_changed = _expire_if_needed(row) or expired_changed
    if expired_changed:
        db.commit()
    return [_operation_out(row, include_sensitive=True) for row in rows]


@router.get("/api/integrations/codex/operations/{operation_id}")
def browser_get_operation(
    operation_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    operation = db.get(IntegrationOperation, operation_id)
    if not operation:
        raise HTTPException(status_code=404, detail="操作不存在")
    _require_owner(auth, operation.owner_user_id)
    if _expire_if_needed(operation):
        db.commit()
    return _operation_out(operation, include_sensitive=True)


@router.post("/api/integrations/codex/operations/{operation_id}/reject")
def browser_reject_operation(
    operation_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    operation = db.get(IntegrationOperation, operation_id)
    if not operation:
        raise HTTPException(status_code=404, detail="操作不存在")
    _require_owner(auth, operation.owner_user_id)
    if operation.status != "pending_approval":
        raise HTTPException(status_code=409, detail="操作已处理")
    operation.status = "rejected"
    operation.rejected_at = _utcnow()
    db.commit()
    return _operation_out(operation, include_sensitive=True)


@router.post("/api/integrations/codex/operations/{operation_id}/approve")
def browser_approve_operation(
    operation_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    operation = db.query(IntegrationOperation).filter(IntegrationOperation.id == operation_id).with_for_update().first()
    if not operation:
        raise HTTPException(status_code=404, detail="操作不存在")
    _require_owner(auth, operation.owner_user_id)
    now = _utcnow()
    if operation.status != "pending_approval":
        raise HTTPException(status_code=409, detail="操作已处理")
    if operation.approval_expires_at <= now:
        operation.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="审批链接已过期，请让 Codex 重新生成预览")
    request = _load(operation.request_json, {})
    prepared, current_before, _ = _prepare_actions(db, operation.owner_user_id, request.get("actions") or [])
    if _hash(current_before) != operation.precondition_hash:
        operation.status = "stale"
        operation.failure_message = "目标数据已变化，必须重新生成预览"
        db.commit()
        raise HTTPException(status_code=409, detail=operation.failure_message)
    normalized = [{key: value for key, value in row.items() if key != "preview"} for row in prepared]
    try:
        results, inverse = _execute_actions(db, operation.owner_user_id, normalized)
        operation.status = "succeeded"
        operation.approved_by_user_id = auth.user_id
        operation.approved_at = now
        operation.executed_at = now
        operation.after_json = _dump(results)
        operation.inverse_json = _dump(inverse)
        operation.undo_expires_at = now + UNDO_TTL
        db.add(
            ActivityLog(
                owner_user_id=auth.user_id,
                action="codex_operation_approved",
                entity_type="integration_operation",
                summary=f"批准并执行 Codex 操作 {operation.id}",
                detail=_dump({"operation_id": operation.id, "actions": [row["action"] for row in normalized]}),
            )
        )
        if operation.undo_of_operation_id:
            original = db.get(IntegrationOperation, operation.undo_of_operation_id)
            if original:
                original.status = "undone"
                original.undone_by_operation_id = operation.id
        db.commit()
    except HTTPException as exc:
        db.rollback()
        failed = db.get(IntegrationOperation, operation_id)
        if failed:
            failed.status = "failed"
            failed.failure_message = str(exc.detail)[:2000]
            db.commit()
        raise
    except Exception as exc:
        db.rollback()
        failed = db.get(IntegrationOperation, operation_id)
        if failed:
            failed.status = "failed"
            failed.failure_message = str(exc)[:2000]
            db.commit()
        raise HTTPException(status_code=409, detail=f"操作未执行，全部动作已回滚：{exc}") from exc
    db.refresh(operation)
    return _operation_out(operation, include_sensitive=True)


@router.post("/api/integrations/codex/operations/{operation_id}/undo")
def browser_request_undo(
    operation_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    operation = db.get(IntegrationOperation, operation_id)
    if not operation:
        raise HTTPException(status_code=404, detail="操作不存在")
    _require_owner(auth, operation.owner_user_id)
    return _operation_out(_make_undo_operation(db, operation, operation.access_token_id or ""), include_sensitive=True)


def prune_expired_operation_snapshots(db: Session, now: datetime | None = None) -> int:
    cutoff = now or _utcnow()
    rows = (
        db.query(IntegrationOperation)
        .filter(
            IntegrationOperation.undo_expires_at.isnot(None),
            IntegrationOperation.undo_expires_at <= cutoff,
            or_(IntegrationOperation.before_json.isnot(None), IntegrationOperation.inverse_json.isnot(None)),
        )
        .all()
    )
    for row in rows:
        row.before_json = None
        row.inverse_json = None
    if rows:
        db.commit()
    return len(rows)
