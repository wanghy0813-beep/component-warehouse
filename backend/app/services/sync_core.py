from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Table


SYNC_NAMESPACE = uuid.UUID("3833041b-4f23-48bb-94ff-89ded4c26a56")
SYNC_CLIENT_ID = "componentwarehouse-desktop-v1"
SYNC_CHUNK_SIZE = 4 * 1024 * 1024
CONFLICT_WINDOW_SECONDS = 5 * 60

SYNC_TABLE_NAMES = {
    "categories",
    "users",
    "components",
    "component_identity_registry",
    "component_price_entries",
    "inventory_lots",
    "stock_movements_v2",
    "projects",
    "project_boards",
    "project_bom_import_batches",
    "project_bom_import_rows",
    "project_bom_import_candidates",
    "project_bom_items",
    "project_bom_solder_points",
    "project_assembly_operations",
    "project_assembly_loss_events",
    "project_assembly_placements",
    "project_code_aliases",
    "project_expenses",
    "project_fabrication_revisions",
    "project_fabrication_layers",
    "project_material_cost_events",
    "project_pcb_versions",
    "project_status_events",
    "personal_projects_v2",
    "personal_project_versions_v2",
    "personal_project_status_events_v2",
    "personal_project_bom_items_v2",
    "personal_project_boards_v2",
    "personal_project_solder_points_v2",
    "personal_project_cost_events_v2",
    "personal_project_expenses_v2",
    "personal_project_risks_v2",
    "personal_project_files_v2",
    "personal_project_fabrication_revisions_v2",
    "personal_project_fabrication_layers_v2",
    "personal_project_assembly_placements_v2",
    "personal_project_assembly_operations_v2",
    "custom_label_templates",
    "custom_label_assets",
    "eda_assets",
    "eda_attachment_links",
    "eda_component_bindings",
    "eda_footprints",
    "eda_libraries",
    "eda_library_versions",
    "eda_symbols",
    "eda_verifications",
    "supplier_parts",
    "purchase_orders",
    "purchase_lines",
    "purchase_receipts",
    "risk_issues",
}

EXCLUDED_SYNC_FIELDS = {
    "password_hash",
    "ai_summary",
    "ai_usage",
    "ai_risk_notes",
    "ai_pcb_notes",
    "ai_substitutes",
    "ai_tags",
    "ai_confidence",
    "ai_cache_key",
    "ai_status",
    "ai_error",
    "ai_updated_at",
    "ai_bom_analysis",
    "ai_bom_cache_key",
    "ai_bom_updated_at",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(value: datetime | None = None) -> str:
    aware = value or datetime.now(timezone.utc)
    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return utc_now()
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        raise ValueError("二进制字段不能直接进入同步负载")
    return str(value)


def stable_entity_uid(owner_user_id: int, entity_type: str, local_id: str | int) -> str:
    raw = str(local_id)
    try:
        parsed = uuid.UUID(raw)
        if str(parsed) == raw.lower():
            return str(parsed)
    except ValueError:
        pass
    return str(uuid.uuid5(SYNC_NAMESPACE, f"{owner_user_id}:{entity_type}:{raw}"))


def primary_key_column(table: Table):
    columns = list(table.primary_key.columns)
    if len(columns) != 1:
        raise ValueError(f"同步表必须有单一主键：{table.name}")
    return columns[0]


def safe_fields(table: Table, fields: dict) -> dict:
    allowed = {column.name for column in table.columns} - EXCLUDED_SYNC_FIELDS
    allowed -= {primary_key_column(table).name}
    return {key: value for key, value in fields.items() if key in allowed}


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def loads(value: str | None, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed
    except (TypeError, json.JSONDecodeError):
        return fallback


def data_root_for_database(database_path: Path) -> Path:
    return database_path.resolve().parent
