from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO
import re
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import or_
from sqlalchemy.orm import Session
import xlrd

from ..models import Component
from .component_normalizer import clean_lcsc_keyword
from .mimo_ai import component_to_dict, lcsc_search_url


HEADER_ALIASES = {
    "no": ["no.", "no", "序号", "编号"],
    "quantity": ["quantity", "qty", "数量", "用量"],
    "comment": ["comment", "备注", "注释", "描述"],
    "designator": ["designator", "refdes", "位号", "器件位号"],
    "footprint": ["footprint", "package", "封装", "封装格式"],
    "value": ["value", "参数", "阻值", "容值"],
    "manufacturer_part": ["manufacturer part", "mpn", "型号", "制造商型号", "商品型号"],
    "manufacturer": ["manufacturer", "brand", "品牌", "制造商"],
    "supplier_part": ["supplier part", "lcsc", "lcsc part", "立创编号", "商品编号", "物料编号"],
    "supplier": ["supplier", "供应商"],
    "category": ["category", "分类", "商品类型"],
    "primary_category": ["primary category", "一级分类", "主分类"],
    "mounting_style": ["mounting style", "安装方式"],
    "layer": ["layer", "层"],
}


@dataclass
class BomRow:
    source_row: int
    data: dict[str, Any]


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return default


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9.\u4e00-\u9fff]+", "", value.lower())


def _normalize_package(value: str | None) -> str:
    text = _normalize(value)
    text = re.sub(r"^[crl]", "", text)
    return text


def _passive_kind(row: dict[str, Any] | None = None, component: Component | None = None) -> str | None:
    parts = []
    if row:
        parts.extend(str(row.get(key) or "") for key in ["primary_category", "category", "comment", "value", "manufacturer_part"])
        designator = str(row.get("designator") or "").strip().upper()
        if re.match(r"^R\d", designator):
            parts.append("电阻")
        elif re.match(r"^C\d", designator):
            parts.append("电容")
        elif re.match(r"^L\d", designator):
            parts.append("电感")
    if component:
        parts.extend([component.category.name if component.category else "", component.name or "", component.parameters or "", component.tags or ""])
    text = " ".join(parts).lower()
    if any(token in text for token in ["电阻", "resistor", "ohm", "Ω", "ω", "kohm", "mohm"]):
        return "resistance"
    if any(token in text for token in ["电容", "capacitor", "uf", "µf", "nf", "pf"]):
        return "capacitance"
    if any(token in text for token in ["电感", "inductor", "uh", "µh", "mh"]):
        return "inductance"
    return None


