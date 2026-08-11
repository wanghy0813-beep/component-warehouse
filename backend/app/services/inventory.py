import json
import re

from sqlalchemy.orm import Session, joinedload

from ..models import Component, ProjectBomItem


PASSIVE_DIMENSIONS = {
    "电阻": "resistance",
    "电容": "capacitance",
    "电感": "inductance",
}

STANDARD_CATEGORY_ORDER = [
    "电阻",
    "电容",
    "电感",
    "二极管",
    "三极管",
    "MOS管",
    "芯片",
    "电源",
    "接口",
    "开关",
    "开发板",
    "设备",
    "保护器件",
    "传感器",
    "连接件",
    "时钟源",
    "功能模块",
    "通信模块",
    "显示模块",
    "机电件",
    "散热件",
    "结构件",
]
STANDARD_CATEGORY_RANK = {name: index for index, name in enumerate(STANDARD_CATEGORY_ORDER)}

TRANSIT_LOCATION_LABELS = {
    "运输中",
    "在途",
    "快递中",
    "配送中",
    "物流中",
    "物流运输中",
}
TRANSIT_STOCK_STATUSES = {
    "in_transit",
    "transit",
    "shipping",
    "shipped",
    "运输中",
    "在途",
}


def normalize_inventory_location(value: str | None) -> str | None:
    """Inventory locations describe where an owned item is stored, not its delivery stage."""
    text = str(value or "").strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    return None if compact in TRANSIT_LOCATION_LABELS else text


def normalize_inventory_status(value: str | None, *, location: str | None = None) -> str:
    status = str(value or "in_stock").strip() or "in_stock"
    compact_status = re.sub(r"\s+", "", status).lower()
    compact_location = re.sub(r"\s+", "", str(location or "").strip())
    if compact_status in TRANSIT_STOCK_STATUSES:
        return "in_stock"
    if compact_location in TRANSIT_LOCATION_LABELS and compact_status in {"in_stock", "pending", "pending_purchase"}:
        return "in_stock"
    return status


def is_durable_equipment(component) -> bool:
    category = getattr(component, "category", None)
    category_name = category.get("name") if isinstance(category, dict) else getattr(category, "name", category)
    warehouse_code = str(getattr(component, "warehouse_code", "") or "").strip().upper()
    return str(category_name or "").strip() == "设备" or warehouse_code.startswith("EQP-")


def equipment_occupied_quantity(component) -> int:
    if not is_durable_equipment(component):
        return 0
    quantity = max(0, int(getattr(component, "quantity", 0) or 0))
    return min(quantity, max(0, int(getattr(component, "occupied_quantity", 0) or 0)))


def component_available_quantity(component, reserved: int = 0) -> int:
    quantity = max(0, int(getattr(component, "quantity", 0) or 0))
    return max(0, quantity - max(0, int(reserved or 0)) - equipment_occupied_quantity(component))


def category_sort_key(category_name: str | None):
    name = str(category_name or "").strip()
    if not name or name == "未分类":
        return (3, 0, "")
    if name == "其他":
        return (2, 0, name)
    if name in STANDARD_CATEGORY_RANK:
        return (0, STANDARD_CATEGORY_RANK[name], name)
    return (1, 0, name.casefold())


def reserved_quantities(db: Session, component_ids: list[int] | None = None) -> dict[int, int]:
    query = (
        db.query(ProjectBomItem)
        .options(joinedload(ProjectBomItem.solder_points))
        .filter(ProjectBomItem.status == "reserved")
    )
    if component_ids is not None:
        clean_ids = [int(item) for item in component_ids if item is not None]
        if not clean_ids:
            return {}
        query = query.filter(ProjectBomItem.component_id.in_(clean_ids))
    reserved: dict[int, int] = {}
    for item in query.all():
        points = getattr(item, "solder_points", []) or []
        remaining = (
            sum(1 for point in points if not point.soldered)
            if points
            else int(item.required_quantity or 0)
        )
        reserved[item.component_id] = reserved.get(item.component_id, 0) + remaining
    return reserved


def _json_value(value):
    if not value or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _candidate_text(component) -> str:
    values = [
        getattr(component, "normalized_spec", None),
        getattr(component, "parameters", None),
        getattr(component, "model", None),
        getattr(component, "name", None),
    ]
    usage = _json_value(getattr(component, "ai_usage", None))
    if isinstance(usage, dict):
        for spec in usage.get("key_specs") or []:
            if isinstance(spec, dict):
                values.append(spec.get("value"))
    return " ".join(str(value or "") for value in values).replace("μ", "u").replace("µ", "u")


def parse_passive_si_value(component, category_name: str | None = None) -> float | None:
    category = category_name or getattr(getattr(component, "category", None), "name", None) or getattr(component, "category", None)
    category_text = str(category or "")
    dimension = next(
        (value for keyword, value in PASSIVE_DIMENSIONS.items() if keyword in category_text),
        None,
    )
    if not dimension:
        return None
    text = _candidate_text(component)
    if dimension == "resistance":
        match = re.search(
            r"(?<![\w.])(\d+(?:\.\d+)?)\s*([mMkK])?\s*(?:Ω|(?i:ohms?|R))(?![A-Za-z])",
            text,
        )
        if not match:
            return None
        prefix = match.group(2) or ""
        multiplier = {"m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6}.get(prefix, 1)
        return float(match.group(1)) * multiplier
    if dimension == "capacitance":
        match = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(p|n|u|m)?\s*F\b", text, flags=re.IGNORECASE)
        if not match:
            return None
        multiplier = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3}.get((match.group(2) or "").lower(), 1)
        return float(match.group(1)) * multiplier
    match = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(n|u|m)?\s*H\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    multiplier = {"n": 1e-9, "u": 1e-6, "m": 1e-3}.get((match.group(2) or "").lower(), 1)
    return float(match.group(1)) * multiplier


def component_value_sort_key(component, category_name: str | None = None):
    category = category_name or getattr(getattr(component, "category", None), "name", None) or getattr(component, "category", None) or ""
    parsed = parse_passive_si_value(component, str(category))
    fallback = (
        str(getattr(component, "model", None) or ""),
        str(getattr(component, "name", None) or ""),
        str(getattr(component, "id", "") or ""),
    )
    return (parsed is None, parsed if parsed is not None else float("inf"), *fallback)


def sort_components_by_value(components: list, category_name_getter=None) -> list:
    def key(component):
        category_name = category_name_getter(component) if category_name_getter else None
        category = category_name or getattr(getattr(component, "category", None), "name", None) or getattr(component, "category", None) or ""
        return (
            *category_sort_key(str(category)),
            *component_value_sort_key(component, str(category)),
        )

    return sorted(components, key=key)
