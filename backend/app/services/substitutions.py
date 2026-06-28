import re
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..models import Component, ProjectBomItem
from .bom_match import (
    _component_passive_value,
    _format_passive_value,
    _normalize,
    _normalize_package,
    _passive_kind,
    _values_match,
)
from .inventory import reserved_quantities


def _component_scope_filter(query, source: Component):
    if source.owner_user_id is not None:
        query = query.filter(Component.owner_user_id == source.owner_user_id)
    return query


def _component_category_key(component: Component) -> str:
    if component.category_id:
        return f"id:{component.category_id}"
    return f"name:{_normalize(component.category.name if component.category else '')}"


def _component_value_key(component: Component, kind: str | None) -> str:
    parsed = _component_passive_value(component, kind)
    if parsed is not None and kind:
        return f"{kind}:{_format_passive_value(parsed, kind).lower()}"
    return _normalize(component.normalized_spec or component.parameters or component.name)


def _voltage_values(component: Component) -> list[float]:
    text = " ".join(
        str(value or "")
        for value in [
            component.normalized_spec,
            component.parameters,
            component.name,
            component.model,
            component.tags,
            component.ai_tags,
        ]
    )
    values: list[float] = []
    for match in re.finditer(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*v(?![a-z0-9])", text.lower()):
        try:
            number = float(match.group(1))
        except ValueError:
            continue
        if 0 < number <= 2000 and number not in values:
            values.append(number)
    return values


def _model_family_flag(source: Component, candidate: Component) -> str | None:
    left = _normalize(source.model or source.name)
    right = _normalize(candidate.model or candidate.name)
    if not left or not right:
        return None
    prefix = 0
    for a, b in zip(left, right):
        if a != b:
            break
        prefix += 1
    if prefix >= 5:
        return "型号系列相近"
    return None


def _minimal_component(component: Component, available: int) -> dict:
    return {
        "id": component.id,
        "warehouse_code": component.warehouse_code,
        "name": component.name,
        "model": component.model,
        "manufacturer": component.manufacturer,
        "category_id": component.category_id,
        "category": component.category,
        "parameters": component.parameters,
        "package": component.package,
        "quantity": int(component.quantity or 0),
        "available_quantity": available,
        "lcsc_number": component.lcsc_number,
        "tags": component.tags,
        "normalized_spec": component.normalized_spec,
        "ai_summary": component.ai_summary,
        "ai_tags": component.ai_tags,
    }


def _candidate_matches(source: Component, candidate: Component, kind: str | None, source_value: float | None, source_value_key: str) -> tuple[bool, list[str]]:
    flags: list[str] = []
    if _component_category_key(source) != _component_category_key(candidate):
        return False, flags
    flags.append("同类别")

    source_package = _normalize_package(source.package)
    candidate_package = _normalize_package(candidate.package)
    if not source_package or not candidate_package or source_package != candidate_package:
        return False, flags
    flags.append("同封装")

    candidate_value = _component_passive_value(candidate, kind)
    if source_value is not None and candidate_value is not None and kind:
        if not _values_match(source_value, candidate_value, tolerance=0.01):
            return False, flags
        flags.append(f"同标称值 {_format_passive_value(source_value, kind)}")
        return True, flags

    if source_value_key and source_value_key == _component_value_key(candidate, kind):
        flags.append("同规格值")
        return True, flags

    return False, flags


def _substitution_warning(source: Component, candidate: Component) -> tuple[list[str], int]:
    warnings: list[str] = []
    voltage_rank = 1
    source_voltages = _voltage_values(source)
    candidate_voltages = _voltage_values(candidate)
    if source_voltages and candidate_voltages:
        source_voltage = max(source_voltages)
        candidate_voltage = max(candidate_voltages)
        if candidate_voltage < source_voltage:
            warnings.append(f"耐压更低：原 {source_voltage:g}V，候选 {candidate_voltage:g}V，必须确认电路最高电压")
            voltage_rank = 0
        elif candidate_voltage > source_voltage:
            warnings.append(f"耐压不同：原 {source_voltage:g}V，候选 {candidate_voltage:g}V，仍需确认尺寸、介质和降额")
            voltage_rank = 2
        else:
            voltage_rank = 3
    else:
        warnings.append("未能完整确认耐压/功率等限制参数，请人工核对数据手册或订单参数")
    return warnings, voltage_rank


def substitution_suggestions_for_bom_items(
    db: Session,
    items: Iterable[ProjectBomItem],
    reserved_by_component: dict[int, int] | None = None,
    *,
    limit: int = 3,
) -> dict[int, list[dict]]:
    reserved_by_component = reserved_by_component or {}
    result: dict[int, list[dict]] = {}
    source_items = [item for item in items if item.component]
    if not source_items:
        return result

    for item in source_items:
        source = item.component
        required = int(item.required_quantity or 0)
        solder_points = list(getattr(item, "solder_points", []) or [])
        pending_count = sum(1 for point in solder_points if not getattr(point, "soldered", False))
        own_reserved = pending_count if solder_points and (item.status or "reserved") == "reserved" else required
        reserved_by_others = max(0, int(reserved_by_component.get(source.id, 0)) - own_reserved)
        source_available_for_item = max(0, int(source.quantity or 0) - reserved_by_others)
        if source_available_for_item >= required and source_available_for_item > 0:
            continue

        kind = _passive_kind(component=source)
        source_value = _component_passive_value(source, kind)
        source_value_key = _component_value_key(source, kind)
        package_key = _normalize_package(source.package)
        if not package_key or (source_value is None and not source_value_key):
            continue

        query = (
            db.query(Component)
            .options(joinedload(Component.category))
            .filter(Component.id != source.id, Component.revoked_at.is_(None), Component.quantity > 0)
            .order_by(Component.quantity.desc(), Component.updated_at.desc())
        )
        if source.category_id:
            query = query.filter(Component.category_id == source.category_id)
        elif source.category:
            query = query.filter(Component.category.has(name=source.category.name))
        query = _component_scope_filter(query, source)
        candidates = query.limit(300).all()
        candidate_ids = [candidate.id for candidate in candidates]
        candidate_reserved = reserved_quantities(db, candidate_ids) if candidate_ids else {}

        suggestions: list[tuple[int, int, dict]] = []
        for candidate in candidates:
            available = max(0, int(candidate.quantity or 0) - int(candidate_reserved.get(candidate.id, 0)))
            if available <= 0:
                continue
            matches, flags = _candidate_matches(source, candidate, kind, source_value, source_value_key)
            if not matches:
                continue
            warnings, voltage_rank = _substitution_warning(source, candidate)
            family_flag = _model_family_flag(source, candidate)
            if family_flag:
                flags.append(family_flag)
            suggestions.append(
                (
                    voltage_rank,
                    available,
                    {
                        "component": _minimal_component(candidate, available),
                        "available_quantity": available,
                        "reason": "、".join(flags),
                        "warnings": warnings,
                        "auto_replace": False,
                    },
                )
            )
        result[item.id] = [
            suggestion
            for _, _, suggestion in sorted(suggestions, key=lambda row: (row[0], row[1]), reverse=True)[:limit]
        ]
    return result
