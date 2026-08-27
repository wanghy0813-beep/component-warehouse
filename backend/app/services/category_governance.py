from sqlalchemy.orm import Session

from ..models import Category, Component
from .hardware_categories import classify_hardware_category


ORDER_CATEGORY_ALIASES = {
    "电阻器": "贴片电阻", "贴片电阻": "贴片电阻", "插件电阻": "直插/采样电阻",
    "采样电阻": "直插/采样电阻", "电位器": "直插/采样电阻",
    "电容器": "MLCC", "贴片电容": "MLCC", "陶瓷电容": "MLCC", "插件电容": "电解/固态",
    "电解电容": "电解/固态", "电感器": "电感/晶振", "磁珠": "电感/晶振", "晶振": "电感/晶振",
    "振荡器": "电感/晶振", "发光二极管": "二极管/保护", "led": "二极管/保护",
    "保护器件": "二极管/保护", "晶体管": "BJT/MOS", "mosfet": "BJT/MOS", "三极管": "BJT/MOS",
    "电源": "电源IC", "电源芯片": "电源IC", "模拟芯片": "模拟IC", "接口芯片": "数字/接口IC",
    "集成电路": "数字/接口IC", "ic": "数字/接口IC", "连接器": "USB/XT/线束",
    "接插件": "USB/XT/线束", "开发板": "模块/开发板/显示", "显示模块": "模块/开发板/显示",
    "功能模块": "模块/开发板/显示", "通信模块": "模块/开发板/显示", "设备": "结构/工具/电池",
    "结构件": "结构/工具/电池", "机电件": "开关/机电", "开关": "开关/机电",
}

LEGACY_ORDER_CATEGORY_ALIASES = {
    "电阻器": "电阻", "贴片电阻": "电阻", "插件电阻": "电阻", "采样电阻": "电阻",
    "电容器": "电容", "贴片电容": "电容", "陶瓷电容": "电容", "插件电容": "电容",
    "电感器": "电感", "磁珠": "电感", "发光二极管": "二极管", "led": "二极管",
    "晶体管": "三极管", "mosfet": "MOS管", "集成电路": "芯片", "ic": "芯片",
    "连接器": "连接件", "接插件": "连接件", "晶振": "时钟源", "振荡器": "时钟源",
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
    if alias_name in available_names:
        return alias_name
    legacy_name = LEGACY_ORDER_CATEGORY_ALIASES.get(normalized)
    if legacy_name in available_names:
        return legacy_name
    classified, _ = classify_hardware_category(value)
    return classified if classified in available_names else None


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
