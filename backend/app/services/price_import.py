from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any

from .excel_import import _all_rows, _cell_text


MONEY_QUANTUM = Decimal("0.000001")
SHIPPED_STATUS = "已发货"

PRICE_HEADER_ALIASES = {
    "order_number": ["订单编号", "订单号"],
    "order_status": ["订单状态", "状态"],
    "ordered_at": ["下单时间", "购买时间"],
    "lcsc_number": ["商品编号", "立创编号", "立创 ID", "LCSC编号"],
    "name": ["商品名称", "物料名称", "名称"],
    "model": ["商品型号", "型号", "规格型号"],
    "quantity": ["订购数量", "购买数量", "数量"],
    "unit_price": ["单价（人民币含税）", "单价(人民币含税)", "含税单价", "单价"],
    "subtotal": ["小计金额（人民币含税）", "小计金额(人民币含税)", "含税小计", "小计金额", "小计"],
}


class PriceStatementError(ValueError):
    pass


@dataclass
class PriceStatementRow:
    order_number: str
    order_status: str
    ordered_at: str | None
    lcsc_number: str
    name: str | None
    model: str | None
    quantity: int
    merchandise_total: Decimal
    allocated_shipping: Decimal
    landed_total: Decimal
    source_row: int

    @property
    def key(self) -> tuple[str, str]:
        return self.order_number, self.lcsc_number

    @property
    def is_shipped(self) -> bool:
        return self.order_status == SHIPPED_STATUS

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_number": self.order_number,
            "order_status": self.order_status,
            "ordered_at": self.ordered_at,
            "lcsc_number": self.lcsc_number,
            "name": self.name,
            "model": self.model,
            "quantity": self.quantity,
            "merchandise_total": self.merchandise_total,
            "allocated_shipping": self.allocated_shipping,
            "landed_total": self.landed_total,
            "source_row": self.source_row,
        }


