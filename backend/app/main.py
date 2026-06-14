import csv
import base64
import hashlib
import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import Session, joinedload

from .auth import ACCESS_TOKEN, APP_PASSWORD, auth_required, require_access
from .database import Base, SessionLocal, engine, get_db
from .models import ActivityLog, AiKnowledgeCard, AiTask, Category, Component, Project, ProjectBomImportBatch, ProjectBomImportCandidate, ProjectBomImportRow, ProjectBomItem
from .schemas import (
    AiComponentSearchRequest,
    AiComponentInfoRequest,
    AiClassifyRequest,
    AiExplainRequest,
    ImageImportPreviewRow,
    AiProjectPlanRequest,
    AiKnowledgeCardOut,
    AiRefreshRequest,
    AiTaskOut,
    AiTaskSummary,
    ActivityLogOut,
    AuthLoginRequest,
    AuthLoginResponse,
    BomItemCreate,
    BomItemStatusRequest,
    BomItemOut,
    BomItemUpdate,
    BomMatchCommitRequest,
    BomMatchCommitResult,
    CategoryOut,
    ComponentCreate,
    ComponentAiOut,
    ComponentGroup,
    ComponentGroupPage,
    ComponentConsumeRequest,
    ComponentList,
    ComponentOut,
    ComponentUpdate,
    ImportCommitRequest,
    ImportCommitResult,
    ImportPreviewRow,
    ProjectAiPlanRequest,
    ProjectAiConsultRequest,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from .seed import seed_categories
from .services.bom_match import match_bom_rows, parse_bom_excel
from .services.excel_import import (
    component_values,
    create_import_record,
    find_duplicate,
    find_import_record,
    merge_component,
    parse_excel,
)
from .services.mimo_ai import (
    MimoNotConfiguredError,
    MimoRequestError,
    assist_bom_matches,
    classify_component,
    analyze_bom,
    component_to_dict,
    component_info,
    image_import_preview,
    lcsc_search_url,
    component_search,
    explain_component,
    organize_component,
    project_plan,
    project_consult,
    search_component_candidates,
    search_empty_suggestions,
)
from .services.component_normalizer import (
    clean_component_name,
    clean_lcsc_keyword,
    normalize_component_values,
    normalize_tag_text,
)


ENABLE_API_DOCS = os.getenv("ENABLE_API_DOCS", "0") == "1"
app = FastAPI(
    title="Component Warehouse",
    version="0.3.0",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
)

allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
allowed_hosts = os.getenv("ALLOWED_HOSTS", "wxylab.ltd,*.wxylab.ltd,localhost,127.0.0.1").split(",")
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[host.strip() for host in allowed_hosts if host.strip()],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


LOGIN_ATTEMPTS: dict[str, list[float]] = {}
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW", "600"))
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_MAX", "8"))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store" if request.url.path.startswith("/api/") else "no-cache")
    return response


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def check_login_rate_limit(request: Request) -> str:
    ip = client_ip(request)
    now = time.time()
    attempts = [item for item in LOGIN_ATTEMPTS.get(ip, []) if now - item < LOGIN_WINDOW_SECONDS]
    LOGIN_ATTEMPTS[ip] = attempts
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts, please try later")
    return ip


def record_login_failure(ip: str) -> None:
    LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


def clear_login_failures(ip: str) -> None:
    LOGIN_ATTEMPTS.pop(ip, None)


