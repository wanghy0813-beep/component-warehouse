from sqlalchemy.orm import Session

from ..models import Category, Component


ORDER_CATEGORY_ALIASES = {
    "电阻器": "电阻",
    "贴片电阻": "电阻",
    "插件电阻": "电阻",
    "电容器": "电容",
    "贴片电容": "电容",
    "插件电容": "电容",
    "电感器": "电感",
    "磁珠": "电感",
    "发光二极管": "二极管",
    "led": "二极管",
    "晶体管": "三极管",
    "mosfet": "MOS管",
    "集成电路": "芯片",
    "ic": "芯片",
    "连接器": "连接件",
    "接插件": "连接件",
    "晶振": "时钟源",
    "振荡器": "时钟源",
}


def normalized_category_text(value: str | None) -> str:
    text = str(value or "").strip()
    return "".join(character for character in text if character not in {" ", "\t", "\r", "\n", "-", "_"}).casefold()


def canonical_order_category_name(value: str | None, available_names: set[str]) -> str | None:
    normalized = normalized_category_text(value)
    if not normalized:
        return None
    exact = {normalized_category_text(name): name for name in available_names}
    if normalized in exact:
        return exact[normalized]
    alias_name = ORDER_CATEGORY_ALIASES.get(normalized)
    return alias_name if alias_name in available_names else None


def category_from_order_text(db: Session, value: str | None) -> Category | None:
    categories = db.query(Category).all()
    category_name = canonical_order_category_name(value, {item.name for item in categories})
    return next((item for item in categories if item.name == category_name), None)


def component_has_trusted_order_category(component: Component) -> bool:
    if not component.category or component.category.name in {"其他", "未分类"}:
        return False
    source = str(component.source or "").casefold()
    return any(marker in source for marker in ("立创", "订单", "lcsc"))


def ai_category_allowed(component: Component, result: dict) -> bool:
    if component_has_trusted_order_category(component):
        return False
    confidence = str(result.get("confidence") or "").strip().casefold()
    requires_confirmation = bool(result.get("requires_confirmation"))
    return confidence in {"high", "0.9", "0.95", "1", "1.0"} and not requires_confirmation