def _parse_passive_value(text: str | None, kind: str | None) -> float | None:
    if not text or not kind:
        return None
    value = (
        str(text)
        .lower()
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("ω", "ohm")
        .replace("Ω", "ohm")
    )
    if kind == "resistance":
        explicit = re.search(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*(megohm|mohm|kohm|ohm)(?![a-z0-9])", value)
        if explicit:
            number = float(explicit.group(1))
            unit = explicit.group(2)
            if unit in {"mohm", "megohm"}:
                return number * 1_000_000
            if unit == "kohm":
                return number * 1_000
            return number
        code = re.search(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)([rkm])(\d*)(?![a-z0-9])", value)
        if code and "ohm" not in value:
            whole, marker, frac = code.groups()
            number = float(f"{whole}.{frac}") if frac else float(whole)
            return number * {"r": 1, "k": 1_000, "m": 1_000_000}[marker]
        return None
    if kind == "capacitance":
        match = re.search(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*(uf|nf|pf|f)(?![a-z0-9])", value)
        if not match:
            return None
        number = float(match.group(1))
        return number * {"f": 1, "uf": 1e-6, "nf": 1e-9, "pf": 1e-12}[match.group(2)]
    if kind == "inductance":
        match = re.search(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*(uh|mh|nh|h)(?![a-z0-9])", value)
        if not match:
            return None
        number = float(match.group(1))
        return number * {"h": 1, "mh": 1e-3, "uh": 1e-6, "nh": 1e-9}[match.group(2)]
    return None


def _component_passive_value(component: Component, kind: str | None) -> float | None:
    texts = [component.normalized_spec, component.parameters, component.name, component.tags]
    for text in texts:
        parsed = _parse_passive_value(text, kind)
        if parsed is not None:
            return parsed
    return None


def _format_passive_value(value: float, kind: str) -> str:
    if kind == "resistance":
        if value >= 1_000_000:
            return f"{value / 1_000_000:g}MΩ"
        if value >= 1_000:
            return f"{value / 1_000:g}kΩ"
        return f"{value:g}Ω"
    if kind == "capacitance":
        if value >= 1e-6:
            return f"{value / 1e-6:g}uF"
        if value >= 1e-9:
            return f"{value / 1e-9:g}nF"
        return f"{value / 1e-12:g}pF"
    if kind == "inductance":
        if value >= 1e-3:
            return f"{value / 1e-3:g}mH"
        if value >= 1e-6:
            return f"{value / 1e-6:g}uH"
        return f"{value / 1e-9:g}nH"
    return f"{value:g}"


def _values_match(left: float | None, right: float | None, tolerance: float = 0.02) -> bool | None:
    if left is None or right is None:
        return None
    base = max(abs(left), abs(right), 1e-30)
    return abs(left - right) / base <= tolerance


def _header_map(headers: list[str]) -> dict[str, int]:
    normalized = {_normalize(header): idx for idx, header in enumerate(headers)}
    result: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = _normalize(alias)
            if key in normalized:
                result[field] = normalized[key]
                break
    return result


def _all_rows_from_xlsx(content: bytes) -> list[tuple[int, list[Any]]]:
    workbook = load_workbook(BytesIO(content), data_only=True)
    sheet = workbook.active
    return [(idx, list(row)) for idx, row in enumerate(sheet.iter_rows(values_only=True), start=1)]


def _all_rows_from_xls(content: bytes) -> list[tuple[int, list[Any]]]:
    workbook = xlrd.open_workbook(file_contents=content)
    sheet = workbook.sheet_by_index(0)
    return [
        (idx + 1, [sheet.cell_value(idx, col_idx) for col_idx in range(sheet.ncols)])
        for idx in range(sheet.nrows)
    ]


def _all_rows(content: bytes, filename: str | None) -> list[tuple[int, list[Any]]]:
    lower_name = (filename or "").lower()
    if lower_name.endswith(".xls") and not lower_name.endswith(".xlsx"):
        return _all_rows_from_xls(content)
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        return _all_rows_from_xls(content)
    return _all_rows_from_xlsx(content)


def _find_header(rows: list[tuple[int, list[Any]]]) -> tuple[int | None, dict[str, int]]:
    best_row = None
    best_mapping: dict[str, int] = {}
    best_score = 0
    for row_idx, values in rows[:30]:
        mapping = _header_map([_cell_text(value) for value in values])
        score = sum(1 for field in ["quantity", "designator", "footprint", "manufacturer_part", "supplier_part"] if field in mapping)
        if score > best_score:
            best_row = row_idx
            best_mapping = mapping
            best_score = score
        if score >= 3 and "quantity" in mapping:
            return row_idx, mapping
    return (best_row, best_mapping) if best_score >= 2 else (None, {})


def _pick(values: list[Any], mapping: dict[str, int], field: str) -> str:
    col = mapping.get(field)
    if col is None or col >= len(values):
        return ""
    return _cell_text(values[col])


def parse_bom_excel(content: bytes, filename: str | None = None) -> list[BomRow]:
    raw_rows = _all_rows(content, filename)
    header_row, mapping = _find_header(raw_rows)
    if header_row is None:
        return []

    rows: list[BomRow] = []
    for row_idx, values in raw_rows:
        if row_idx <= header_row:
            continue
        if not any(_cell_text(value) for value in values):
            continue
        quantity = _to_int(_pick(values, mapping, "quantity"), 0)
        manufacturer_part = _pick(values, mapping, "manufacturer_part")
        supplier_part = _pick(values, mapping, "supplier_part")
        comment = _pick(values, mapping, "comment")
        value = _pick(values, mapping, "value")
        footprint = _pick(values, mapping, "footprint")
        designator = _pick(values, mapping, "designator")
        if quantity <= 0 or not any([manufacturer_part, supplier_part, comment, value, footprint, designator]):
            continue
        rows.append(
            BomRow(
                source_row=row_idx,
                data={
                    "source_row": row_idx,
                    "no": _pick(values, mapping, "no"),
                    "required_quantity": quantity,
                    "comment": comment,
                    "designator": designator,
                    "footprint": footprint,
                    "value": value,
                    "manufacturer_part": manufacturer_part,
                    "manufacturer": _pick(values, mapping, "manufacturer"),
                    "supplier_part": supplier_part,
                    "supplier": _pick(values, mapping, "supplier"),
                    "category": _pick(values, mapping, "category"),
                    "primary_category": _pick(values, mapping, "primary_category"),
                    "mounting_style": _pick(values, mapping, "mounting_style"),
                    "layer": _pick(values, mapping, "layer"),
                },
            )
        )
    return rows


def _candidate_query(db: Session, row: dict[str, Any], limit: int = 120) -> list[Component]:
    terms = [
        row.get("supplier_part"),
        row.get("manufacturer_part"),
        row.get("value"),
        row.get("comment"),
        row.get("footprint"),
        row.get("primary_category"),
    ]
    filters = []
    for term in terms:
        if not term:
            continue
        like = f"%{term}%"
        filters.append(
            or_(
                Component.lcsc_number.ilike(like),
                Component.model.ilike(like),
                Component.name.ilike(like),
                Component.parameters.ilike(like),
                Component.package.ilike(like),
                Component.tags.ilike(like),
            )
        )
    query = db.query(Component)
    if filters:
        query = query.filter(or_(*filters))
    return query.order_by(Component.quantity.desc(), Component.updated_at.desc()).limit(limit).all()


def _score_match(row: dict[str, Any], component: Component) -> tuple[int, str, list[str]]:
    supplier_part = _normalize(row.get("supplier_part"))
    manufacturer_part = _normalize(row.get("manufacturer_part"))
    value = _normalize(row.get("value") or row.get("comment"))
    footprint = _normalize_package(row.get("footprint"))
    category = _normalize(row.get("primary_category") or row.get("category"))
    passive_kind = _passive_kind(row, component)
    bom_value = _parse_passive_value(" ".join(str(row.get(key) or "") for key in ["value", "comment", "manufacturer_part"]), passive_kind)

    lcsc = _normalize(component.lcsc_number)
    model = _normalize(component.model)
    name = _normalize(component.name)
    params = _normalize(component.parameters)
    package = _normalize_package(component.package)
    tags = _normalize(component.tags)
    component_value = _component_passive_value(component, passive_kind)

    reasons: list[str] = []
    flags: list[str] = []
    score = 0
    if supplier_part and lcsc and supplier_part == lcsc:
        flags.append("编号一致")
        if passive_kind and bom_value is not None and component_value is not None:
            flags.append("标称值一致" if _values_match(bom_value, component_value) else "标称值不一致")
        if footprint and package:
            flags.append("封装一致" if (footprint == package or footprint in package or package in footprint) else "封装不一致")
        return 100, "立创编号精确匹配", flags
    if manufacturer_part and model and manufacturer_part == model:
        score += 88
        reasons.append("型号精确匹配")
    elif manufacturer_part:
        ratio = max(SequenceMatcher(None, manufacturer_part, model).ratio(), SequenceMatcher(None, manufacturer_part, name).ratio())
        score += int(ratio * 45)
        if ratio >= 0.72:
            reasons.append("型号相似")

    haystack = " ".join([name, model, params, tags])
    if value and value in haystack:
        score += 22
        reasons.append("参数/标称值匹配")
    if passive_kind and bom_value is not None and component_value is not None:
        if _values_match(bom_value, component_value):
            score += 28
            flags.append("标称值一致")
        else:
            flags.append("标称值不一致")
            return min(score, 42), f"标称值不一致：BOM {_format_passive_value(bom_value, passive_kind)}，库存 {_format_passive_value(component_value, passive_kind)}", flags
    if footprint and package:
        if footprint == package or footprint in package or package in footprint:
            score += 18
            reasons.append("封装匹配")
            flags.append("封装一致")
        else:
            flags.append("封装不一致")
            if passive_kind:
                return min(score, 42), "封装不一致，基础器件不自动替代", flags
            score += int(SequenceMatcher(None, footprint, package).ratio() * 8)
    if category and category in tags + name + params:
        score += 10
        reasons.append("分类接近")
    if component.quantity > 0:
        score += 4
    return min(score, 99), "，".join(reasons) or "文本相似", flags


def _bom_role(row: dict[str, Any]) -> str:
    text = " ".join(str(row.get(key) or "") for key in ["comment", "value", "manufacturer_part", "category", "primary_category"]).lower()
    if any(word in text for word in ["电容", "capacitor", "uf", "nf", "pf"]):
        return "用于去耦、滤波、储能或时序相关电路，需按位置确认耐压和介质。"
    if any(word in text for word in ["电阻", "resistor", "ohm", "ω", "k"]):
        return "用于限流、分压、上拉下拉或反馈网络，需核对阻值、精度和功耗。"
    if any(word in text for word in ["电感", "inductor", "uh"]):
        return "用于电源储能、滤波或 EMI 抑制，需核对饱和电流和 DCR。"
    if any(word in text for word in ["tvs", "esd", "保护", "浪涌"]):
        return "用于接口或电源保护，需核对工作电压、钳位电压和封装功率。"
    if any(word in text for word in ["usb", "type-c", "connector", "排针", "端子", "插座"]):
        return "用于板级或外部连接，需核对脚位、间距、耐流和机械方向。"
    if any(word in text for word in ["ldo", "dc-dc", "稳压", "电源"]):
        return "用于电源转换或稳压，需核对输入输出范围、电流和热设计。"
    if any(word in text for word in ["mcu", "芯片", "ic", "esp32"]):
        return "用于核心控制或功能实现，需核对供电、封装、外设和启动条件。"
    return "BOM 行用途需结合原理图位号确认，建议先核对型号、封装和参数。"


def _missing_suggestion(row: dict[str, Any]) -> dict[str, Any]:
    keyword = clean_lcsc_keyword(row.get("supplier_part") or row.get("manufacturer_part") or row.get("value") or row.get("comment"))
    description = row.get("manufacturer_part") or row.get("comment") or row.get("value") or "未匹配物料"
    return {
        "description": description,
        "reason": "库存中没有找到足够可靠的匹配项，请按型号/参数/封装确认后采购或手动匹配。",
        "lcsc_search_keyword": keyword,
        "lcsc_search_url": lcsc_search_url(keyword),
    }


def _combination_suggestions(db: Session, row: dict[str, Any], limit: int = 3) -> list[dict[str, str]]:
    kind = _passive_kind(row)
    target = _parse_passive_value(" ".join(str(row.get(key) or "") for key in ["value", "comment", "manufacturer_part"]), kind)
    if not kind or target is None:
        return []
    components = db.query(Component).filter(Component.quantity > 0).order_by(Component.quantity.desc(), Component.id.asc()).limit(300).all()
    candidates = []
    for component in components:
        if _passive_kind(component=component) != kind:
            continue
        value = _component_passive_value(component, kind)
        if value is None:
            continue
        candidates.append((component, value))
    suggestions: list[dict[str, str]] = []
    seen = set()
    for idx, (left_component, left_value) in enumerate(candidates):
        for right_component, right_value in candidates[idx:]:
            modes = []
            if kind in {"resistance", "inductance"}:
                modes.append(("串联", left_value + right_value))
            if kind in {"resistance", "capacitance"} and left_value + right_value > 0:
                parallel = (left_value * right_value) / (left_value + right_value) if kind == "resistance" else left_value + right_value
                modes.append(("并联", parallel))
            for mode, combined in modes:
                if not _values_match(target, combined, tolerance=0.03):
                    continue
                key = tuple(sorted([left_component.id, right_component.id]) + [mode])
                if key in seen:
                    continue
                seen.add(key)
                left_label = left_component.model or left_component.name
                right_label = right_component.model or right_component.name
                suggestions.append(
                    {
                        "description": f"{left_label} + {right_label} {mode} ≈ {_format_passive_value(target, kind)}",
                        "reason": "组合替代仅作临时建议，需核对精度、功耗/纹波、温漂、空间和可靠性。",
                    }
                )
                if len(suggestions) >= limit:
                    return suggestions
    return suggestions


def match_bom_rows(db: Session, rows: list[BomRow], top_n: int = 5) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        matches = []
        seen = set()
        for component in _candidate_query(db, row.data):
            if component.id in seen:
                continue
            seen.add(component.id)
            score, reason, flags = _score_match(row.data, component)
            if score < 18:
                continue
            available = component.quantity
            required = row.data["required_quantity"]
            matches.append(
                {
                    "component": component_to_dict(component),
                    "score": score,
                    "match_type": "exact" if score >= 95 else "approximate",
                    "reason": reason,
                    "flags": flags,
                    "available_quantity": available,
                    "shortage_quantity": max(0, required - available),
                    "enough": available >= required,
                }
            )
        matches.sort(key=lambda item: item["score"], reverse=True)
        top_matches = matches[:top_n]
        has_supplier_part = bool(str(row.data.get("supplier_part") or "").strip())
        exact_lcsc_match = bool(top_matches and top_matches[0]["score"] >= 100 and "编号一致" in top_matches[0].get("flags", []))
        selected = top_matches[0]["component"]["id"] if top_matches and top_matches[0]["score"] >= 45 else None
        if exact_lcsc_match:
            status = "exact_lcsc"
        elif has_supplier_part:
            selected = None
            status = "supplier_missing"
        elif top_matches and top_matches[0]["score"] >= 95:
            status = "exact"
        elif selected:
            status = "approximate"
        elif top_matches:
            status = "low_confidence"
        else:
            status = "missing"
        missing_suggestion = _missing_suggestion(row.data) if status in {"missing", "low_confidence", "supplier_missing"} else None
        alternatives = _combination_suggestions(db, row.data) if status in {"missing", "low_confidence", "supplier_missing"} else []
        if status == "supplier_missing" and missing_suggestion:
            missing_suggestion["reason"] = "BOM 指定立创编号未在库存中找到；如不替换，采购时优先购买 BOM 中的该立创编号。"
            similar = []
            for match in top_matches[:3]:
                component = match["component"]
                label = component.get("model") or component.get("name") or f"库存 #{component.get('id')}"
                similar.append(
                    {
                        "description": f"库内相似：{label}，{match['score']}%（{match['reason']}）",
                        "reason": "编号不同，仅作为避免重复采购的替换提醒，需人工确认参数、封装和风险。",
                    }
                )
            alternatives = similar + alternatives
        if missing_suggestion and alternatives:
            missing_suggestion["alternatives"] = alternatives
        result.append(
            {
                **row.data,
                "status": status,
                "selected_component_id": selected,
                "match_confidence": top_matches[0]["score"] if top_matches else 0,
                "matches": top_matches[: max(3, top_n)],
                "role": _bom_role(row.data),
                "missing_suggestion": missing_suggestion,
                "lcsc_search_url": lcsc_search_url(row.data.get("supplier_part") or row.data.get("manufacturer_part") or row.data.get("value")),
                "ai_reason": (
                    "编号一致自动匹配。"
                    if status == "exact_lcsc"
                    else "BOM 指定立创编号未入库，候选库存仅作为同值/相似替换提醒。"
                    if status == "supplier_missing"
                    else "规则匹配生成，低置信行可由 AI 补充判断。"
                ),
            }
        )
    return result