@dataclass
class ParsedPriceStatement:
    rows: list[PriceStatementRow]
    warnings: list[str]
    item_row_count: int
    shipped_item_row_count: int
    canceled_item_row_count: int
    shipping_row_count: int
    shipped_merchandise_total: Decimal
    shipped_shipping_total: Decimal

    @property
    def shipped_landed_total(self) -> Decimal:
        return money(self.shipped_merchandise_total + self.shipped_shipping_total)


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _decimal(value: Any) -> Decimal | None:
    text = _cell_text(value).replace(",", "").replace("¥", "").replace("￥", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _positive_int(value: Any) -> int:
    number = _decimal(value)
    if number is None or number <= 0 or number != number.to_integral_value():
        return 0
    return int(number)


def _normalize_header(value: Any) -> str:
    return re.sub(r"\s+", "", _cell_text(value)).lower()


def _header_mapping(values: list[Any]) -> dict[str, int]:
    normalized = {_normalize_header(value): index for index, value in enumerate(values)}
    mapping: dict[str, int] = {}
    for field, aliases in PRICE_HEADER_ALIASES.items():
        for alias in aliases:
            if _normalize_header(alias) in normalized:
                mapping[field] = normalized[_normalize_header(alias)]
                break
    return mapping


def _find_header(rows: list[tuple[int, list[Any]]]) -> tuple[int, dict[str, int]]:
    required = {"order_number", "order_status", "lcsc_number", "quantity", "subtotal"}
    best: tuple[int, dict[str, int]] | None = None
    for row_number, values in rows[:30]:
        mapping = _header_mapping(values)
        if best is None or len(mapping) > len(best[1]):
            best = (row_number, mapping)
        if required.issubset(mapping):
            return row_number, mapping
    missing = sorted(required - set(best[1] if best else {}))
    raise PriceStatementError(f"无法识别立创对账单表头，缺少字段：{', '.join(missing)}")


def _pick(values: list[Any], mapping: dict[str, int], field: str) -> Any:
    index = mapping.get(field)
    return values[index] if index is not None and index < len(values) else None


def _lcsc_number(value: Any) -> str:
    text = _cell_text(value).upper().replace(" ", "")
    return text if re.fullmatch(r"C\d+", text) else ""


def _allocate_shipping(rows: list[PriceStatementRow], shipping_by_order: dict[str, Decimal]) -> None:
    shipped_by_order: dict[str, list[PriceStatementRow]] = {}
    for row in rows:
        if row.is_shipped and row.quantity > 0 and row.merchandise_total >= 0:
            shipped_by_order.setdefault(row.order_number, []).append(row)

    for order_number, fee in shipping_by_order.items():
        candidates = shipped_by_order.get(order_number, [])
        merchandise_total = sum((row.merchandise_total for row in candidates), Decimal("0"))
        if not candidates or merchandise_total <= 0:
            continue
        allocated = Decimal("0")
        ordered = sorted(candidates, key=lambda row: (row.lcsc_number, row.source_row))
        for index, row in enumerate(ordered):
            share = money(fee - allocated) if index == len(ordered) - 1 else money(fee * row.merchandise_total / merchandise_total)
            row.allocated_shipping = share
            row.landed_total = money(row.merchandise_total + share)
            allocated += share


def parse_price_statement(content: bytes, filename: str | None = None) -> ParsedPriceStatement:
    raw_rows = _all_rows(content, filename)
    if not raw_rows:
        raise PriceStatementError("对账单为空")
    header_row, mapping = _find_header(raw_rows)
    warnings: list[str] = []
    aggregated: dict[tuple[str, str], PriceStatementRow] = {}
    shipping_by_order: dict[str, Decimal] = {}
    current_order = ""
    current_status = ""
    item_row_count = 0
    shipped_item_row_count = 0
    canceled_item_row_count = 0
    shipping_row_count = 0

    for source_row, values in raw_rows:
        if source_row <= header_row or not any(_cell_text(value) for value in values):
            continue
        order_number = _cell_text(_pick(values, mapping, "order_number"))
        order_status = _cell_text(_pick(values, mapping, "order_status"))
        name = _cell_text(_pick(values, mapping, "name"))
        lcsc_number = _lcsc_number(_pick(values, mapping, "lcsc_number"))
        subtotal = _decimal(_pick(values, mapping, "subtotal"))

        if order_number:
            current_order = order_number
            current_status = order_status
        if "配送费" in name and not lcsc_number:
            if not current_order or subtotal is None:
                warnings.append(f"第 {source_row} 行配送费缺少可归属的前序订单，已跳过")
                continue
            shipping_row_count += 1
            if current_status == SHIPPED_STATUS:
                shipping_by_order[current_order] = money(shipping_by_order.get(current_order, Decimal("0")) + subtotal)
            continue

        if not lcsc_number and not name:
            continue
        if not lcsc_number:
            continue
        if not order_number or not lcsc_number:
            warnings.append(f"第 {source_row} 行订单号或 C 编号无效，已跳过")
            continue
        quantity = _positive_int(_pick(values, mapping, "quantity"))
        if quantity <= 0:
            warnings.append(f"第 {source_row} 行 {lcsc_number} 采购数量无效，已跳过")
            continue
        if subtotal is None:
            unit_price = _decimal(_pick(values, mapping, "unit_price"))
            subtotal = unit_price * quantity if unit_price is not None else None
        if subtotal is None or subtotal < 0:
            warnings.append(f"第 {source_row} 行 {lcsc_number} 含税小计无效，已跳过")
            continue
        item_row_count += 1
        if order_status == SHIPPED_STATUS:
            shipped_item_row_count += 1
        else:
            canceled_item_row_count += 1
        ordered_at = _cell_text(_pick(values, mapping, "ordered_at")) or None
        key = (order_number, lcsc_number)
        if key in aggregated:
            existing = aggregated[key]
            if existing.order_status != order_status:
                raise PriceStatementError(f"订单 {order_number} 的 {lcsc_number} 存在冲突状态")
            existing.quantity += quantity
            existing.merchandise_total = money(existing.merchandise_total + subtotal)
            existing.landed_total = existing.merchandise_total
            existing.source_row = min(existing.source_row, source_row)
        else:
            merchandise_total = money(subtotal)
            aggregated[key] = PriceStatementRow(
                order_number=order_number,
                order_status=order_status,
                ordered_at=ordered_at,
                lcsc_number=lcsc_number,
                name=name or None,
                model=_cell_text(_pick(values, mapping, "model")) or None,
                quantity=quantity,
                merchandise_total=merchandise_total,
                allocated_shipping=money(0),
                landed_total=merchandise_total,
                source_row=source_row,
            )

    rows = sorted(aggregated.values(), key=lambda row: (row.order_number, row.lcsc_number))
    _allocate_shipping(rows, shipping_by_order)
    shipped_merchandise_total = money(sum((row.merchandise_total for row in rows if row.is_shipped), Decimal("0")))
    shipped_shipping_total = money(sum((row.allocated_shipping for row in rows if row.is_shipped), Decimal("0")))
    if not rows:
        raise PriceStatementError("对账单中没有可识别的立创商品明细")
    return ParsedPriceStatement(
        rows=rows,
        warnings=warnings,
        item_row_count=item_row_count,
        shipped_item_row_count=shipped_item_row_count,
        canceled_item_row_count=canceled_item_row_count,
        shipping_row_count=shipping_row_count,
        shipped_merchandise_total=shipped_merchandise_total,
        shipped_shipping_total=shipped_shipping_total,
    )