def ensure_sqlite_columns(connection, table: str, columns: dict[str, str]) -> None:
    existing = [row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))]
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        ensure_sqlite_columns(connection, "categories", {"color": "VARCHAR(40) DEFAULT '#eef6ff'"})
        ensure_sqlite_columns(
            connection,
            "components",
            {
                "ai_summary": "TEXT",
                "ai_usage": "TEXT",
                "ai_risk_notes": "TEXT",
                "ai_pcb_notes": "TEXT",
                "ai_substitutes": "TEXT",
                "ai_tags": "VARCHAR(500)",
                "source_title": "TEXT",
                "ai_confidence": "VARCHAR(40)",
                "ai_cache_key": "VARCHAR(80)",
                "ai_status": "VARCHAR(40) DEFAULT 'pending'",
                "ai_error": "TEXT",
                "ai_updated_at": "DATETIME",
                "part_family": "VARCHAR(40) DEFAULT 'component'",
                "count_mode": "VARCHAR(40) DEFAULT 'exact'",
                "normalized_spec": "VARCHAR(160)",
                "is_hand_solder_friendly": "BOOLEAN DEFAULT 0",
                "is_power_component": "BOOLEAN DEFAULT 0",
                "is_signal_component": "BOOLEAN DEFAULT 0",
                "is_high_current": "BOOLEAN DEFAULT 0",
                "is_high_voltage": "BOOLEAN DEFAULT 0",
                "is_common": "BOOLEAN DEFAULT 0",
            },
        )
        ensure_sqlite_columns(connection, "project_bom_items", {"status": "VARCHAR(40) DEFAULT 'reserved'"})
        ensure_sqlite_columns(connection, "ai_tasks", {"next_attempt_at": "DATETIME"})
        ensure_sqlite_columns(
            connection,
            "projects",
            {
                "ai_bom_analysis": "TEXT",
                "ai_bom_cache_key": "VARCHAR(80)",
                "ai_bom_updated_at": "DATETIME",
                "bom_match_total": "INTEGER DEFAULT 0",
                "bom_match_matched": "INTEGER DEFAULT 0",
                "bom_match_review": "INTEGER DEFAULT 0",
                "bom_match_missing": "INTEGER DEFAULT 0",
                "bom_match_missing_items": "TEXT",
                "bom_match_rows": "TEXT",
                "bom_match_updated_at": "DATETIME",
            },
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_project_bom_items_status ON project_bom_items(status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_components_ai_status ON components(ai_status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_components_ai_cache_key ON components(ai_cache_key)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_tasks_next_attempt_at ON ai_tasks(next_attempt_at)"))
    db = next(get_db())
    try:
        seed_categories(db)
        ensure_category(db, "连接件", "#e8fff8")
        ensure_category(db, "时钟源", "#eef2ff")
        resolve_superseded_ai_failures(db)
        enqueue_organize_component_tasks(db, force=False, limit=80)
        enqueue_missing_component_ai_tasks(db, include_failed=True)
        db.commit()
    finally:
        db.close()
    ensure_ai_worker()


Protected = Annotated[None, Depends(require_access)]
AI_ANALYSIS_VERSION = "component-ai-v2-design-insights"
AI_TASK_MAX_RETRIES = int(os.getenv("AI_TASK_MAX_RETRIES", "8"))
AI_TASK_RETRY_BASE_SECONDS = int(os.getenv("AI_TASK_RETRY_BASE_SECONDS", "45"))
AI_TASK_RETRY_MAX_SECONDS = int(os.getenv("AI_TASK_RETRY_MAX_SECONDS", "1800"))
AI_AUTO_REFRESH_ENABLED = os.getenv("AI_AUTO_REFRESH_ENABLED", "1") == "1"
AI_AUTO_REFRESH_INTERVAL_HOURS = int(os.getenv("AI_AUTO_REFRESH_INTERVAL_HOURS", "12"))
AI_AUTO_REFRESH_MAX_PER_RUN = int(os.getenv("AI_AUTO_REFRESH_MAX_PER_RUN", "5"))
AI_AUTO_REFRESH_AFTER_DAYS = int(os.getenv("AI_AUTO_REFRESH_AFTER_DAYS", "30"))
AI_LAST_AUTO_REFRESH_AT: datetime | None = None


def infer_small_part_fields(values: dict) -> dict:
    values["part_family"] = values.get("part_family") or "component"
    values["count_mode"] = values.get("count_mode") or "exact"
    return values


def category_id_by_name(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    category = db.query(Category).filter(Category.name == name).first()
    return category.id if category else None


def ensure_category(db: Session, name: str, color: str = "#e8fff8") -> Category:
    category = db.query(Category).filter(Category.name == name).first()
    if category:
        if not category.color:
            category.color = color
        return category
    category = Category(name=name, color=color)
    db.add(category)
    db.flush()
    return category


def normalize_for_inventory(db: Session, values: dict, *, clean_name: bool = True) -> dict:
    normalized = normalize_component_values(values) if clean_name else dict(values)
    normalized = infer_small_part_fields(normalized)
    if not normalized.get("datasheet_url") and normalized.get("lcsc_number"):
        normalized["datasheet_url"] = f"https://www.lcsc.com/product-detail/{normalized['lcsc_number']}.html"
    return normalized


def organize_cache_key(component: Component) -> str:
    payload = {
        "version": "component-organize-v1-ai-name",
        "name": component.name,
        "model": component.model,
        "parameters": component.parameters,
        "package": component.package,
        "tags": component.tags,
        "category_id": component.category_id,
        "part_family": component.part_family,
        "normalized_spec": component.normalized_spec,
        "source_title": getattr(component, "source_title", None),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def looks_like_needs_organize(component: Component) -> bool:
    category_name = component.category.name if component.category else ""
    tag_count = len(str(component.tags or "").split(",")) if component.tags else 0
    normalized_tag_count = len(normalize_tag_text(component.tags))
    return any(
        [
            not component.category_id,
            category_name in {"未分类", "其他", ""},
            len(component.name or "") > 36,
            tag_count > normalized_tag_count,
        ]
    )


def log_activity(
    db: Session,
    action: str,
    entity_type: str,
    summary: str,
    *,
    entity_id: int | None = None,
    component_id: int | None = None,
    project_id: int | None = None,
    quantity_delta: int | None = None,
    detail: dict | str | None = None,
) -> None:
    if isinstance(detail, dict):
        detail_text = json.dumps(detail, ensure_ascii=False)
    else:
        detail_text = detail
    db.add(
        ActivityLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            component_id=component_id,
            project_id=project_id,
            quantity_delta=quantity_delta,
            summary=summary,
            detail=detail_text,
        )
    )


def _json_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def component_ai_payload(component: Component) -> dict:
    return {
        "ai_analysis_version": AI_ANALYSIS_VERSION,
        "name": component.name,
        "model": component.model,
        "parameters": component.parameters,
        "package": component.package,
        "category_id": component.category_id,
        "category": component.category.name if component.category else None,
        "lcsc_number": component.lcsc_number,
        "datasheet_url": component.datasheet_url,
        "remark": component.remark,
        "tags": component.tags,
        "source_title": getattr(component, "source_title", None),
        "part_family": component.part_family,
        "normalized_spec": component.normalized_spec,
    }


def component_organize_payload(component: Component) -> dict:
    return {
        "id": component.id,
        "name": component.name,
        "model": component.model,
        "category": component.category.name if component.category else None,
        "parameters": component.parameters,
        "package": component.package,
        "quantity": component.quantity,
        "source": component.source,
        "lcsc_number": component.lcsc_number,
        "tags": component.tags,
        "source_title": getattr(component, "source_title", None),
        "part_family": component.part_family,
        "count_mode": component.count_mode,
        "normalized_spec": component.normalized_spec,
        "status": component.status,
        "remark": component.remark,
    }


def component_ai_cache_key(component: Component) -> str:
    raw = json.dumps(component_ai_payload(component), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def project_bom_cache_key(project: Project) -> str:
    rows = [
        {
            "component_id": item.component_id,
            "required_quantity": item.required_quantity,
            "status": item.status,
            "remark": item.remark,
            "name": item.component.name if item.component else None,
            "model": item.component.model if item.component else None,
            "parameters": item.component.parameters if item.component else None,
            "package": item.component.package if item.component else None,
        }
        for item in project.bom_items
    ]
    raw = json.dumps({"project": project.name, "description": project.description, "bom": rows}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def apply_component_ai_result(db: Session, component: Component, result: dict, cache_key: str) -> None:
    component.ai_summary = result.get("summary") or result.get("normalized_name") or component.ai_summary
    usage_payload = {
        "usage": result.get("usage"),
        "key_specs": result.get("key_specs"),
        "typical_applications": result.get("typical_applications") or result.get("applications"),
        "design_insights": result.get("design_insights"),
        "do_not_use_for": result.get("do_not_use_for"),
        "recommended_pairings": result.get("recommended_pairings"),
        "datasheet_notes": result.get("datasheet_notes"),
        "source_notes": result.get("source_notes"),
    }
    fallback = result.get("applications") or result.get("typical_applications")
    if isinstance(fallback, list):
        fallback = {"usage": "", "key_specs": [], "typical_applications": fallback}
    component.ai_usage = _json_text({key: value for key, value in usage_payload.items() if value}) or _json_text(fallback)
    component.ai_risk_notes = _json_text(result.get("risk_notes") or result.get("risks"))
    component.ai_pcb_notes = _json_text(result.get("pcb_notes"))
    component.ai_substitutes = _json_text(
        {
            "substitutes": result.get("substitutes"),
            "substitution_notes": result.get("substitution_notes"),
        }
    )
    component.ai_tags = ",".join(result.get("ai_tags") or result.get("recommended_tags") or result.get("completion_suggestions") or [])[:500]
    component.ai_confidence = result.get("confidence") or "medium"
    component.ai_cache_key = cache_key
    component.ai_status = "completed"
    component.ai_error = None
    component.ai_updated_at = datetime.now()
    if result.get("datasheet_url") and not component.datasheet_url:
        component.datasheet_url = str(result["datasheet_url"])[:500]
    if not component.datasheet_url and component.lcsc_number:
        component.datasheet_url = f"https://www.lcsc.com/product-detail/{component.lcsc_number}.html"
    component.is_hand_solder_friendly = bool(result.get("is_hand_solder_friendly", component.is_hand_solder_friendly))
    component.is_power_component = bool(result.get("is_power_component", component.is_power_component))
    component.is_signal_component = bool(result.get("is_signal_component", component.is_signal_component))
    component.is_high_current = bool(result.get("is_high_current", component.is_high_current))
    component.is_high_voltage = bool(result.get("is_high_voltage", component.is_high_voltage))
    component.is_common = bool(result.get("is_common", component.is_common))
    card = AiKnowledgeCard(
        component_id=component.id,
        title=f"{component.model or component.name} AI 知识卡片",
        content=json.dumps(result, ensure_ascii=False, indent=2),
        tags=component.ai_tags,
        source_type="ai",
        confidence=component.ai_confidence,
    )
    db.add(card)


def mark_component_ai_stale(component: Component) -> None:
    cache_key = component_ai_cache_key(component)
    if component.ai_cache_key and component.ai_cache_key != cache_key:
        component.ai_status = "stale"


def apply_component_organize_result(db: Session, component: Component, result: dict, *, source: str) -> dict:
    before = {
        "name": component.name,
        "category_id": component.category_id,
        "parameters": component.parameters,
        "package": component.package,
        "tags": component.tags,
        "part_family": component.part_family,
        "count_mode": component.count_mode,
        "normalized_spec": component.normalized_spec,
    }
    category_name = result.get("category") or result.get("category_suggestion")
    category_id = category_id_by_name(db, category_name) or component.category_id
    normalized_name = clean_component_name(result.get("normalized_name") or component.name, component.model, component.lcsc_number)
    if normalized_name and normalized_name != component.name:
        component.source_title = component.source_title or component.name
        component.name = normalized_name
    if category_id:
        component.category_id = category_id
    if result.get("parameters"):
        component.parameters = str(result.get("parameters"))[:1000]
    if result.get("package"):
        component.package = str(result.get("package"))[:120]
    tags = result.get("tags") or result.get("ai_tags")
    if isinstance(tags, str):
        tags = normalize_tag_text(tags, component.package)
    if isinstance(tags, list):
        component.tags = ",".join(normalize_tag_text(",".join(str(item) for item in tags), component.package))[:300]
    for field in ["part_family", "count_mode", "normalized_spec"]:
        if result.get(field):
            setattr(component, field, str(result[field])[:160])
    component.ai_status = component.ai_status or "pending"
    after = {
        "name": component.name,
        "category_id": component.category_id,
        "parameters": component.parameters,
        "package": component.package,
        "tags": component.tags,
        "part_family": component.part_family,
        "count_mode": component.count_mode,
        "normalized_spec": component.normalized_spec,
    }
    log_activity(
        db,
        "ai.component.organize",
        "component",
        f"AI 规范化元器件 {component.name}",
        entity_id=component.id,
        component_id=component.id,
        detail={"source": source, "before": before, "after": after, "confidence": result.get("confidence"), "reason": result.get("reason")},
    )
    return {"before": before, "after": after, "result": result}


def enqueue_ai_task(db: Session, task_type: str, target_type: str, target_id: int, input_hash: str | None = None) -> AiTask:
    existing = (
        db.query(AiTask)
        .filter(
            AiTask.task_type == task_type,
            AiTask.target_type == target_type,
            AiTask.target_id == target_id,
            AiTask.status.in_(["pending", "processing", "stale", "failed"]),
        )
        .order_by(AiTask.id.desc())
        .first()
    )
    if existing:
        if input_hash:
            existing.input_hash = input_hash
        if existing.status == "failed":
            existing.status = "pending"
            existing.next_attempt_at = datetime.now()
            existing.error_message = None
        elif existing.status != "processing":
            existing.status = "pending"
        return existing
    task = AiTask(task_type=task_type, target_type=target_type, target_id=target_id, input_hash=input_hash, status="pending")
    db.add(task)
    return task


def retry_delay_for(task: AiTask) -> int:
    retry_count = max(1, task.retry_count or 1)
    delay = AI_TASK_RETRY_BASE_SECONDS * (2 ** max(0, retry_count - 1))
    return min(delay, AI_TASK_RETRY_MAX_SECONDS)


def resolve_superseded_ai_failures(db: Session) -> int:
    resolved = 0
    failed_tasks = db.query(AiTask).filter(AiTask.status == "failed").all()
    for task in failed_tasks:
        newer_success = (
            db.query(AiTask.id)
            .filter(
                AiTask.task_type == task.task_type,
                AiTask.target_type == task.target_type,
                AiTask.target_id == task.target_id,
                AiTask.status == "completed",
                AiTask.id > task.id,
            )
            .first()
        )
        if not newer_success:
            continue
        task.status = "superseded"
        task.error_message = f"已被后续成功任务覆盖：{task.error_message or ''}"[:1000]
        task.next_attempt_at = None
        resolved += 1
    completed_component_ids = [
        component_id
        for (component_id,) in db.query(AiTask.target_id)
        .filter(
            AiTask.task_type == "component_analyze",
            AiTask.target_type == "component",
            AiTask.status == "completed",
        )
        .distinct()
        .all()
    ]
    if completed_component_ids:
        db.query(Component).filter(
            Component.id.in_(completed_component_ids),
            Component.ai_status == "failed",
            Component.ai_summary.isnot(None),
        ).update({Component.ai_status: "completed", Component.ai_error: None}, synchronize_session=False)
    return resolved


def reserved_quantities(db: Session, component_ids: list[int] | None = None) -> dict[int, int]:
    if component_ids == []:
        return {}
    query = db.query(
        ProjectBomItem.component_id,
        func.coalesce(func.sum(ProjectBomItem.required_quantity), 0),
    ).filter(ProjectBomItem.status == "reserved")
    if component_ids:
        query = query.filter(ProjectBomItem.component_id.in_(component_ids))
    rows = query.group_by(ProjectBomItem.component_id).all()
    return {component_id: int(quantity or 0) for component_id, quantity in rows}


def component_out(component: Component, reserved: int = 0) -> dict:
    quantity = component.quantity or 0
    return {
        "id": component.id,
        "name": component.name,
        "model": component.model,
        "category_id": component.category_id,
        "parameters": component.parameters,
        "package": component.package,
        "quantity": quantity,
        "source": component.source,
        "lcsc_number": component.lcsc_number,
        "tags": component.tags,
        "source_title": getattr(component, "source_title", None),
        "part_family": component.part_family or "component",
        "count_mode": component.count_mode or "exact",
        "normalized_spec": component.normalized_spec,
        "status": component.status,
        "location": component.location,
        "remark": component.remark,
        "datasheet_url": component.datasheet_url,
        "is_hand_solder_friendly": bool(component.is_hand_solder_friendly),
        "is_power_component": bool(component.is_power_component),
        "is_signal_component": bool(component.is_signal_component),
        "is_high_current": bool(component.is_high_current),
        "is_high_voltage": bool(component.is_high_voltage),
        "is_common": bool(component.is_common),
        "category": component.category,
        "reserved_quantity": reserved,
        "available_quantity": max(0, quantity - reserved),
        "ai_summary": component.ai_summary,
        "ai_usage": component.ai_usage,
        "ai_risk_notes": component.ai_risk_notes,
        "ai_pcb_notes": component.ai_pcb_notes,
        "ai_substitutes": component.ai_substitutes,
        "ai_tags": component.ai_tags,
        "ai_confidence": component.ai_confidence,
        "ai_cache_key": component.ai_cache_key,
        "ai_status": component.ai_status or "pending",
        "ai_error": component.ai_error,
        "ai_updated_at": component.ai_updated_at,
        "created_at": component.created_at,
        "updated_at": component.updated_at,
    }


def apply_component_filters(
    query,
    *,
    category_id: int | None = None,
    status: str | None = None,
    tag: str | None = None,
    keyword: str | None = None,
    package: str | None = None,
    ai_status: str | None = None,
    stock: str | None = None,
    is_hand_solder_friendly: bool | None = None,
    is_power_component: bool | None = None,
    is_signal_component: bool | None = None,
    is_high_current: bool | None = None,
    is_high_voltage: bool | None = None,
):
    if category_id:
        query = query.filter(Component.category_id == category_id)
    if status:
        query = query.filter(Component.status == status)
    if tag:
        query = query.filter(or_(Component.tags.ilike(f"%{tag}%"), Component.ai_tags.ilike(f"%{tag}%")))
    if package:
        query = query.filter(Component.package.ilike(f"%{package}%"))
    if ai_status:
        query = query.filter(Component.ai_status == ai_status)
    if stock == "empty":
        query = query.filter(Component.quantity <= 0)
    elif stock == "low":
        query = query.filter(Component.quantity > 0, Component.quantity <= 5)
    elif stock == "available":
        query = query.filter(Component.quantity > 0)
    bool_filters = {
        Component.is_hand_solder_friendly: is_hand_solder_friendly,
        Component.is_power_component: is_power_component,
        Component.is_signal_component: is_signal_component,
        Component.is_high_current: is_high_current,
        Component.is_high_voltage: is_high_voltage,
    }
    for column, value in bool_filters.items():
        if value is not None:
            query = query.filter(column == value)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                Component.name.ilike(like),
                Component.model.ilike(like),
                Component.parameters.ilike(like),
                Component.package.ilike(like),
                Component.lcsc_number.ilike(like),
                Component.location.ilike(like),
                Component.remark.ilike(like),
                Component.ai_summary.ilike(like),
                Component.ai_tags.ilike(like),
            )
        )
    return query


PASSIVE_COVERAGE = {
    "电阻": {"unit": "Ω", "dimension": "resistance"},
    "电容": {"unit": "F", "dimension": "capacitance"},
    "电感": {"unit": "H", "dimension": "inductance"},
}


def parse_json_value(value):
    if not value:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def parse_unit_value(value: str, dimension: str) -> float | None:
    text_value = str(value or "").strip().replace("μ", "u").replace("µ", "u")
    if dimension == "resistance":
        match = re.search(r"(\d+(?:\.\d+)?)\s*(m|k|K|M)?\s*(?:Ω|ohm|R)", text_value, flags=re.IGNORECASE)
        if not match:
            return None
        multipliers = {"m": 0.001, "k": 1000, "K": 1000, "M": 1000000}
        return float(match.group(1)) * multipliers.get(match.group(2) or "", 1)
    if dimension == "capacitance":
        match = re.search(r"(\d+(?:\.\d+)?)\s*(p|n|u|m)?\s*F", text_value, flags=re.IGNORECASE)
        if not match:
            return None
        multipliers = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3}
        return float(match.group(1)) * multipliers.get((match.group(2) or "").lower(), 1)
    if dimension == "inductance":
        match = re.search(r"(\d+(?:\.\d+)?)\s*(n|u|m)?\s*H", text_value, flags=re.IGNORECASE)
        if not match:
            return None
        multipliers = {"n": 1e-9, "u": 1e-6, "m": 1e-3}
        return float(match.group(1)) * multipliers.get((match.group(2) or "").lower(), 1)
    return None


def key_specs_from_component(component: Component) -> list[dict]:
    parsed = parse_json_value(component.ai_usage)
    if not isinstance(parsed, dict):
        return []
    specs = parsed.get("key_specs")
    return specs if isinstance(specs, list) else []


def bom_item_out(item: ProjectBomItem, reserved_by_component: dict[int, int] | None = None) -> dict:
    reserved_by_component = reserved_by_component or {}
    status = item.status or "reserved"
    component_quantity = item.component.quantity if item.component else 0
    total_reserved = reserved_by_component.get(item.component_id, 0)
    own_reserved = item.required_quantity if status == "reserved" else 0
    reserved_by_others = max(0, total_reserved - own_reserved)
    available_for_item = max(0, component_quantity - reserved_by_others)
    free_quantity = max(0, component_quantity - total_reserved)
    shortage = max(0, item.required_quantity - available_for_item) if status == "reserved" else 0
    return {
        "id": item.id,
        "component_id": item.component_id,
        "required_quantity": item.required_quantity,
        "status": status,
        "remark": item.remark,
        "component": component_out(item.component, total_reserved) if item.component else None,
        "available_quantity": available_for_item,
        "reserved_quantity": total_reserved,
        "free_quantity": free_quantity,
        "shortage_quantity": shortage,
        "enough": shortage == 0,
    }


def project_out(project: Project, reserved_by_component: dict[int, int] | None = None) -> dict:
    reserved_by_component = reserved_by_component or {}
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "ai_bom_analysis": project.ai_bom_analysis,
        "ai_bom_cache_key": project.ai_bom_cache_key,
        "ai_bom_updated_at": project.ai_bom_updated_at,
        "bom_match_total": project.bom_match_total or 0,
        "bom_match_matched": project.bom_match_matched or 0,
        "bom_match_review": project.bom_match_review or 0,
        "bom_match_missing": project.bom_match_missing or 0,
        "bom_match_missing_items": project.bom_match_missing_items,
        "bom_match_rows": project.bom_match_rows,
        "bom_match_updated_at": project.bom_match_updated_at,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "bom_items": [bom_item_out(item, reserved_by_component) for item in project.bom_items],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/config")
def auth_config():
    return {"auth_required": auth_required()}


@app.post("/api/auth/login", response_model=AuthLoginResponse)
def login(payload: AuthLoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = check_login_rate_limit(request)
    if not auth_required():
        clear_login_failures(ip)
        log_activity(db, "auth.login", "auth", "本地免登录访问", detail={"ip": ip})
        db.commit()
        return AuthLoginResponse(token="local-dev-token")
    if payload.password != APP_PASSWORD:
        record_login_failure(ip)
        log_activity(db, "auth.login.failed", "auth", "登录失败：密码错误", detail={"ip": ip})
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid password")
    clear_login_failures(ip)
    log_activity(db, "auth.login", "auth", "登录成功", detail={"ip": ip})
    db.commit()
    return AuthLoginResponse(token=ACCESS_TOKEN)


@app.get("/api/categories", response_model=list[CategoryOut])
def list_categories(_: Protected, db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.id).all()


@app.post("/api/categories", response_model=CategoryOut)
def create_category(name: str, _: Protected, db: Session = Depends(get_db)):
    existing = db.query(Category).filter(Category.name == name).first()
    if existing:
        return existing
    category = Category(name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@app.get("/api/components", response_model=ComponentList)
def list_components(
    _: Protected,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category_id: int | None = None,
    status: str | None = None,
    tag: str | None = None,
    keyword: str | None = None,
    package: str | None = None,
    ai_status: str | None = None,
    stock: str | None = None,
    is_hand_solder_friendly: bool | None = None,
    is_power_component: bool | None = None,
    is_signal_component: bool | None = None,
    is_high_current: bool | None = None,
    is_high_voltage: bool | None = None,
):
    query = db.query(Component).options(joinedload(Component.category))
    query = apply_component_filters(
        query,
        category_id=category_id,
        status=status,
        tag=tag,
        keyword=keyword,
        package=package,
        ai_status=ai_status,
        stock=stock,
        is_hand_solder_friendly=is_hand_solder_friendly,
        is_power_component=is_power_component,
        is_signal_component=is_signal_component,
        is_high_current=is_high_current,
        is_high_voltage=is_high_voltage,
    )
    total = query.count()
    items = query.order_by(Component.updated_at.desc(), Component.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    reserved = reserved_quantities(db, [item.id for item in items])
    return {"items": [component_out(item, reserved.get(item.id, 0)) for item in items], "total": total}


def group_component_page(db: Session, components: list[Component], total: int, page: int, page_size: int) -> dict:
    reserved = reserved_quantities(db, [item.id for item in components])
    items = [component_out(item, reserved.get(item.id, 0)) for item in components]
    by_category: dict[int | None, dict] = {}
    for item in items:
        category = item["category"]
        key = category.id if category else None
        if key not in by_category:
            by_category[key] = {"category": category, "items": [], "total": 0}
        by_category[key]["items"].append(item)
        by_category[key]["total"] += 1
    return {"groups": list(by_category.values()), "total": total, "page": page, "page_size": page_size}


@app.get("/api/components/grouped-page", response_model=ComponentGroupPage)
def list_components_grouped_page(
    _: Protected,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=120),
    keyword: str | None = None,
    category_id: int | None = None,
    status: str | None = None,
    ai_status: str | None = None,
    stock: str | None = None,
    tag: str | None = None,
    package: str | None = None,
    is_hand_solder_friendly: bool | None = None,
    is_power_component: bool | None = None,
    is_signal_component: bool | None = None,
    is_high_current: bool | None = None,
    is_high_voltage: bool | None = None,
):
    query = db.query(Component).outerjoin(Category).options(joinedload(Component.category))
    query = apply_component_filters(
        query,
        category_id=category_id,
        status=status,
        tag=tag,
        keyword=keyword,
        package=package,
        ai_status=ai_status,
        stock=stock,
        is_hand_solder_friendly=is_hand_solder_friendly,
        is_power_component=is_power_component,
        is_signal_component=is_signal_component,
        is_high_current=is_high_current,
        is_high_voltage=is_high_voltage,
    )
    total = query.count()
    components = (
        query.order_by(Component.category_id.is_(None), Category.id.asc(), Component.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return group_component_page(db, components, total, page, page_size)


@app.get("/api/components/grouped", response_model=list[ComponentGroup])
def list_components_grouped(
    _: Protected,
    db: Session = Depends(get_db),
    keyword: str | None = None,
    category_id: int | None = None,
    status: str | None = None,
    ai_status: str | None = None,
    stock: str | None = None,
    tag: str | None = None,
    package: str | None = None,
    is_hand_solder_friendly: bool | None = None,
    is_power_component: bool | None = None,
    is_signal_component: bool | None = None,
    is_high_current: bool | None = None,
    is_high_voltage: bool | None = None,
):
    query = db.query(Component).outerjoin(Category).options(joinedload(Component.category))
    if category_id:
        query = query.filter(Component.category_id == category_id)
    if status:
        query = query.filter(Component.status == status)
    if tag:
        query = query.filter(or_(Component.tags.ilike(f"%{tag}%"), Component.ai_tags.ilike(f"%{tag}%")))
    if package:
        query = query.filter(Component.package.ilike(f"%{package}%"))
    if ai_status:
        query = query.filter(Component.ai_status == ai_status)
    if stock == "empty":
        query = query.filter(Component.quantity <= 0)
    elif stock == "low":
        query = query.filter(Component.quantity > 0, Component.quantity <= 5)
    elif stock == "available":
        query = query.filter(Component.quantity > 0)
    bool_filters = {
        Component.is_hand_solder_friendly: is_hand_solder_friendly,
        Component.is_power_component: is_power_component,
        Component.is_signal_component: is_signal_component,
        Component.is_high_current: is_high_current,
        Component.is_high_voltage: is_high_voltage,
    }
    for column, value in bool_filters.items():
        if value is not None:
            query = query.filter(column == value)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                Component.name.ilike(like),
                Component.model.ilike(like),
                Component.parameters.ilike(like),
                Component.package.ilike(like),
                Component.lcsc_number.ilike(like),
                Component.location.ilike(like),
                Component.remark.ilike(like),
                Component.ai_summary.ilike(like),
                Component.ai_tags.ilike(like),
            )
        )
    components = (
        query.order_by(Component.category_id.is_(None), Category.id.asc(), Component.id.asc())
        .limit(500)
        .all()
    )
    reserved = reserved_quantities(db, [item.id for item in components])
    items = [component_out(item, reserved.get(item.id, 0)) for item in components]
    by_category: dict[int | None, dict] = {}
    for item in items:
        category = item["category"]
        key = category.id if category else None
        if key not in by_category:
            by_category[key] = {"category": category, "items": [], "total": 0}
        by_category[key]["items"].append(item)
        by_category[key]["total"] += 1
    return list(by_category.values())


@app.get("/api/components/coverage")
def components_coverage(
    _: Protected,
    db: Session = Depends(get_db),
    category: str | None = None,
    package: str | None = None,
    only_available: bool = False,
):
    category_names = [category] if category in PASSIVE_COVERAGE else list(PASSIVE_COVERAGE.keys())
    rows = (
        db.query(Component)
        .join(Category, Component.category_id == Category.id)
        .options(joinedload(Component.category))
        .filter(Category.name.in_(category_names))
        .order_by(Category.id.asc(), Component.id.asc())
        .all()
    )
    component_ids = [item.id for item in rows]
    reserved = reserved_quantities(db, component_ids)
    coverage: dict[str, dict] = {
        name: {
            "category": name,
            "unit": PASSIVE_COVERAGE[name]["unit"],
            "dimension": PASSIVE_COVERAGE[name]["dimension"],
            "items": [],
            "packages": set(),
            "unparsed_count": 0,
            "total": 0,
        }
        for name in category_names
    }
    for component in rows:
        category_name = component.category.name if component.category else ""
        bucket = coverage.get(category_name)
        if not bucket:
            continue
        available = max(0, int(component.quantity or 0) - reserved.get(component.id, 0))
        if only_available and available <= 0:
            continue
        if package and package not in str(component.package or component.normalized_spec or ""):
            continue
        bucket["total"] += 1
        if component.package:
            bucket["packages"].add(component.package)
        parsed_value = None
        parsed_spec = None
        for spec in key_specs_from_component(component):
            if not isinstance(spec, dict) or spec.get("confidence") != "high":
                continue
            parsed_value = parse_unit_value(str(spec.get("value") or ""), bucket["dimension"])
            if parsed_value is not None:
                parsed_spec = spec
                break
        if parsed_value is None:
            bucket["unparsed_count"] += 1
            continue
        bucket["items"].append(
            {
                "id": component.id,
                "name": component.name,
                "model": component.model,
                "value": parsed_value,
                "display_value": parsed_spec.get("value") if parsed_spec else "",
                "spec_name": parsed_spec.get("name") if parsed_spec else "",
                "package": component.package,
                "normalized_spec": component.normalized_spec,
                "quantity": int(component.quantity or 0),
                "available_quantity": available,
                "tags": component.tags,
            }
        )
    result = []
    for item in coverage.values():
        item["packages"] = sorted(item["packages"])
        item["items"].sort(key=lambda value: value["value"])
        result.append(item)
    return {"categories": result}


@app.post("/api/components", response_model=ComponentOut)
def create_component(payload: ComponentCreate, _: Protected, db: Session = Depends(get_db)):
    if payload.lcsc_number:
        duplicate = db.query(Component).filter(Component.lcsc_number == payload.lcsc_number).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="LCSC number already exists")
    component = Component(**normalize_for_inventory(db, payload.model_dump(), clean_name=True))
    component.ai_status = "pending"
    db.add(component)
    db.flush()
    enqueue_ai_task(db, "component_analyze", "component", component.id, component_ai_cache_key(component))
    enqueue_ai_task(db, "component_organize", "component", component.id, organize_cache_key(component))
    log_activity(
        db,
        "component.create",
        "component",
        f"新增元器件 {component.name}",
        entity_id=component.id,
        component_id=component.id,
        quantity_delta=component.quantity,
    )
    db.commit()
    db.refresh(component)
    return component_out(component, 0)


@app.put("/api/components/{component_id}", response_model=ComponentOut)
def update_component(component_id: int, payload: ComponentUpdate, _: Protected, db: Session = Depends(get_db)):
    component = db.get(Component, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    old_quantity = component.quantity or 0
    old_cache_key = component_ai_cache_key(component)
    values = normalize_for_inventory(db, {**component_out(component), **payload.model_dump(exclude_unset=True)}, clean_name=True)
    values = {key: value for key, value in values.items() if key in payload.model_fields or key in {"part_family", "count_mode", "normalized_spec", "category_id"}}
    for key, value in values.items():
        setattr(component, key, value)
    new_cache_key = component_ai_cache_key(component)
    if new_cache_key != old_cache_key:
        component.ai_status = "stale"
        enqueue_ai_task(db, "component_analyze", "component", component.id, new_cache_key)
        enqueue_ai_task(db, "component_organize", "component", component.id, organize_cache_key(component))
    new_quantity = component.quantity or 0
    if new_quantity != old_quantity:
        log_activity(
            db,
            "component.quantity.update",
            "component",
            f"修改 {component.name} 库存数量：{old_quantity} -> {new_quantity}",
            entity_id=component.id,
            component_id=component.id,
            quantity_delta=new_quantity - old_quantity,
        )
    db.commit()
    db.refresh(component)
    reserved = reserved_quantities(db, [component.id]).get(component.id, 0)
    return component_out(component, reserved)


@app.post("/api/components/{component_id}/quantity/decrement", response_model=ComponentOut)
def decrement_component_quantity(
    component_id: int,
    _: Protected,
    db: Session = Depends(get_db),
    payload: ComponentConsumeRequest | None = None,
):
    component = db.get(Component, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    consume_quantity = payload.quantity if payload else 1
    if (component.quantity or 0) < consume_quantity:
        raise HTTPException(status_code=400, detail="Quantity is not enough")
    component.quantity -= consume_quantity
    log_activity(
        db,
        "component.consume",
        "component",
        f"使用元器件 {component.name} x {consume_quantity}",
        entity_id=component.id,
        component_id=component.id,
        project_id=payload.project_id if payload else None,
        quantity_delta=-consume_quantity,
        detail={"remark": payload.remark} if payload and payload.remark else None,
    )
    db.commit()
    db.refresh(component)
    reserved = reserved_quantities(db, [component.id]).get(component.id, 0)
    return component_out(component, reserved)


@app.post("/api/components/{component_id}/quantity/increment", response_model=ComponentOut)
def increment_component_quantity(
    component_id: int,
    _: Protected,
    db: Session = Depends(get_db),
    payload: ComponentConsumeRequest | None = None,
):
    component = db.get(Component, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    add_quantity = payload.quantity if payload else 1
    component.quantity = (component.quantity or 0) + add_quantity
    log_activity(
        db,
        "component.increment",
        "component",
        f"增加库存 {component.name} x {add_quantity}",
        entity_id=component.id,
        component_id=component.id,
        quantity_delta=add_quantity,
        detail={"remark": payload.remark} if payload and payload.remark else None,
    )
    db.commit()
    db.refresh(component)
    reserved = reserved_quantities(db, [component.id]).get(component.id, 0)
    return component_out(component, reserved)


@app.get("/api/components/{component_id}/ai", response_model=ComponentAiOut)
def get_component_ai(component_id: int, _: Protected, db: Session = Depends(get_db)):
    component = db.query(Component).options(joinedload(Component.category)).filter(Component.id == component_id).first()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    mark_component_ai_stale(component)
    cards = (
        db.query(AiKnowledgeCard)
        .filter(AiKnowledgeCard.component_id == component_id)
        .order_by(AiKnowledgeCard.updated_at.desc(), AiKnowledgeCard.id.desc())
        .limit(20)
        .all()
    )
    reserved = reserved_quantities(db, [component.id]).get(component.id, 0)
    return {"component": component_out(component, reserved), "knowledge_cards": cards}


@app.post("/api/components/{component_id}/ai/refresh", response_model=ComponentAiOut)
def refresh_component_ai(component_id: int, payload: AiRefreshRequest, _: Protected, db: Session = Depends(get_db)):
    component = db.query(Component).options(joinedload(Component.category)).filter(Component.id == component_id).first()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    try:
        analyze_component_with_ai(db, component, payload.scope, payload.force)
        db.commit()
    except Exception as error:
        handle_mimo_error(error)
    cards = (
        db.query(AiKnowledgeCard)
        .filter(AiKnowledgeCard.component_id == component_id)
        .order_by(AiKnowledgeCard.updated_at.desc(), AiKnowledgeCard.id.desc())
        .limit(20)
        .all()
    )
    reserved = reserved_quantities(db, [component.id]).get(component.id, 0)
    return {"component": component_out(component, reserved), "knowledge_cards": cards}


@app.post("/api/components/{component_id}/organize", response_model=ComponentOut)
def organize_single_component(component_id: int, _: Protected, db: Session = Depends(get_db), force: bool = True):
    component = db.query(Component).options(joinedload(Component.category)).filter(Component.id == component_id).first()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    try:
        organize_component_record(db, component, force=force)
        db.commit()
    except Exception as error:
        handle_mimo_error(error)
    db.refresh(component)
    reserved = reserved_quantities(db, [component.id]).get(component.id, 0)
    return component_out(component, reserved)


@app.delete("/api/components/{component_id}")
def delete_component(component_id: int, _: Protected, db: Session = Depends(get_db)):
    component = db.get(Component, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    log_activity(
        db,
        "component.delete",
        "component",
        f"删除元器件 {component.name}",
        entity_id=component.id,
        component_id=component.id,
        quantity_delta=-(component.quantity or 0),
    )
    db.delete(component)
    db.commit()
    return {"deleted": True}


@app.get("/api/dashboard/summary")
def dashboard(_: Protected, db: Session = Depends(get_db)):
    total_kinds = db.query(func.count(Component.id)).scalar() or 0
    total_quantity = db.query(func.coalesce(func.sum(Component.quantity), 0)).scalar() or 0
    low_stock = db.query(func.count(Component.id)).filter(Component.quantity <= 5).scalar() or 0
    pending = db.query(func.count(Component.id)).filter(Component.status == "pending").scalar() or 0
    recent_projects = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .order_by(Project.updated_at.desc(), Project.id.desc())
        .limit(5)
        .all()
    )
    recent_component_ids = list({item.component_id for project in recent_projects for item in project.bom_items})
    recent_reserved = reserved_quantities(db, recent_component_ids)
    all_reserved = reserved_quantities(db)
    reserved_total = sum(all_reserved.values())
    category_stats = [
        {"name": name or "未分类", "value": count}
        for name, count in (
            db.query(Category.name, func.count(Component.id))
            .join(Component, Component.category_id == Category.id, isouter=True)
            .group_by(Category.id)
            .order_by(Category.id)
            .all()
        )
    ]
    status_stats = [{"name": status or "未知", "value": count} for status, count in db.query(Component.status, func.count(Component.id)).group_by(Component.status).all()]
    low_stock_items = (
        db.query(Component)
        .options(joinedload(Component.category))
        .outerjoin(Category)
        .filter(
            Component.quantity <= 5,
            or_(
                Component.is_common == True,
                Category.name.in_(["电阻", "电容", "电感", "二极管", "MOS管", "保护器件", "连接件"]),
                Component.part_family.in_(["screw", "nut", "standoff", "pin_header"]),
            ),
            ~Category.name.in_(["开发板"]),
        )
        .order_by(Component.quantity.asc(), Component.updated_at.desc())
        .limit(8)
        .all()
    )
    ai_task_summary = {
        status: count for status, count in db.query(Component.ai_status, func.count(Component.id)).group_by(Component.ai_status).all()
    }
    recent_project_rows = [project_out(project, recent_reserved) for project in recent_projects]
    project_snapshots = []
    for project in recent_project_rows:
        bom_items = project.get("bom_items") or []
        shortage_count = sum(1 for item in bom_items if not item.get("enough"))
        satisfied_count = sum(1 for item in bom_items if item.get("enough"))
        reserved_count = sum(int(item.get("required_quantity") or 0) for item in bom_items if item.get("status") == "reserved")
        project_snapshots.append(
            {
                "id": project["id"],
                "name": project["name"],
                "status": project["status"],
                "bom_total": len(bom_items),
                "satisfied": satisfied_count,
                "shortage": shortage_count,
                "reserved_quantity": reserved_count,
                "bom_match_total": project.get("bom_match_total") or 0,
                "bom_match_matched": project.get("bom_match_matched") or 0,
                "bom_match_review": project.get("bom_match_review") or 0,
                "bom_match_missing": project.get("bom_match_missing") or 0,
                "bom_match_rate": round(((project.get("bom_match_matched") or 0) / (project.get("bom_match_total") or 1)) * 100) if project.get("bom_match_total") else 0,
                "bom_match_updated_at": project.get("bom_match_updated_at"),
                "updated_at": project.get("updated_at"),
            }
        )
    shortage_projects = sum(1 for item in project_snapshots if item["shortage"] > 0)
    datasheet_missing = db.query(func.count(Component.id)).filter(or_(Component.datasheet_url == None, Component.datasheet_url == "")).scalar() or 0
    ai_pending = ai_task_summary.get("pending", 0) + ai_task_summary.get("stale", 0)
    mechanical_stats = [
        {
            "family": family or "other",
            "spec": spec or "未归一",
            "quantity": int(quantity or 0),
            "count_mode": count_mode or "exact",
        }
        for family, spec, count_mode, quantity in (
            db.query(Component.part_family, Component.normalized_spec, Component.count_mode, func.coalesce(func.sum(Component.quantity), 0))
            .filter(Component.part_family.in_(["screw", "nut", "standoff", "pin_header"]))
            .group_by(Component.part_family, Component.normalized_spec, Component.count_mode)
            .order_by(Component.part_family, Component.normalized_spec)
            .limit(20)
            .all()
        )
    ]
    ai_summary = (
        f"需要行动的库存提醒 {len(low_stock_items)} 项，最近项目中 {shortage_projects} 个存在缺料；"
        f"待 AI 整理 {ai_pending} 项，{datasheet_missing} 个器件缺数据手册链接。"
        f"机械件已归类 {len(mechanical_stats)} 个规格。"
    )
    action_items = []
    for project in recent_project_rows:
        shortage_count = sum(1 for item in project.get("bom_items", []) if not item.get("enough"))
        if shortage_count:
            action_items.append({"type": "project_shortage", "title": f"{project['name']} 有 {shortage_count} 项缺料", "hint": "进入 BOM 页确认替代料或采购", "severity": "danger"})
    for item in low_stock_items[:5]:
        action_items.append(
            {
                "type": "stock_watch",
                "title": item.name,
                "hint": f"{item.category.name if item.category else '未分类'} · 库存 {item.quantity}，建议确认是否需要补货",
                "severity": "warning" if (item.quantity or 0) > 0 else "danger",
                "component_id": item.id,
            }
        )
    if datasheet_missing:
        action_items.append({"type": "datasheet_missing", "title": f"{datasheet_missing} 个器件缺数据手册", "hint": "优先补齐电源、接口和保护器件资料", "severity": "info"})
    if ai_task_summary.get("failed", 0):
        action_items.append({"type": "ai_failed", "title": f"AI 整理失败 {ai_task_summary.get('failed', 0)} 项", "hint": "检查 API 或重试后台整理", "severity": "warning"})
    return {
        "total_kinds": total_kinds,
        "category_count": db.query(func.count(Category.id)).scalar() or 0,
        "total_quantity": total_quantity,
        "reserved_quantity": reserved_total,
        "available_quantity": max(0, total_quantity - reserved_total),
        "low_stock": low_stock,
        "pending": pending,
        "common_count": db.query(func.count(Component.id)).filter(Component.is_common == True).scalar() or 0,
        "ai_pending": ai_task_summary.get("pending", 0) + ai_task_summary.get("stale", 0),
        "ai_failed": ai_task_summary.get("failed", 0),
        "shortage_projects": shortage_projects,
        "datasheet_missing": datasheet_missing,
        "mechanical_stats": mechanical_stats,
        "action_items": action_items[:10],
        "category_stats": category_stats,
        "status_stats": status_stats,
        "low_stock_items": [component_out(item, 0) for item in low_stock_items],
        "ai_summary": ai_summary,
        "recent_projects": recent_project_rows,
        "project_snapshots": project_snapshots,
    }


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(_: Protected, db: Session = Depends(get_db)):
    projects = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .order_by(Project.updated_at.desc(), Project.id.desc())
        .all()
    )
    component_ids = list({item.component_id for project in projects for item in project.bom_items})
    reserved = reserved_quantities(db, component_ids)
    return [project_out(project, reserved) for project in projects]


@app.post("/api/projects", response_model=ProjectOut)
def create_project(payload: ProjectCreate, _: Protected, db: Session = Depends(get_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    db.flush()
    log_activity(
        db,
        "project.create",
        "project",
        f"创建项目 {project.name}",
        entity_id=project.id,
        project_id=project.id,
    )
    db.commit()
    db.refresh(project)
    return project_out(project, {})


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, _: Protected, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    reserved = reserved_quantities(db, list({item.component_id for item in project.bom_items}))
    return project_out(project, reserved)


@app.put("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, _: Protected, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    reserved = reserved_quantities(db, list({item.component_id for item in project.bom_items}))
    return project_out(project, reserved)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, _: Protected, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    log_activity(
        db,
        "project.delete",
        "project",
        f"删除项目 {project.name}",
        entity_id=project.id,
        project_id=project.id,
    )
    db.delete(project)
    db.commit()
    return {"deleted": True}


@app.post("/api/projects/{project_id}/bom", response_model=BomItemOut)
def add_bom_item(project_id: int, payload: BomItemCreate, _: Protected, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    component = db.get(Component, payload.component_id)
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    item = ProjectBomItem(project_id=project_id, **payload.model_dump())
    db.add(item)
    db.flush()
    if item.status == "reserved":
        log_activity(
            db,
            "bom.reserve",
            "project_bom_item",
            f"项目 {project_id} 占用 {component.name} x {item.required_quantity}",
            entity_id=item.id,
            component_id=component.id,
            project_id=project_id,
            quantity_delta=item.required_quantity,
            detail={"remark": item.remark},
        )
    db.commit()
    db.refresh(item)
    item.component = component
    reserved = reserved_quantities(db, [item.component_id])
    return bom_item_out(item, reserved)


@app.put("/api/projects/{project_id}/bom/{item_id}", response_model=BomItemOut)
def update_bom_item(project_id: int, item_id: int, payload: BomItemUpdate, _: Protected, db: Session = Depends(get_db)):
    item = db.query(ProjectBomItem).filter(ProjectBomItem.project_id == project_id, ProjectBomItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="BOM item not found")
    old_quantity = item.required_quantity
    old_status = item.status or "reserved"
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    new_status = item.status or "reserved"
    if old_quantity != item.required_quantity or old_status != new_status:
        old_reserved = old_quantity if old_status == "reserved" else 0
        new_reserved = item.required_quantity if new_status == "reserved" else 0
        log_activity(
            db,
            "bom.reserve.update",
            "project_bom_item",
            f"调整项目 {project_id} 的 {item.component.name} BOM：{old_quantity}/{old_status} -> {item.required_quantity}/{new_status}",
            entity_id=item.id,
            component_id=item.component_id,
            project_id=project_id,
            quantity_delta=new_reserved - old_reserved,
        )
    db.commit()
    db.refresh(item)
    reserved = reserved_quantities(db, [item.component_id])
    return bom_item_out(item, reserved)


@app.delete("/api/projects/{project_id}/bom/{item_id}")
def delete_bom_item(project_id: int, item_id: int, _: Protected, db: Session = Depends(get_db)):
    item = db.query(ProjectBomItem).filter(ProjectBomItem.project_id == project_id, ProjectBomItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="BOM item not found")
    old_status = item.status or "reserved"
    item.status = "released"
    log_activity(
        db,
        "bom.reserve.release",
        "project_bom_item",
        f"释放项目 {project_id} 的 {item.component.name} 占用 x {item.required_quantity}",
        entity_id=item.id,
        component_id=item.component_id,
        project_id=project_id,
        quantity_delta=-item.required_quantity if old_status == "reserved" else 0,
    )
    db.commit()
    return {"released": True}


@app.post("/api/projects/{project_id}/bom/{item_id}/status", response_model=BomItemOut)
def mark_bom_item_status(
    project_id: int,
    item_id: int,
    payload: BomItemStatusRequest,
    _: Protected,
    db: Session = Depends(get_db),
):
    if payload.status not in {"reserved", "picked", "done", "released"}:
        raise HTTPException(status_code=400, detail="Invalid BOM status")
    item = (
        db.query(ProjectBomItem)
        .options(joinedload(ProjectBomItem.component).joinedload(Component.category))
        .filter(ProjectBomItem.project_id == project_id, ProjectBomItem.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="BOM item not found")
    old_status = item.status or "reserved"
    old_reserved = item.required_quantity if old_status == "reserved" else 0
    new_reserved = item.required_quantity if payload.status == "reserved" else 0
    if payload.consume_stock:
        if (item.component.quantity or 0) < item.required_quantity:
            raise HTTPException(status_code=400, detail="Quantity is not enough")
        item.component.quantity -= item.required_quantity
        log_activity(
            db,
            "component.consume",
            "component",
            f"项目 {project_id} 取料 {item.component.name} x {item.required_quantity}",
            entity_id=item.component_id,
            component_id=item.component_id,
            project_id=project_id,
            quantity_delta=-item.required_quantity,
            detail={"bom_item_id": item.id, "remark": payload.remark},
        )
    item.status = payload.status
    if payload.remark:
        item.remark = f"{item.remark or ''}\n{payload.remark}".strip()
    log_activity(
        db,
        "bom.status",
        "project_bom_item",
        f"项目 {project_id} 的 {item.component.name} BOM 状态：{old_status} -> {item.status}",
        entity_id=item.id,
        component_id=item.component_id,
        project_id=project_id,
        quantity_delta=new_reserved - old_reserved,
        detail={"consume_stock": payload.consume_stock},
    )
    db.commit()
    db.refresh(item)
    reserved = reserved_quantities(db, [item.component_id])
    return bom_item_out(item, reserved)


@app.post("/api/projects/{project_id}/bom/import-matches", response_model=BomMatchCommitResult)
def import_matched_bom_items(
    project_id: int,
    payload: BomMatchCommitRequest,
    _: Protected,
    db: Session = Depends(get_db),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    added = updated = skipped = 0
    for item in payload.items:
        component = db.get(Component, item.component_id)
        if not component:
            skipped += 1
            continue
        existing = (
            db.query(ProjectBomItem)
            .filter(ProjectBomItem.project_id == project_id, ProjectBomItem.component_id == item.component_id)
            .first()
        )
        if existing:
            old_quantity = existing.required_quantity
            old_status = existing.status or "reserved"
            existing.required_quantity += item.required_quantity
            if item.remark:
                existing.remark = f"{existing.remark or ''}\n{item.remark}".strip()
            existing.status = "reserved"
            log_activity(
                db,
                "bom.reserve.update",
                "project_bom_item",
                f"导入 BOM 更新占用 {component.name}：{old_quantity}/{old_status} -> {existing.required_quantity}/reserved",
                entity_id=existing.id,
                component_id=component.id,
                project_id=project_id,
                quantity_delta=item.required_quantity if old_status == "reserved" else existing.required_quantity,
            )
            updated += 1
        else:
            bom_item = ProjectBomItem(
                project_id=project_id,
                component_id=item.component_id,
                required_quantity=item.required_quantity,
                remark=item.remark,
                status="reserved",
            )
            db.add(bom_item)
            db.flush()
            log_activity(
                db,
                "bom.reserve",
                "project_bom_item",
                f"导入 BOM 占用 {component.name} x {item.required_quantity}",
                entity_id=bom_item.id,
                component_id=component.id,
                project_id=project_id,
                quantity_delta=item.required_quantity,
                detail={"remark": item.remark},
            )
            added += 1
    db.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@app.post("/api/projects/{project_id}/bom/import-rows/{row_id}/ignore")
def ignore_bom_import_row(project_id: int, row_id: int, _: Protected, db: Session = Depends(get_db)):
    row = (
        db.query(ProjectBomImportRow)
        .filter(ProjectBomImportRow.project_id == project_id, ProjectBomImportRow.id == row_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="BOM import row not found")
    if row.auto_imported:
        raise HTTPException(status_code=400, detail="该行已自动导入正式 BOM，请先在正式 BOM 中释放后再处理")
    row.status = "ignored"
    row.selected_component_id = None
    row.match_confidence = 0
    row.ai_reason = "已手动忽略，不参与匹配进度和待采购统计。"
    row.updated_at = datetime.utcnow()
    batch = db.get(ProjectBomImportBatch, row.batch_id)
    if batch:
        recompute_bom_import_batch(db, batch)
    log_activity(
        db,
        "bom.import.ignore",
        "project_bom_import_row",
        f"忽略 BOM 导入行 {row.designator or row.source_row or row.id}",
        entity_id=row.id,
        project_id=project_id,
        detail={
            "source_row": row.source_row,
            "designator": row.designator,
            "manufacturer_part": row.manufacturer_part,
            "value": row.value,
            "footprint": row.footprint,
        },
    )
    db.commit()
    return latest_bom_import_batch_out(db, project_id) or {"rows": []}


@app.post("/api/projects/{project_id}/bom/import-rows/{row_id}/pending-component")
def create_pending_component_from_bom_row(project_id: int, row_id: int, _: Protected, db: Session = Depends(get_db)):
    row = (
        db.query(ProjectBomImportRow)
        .filter(ProjectBomImportRow.project_id == project_id, ProjectBomImportRow.id == row_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="BOM import row not found")
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not row.supplier_part and not row.manufacturer_part:
        raise HTTPException(status_code=400, detail="该行缺少立创编号或型号，无法加入待采购库")

    component = None
    if row.supplier_part:
        component = db.query(Component).filter(Component.lcsc_number == row.supplier_part).first()
    if not component and row.manufacturer_part:
        component = db.query(Component).filter(Component.model == row.manufacturer_part, Component.source == "BOM 待采购库").first()

    if not component:
        category = None
        if row.comment:
            category = db.query(Category).filter(Category.name == row.comment).first()
        display_name = row.value or row.manufacturer_part or row.supplier_part or f"BOM 行 {row.source_row}"
        component = Component(
            name=display_name,
            model=row.manufacturer_part or row.supplier_part,
            category_id=category.id if category else None,
            parameters=row.value,
            package=row.footprint,
            quantity=0,
            source="BOM 待采购库",
            lcsc_number=row.supplier_part,
            tags="待采购",
            source_title=" / ".join(part for part in [row.manufacturer_part, row.value, row.footprint, row.supplier_part] if part),
            normalized_spec=row.value or row.footprint,
            status="pending_purchase",
            location="待采购",
            remark=f"由项目 {project.name} 的 BOM 导入行创建；位号 {row.designator or '-'}；数量 {row.required_quantity}",
            ai_status="pending",
        )
        db.add(component)
        db.flush()
        enqueue_ai_task(db, "component_organize", "component", component.id, organize_cache_key(component))
        enqueue_ai_task(db, "component_analyze", "component", component.id, component_ai_cache_key(component))

    remark = "；".join(
        [
            "待采购库占位",
            f"BOM 位号: {row.designator or '-'}",
            f"BOM 型号: {row.manufacturer_part or '-'}",
            f"BOM 立创编号: {row.supplier_part or '-'}",
            f"BOM 封装: {row.footprint or '-'}",
        ]
    )
    existing = (
        db.query(ProjectBomItem)
        .filter(ProjectBomItem.project_id == project_id, ProjectBomItem.component_id == component.id)
        .first()
    )
    if existing:
        existing.required_quantity += int(row.required_quantity or 1)
        existing.status = "reserved"
        existing.remark = f"{existing.remark or ''}\n{remark}".strip()
    else:
        db.add(
            ProjectBomItem(
                project_id=project_id,
                component_id=component.id,
                required_quantity=int(row.required_quantity or 1),
                remark=remark,
                status="reserved",
            )
        )
    row.selected_component_id = component.id
    row.status = "pending_purchase"
    row.match_confidence = 100
    row.ai_reason = "已加入待采购库并匹配到项目 BOM，后续采购入库后补充库存数量。"
    row.auto_import_note = "待采购库占位，库存数量为 0"
    batch = db.get(ProjectBomImportBatch, row.batch_id)
    if batch:
        recompute_bom_import_batch(db, batch)
    log_activity(
        db,
        "bom.import.pending_purchase",
        "project_bom_import_row",
        f"加入待采购库并匹配 BOM：{component.name}",
        entity_id=row.id,
        component_id=component.id,
        project_id=project_id,
        quantity_delta=int(row.required_quantity or 1),
        detail={"lcsc_number": row.supplier_part, "source_row": row.source_row, "designator": row.designator},
    )
    db.commit()
    return latest_bom_import_batch_out(db, project_id) or {"rows": []}


@app.get("/api/projects/{project_id}/shortage")
def project_shortage(project_id: int, _: Protected, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    reserved = reserved_quantities(db, list({item.component_id for item in project.bom_items}))
    rows = [bom_item_out(item, reserved) for item in project.bom_items]
    return [row for row in rows if not row["enough"]]


@app.get("/api/projects/{project_id}/export")
def export_project_bom(project_id: int, _: Protected, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    reserved = reserved_quantities(db, list({item.component_id for item in project.bom_items}))
    writer.writerow(["项目", "名称", "型号", "分类", "参数", "封装", "需求数量", "总库存", "已占用", "可用库存", "缺料数量", "立创编号", "备注"])
    for item in project.bom_items:
        component = item.component
        row = bom_item_out(item, reserved)
        writer.writerow(
            [
                project.name,
                component.name,
                component.model or "",
                component.category.name if component.category else "",
                component.parameters or "",
                component.package or "",
                item.required_quantity,
                component.quantity,
                row["reserved_quantity"],
                row["available_quantity"],
                row["shortage_quantity"],
                component.lcsc_number or "",
                item.remark or "",
            ]
        )
    buffer.seek(0)
    filename = f"project-{project_id}-bom.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/projects/{project_id}/ai/analyze-bom")
def analyze_project_bom(project_id: int, _: Protected, db: Session = Depends(get_db), force: bool = False):
    project = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    cache_key = project_bom_cache_key(project)
    if not force and project.ai_bom_analysis and project.ai_bom_cache_key == cache_key:
        return json.loads(project.ai_bom_analysis)
    reserved = reserved_quantities(db, list({item.component_id for item in project.bom_items}))
    bom_items = [bom_item_out(item, reserved) for item in project.bom_items]
    try:
        result = analyze_bom(
            {"id": project.id, "name": project.name, "description": project.description, "status": project.status},
            bom_items,
        )
    except Exception as error:
        handle_mimo_error(error)
    result["cache_key"] = cache_key
    result["generated_at"] = datetime.now().isoformat()
    project.ai_bom_analysis = json.dumps(result, ensure_ascii=False)
    project.ai_bom_cache_key = cache_key
    project.ai_bom_updated_at = datetime.now()
    db.add(
        AiKnowledgeCard(
            project_id=project.id,
            title=f"{project.name} BOM AI 分析",
            content=json.dumps(result, ensure_ascii=False, indent=2),
            tags="BOM,缺料,风险",
            source_type="ai",
            confidence=result.get("confidence"),
        )
    )
    db.commit()
    return result


@app.post("/api/projects/{project_id}/ai/plan")
def project_ai_plan(project_id: int, payload: ProjectAiPlanRequest, _: Protected, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    candidates = search_component_candidates(db, payload.goal, 30)
    try:
        result = project_plan(payload.goal, candidates)
    except Exception as error:
        handle_mimo_error(error)
    result["generated_at"] = datetime.now().isoformat()
    db.add(
        AiKnowledgeCard(
            project_id=project.id,
            title=f"{project.name} 项目规划",
            content=json.dumps(result, ensure_ascii=False, indent=2),
            tags="项目规划,推荐BOM,风险",
            source_type="ai",
            confidence=result.get("confidence"),
        )
    )
    db.commit()
    return result


@app.post("/api/projects/{project_id}/ai/consult")
def project_ai_consult(project_id: int, payload: ProjectAiConsultRequest, _: Protected, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    reserved = reserved_quantities(db, list({item.component_id for item in project.bom_items}))
    bom_items = [bom_item_out(item, reserved) for item in project.bom_items]
    candidates = search_component_candidates(db, payload.question, 30)
    try:
        result = project_consult(
            payload.question,
            {"id": project.id, "name": project.name, "description": project.description, "status": project.status},
            bom_items,
            candidates,
        )
    except Exception as error:
        handle_mimo_error(error)
    result["generated_at"] = datetime.now().isoformat()
    db.add(
        AiKnowledgeCard(
            project_id=project.id,
            title=f"{project.name} AI 咨询",
            content=json.dumps(result, ensure_ascii=False, indent=2),
            tags="项目咨询,BOM,推荐",
            source_type="ai",
            confidence=result.get("confidence"),
        )
    )
    db.commit()
    return result


@app.post("/api/import/excel/preview", response_model=list[ImportPreviewRow])
async def preview_excel(_: Protected, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    parsed = parse_excel(content, db, file.filename)
    result: list[dict] = []
    for row in parsed:
        duplicate = find_duplicate(db, row.data)
        already_imported = find_import_record(db, row.data) is not None
        suggested_action = "skip" if already_imported else "merge" if duplicate else "create"
        result.append(
            {
                **row.data,
                "source_row": row.source_row,
                "duplicate": duplicate is not None,
                "duplicate_component_id": duplicate.id if duplicate else None,
                "already_imported": already_imported,
                "suggested_action": suggested_action,
                "action": suggested_action,
            }
        )
    return result


@app.post("/api/import/excel/commit", response_model=ImportCommitResult)
def commit_excel(payload: ImportCommitRequest, _: Protected, db: Session = Depends(get_db)):
    created = merged = skipped = already_imported = 0
    touched_component_ids: set[int] = set()
    for row in payload.rows:
        values = row.model_dump()
        if not values.get("name"):
            skipped += 1
            continue
        action = values.get("action") or values.get("suggested_action")
        if action == "skip":
            skipped += 1
            continue
        if find_import_record(db, values):
            already_imported += 1
            skipped += 1
            continue
        component_data = normalize_for_inventory(db, component_values(values), clean_name=True)
        duplicate = find_duplicate(db, values)
        if duplicate:
            resolved_pending_purchase = duplicate.status == "pending_purchase"
            merge_component(duplicate, component_data)
            duplicate.ai_status = "stale"
            create_import_record(db, values, duplicate.id)
            touched_component_ids.add(duplicate.id)
            merged += 1
        else:
            component = Component(**component_data)
            component.ai_status = "pending"
            db.add(component)
            db.flush()
            create_import_record(db, values, component.id)
            touched_component_ids.add(component.id)
            created += 1
        log_activity(
            db,
            "import.excel.row",
            "component",
            f"Excel 导入 {values.get('name')} x {values.get('quantity') or 0}",
            component_id=(duplicate.id if duplicate else component.id),
            quantity_delta=int(values.get("quantity") or 0),
            detail={
                "order_number": values.get("order_number"),
                "lcsc_number": values.get("lcsc_number"),
                "action": action,
                "source_file": values.get("source_file"),
                "resolved_pending_purchase": bool(duplicate and action != "skip" and locals().get("resolved_pending_purchase", False)),
            },
        )
    for component_id in touched_component_ids:
        component = db.get(Component, component_id)
        if component:
            enqueue_ai_task(db, "component_organize", "component", component.id, organize_cache_key(component))
            enqueue_ai_task(db, "component_analyze", "component", component.id, component_ai_cache_key(component))
    db.commit()
    log_activity(
        db,
        "import.excel.commit",
        "import",
        f"Excel 导入完成：新增 {created}，合并 {merged}，跳过 {skipped}，已导入 {already_imported}",
        detail={"created": created, "merged": merged, "skipped": skipped, "already_imported": already_imported},
    )
    db.commit()
    return {"created": created, "merged": merged, "skipped": skipped, "already_imported": already_imported}


def bom_match_bucket(row: dict) -> str:
    if row.get("status") == "ignored":
        return "ignored"
    if row.get("status") == "supplier_missing":
        return "missing"
    if row.get("selected_component_id") and row.get("status") not in {"low_confidence", "missing"}:
        return "matched"
    if row.get("matches"):
        return "review"
    return "missing"


def recompute_bom_import_batch(db: Session, batch: ProjectBomImportBatch) -> None:
    rows = db.query(ProjectBomImportRow).filter(ProjectBomImportRow.batch_id == batch.id).all()
    candidate_counts = {
        row_id: count
        for row_id, count in (
            db.query(ProjectBomImportCandidate.import_row_id, func.count(ProjectBomImportCandidate.id))
            .filter(ProjectBomImportCandidate.import_row_id.in_([row.id for row in rows] or [0]))
            .group_by(ProjectBomImportCandidate.import_row_id)
            .all()
        )
    }
    buckets = {"matched": 0, "review": 0, "missing": 0}
    for row in rows:
        if row.status == "ignored":
            continue
        if row.status == "supplier_missing":
            buckets["missing"] += 1
        elif row.selected_component_id and row.status not in {"low_confidence", "missing"}:
            buckets["matched"] += 1
        elif candidate_counts.get(row.id, 0) > 0:
            buckets["review"] += 1
        else:
            buckets["missing"] += 1
    batch.total_count = sum(buckets.values())
    batch.matched_count = buckets["matched"]
    batch.review_count = buckets["review"]
    batch.missing_count = buckets["missing"]
    batch.auto_imported_count = sum(1 for row in rows if row.auto_imported)
    project = db.get(Project, batch.project_id)
    if project:
        project.bom_match_total = batch.total_count
        project.bom_match_matched = batch.matched_count
        project.bom_match_review = batch.review_count
        project.bom_match_missing = batch.missing_count
        project.bom_match_missing_items = None
        project.bom_match_rows = None
        project.bom_match_updated_at = datetime.utcnow()


def auto_import_exact_lcsc_rows(db: Session, project_id: int | None, rows: list[dict]) -> dict[str, int]:
    if not project_id:
        return {"added": 0, "updated": 0, "skipped": 0}
    if not db.get(Project, project_id):
        return {"added": 0, "updated": 0, "skipped": 0}
    added = updated = skipped = 0
    for row in rows:
        if row.get("status") != "exact_lcsc" or not row.get("selected_component_id"):
            continue
        component_id = int(row["selected_component_id"])
        component = db.get(Component, component_id)
        if not component:
            skipped += 1
            continue
        marker = f"BOM自动导入行:{row.get('source_row')}"
        remark = "；".join(
            [
                marker,
                "编号一致",
                f"BOM 位号: {row.get('designator') or '-'}",
                f"BOM 型号: {row.get('manufacturer_part') or '-'}",
                f"BOM 封装: {row.get('footprint') or '-'}",
            ]
        )
        existing = (
            db.query(ProjectBomItem)
            .filter(ProjectBomItem.project_id == project_id, ProjectBomItem.component_id == component_id)
            .first()
        )
        if existing and marker in (existing.remark or ""):
            row["auto_imported"] = True
            row["auto_import_note"] = "编号一致，已自动导入过"
            skipped += 1
            continue
        if existing:
            old_status = existing.status or "reserved"
            existing.required_quantity += int(row.get("required_quantity") or 1)
            existing.status = "reserved"
            existing.remark = f"{existing.remark or ''}\n{remark}".strip()
            row["auto_imported"] = True
            row["auto_import_note"] = "编号一致，已自动合并到项目 BOM"
            log_activity(
                db,
                "bom.reserve.auto_update",
                "project_bom_item",
                f"编号一致自动合并 {component.name} x {row.get('required_quantity') or 1}",
                entity_id=existing.id,
                component_id=component.id,
                project_id=project_id,
                quantity_delta=int(row.get("required_quantity") or 1) if old_status == "reserved" else existing.required_quantity,
                detail={"source_row": row.get("source_row"), "reason": "编号一致"},
            )
            updated += 1
        else:
            bom_item = ProjectBomItem(
                project_id=project_id,
                component_id=component_id,
                required_quantity=int(row.get("required_quantity") or 1),
                remark=remark,
                status="reserved",
            )
            db.add(bom_item)
            db.flush()
            row["auto_imported"] = True
            row["auto_import_note"] = "编号一致，已自动导入项目 BOM"
            log_activity(
                db,
                "bom.reserve.auto",
                "project_bom_item",
                f"编号一致自动导入 {component.name} x {row.get('required_quantity') or 1}",
                entity_id=bom_item.id,
                component_id=component.id,
                project_id=project_id,
                quantity_delta=int(row.get("required_quantity") or 1),
                detail={"source_row": row.get("source_row"), "reason": "编号一致"},
            )
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped}


def save_bom_match_snapshot(db: Session, project_id: int | None, rows: list[dict], source_file: str | None = None) -> None:
    if not project_id:
        return
    project = db.get(Project, project_id)
    if not project:
        return
    batch = ProjectBomImportBatch(project_id=project_id, source_file=source_file, status="pending")
    db.add(batch)
    db.flush()
    buckets = {"matched": 0, "review": 0, "missing": 0}
    for row in rows:
        bucket = bom_match_bucket(row)
        buckets[bucket] += 1
        suggestion = row.get("missing_suggestion") or {}
        alternatives = suggestion.get("alternatives") or []
        reason_parts = [suggestion.get("reason")]
        reason_parts.extend(item.get("description") for item in alternatives if isinstance(item, dict))
        import_row = ProjectBomImportRow(
            batch_id=batch.id,
            project_id=project_id,
            source_row=row.get("source_row"),
            designator=row.get("designator"),
            required_quantity=int(row.get("required_quantity") or 1),
            comment=row.get("comment"),
            footprint=row.get("footprint"),
            value=row.get("value"),
            manufacturer_part=row.get("manufacturer_part"),
            supplier_part=row.get("supplier_part"),
            status=row.get("status") or "missing",
            selected_component_id=row.get("selected_component_id"),
            match_confidence=int(row.get("match_confidence") or 0),
            role=row.get("role"),
            ai_reason=row.get("ai_reason"),
            ai_confidence=row.get("ai_confidence"),
            ai_error=row.get("ai_error"),
            missing_description=suggestion.get("description"),
            missing_reason="\n".join(part for part in reason_parts if part),
            lcsc_search_keyword=suggestion.get("lcsc_search_keyword"),
            lcsc_search_url=suggestion.get("lcsc_search_url"),
            auto_imported=bool(row.get("auto_imported")),
            auto_import_note=row.get("auto_import_note"),
        )
        db.add(import_row)
        db.flush()
        for rank, match in enumerate(row.get("matches") or []):
            component = match.get("component") or {}
            if not component.get("id"):
                continue
            db.add(
                ProjectBomImportCandidate(
                    import_row_id=import_row.id,
                    component_id=int(component["id"]),
                    score=int(match.get("score") or 0),
                    match_type=match.get("match_type"),
                    reason=match.get("reason"),
                    flags=",".join(match.get("flags") or []),
                    available_quantity=int(match.get("available_quantity") or 0),
                    shortage_quantity=int(match.get("shortage_quantity") or 0),
                    enough=bool(match.get("enough")),
                    rank=rank,
                )
            )
    batch.total_count = len(rows)
    batch.matched_count = buckets["matched"]
    batch.review_count = buckets["review"]
    batch.missing_count = buckets["missing"]
    batch.auto_imported_count = sum(1 for row in rows if row.get("auto_imported"))
    project.bom_match_total = len(rows)
    project.bom_match_matched = buckets["matched"]
    project.bom_match_review = buckets["review"]
    project.bom_match_missing = buckets["missing"]
    project.bom_match_missing_items = None
    project.bom_match_rows = None
    project.bom_match_updated_at = datetime.utcnow()
    db.commit()


def bom_import_row_out(db: Session, row: ProjectBomImportRow) -> dict:
    candidates = (
        db.query(ProjectBomImportCandidate)
        .filter(ProjectBomImportCandidate.import_row_id == row.id)
        .order_by(ProjectBomImportCandidate.rank.asc(), ProjectBomImportCandidate.score.desc())
        .all()
    )
    matches = []
    for candidate in candidates:
        component = db.get(Component, candidate.component_id)
        if not component:
            continue
        matches.append(
            {
                "component": component_to_dict(component),
                "score": candidate.score,
                "match_type": candidate.match_type,
                "reason": candidate.reason,
                "flags": [flag for flag in (candidate.flags or "").split(",") if flag],
                "available_quantity": candidate.available_quantity,
                "shortage_quantity": candidate.shortage_quantity,
                "enough": candidate.enough,
            }
        )
    alternatives = []
    reason_lines = [line.strip() for line in (row.missing_reason or "").splitlines() if line.strip()]
    if len(reason_lines) > 1:
        alternatives = [{"description": line, "reason": "组合替代建议"} for line in reason_lines[1:]]
    return {
        "id": row.id,
        "source_row": row.source_row,
        "designator": row.designator,
        "required_quantity": row.required_quantity,
        "comment": row.comment,
        "footprint": row.footprint,
        "value": row.value,
        "manufacturer_part": row.manufacturer_part,
        "supplier_part": row.supplier_part,
        "status": row.status,
        "selected_component_id": row.selected_component_id,
        "match_confidence": row.match_confidence,
        "matches": matches,
        "role": row.role,
        "ai_reason": row.ai_reason,
        "ai_confidence": row.ai_confidence,
        "ai_error": row.ai_error,
        "auto_imported": row.auto_imported,
        "auto_import_note": row.auto_import_note,
        "missing_suggestion": {
            "description": row.missing_description,
            "reason": reason_lines[0] if reason_lines else None,
            "lcsc_search_keyword": row.lcsc_search_keyword,
            "lcsc_search_url": row.lcsc_search_url,
            "alternatives": alternatives,
        }
        if row.missing_description or row.lcsc_search_keyword or alternatives
        else None,
        "lcsc_search_url": row.lcsc_search_url,
    }


def latest_bom_import_batch_out(db: Session, project_id: int) -> dict | None:
    batch = (
        db.query(ProjectBomImportBatch)
        .filter(ProjectBomImportBatch.project_id == project_id)
        .order_by(ProjectBomImportBatch.created_at.desc(), ProjectBomImportBatch.id.desc())
        .first()
    )
    if not batch:
        return None
    rows = (
        db.query(ProjectBomImportRow)
        .filter(ProjectBomImportRow.batch_id == batch.id)
        .order_by(ProjectBomImportRow.source_row.asc(), ProjectBomImportRow.id.asc())
        .all()
    )
    return {
        "id": batch.id,
        "project_id": batch.project_id,
        "status": batch.status,
        "total_count": batch.total_count,
        "matched_count": batch.matched_count,
        "review_count": batch.review_count,
        "missing_count": batch.missing_count,
        "auto_imported_count": batch.auto_imported_count,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "rows": [bom_import_row_out(db, row) for row in rows],
    }


@app.get("/api/projects/{project_id}/bom/import-batch/latest")
def latest_bom_import_batch(project_id: int, _: Protected, db: Session = Depends(get_db)):
    result = latest_bom_import_batch_out(db, project_id)
    if not result:
        return {"rows": [], "total_count": 0, "matched_count": 0, "review_count": 0, "missing_count": 0, "auto_imported_count": 0}
    return result


@app.post("/api/ai/bom-match/preview")
async def preview_bom_match(
    _: Protected,
    file: UploadFile = File(...),
    project_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    content = await file.read()
    rows = parse_bom_excel(content, file.filename)
    matched = match_bom_rows(db, rows)
    for row in matched:
        row["ai_checked"] = False
        row["ai_error"] = None
    low_rows = [row for row in matched if row.get("status") in {"missing", "low_confidence", "supplier_missing"}][:10]
    if low_rows:
        inventory = db.query(Component).options(joinedload(Component.category)).order_by(Component.quantity.desc(), Component.updated_at.desc()).limit(120).all()
        try:
            ai_result = assist_bom_matches(low_rows, inventory)
            ai_rows = {int(row.get("source_row")): row for row in ai_result.get("rows", []) if row.get("source_row") is not None}
            for row in matched:
                ai_row = ai_rows.get(int(row.get("source_row") or 0))
                if not ai_row:
                    continue
                row["ai_checked"] = True
                row["role"] = ai_row.get("role") or row.get("role")
                row["ai_reason"] = ai_row.get("reason") or row.get("ai_reason")
                row["ai_confidence"] = ai_row.get("confidence")
                if row.get("status") != "supplier_missing" and not row.get("selected_component_id") and ai_row.get("selected_component_id"):
                    try:
                        candidate_id = int(ai_row["selected_component_id"])
                    except (TypeError, ValueError):
                        candidate_id = None
                    if candidate_id and any(match["component"]["id"] == candidate_id for match in row.get("matches", [])):
                        row["selected_component_id"] = candidate_id
                        row["status"] = "approximate"
                if ai_row.get("missing_suggestion"):
                    row["missing_suggestion"] = ai_row["missing_suggestion"]
        except Exception as exc:
            message = f"AI 辅助失败，已使用库存预匹配结果：{exc}"
            for row in low_rows:
                row["ai_checked"] = False
                row["ai_error"] = message
    auto_result = auto_import_exact_lcsc_rows(db, project_id, matched)
    if any(auto_result.values()):
        for row in matched:
            row["auto_import_result"] = auto_result
    save_bom_match_snapshot(db, project_id, matched, file.filename)
    return matched


@app.get("/api/activity-logs", response_model=list[ActivityLogOut])
def list_activity_logs(
    _: Protected,
    db: Session = Depends(get_db),
    limit: int = Query(80, ge=1, le=300),
    component_id: int | None = None,
    project_id: int | None = None,
    action: str | None = None,
):
    query = db.query(ActivityLog)
    if component_id:
        query = query.filter(ActivityLog.component_id == component_id)
    if project_id:
        query = query.filter(ActivityLog.project_id == project_id)
    if action:
        query = query.filter(ActivityLog.action == action)
    return query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(limit).all()


@app.get("/api/ai/tasks/summary", response_model=AiTaskSummary)
def ai_tasks_summary(_: Protected, db: Session = Depends(get_db)):
    if resolve_superseded_ai_failures(db):
        db.commit()
    counts = {status: 0 for status in ["pending", "processing", "completed", "failed", "stale"]}
    for status, count in db.query(AiTask.status, func.count(AiTask.id)).group_by(AiTask.status).all():
        if status in counts:
            counts[status] = count
    missing = db.query(func.count(Component.id)).filter(Component.ai_status.in_(["pending", "failed", "stale"])).scalar() or 0
    current_task = db.query(AiTask).filter(AiTask.status == "processing").order_by(AiTask.started_at.desc()).first()
    current_component = None
    if current_task and current_task.target_type == "component":
        component = db.get(Component, current_task.target_id)
        current_component = component.name if component else None
    last_finished_at = db.query(func.max(AiTask.finished_at)).scalar()
    return {
        **counts,
        "missing_components": missing,
        "current_component": current_component,
        "last_finished_at": last_finished_at,
        "running": AI_WORKER_RUNNING,
        "paused": AI_WORKER_PAUSED,
    }


@app.post("/api/ai/tasks/enqueue-missing", response_model=AiTaskSummary)
def enqueue_missing_ai_tasks(_: Protected, db: Session = Depends(get_db)):
    enqueue_missing_component_ai_tasks(db, include_failed=True)
    db.commit()
    return ai_tasks_summary(_, db)


@app.post("/api/ai/tasks/enqueue-organize", response_model=AiTaskSummary)
def enqueue_organize_ai_tasks(_: Protected, db: Session = Depends(get_db), force: bool = False):
    enqueue_organize_component_tasks(db, force=force)
    db.commit()
    return ai_tasks_summary(_, db)


@app.post("/api/ai/reset-and-reorganize")
def reset_and_reorganize(_: Protected, db: Session = Depends(get_db)):
    db.query(Component).update(
        {
            Component.ai_summary: None,
            Component.ai_usage: None,
            Component.ai_risk_notes: None,
            Component.ai_pcb_notes: None,
            Component.ai_substitutes: None,
            Component.ai_tags: None,
            Component.ai_confidence: None,
            Component.ai_cache_key: None,
            Component.ai_status: "pending",
            Component.ai_error: None,
            Component.ai_updated_at: None,
            Component.tags: None,
        },
        synchronize_session=False,
    )
    db.query(AiKnowledgeCard).filter(AiKnowledgeCard.source_type == "ai").delete(synchronize_session=False)
    db.query(AiTask).delete(synchronize_session=False)
    db.commit()
    organize_count = enqueue_organize_component_tasks(db, force=True)
    analyze_count = enqueue_missing_component_ai_tasks(db, include_failed=True)
    db.commit()
    return {"reset": True, "organize_queued": organize_count, "analyze_queued": analyze_count}


@app.post("/api/ai/tasks/start", response_model=AiTaskSummary)
def start_ai_tasks(_: Protected, db: Session = Depends(get_db)):
    global AI_WORKER_PAUSED
    ensure_ai_worker()
    AI_WORKER_PAUSED = False
    return ai_tasks_summary(_, db)


@app.post("/api/ai/tasks/pause", response_model=AiTaskSummary)
def pause_ai_tasks(_: Protected, db: Session = Depends(get_db)):
    global AI_WORKER_PAUSED
    AI_WORKER_PAUSED = True
    return ai_tasks_summary(_, db)


@app.get("/api/ai/tasks", response_model=list[AiTaskOut])
def list_ai_tasks(_: Protected, db: Session = Depends(get_db), limit: int = Query(80, ge=1, le=300)):
    return db.query(AiTask).order_by(AiTask.created_at.desc(), AiTask.id.desc()).limit(limit).all()


@app.get("/api/integrations/components", response_model=ComponentList)
def integration_components(_: Protected, db: Session = Depends(get_db), keyword: str | None = None, limit: int = Query(50, ge=1, le=200)):
    query = db.query(Component).options(joinedload(Component.category))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                Component.name.ilike(like),
                Component.model.ilike(like),
                Component.parameters.ilike(like),
                Component.lcsc_number.ilike(like),
                Component.tags.ilike(like),
            )
        )
    items = query.order_by(Component.updated_at.desc(), Component.id.desc()).limit(limit).all()
    reserved = reserved_quantities(db, [item.id for item in items])
    return {"items": [component_out(item, reserved.get(item.id, 0)) for item in items], "total": len(items)}


@app.get("/api/integrations/projects", response_model=list[ProjectOut])
def integration_projects(_: Protected, db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)):
    projects = (
        db.query(Project)
        .options(joinedload(Project.bom_items).joinedload(ProjectBomItem.component).joinedload(Component.category))
        .order_by(Project.updated_at.desc(), Project.id.desc())
        .limit(limit)
        .all()
    )
    reserved = reserved_quantities(db, list({item.component_id for project in projects for item in project.bom_items}))
    return [project_out(project, reserved) for project in projects]


@app.post("/api/integrations/components/{component_id}/consume", response_model=ComponentOut)
def integration_consume_component(
    component_id: int,
    payload: ComponentConsumeRequest,
    _: Protected,
    db: Session = Depends(get_db),
):
    return decrement_component_quantity(component_id, _, db, payload)


@app.get("/api/integrations/activity-logs", response_model=list[ActivityLogOut])
def integration_activity_logs(_: Protected, db: Session = Depends(get_db), limit: int = Query(80, ge=1, le=300)):
    return db.query(ActivityLog).order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(limit).all()


def enqueue_missing_component_ai_tasks(db: Session, include_failed: bool = False) -> int:
    count = 0
    components = db.query(Component).options(joinedload(Component.category)).all()
    for component in components:
        mark_component_ai_stale(component)
        status = component.ai_status or "pending"
        cache_key = component_ai_cache_key(component)
        needs_initial_run = not component.ai_summary and status != "failed"
        needs_refresh = status in {"pending", "stale"}
        needs_manual_retry = include_failed and status == "failed"
        if needs_initial_run or needs_refresh or needs_manual_retry:
            enqueue_ai_task(db, "component_analyze", "component", component.id, cache_key)
            if status == "failed" and include_failed:
                component.ai_status = "pending"
            count += 1
    return count


def enqueue_auto_refresh_component_ai_tasks(db: Session) -> int:
    global AI_LAST_AUTO_REFRESH_AT
    if not AI_AUTO_REFRESH_ENABLED:
        return 0
    now = datetime.now()
    if AI_LAST_AUTO_REFRESH_AT and now - AI_LAST_AUTO_REFRESH_AT < timedelta(hours=AI_AUTO_REFRESH_INTERVAL_HOURS):
        return 0
    cutoff = now - timedelta(days=AI_AUTO_REFRESH_AFTER_DAYS)
    components = (
        db.query(Component)
        .filter(
            Component.ai_status == "completed",
            Component.ai_summary.isnot(None),
            or_(Component.ai_updated_at == None, Component.ai_updated_at < cutoff),
        )
        .order_by(Component.ai_updated_at.asc().nullsfirst(), Component.id.asc())
        .limit(AI_AUTO_REFRESH_MAX_PER_RUN)
        .all()
    )
    for component in components:
        component.ai_status = "stale"
        enqueue_ai_task(db, "component_analyze", "component", component.id, component_ai_cache_key(component))
    AI_LAST_AUTO_REFRESH_AT = now
    return len(components)


def enqueue_organize_component_tasks(db: Session, force: bool = False, limit: int | None = None) -> int:
    count = 0
    query = db.query(Component).options(joinedload(Component.category)).order_by(Component.id.asc())
    if limit:
        query = query.limit(limit)
    for component in query.all():
        cache_key = organize_cache_key(component)
        if not force:
            completed = (
                db.query(AiTask)
                .filter(
                    AiTask.task_type == "component_organize",
                    AiTask.target_type == "component",
                    AiTask.target_id == component.id,
                    AiTask.input_hash == cache_key,
                    AiTask.status == "completed",
                )
                .first()
            )
            if completed or not looks_like_needs_organize(component):
                continue
        enqueue_ai_task(db, "component_organize", "component", component.id, cache_key)
        count += 1
    return count


def analyze_component_with_ai(db: Session, component: Component, scope: str = "full", force: bool = False) -> dict:
    cache_key = component_ai_cache_key(component)
    if not force and scope == "full" and component.ai_status == "completed" and component.ai_cache_key == cache_key:
        return {"cached": True, "summary": component.ai_summary, "cache_key": cache_key}
    known_specs = json.dumps(component_ai_payload(component), ensure_ascii=False)
    result = component_info(component.model or component.name, known_specs, "auto")
    result["generated_at"] = datetime.now().isoformat()
    result["cache_key"] = cache_key
    result["scope"] = scope
    apply_component_ai_result(db, component, result, cache_key)
    log_activity(
        db,
        "ai.component.analyze",
        "component",
        f"AI 整理元器件 {component.name}",
        entity_id=component.id,
        component_id=component.id,
        detail={"scope": scope, "confidence": result.get("confidence")},
    )
    return result


def organize_component_record(db: Session, component: Component, force: bool = False) -> dict:
    cache_key = organize_cache_key(component)
    completed = (
        db.query(AiTask)
        .filter(
            AiTask.task_type == "component_organize",
            AiTask.target_type == "component",
            AiTask.target_id == component.id,
            AiTask.input_hash == cache_key,
            AiTask.status == "completed",
        )
        .first()
    )
    if completed and not force:
        return {"cached": True, "cache_key": cache_key}

    current_fields = {
        "current_name": component.name,
        "current_category": component.category.name if component.category else None,
        "current_part_family": component.part_family,
        "current_count_mode": component.count_mode,
        "current_normalized_spec": component.normalized_spec,
        "current_tags": component.tags,
    }
    categories = [name for (name,) in db.query(Category.name).order_by(Category.id).all()]
    result = organize_component(component_organize_payload(component), categories, current_fields)
    source = "ai"
    apply_result = apply_component_organize_result(db, component, result, source=source)
    return {"cache_key": cache_key, **apply_result}


def process_ai_task(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.get(AiTask, task_id)
        if not task:
            return
        task.status = "processing"
        task.started_at = datetime.now()
        db.commit()
        if task.task_type == "component_analyze" and task.target_type == "component":
            component = db.get(Component, task.target_id)
            if not component:
                raise RuntimeError("Component not found")
            component.ai_status = "processing"
            component.ai_error = None
            db.commit()
            result = analyze_component_with_ai(db, component, "full", False)
        elif task.task_type == "component_organize" and task.target_type == "component":
            component = db.query(Component).options(joinedload(Component.category)).filter(Component.id == task.target_id).first()
            if not component:
                raise RuntimeError("Component not found")
            result = organize_component_record(db, component, False)
        else:
            raise RuntimeError(f"Unsupported AI task: {task.task_type}")
        task.result_json = json.dumps(result, ensure_ascii=False)
        task.status = "completed"
        task.finished_at = datetime.now()
        task.error_message = None
        task.next_attempt_at = None
        db.query(AiTask).filter(
            AiTask.task_type == task.task_type,
            AiTask.target_type == task.target_type,
            AiTask.target_id == task.target_id,
            AiTask.status == "failed",
            AiTask.id != task.id,
        ).update({AiTask.status: "superseded", AiTask.next_attempt_at: None}, synchronize_session=False)
        db.commit()
    except Exception as error:
        db.rollback()
        task = db.get(AiTask, task_id)
        if task:
            task.retry_count = (task.retry_count or 0) + 1
            task.error_message = str(error)
            if task.retry_count < AI_TASK_MAX_RETRIES:
                task.status = "pending"
                task.next_attempt_at = datetime.now() + timedelta(seconds=retry_delay_for(task))
            else:
                task.status = "failed"
                task.next_attempt_at = None
            task.finished_at = datetime.now()
            if task.target_type == "component":
                component = db.get(Component, task.target_id)
                if component:
                    component.ai_status = "pending" if task.status == "pending" else "failed"
                    component.ai_error = str(error)
            db.commit()
    finally:
        db.close()


AI_WORKER_RUNNING = False
AI_WORKER_PAUSED = False
AI_WORKER_THREAD: threading.Thread | None = None
AI_WORKER_CONCURRENCY = 3


def ai_worker_loop() -> None:
    global AI_WORKER_RUNNING
    while AI_WORKER_RUNNING:
        if AI_WORKER_PAUSED:
            time.sleep(1)
            continue
        db = SessionLocal()
        try:
            tasks = (
                db.query(AiTask.id)
                .filter(
                    AiTask.status.in_(["pending", "stale"]),
                    or_(AiTask.next_attempt_at.is_(None), AiTask.next_attempt_at <= datetime.now()),
                )
                .order_by(
                    (AiTask.task_type == "component_organize").desc(),
                    AiTask.next_attempt_at.asc().nullsfirst(),
                    AiTask.created_at.asc(),
                    AiTask.id.asc(),
                )
                .limit(AI_WORKER_CONCURRENCY * 2)
                .all()
            )
            task_ids = [t.id for t in tasks]
        finally:
            db.close()
        if task_ids:
            with ThreadPoolExecutor(max_workers=AI_WORKER_CONCURRENCY) as pool:
                futures = {pool.submit(process_ai_task, tid): tid for tid in task_ids}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        pass
        else:
            db = SessionLocal()
            try:
                enqueue_missing_component_ai_tasks(db, include_failed=True)
                enqueue_auto_refresh_component_ai_tasks(db)
                db.commit()
            finally:
                db.close()
            time.sleep(2)


def ensure_ai_worker() -> None:
    global AI_WORKER_RUNNING, AI_WORKER_THREAD
    if AI_WORKER_THREAD and AI_WORKER_THREAD.is_alive():
        return
    AI_WORKER_RUNNING = True
    AI_WORKER_THREAD = threading.Thread(target=ai_worker_loop, daemon=True)
    AI_WORKER_THREAD.start()


def handle_mimo_error(error: Exception):
    if isinstance(error, MimoNotConfiguredError):
        raise HTTPException(status_code=503, detail="MIMO_API_KEY is not configured") from error
    if isinstance(error, MimoRequestError):
        raise HTTPException(status_code=502, detail=str(error)) from error
    raise error


@app.post("/api/ai/classify")
def ai_classify(payload: AiClassifyRequest, _: Protected, db: Session = Depends(get_db)):
    categories = [name for (name,) in db.query(Category.name).order_by(Category.id).all()]
    try:
        result = classify_component(payload.model_dump(), categories)
    except Exception as error:
        handle_mimo_error(error)
    result["requires_confirmation"] = True
    return result


@app.post("/api/ai/explain")
def ai_explain(payload: AiExplainRequest, _: Protected):
    try:
        return explain_component(payload.model_dump())
    except Exception as error:
        handle_mimo_error(error)


@app.post("/api/ai/project-plan")
def ai_project_plan(payload: AiProjectPlanRequest, _: Protected, db: Session = Depends(get_db)):
    candidates = search_component_candidates(db, payload.goal, 20)
    try:
        return project_plan(payload.goal, candidates)
    except Exception as error:
        handle_mimo_error(error)


@app.post("/api/ai/component-search")
def ai_component_search(payload: AiComponentSearchRequest, _: Protected, db: Session = Depends(get_db)):
    candidates = search_component_candidates(db, payload.requirement, payload.limit)
    try:
        return component_search(payload.requirement, candidates)
    except Exception as error:
        handle_mimo_error(error)


@app.get("/api/ai/search-suggestions")
def ai_search_suggestions(
    _: Protected,
    db: Session = Depends(get_db),
    keyword: str = Query(..., min_length=1, max_length=120),
    category_id: int | None = None,
    status: str | None = None,
    ai_status: str | None = None,
    stock: str | None = None,
):
    categories = [name for (name,) in db.query(Category.name).order_by(Category.id).all()]
    filters = {
        "category": db.get(Category, category_id).name if category_id and db.get(Category, category_id) else "",
        "status": status or "",
        "ai_status": ai_status or "",
        "stock": stock or "",
    }
    try:
        return search_empty_suggestions(keyword, filters, categories)
    except Exception as error:
        handle_mimo_error(error)


@app.post("/api/ai/component-info")
def ai_component_info(payload: AiComponentInfoRequest, _: Protected):
    try:
        return component_info(payload.query, payload.known_specs, payload.web_search)
    except Exception as error:
        handle_mimo_error(error)


@app.post("/api/ai/image-import/preview", response_model=list[ImageImportPreviewRow])
async def ai_image_import_preview(_: Protected, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    if not files:
        raise HTTPException(status_code=400, detail="No image files uploaded")
    if len(files) > 8:
        raise HTTPException(status_code=400, detail="At most 8 images are allowed")
    images: list[dict[str, str]] = []
    for file in files:
        content_type = file.content_type or "application/octet-stream"
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {content_type}")
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"Image is too large: {file.filename}")
        images.append({"content_type": content_type, "base64": base64.b64encode(content).decode("ascii")})
    inventory = db.query(Component).options(joinedload(Component.category)).order_by(Component.updated_at.desc()).limit(80).all()
    categories = [name for (name,) in db.query(Category.name).order_by(Category.id).all()]
    try:
        result = image_import_preview(images, inventory, categories)
    except Exception as error:
        handle_mimo_error(error)
    rows = []
    for item in result.get("items", []):
        if not isinstance(item, dict):
            continue
        values = {
            "name": clean_component_name(item.get("normalized_name") or item.get("name") or item.get("model"), item.get("model")),
            "model": item.get("model"),
            "category_id": category_id_by_name(db, item.get("category_suggestion")),
            "parameters": item.get("parameters"),
            "package": item.get("package"),
            "quantity": int(item.get("quantity") or 1),
            "source": item.get("source") or "图片识别导入",
            "lcsc_number": item.get("lcsc_number"),
            "tags": ",".join(normalize_tag_text(item.get("tags"))),
            "source_title": item.get("source_title") or item.get("name") or item.get("evidence_text"),
            "status": "in_stock",
            "location": None,
            "remark": item.get("evidence_text"),
            "datasheet_url": None,
            "part_family": item.get("part_family") or "component",
            "count_mode": item.get("count_mode") or "exact",
            "normalized_spec": item.get("normalized_spec"),
        }
        values.update(
            {
                "confidence": item.get("confidence") or "low",
                "evidence_text": item.get("evidence_text"),
                "category_suggestion": item.get("category_suggestion"),
                "matched_component_id": item.get("matched_component_id"),
                "match_score": int(item.get("match_score") or 0),
                "lcsc_search_url": item.get("lcsc_search_url") or lcsc_search_url(item.get("model") or item.get("name")),
                "action": (
                    "skip"
                    if (item.get("confidence") == "low" or values.get("part_family") == "other")
                    else "merge"
                    if item.get("matched_component_id")
                    else "create"
                ),
            }
        )
        rows.append(values)
    return rows
