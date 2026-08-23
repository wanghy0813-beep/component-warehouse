import json
import os
import re
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Component
from ..branding import APP_BRAND_NAME
from .component_normalizer import clean_lcsc_keyword


MIMO_API_KEY = os.getenv("AI_API_KEY", os.getenv("MIMO_API_KEY", ""))
MIMO_BASE_URL = os.getenv("AI_BASE_URL", os.getenv("MIMO_BASE_URL", "")).rstrip("/")
MIMO_MODEL = os.getenv("AI_MODEL", os.getenv("MIMO_MODEL", "gpt-compatible-model"))
MIMO_TIMEOUT_SECONDS = float(os.getenv("MIMO_TIMEOUT_SECONDS", "90"))
LCSC_SEARCH_BASE = "https://m.szlcsc.com/pages-list/global-product/index"


class MimoNotConfiguredError(RuntimeError):
    pass


class MimoRequestError(RuntimeError):
    pass


def lcsc_search_url(keyword: str | None) -> str | None:
    keyword = clean_lcsc_keyword(keyword)
    if not keyword:
        return None
    encoded = str(httpx.QueryParams({"keyword": keyword})).split("=", 1)[1]
    return f"{LCSC_SEARCH_BASE}?keyword={encoded}"


def component_to_dict(component: Component) -> dict[str, Any]:
    return {
        "id": component.id,
        "warehouse_code": component.warehouse_code,
        "name": component.name,
        "model": component.model,
        "category": component.category.name if component.category else None,
        "parameters": component.parameters,
        "package": component.package,
        "quantity": component.quantity,
        "source": component.source,
        "lcsc_number": component.lcsc_number,
        "lcsc_search_url": lcsc_search_url(component.lcsc_number or component.model or component.name),
        "tags": component.tags,
        "source_title": getattr(component, "source_title", None),
        "part_family": getattr(component, "part_family", None),
        "count_mode": getattr(component, "count_mode", None),
        "normalized_spec": getattr(component, "normalized_spec", None),
        "status": component.status,
        "location": component.location,
        "remark": component.remark,
        "datasheet_url": component.datasheet_url,
    }


def _json_from_text(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise MimoRequestError("MiMo did not return JSON")
        return json.loads(match.group(0))


def _repair_json_from_text(text: str, error: Exception, max_tokens: int) -> dict[str, Any]:
    payload = {
        "model": MIMO_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是严格的 JSON 修复器。只输出一个合法 JSON object，"
                    "不得解释，不得使用 Markdown，不得新增与原文无关的信息。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "repair_invalid_json",
                        "parse_error": str(error),
                        "invalid_json_text": text,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "max_completion_tokens": max(800, min(max_tokens, 2400)),
        "temperature": 0,
        "top_p": 0.8,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=MIMO_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{MIMO_BASE_URL}/chat/completions",
                headers={"api-key": MIMO_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise MimoRequestError(f"MiMo JSON repair error: {exc.response.status_code} {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise MimoRequestError(f"MiMo JSON repair failed: {exc}") from exc
    data = response.json()
    try:
        repaired = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MimoRequestError("MiMo JSON repair response format is invalid") from exc
    try:
        return _json_from_text(repaired)
    except (json.JSONDecodeError, MimoRequestError) as exc:
        raise MimoRequestError(f"MiMo JSON repair still returned invalid JSON: {exc}") from exc


def _chat_json(messages: list[dict[str, Any]], max_tokens: int = 1600, web_search: str = "off") -> dict[str, Any]:
    if not MIMO_API_KEY or not MIMO_BASE_URL:
        raise MimoNotConfiguredError("AI_API_KEY or AI_BASE_URL is not configured")

    payload = {
        "model": MIMO_MODEL,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "temperature": 0.2,
        "top_p": 0.9,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    if web_search in {"auto", "force"}:
        payload["tools"] = [
            {
                "type": "web_search",
                "max_keyword": 3,
                "force_search": web_search == "force",
                "limit": 3,
            }
        ]
        payload["tool_choice"] = "auto"
    try:
        with httpx.Client(timeout=MIMO_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{MIMO_BASE_URL}/chat/completions",
                headers={"api-key": MIMO_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise MimoRequestError(f"MiMo API error: {exc.response.status_code} {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise MimoRequestError(f"MiMo request failed: {exc}") from exc

    data = response.json()
    try:
        message = data["choices"][0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MimoRequestError("MiMo response format is invalid") from exc
    try:
        result = _json_from_text(content)
    except (json.JSONDecodeError, MimoRequestError) as parse_error:
        result = _repair_json_from_text(content, parse_error, max_tokens)
    annotations = message.get("annotations") or []
    if annotations:
        result["sources"] = [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "site_name": item.get("site_name"),
                "summary": item.get("summary"),
                "publish_time": item.get("publish_time"),
            }
            for item in annotations
            if item.get("url")
        ]
    if data.get("usage", {}).get("web_search_usage"):
        result["web_search_usage"] = data["usage"]["web_search_usage"]
    return result


def _system_prompt() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        f"你是 {APP_BRAND_NAME} 的 PCB 元器件选型助手。"
        f"今天日期是 {today}。"
        "你只能给出建议，不能声明已经修改库存或项目。"
        "优先使用用户已有库存；如果库存没有合适物料，再给出缺失采购建议。"
        "回答必须面向硬件设计决策，不要复述名称、阻值、容值、封装这些用户已经知道的表面信息。"
        "优先给出非显而易见的选型边界、降额、误用场景、布局注意、替代检查项和需要查数据手册的参数。"
        "输出必须是合法 JSON，不要使用 Markdown。"
    )


def suggest_fabrication_mapping(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Return advisory file/column mapping for BOM and placement tables.

    Callers deliberately provide table text only. Gerber artwork, inventory and
    account data must never be included in ``files``.
    """
    return _chat_json(
        [
            {
                "role": "system",
                "content": (
                    "你是 PCB 制造文件映射助手。只分析 BOM/CPL/Pick-and-Place 表格，"
                    "不得猜测元器件替代关系，不得声明已修改项目。输出严格 JSON。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "map_fabrication_tables",
                        "files": files,
                        "required_output": {
                            "bom_file": "string|null",
                            "cpl_file": "string|null",
                            "units": "mm|inch|null",
                            "columns": {
                                "designator": "string|null",
                                "value": "string|null",
                                "model": "string|null",
                                "footprint": "string|null",
                                "x": "string|null",
                                "y": "string|null",
                                "rotation": "string|null",
                                "side": "string|null",
                                "dnp": "string|null",
                            },
                            "confidence": "high|medium|low",
                            "reason": "string",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=2200,
        web_search="off",
    )


def _terms_from_requirement(requirement: str) -> list[str]:
    text = requirement.lower()
    terms = set(re.findall(r"[a-z0-9.+_-]{2,}", text))
    for keyword in ["电源", "稳压", "降压", "升压", "接口", "传感器", "温湿度", "开发板", "保护", "电阻", "电容", "电感"]:
        if keyword in requirement:
            terms.add(keyword)
    expansions = {
        "usb": ["usb", "type-c", "接口"],
        "type-c": ["usb", "type-c", "接口"],
        "esp32": ["esp32", "开发板", "模块"],
        "5v": ["5v", "5V", "电源", "稳压", "dc-dc", "ldo"],
        "3.3v": ["3.3v", "3.3V", "电源", "稳压", "ldo"],
        "温湿度": ["温湿度", "传感器", "sensor"],
        "电源": ["电源", "稳压", "dc-dc", "ldo"],
        "保护": ["保护", "tvs", "esd", "保险丝"],
    }
    for key, values in expansions.items():
        if key in text or key in requirement:
            terms.update(values)
    terms.add(requirement.strip())
    return [term for term in terms if term]


def search_component_candidates(db: Session, requirement: str, limit: int = 20) -> list[Component]:
    terms = _terms_from_requirement(requirement)
    filters = []
    for term in terms:
        like = f"%{term}%"
        filters.append(
            or_(
                Component.name.ilike(like),
                Component.model.ilike(like),
                Component.parameters.ilike(like),
                Component.package.ilike(like),
                Component.tags.ilike(like),
                Component.lcsc_number.ilike(like),
                Component.remark.ilike(like),
            )
        )
    query = db.query(Component)
    if filters:
        query = query.filter(or_(*filters))
    return query.order_by(Component.quantity.desc(), Component.updated_at.desc()).limit(limit).all()


def classify_component(payload: dict[str, Any], categories: list[str]) -> dict[str, Any]:
    return _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "classify_component",
                        "categories": categories,
                        "component": payload,
                        "required_json_schema": {
                            "category": "分类名称，必须来自 categories",
                            "confidence": "0 到 1 的数字",
                            "reason": "简短中文理由",
                            "requires_confirmation": True,
                        },
                        "rules": [
                            "只能从 categories 中选择，禁止创造新类别。",
                            "证据不足时 confidence 必须低于 0.9，并要求人工确认。",
                            "订单原始类别优先于 AI 推断。",
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=800,
    )


def organize_component(component: dict[str, Any], categories: list[str], current_fields: dict[str, Any]) -> dict[str, Any]:
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "normalize_inventory_component",
                        "component": component,
                        "categories": categories,
                        "current_fields": current_fields,
                        "rules": [
                            "你负责补充语义整理，但订单原始类别和系统确定性规则优先于 AI 推断。",
                            "normalized_name 要像个人库存里的短名称，不要保留淘宝/拼多多/1688营销标题。",
                            "如果型号明确，名称应突出型号 + 器件类型/关键规格；不要把整段商品标题原样返回。",
                            "分类必须来自 categories。",
                            "禁止创造新类别；分类证据不足时 confidence 必须为 medium 或 low。",
                            "晶振、无源晶体、有源振荡器、陶瓷谐振器、时钟源归「时钟源」。",
                            "温湿度、TOF/测距、光照、气体、IMU、压力、霍尔、电流检测等传感器芯片、探头或传感器小板归「传感器」。",
                            "风扇、电机、水泵、蜂鸣器、喇叭、电磁铁、继电器模组等把电信号转换为机械/声学/热管理动作的物料归「机电件」；散热片、导热垫、风扇支架等热管理附件归「散热件」。",
                            "成品小板或带外围电路的可直接接线模块，如果不是开发板、传感器、通信模块、电源模块或显示模块，则归「功能模块」。",
                            "Wi-Fi/蓝牙/LoRa/GNSS/蜂窝/射频收发模块归「通信模块」；相关单颗芯片仍归「芯片」。",
                            "OLED/LCD/数码管屏、触摸屏、带驱动显示小板归「显示模块」；单颗 LED 仍归「二极管」。",
                            "外壳、支架、面板、固定座、亚克力板等非电气结构件归「结构件」。",
                            "电源适配器、DC-DC/LDO 模块、充电模块、稳压模块归「电源」；单颗电源管理 IC 也归「电源」。",
                            "Arduino/ESP32/STM32 等可作为主控开发平台的板卡归「开发板」。",
                            "USB/Type-C/HDMI/DP/RJ45 等物理接口连接器归「接口」。",
                            "USB转串口芯片、CAN收发器、以太网PHY等功能芯片归「芯片」，不归「接口」。",
                            "排针、排母、端子、螺丝、螺母、铜柱、线束、跳线归「连接件」，用 part_family 区分细类。",
                            "排针/排母/端子的 normalized_spec 使用统一格式，例如 2.54mm 1x16P、5.08mm 1x3P；无法确认则留空。",
                            "电阻/电容/电感/磁珠的 normalized_spec 只能写核心标称值：如 0Ω、10kΩ、100nF、22µF、10µH、600Ω@100MHz；0805、C0805、R0805、7x6.6mm SMD 这类封装/尺寸必须写 package，绝对不要写 normalized_spec。",
                            "磁珠归「电感」，normalized_name 可写 600Ω@100MHz 磁珠；功率电感归「电感」，normalized_name 可写 10µH 5A 功率电感。",
                            "如果同时含插座类词和接口协议词(如 USB插座、Type-C座)，以协议为准归「接口」。但芯片型号(如 CH340/CP2102/FT232)始终归「芯片」。",
                            "设备/模块类 normalized_name 要一眼能看出用途：型号 + 关键规格 + 类型，例如 SHT31 温湿度传感器、VL53L0X TOF测距模块、5V 3010 风扇、0.96寸 OLED 显示模块。",
                            "设备/模块类 normalized_spec 写最能区分库存的规格组合，例如 5V 3010、I2C 3.3V、0.96寸 I2C、LoRa 433MHz；不确定则留空。",
                            "part_family 可使用 component/module/sensor_module/communication_module/display_module/fan/motor/pump/buzzer/relay/heatsink/enclosure/bracket/cable_assembly/pin_header/screw/nut/standoff/wire/other。",
                            "标签最多 6 个，保留真正帮助检索和选型的词，避免重复封装/型号/分类。",
                            "绝对不要从型号/料号中推测电气参数或封装尺寸，只用 parameters/package 中明确写出的信息。",
                            "不要修改库存数量、位置、立创 ID。",
                        ],
                        "required_json_schema": {
                            "normalized_name": "规范库存名称，短而清楚",
                            "category": "分类名称，必须来自 categories",
                            "parameters": "更规范的参数描述；不确定则沿用或留空",
                            "package": "封装或机械规格；不确定则沿用或留空",
                            "tags": ["最多 6 个标签"],
                            "part_family": "component/module/sensor_module/communication_module/display_module/fan/motor/pump/buzzer/relay/heatsink/enclosure/bracket/cable_assembly/pin_header/screw/nut/standoff/wire/other",
                            "count_mode": "exact/rough/ignore",
                            "normalized_spec": "归一化核心规格。被动件写 0Ω/10kΩ/100nF/10µH/600Ω@100MHz；连接件写 2.54mm 1x16P；模块写 5V 3010/I2C 3.3V。封装尺寸不要写在这里。",
                            "confidence": "high/medium/low",
                            "reason": "为什么这样规范，简短中文",
                            "requires_confirmation": False,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1000,
        web_search="off",
    )
    result["requires_confirmation"] = False
    return result


def normalize_external_component(product_name: str, model_style: str, store_name: str, categories: list[str]) -> dict[str, Any]:
    raw_text = f"{product_name} {model_style}".strip()
    return _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "normalize_external_order_component",
                        "raw_text": raw_text,
                        "store_name": store_name,
                        "categories": categories,
                        "rules": [
                            "从淘宝/1688/拼多多等电商商品标题和款式中提炼出实际的电子元器件信息。",
                            "去掉所有营销词（包邮、现货、正品、原装、100只、编带等），只保留型号和规格。",
                            "如果能识别出标准型号（如 AO3400、CH340G、AMS1117-3.3、0805 100nF），提取为 model。",
                            "normalized_name 格式：型号 + 器件类型/关键规格，例如 AO3400 N-MOSFET、AMS1117-3.3 LDO、0805 100nF 贴片电容。",
                            "分类必须来自 categories。",
                            "绝对不要从型号中推测电气参数，只用标题中明确写出的信息。",
                            "tags 只保留有助于检索的关键词，如器件类型、封装、品牌等。",
                        ],
                        "required_json_schema": {
                            "normalized_name": "规范元器件名称，短而清楚，不含数量信息",
                            "model": "标准型号，如果能识别出来",
                            "category": "分类名称，必须来自 categories",
                            "parameters": "关键参数，如果标题中明确写出",
                            "package": "封装，如果能识别出来",
                            "tags": ["产品参数标签，如阻值/容值/耐压/电流/封装/精度/材质等，不要加店铺名/订单状态等非产品信息"],
                            "extracted_quantity": "从标题中识别出的数量（如50个、100只），没有则留空",
                            "confidence": "high/medium/low",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=600,
        web_search="off",
    )


def organize_lcsc_draft(draft: dict[str, Any], categories: list[str]) -> dict[str, Any]:
    return _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "organize_verified_lcsc_inventory_draft",
                        "verified_lcsc_data": draft,
                        "categories": categories,
                        "rules": [
                            "立创编号、型号、厂商、封装、参数值、数据手册和商品链接均为已核验数据，禁止修改、猜测或替换。",
                            "只负责生成适合中文库存的名称、选择现有分类并整理检索标签。",
                            "name 使用“型号 + 一到两个关键规格 + 器件类型”，例如 LP5907MFX-3.3/NOPB 3.3V 250mA LDO。",
                            "关键规格只能取自 verified_lcsc_data.official_properties，不能从型号数字推测。",
                            "category 必须完全等于 categories 中的一个值；不得创建分类。",
                            "tags 最多 6 个，不重复型号、封装和分类，不包含价格、库存或营销词。",
                        ],
                        "required_json_schema": {
                            "name": "型号 + 关键规格 + 器件类型的中文库存名称",
                            "category": "categories 中的一个分类名称",
                            "tags": ["最多 6 个检索标签"],
                            "confidence": "high/medium/low",
                            "reason": "分类和命名依据，简短中文",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=600,
        web_search="off",
    )


def lookup_lcsc_fallback(parsed: dict[str, Any], categories: list[str]) -> dict[str, Any]:
    return _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "lookup_exact_lcsc_component_after_official_page_failure",
                        "pasted_lcsc_data": parsed,
                        "categories": categories,
                        "rules": [
                            "必须按完整立创编号搜索，并用复制文本中的型号交叉核对。",
                            "只有来源明确出现完全一致的立创编号时 exact_lcsc_match 才能为 true。",
                            "禁止用相似型号、同系列型号或其他品牌兼容型号代替目标器件。",
                            "无法核实时保留复制文本原值，不要猜测型号、厂商、封装、参数或数据手册。",
                            "name 使用“型号 + 一到两个有来源的关键规格 + 器件类型”。",
                            "category 必须完全等于 categories 中的一个分类名称，不得创建分类。",
                            "product_url 必须是立创或 LCSC 的目标商品页；datasheet_url 必须是数据手册而不是商品页。",
                        ],
                        "required_json_schema": {
                            "lcsc_number": "完全一致的立创编号",
                            "exact_lcsc_match": False,
                            "model": "有精确编号来源支持的厂商型号，否则留空",
                            "manufacturer": "有精确编号来源支持的厂商，否则留空",
                            "package": "有精确编号来源支持的封装，否则留空",
                            "description": "有精确编号来源支持的器件描述，否则留空",
                            "parameters": [{"name": "参数名", "value": "带单位的参数值"}],
                            "datasheet_url": "数据手册 URL，否则留空",
                            "product_url": "立创商品 URL，否则留空",
                            "name": "中文库存名称",
                            "category": "categories 中的一个分类名称",
                            "tags": ["最多 6 个检索标签"],
                            "confidence": "high/medium/low",
                            "reason": "精确匹配依据或无法核验的原因",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1000,
        web_search="force",
    )


def analyze_external_order_table(headers: list[str], rows: list[dict[str, Any]], categories: list[str]) -> dict[str, Any]:
    max_tokens = max(1200, min(4200, 900 + len(rows) * 650))
    return _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "analyze_external_order_table_for_component_inventory",
                        "headers": headers,
                        "rows": rows,
                        "categories": categories,
                        "rules": [
                            "这是淘宝、1688、拼多多或其他电商导出的订单表。不同平台列名可能不同，必须结合表头、单元格内容和上下文判断列含义。",
                            "本地不会给你预先标注商品名称、款式、订单数量等字段；你必须自己从整行中识别订单号、店铺、商品标题、规格款式、链接、订单数量、状态等。",
                            "淘宝商品标题经常写一整组可选型号，真正购买的型号通常在规格、款式、颜色分类、SKU、商家编码等列里。必须优先使用这些 SKU/规格字段确定具体型号，商品标题只作为候选范围和上下文。",
                            "如果商品标题中出现多个型号/规格，而 SKU/规格字段只出现其中一个，最终 normalized_name、model、parameters 只能使用 SKU/规格字段对应的那个，不能把标题里的其他可选型号混入。",
                            "如果 SKU/规格字段缺失或无法区分具体型号，confidence 必须为 low，reason 写明“标题含多个型号，规格无法确认”，不要武断选择。",
                            "只输出实际可入库的电子元器件、模块、线材、风扇、传感器、机械小件等库存物料；运费、优惠、售后、空行、店铺汇总、订单备注、物流行必须 skip。",
                            "名称必须是库存规范名，绝对不要保留淘宝营销词、店铺名、包邮、现货、官方、旗舰店、正品、套餐、颜色分类等修饰词。",
                            "必须从商品标题和规格款式中推断实际元器件数量 actual_quantity。比如标题写 100只 且订单数量为 2，则 actual_quantity=200；如果是一个模块买 2 件，则 actual_quantity=2。",
                            "如果数量无法可靠判断，actual_quantity 使用订单购买数量或 1，并把 confidence 降为 medium/low，reason 说明原因。",
                            "分类必须来自 categories；不能确定时用最接近的大类，但 reason 里说明不确定。",
                            "如果原订单存在明确的“分类/品类/物料类型”字段，原样返回 order_category，并优先遵循该字段；AI category 只作为补充建议。",
                            "电阻、电容、电感等基础器件要把标称值放在 normalized_spec 或 name 中，并提取封装、精度、耐压、介质、功率等明确参数。",
                            "磁珠归「电感」，核心规格写阻抗和测试频率，如 600Ω@100MHz 磁珠；功率电感归「电感」，核心规格写 10µH/5A 等。7x6.6mm SMD、0805、C0805 这类封装尺寸只能写 package，不能写 normalized_spec。",
                            "不要从型号内部臆造电气参数；只有标题、规格或表格字段明确出现的信息才能写入 parameters/key specs。",
                        ],
                        "required_json_schema": {
                            "rows": [
                                {
                                    "source_row": "原始 Excel 行号，必须对应输入 rows 的 source_row",
                                    "skip": False,
                                    "skip_reason": "如果 skip=true，说明原因",
                                    "order_number": "订单号，没有则为空",
                                    "order_time": "下单/付款时间，没有则为空",
                                    "store_name": "店铺/卖家，没有则为空",
                                    "product_title": "原始商品标题或最能代表商品的原文",
                                    "sku_text": "规格/款式/颜色分类/SKU/商家编码等决定具体购买型号的原文，优先级高于 product_title",
                                    "product_link": "商品链接，没有则为空",
                                    "order_quantity": "订单购买件数，整数或空",
                                    "component_quantity_per_order": "每件商品包含的元器件数量，整数或空",
                                    "actual_quantity": "最终应入库数量，整数",
                                    "normalized_name": "规范库存名称，简短直观",
                                    "model": "标准型号，没有则为空",
                                    "order_category": "原订单分类字段原文，没有则为空",
                                    "category": "分类名称，必须来自 categories",
                                    "parameters": "明确参数摘要",
                                    "package": "封装/规格尺寸",
                                    "normalized_spec": "阻值/容值/感值/磁珠阻抗@频率等核心值，不要写封装尺寸",
                                    "tags": ["简短标签，不含营销词"],
                                    "confidence": "high/medium/low",
                                    "reason": "字段识别和数量计算依据，中文简短说明",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=max_tokens,
        web_search="off",
    )


def explain_component(payload: dict[str, Any]) -> dict[str, Any]:
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "explain_component",
                        "component": payload,
                        "required_json_schema": {
                            "summary": "用途说明",
                            "tips": ["PCB 选型、封装、参数、替代风险注意事项"],
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1000,
    )
    result["requires_confirmation"] = True
    return result


def project_plan(goal: str, candidates: list[Component]) -> dict[str, Any]:
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "project_plan",
                        "goal": goal,
                        "inventory_candidates": [component_to_dict(item) for item in candidates],
                        "rules": [
                            "优先使用 inventory_candidates 里的已有库存。",
                            "只有库存缺失或参数明显不适合时才给外部采购建议。",
                            "必须输出 markdown 字段用于前端展示，不要让用户阅读原始 JSON。",
                        ],
                        "required_json_schema": {
                            "goal": "项目目标",
                            "markdown": "Markdown 格式的可读规划",
                            "recommended_existing": [
                                {
                                    "component_id": "库存元器件 id",
                                    "role": "它在项目中的作用",
                                    "reason": "推荐理由",
                                    "required_quantity": 1,
                                    "confidence": "high/medium/low",
                                }
                            ],
                            "missing_materials": [
                                {
                                    "description": "缺失物料描述",
                                    "reason": "为什么需要",
                                    "suggested_models": ["可搜索型号或关键词"],
                                    "lcsc_search_keyword": "立创搜索关键词",
                                }
                            ],
                            "risks": ["参数、封装、库存、替代风险"],
                            "pcb_notes": ["PCB 注意事项"],
                            "next_steps": ["下一步操作"],
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1600,
    )
    result["goal"] = goal
    enrich_lcsc_urls(result)
    result["requires_confirmation"] = True
    return result


def project_consult(question: str, project: dict[str, Any], bom_items: list[dict[str, Any]], candidates: list[Component]) -> dict[str, Any]:
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "project_bom_consult",
                        "question": question,
                        "project": project,
                        "bom_items": bom_items,
                        "inventory_candidates": [component_to_dict(item) for item in candidates],
                        "rules": [
                            "优先结合当前 BOM 和已有库存回答。",
                            "已有库存可以解决的问题必须给 component_id。",
                            "外部推荐必须给 lcsc_search_keyword。",
                        ],
                        "required_json_schema": {
                            "markdown": "Markdown 格式的可读答复",
                            "recommended_existing": [
                                {
                                    "component_id": "库存元器件 id",
                                    "role": "作用",
                                    "reason": "推荐理由",
                                    "required_quantity": 1,
                                    "confidence": "high/medium/low",
                                }
                            ],
                            "missing_materials": [
                                {
                                    "description": "缺失物料",
                                    "reason": "原因",
                                    "suggested_models": ["型号或关键词"],
                                    "lcsc_search_keyword": "立创搜索关键词",
                                }
                            ],
                            "risks": ["风险"],
                            "next_steps": ["下一步"],
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=2000,
        web_search="auto",
    )
    result["question"] = question
    enrich_lcsc_urls(result)
    result["requires_confirmation"] = True
    return result


def component_search(requirement: str, candidates: list[Component]) -> dict[str, Any]:
    inventory = [component_to_dict(item) for item in candidates]
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "component_search",
                        "requirement": requirement,
                        "inventory_candidates": inventory,
                        "required_json_schema": {
                            "matched_components": [
                                {
                                    "component_id": "库存元器件 id",
                                    "role": "它在需求中的用途",
                                    "reason": "为什么匹配",
                                    "quantity_risk": "库存数量是否可能不足",
                                }
                            ],
                            "alternative_components": ["可替代库存物料建议"],
                            "missing_suggestions": ["库存没有时建议采购/确认的型号、参数或封装"],
                            "selection_notes": ["选型说明"],
                            "risks": ["PCB 设计风险"],
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1800,
    )
    result["requirement"] = requirement
    result["inventory_candidates"] = inventory
    enrich_lcsc_urls(result)
    result["requires_confirmation"] = True
    return result


def contest_library_assist(
    query_type: str,
    prompt: str,
    components: list[dict[str, Any]],
    pcbs: list[dict[str, Any]],
    cw_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task_rules = {
        "find_components": "根据用户口语需求，从团队器件库中找出最合适的现有器件。",
        "match_cw": "为未关联器件提供个人版人工核对候选，不得把相似结果当成确定匹配。",
        "alternatives": "只从当前团队器件库中推荐可替代器件，并说明必须核对的差异。",
        "recommend_pcbs": "根据题目或任务描述，从当前团队 PCB 库中推荐可用板卡。",
    }
    if query_type not in task_rules:
        raise ValueError("Unsupported contest AI query type")
    result = _chat_json(
        [
            {
                "role": "system",
                "content": (
                    "你是团队器件查询助手。回答要短、直接、口语化。"
                    "只能根据提供的团队器件库数据推荐，不能声称库里存在未提供的器件。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": query_type,
                        "goal": task_rules[query_type],
                        "question": prompt,
                        "team_components": components,
                        "team_pcbs": pcbs,
                        "cw_candidates": cw_candidates or [],
                        "rules": [
                            "优先返回库内真实 ID。",
                            "match_cw 只能从 cw_candidates 中推荐器件 ID；立创 ID 精确匹配由系统在调用 AI 前处理。",
                            "find_components 的 team_components 已由本地搜索预筛选，请只做排序和解释。",
                            "不自动修改或合并数据。",
                            "有不确定性时明确提示需要人工确认。",
                            "不要输出大段背景说明。",
                        ],
                        "required_json_schema": {
                            "answer": "不超过120字的中文结论",
                            "component_matches": [
                                {
                                    "id": "团队器件 ID",
                                    "cw_component_id": "关联器件 ID 或空",
                                    "reason": "简短理由",
                                    "warning": "需要核对的差异或空",
                                }
                            ],
                            "pcb_matches": [
                                {
                                    "id": "PCB ID",
                                    "reason": "简短理由",
                                    "warning": "需要核对的事项或空",
                                }
                            ],
                            "next_steps": ["最多3条下一步"],
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1400,
        web_search="off",
    )
    result["query_type"] = query_type
    result["prompt"] = prompt
    result["requires_confirmation"] = True
    return result


def search_empty_suggestions(query: str, filters: dict[str, Any], categories: list[str]) -> dict[str, Any]:
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "inventory_empty_search_suggestions",
                        "query": query,
                        "filters": filters,
                        "categories": categories,
                        "rules": [
                            "用户在本地库存中没有搜到结果。",
                            "不要声明库存中存在某个物料。",
                            "给出可能的等价写法、相近型号方向、建议放宽的筛选项和外部搜索关键词。",
                            "不要使用正则或关键词匹配结果；这是基于工程语义的建议。",
                            "建议必须简短，最多 6 项。",
                        ],
                        "required_json_schema": {
                            "query": "原始搜索词",
                            "message": "一句中文空态说明",
                            "suggestions": [
                                {
                                    "label": "建议标题，如 尝试 VL53L0X",
                                    "reason": "为什么可能相关",
                                    "search_keyword": "可复制搜索词",
                                    "category": "可能分类，必须来自 categories 或空字符串",
                                }
                            ],
                            "lcsc_keywords": ["适合去立创搜索的关键词"],
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1000,
        web_search="off",
    )
    result["query"] = query
    result["requires_confirmation"] = True
    return result


def component_info(query: str, known_specs: str | None, web_search: str) -> dict[str, Any]:
    web_search_mode = web_search if web_search in {"off", "auto", "force"} else "auto"
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "component_info_and_spec_completion",
                        "query": query,
                        "known_specs": known_specs,
                        "answer_quality_rules": [
                            "不要把 name/model/parameters/package/lcsc_number 简单改写成一句话；这些是已知信息。",
                            "summary 必须包含 1-2 条用户不一定知道的设计结论，例如降额、误用边界、适用/不适用场景。",
                            "risk_notes 和 pcb_notes 必须是可执行的工程注意事项，避免空泛的\u201c注意散热/遵循规范\u201d。",
                            "key_specs 的每条 value 必须带完整单位（如 V/mV/A/mA/Ω/kΩ/µF/nF/pF/MHz 等），纯数字不允许。",
                            "绝对不要从型号/料号中推测电气参数。型号中的数字（如 WJ500V 中的 500、PZ254V 中的 254）不是耐压/电流/阻值。",
                            "连接件/排针/端子的 key_specs 只写引脚数、间距(Pitch)、安装方式(THT/SMD)，不要臆测耐压/电流。",
                            "key_specs 中不确定的参数必须标 confidence: low，宁缺毋滥。",
                            "如果是电阻，重点说明功耗裕量、工作电压/电流估算、分压阻抗对 ADC/偏置的影响、TCR/脉冲功率未知时的保守策略。",
                            "如果是电容，重点说明 MLCC DC Bias、介质/温漂、耐压降额、ESR/纹波、去耦/储能适用边界。",
                            "如果是 MOS/电源/接口/芯片，重点说明关键数据手册参数、典型外围、热设计、封装电流限制、替代时必须核对的参数。",
                            "如果是传感器或传感器模块，重点说明测量对象、供电范围、接口电平、量程/精度、采样率、安装位置、校准和环境干扰。",
                            "如果是风扇、电机、水泵、蜂鸣器、继电器等机电件，重点说明额定电压、工作/启动电流、驱动方式、反灌/感性尖峰保护、噪声、寿命和安装方向。",
                            "如果是显示或通信模块，重点说明接口、供电电平、峰值电流、天线/排线/背光、初始化兼容性和替代模块风险。",
                            "如果无法从资料确认，明确写出\u201c未从资料确认\u201d的限制和建议用户核对的数据手册字段。",
                            "如果已知立创 ID 或型号，尝试填写 datasheet_url 为官方或分销商数据手册链接。",
                        ],
                        "web_search_policy": (
                            "off 表示不要联网；auto 表示只有型号或规格不明确时才搜索；force 表示必须联网核对。"
                            "如 known_specs 中包含立创 ID、LCSC ID 或商品型号，优先参考立创商城、厂商官网、官方数据手册和可信分销商页面。"
                            "联网资料不可用时也要给出保守判断，并把 confidence 降低。"
                        ),
                        "required_json_schema": {
                            "normalized_name": "规范化后的元器件名称或型号",
                            "summary": "不要复述已知规格；用一两句话给出最值得记住的设计结论",
                            "category_suggestion": "分类建议",
                            "usage": "实际项目中什么时候选它、什么时候不该选它，以及与常见电路的关系",
                            "key_specs": [
                                {
                                    "name": "规格名，如耐压/电流/封装/接口/供电范围",
                                    "value": "规格值",
                                    "confidence": "high/medium/low",
                                }
                            ],
                            "typical_applications": ["典型用途"],
                            "applications": ["典型用途"],
                            "design_insights": ["用户不一定知道的设计经验、降额建议、计算边界或选型规则"],
                            "risk_notes": ["具体误用风险、参数风险、替代风险；每条要说明为什么"],
                            "pcb_notes": ["具体 PCB 设计和布局布线注意事项；每条要说明适用条件"],
                            "substitutes": ["替代型号或同类器件"],
                            "substitution_notes": ["替代时必须核对的参数，而不只是列型号"],
                            "datasheet_notes": ["建议从手册核对的字段，如 TCR、额定电压、DC bias 曲线、Rds(on)、SOA 等"],
                            "do_not_use_for": ["不适合的场景"],
                            "recommended_pairings": ["推荐搭配的器件/外围，例如去耦组合、保护器件、栅极电阻等"],
                            "ai_tags": ["适合写入库存的用途标签"],
                            "confidence": "high/medium/low",
                            "need_datasheet_check": True,
                            "datasheet_based": False,
                            "datasheet_url": "如果能确定官方或分销商数据手册PDF链接则填写URL，否则留空字符串",
                            "source_notes": ["资料来源或推断依据；如果没有来源，写基于通用工程经验"],
                            "is_hand_solder_friendly": False,
                            "is_power_component": False,
                            "is_signal_component": False,
                            "is_high_current": False,
                            "is_high_voltage": False,
                            "is_common": False,
                            "completion_suggestions": ["可补全到库存备注/参数/标签中的建议"],
                            "search_used": "是否使用联网搜索",
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1800,
        web_search=web_search_mode,
    )
    result["query"] = query
    result["web_search_mode"] = web_search_mode
    result["requires_confirmation"] = True
    return result


def analyze_bom(project: dict[str, Any], bom_items: list[dict[str, Any]]) -> dict[str, Any]:
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "project_bom_analysis",
                        "project": project,
                        "bom_items": bom_items,
                        "required_json_schema": {
                            "summary": "当前 BOM 完整度和适用性摘要",
                            "markdown": "Markdown 格式的可读分析",
                            "completeness": "0-100 的整数",
                            "recommended_existing": [
                                {
                                    "component_id": "库存元器件 id",
                                    "role": "可补充到 BOM 的作用",
                                    "reason": "推荐理由",
                                    "required_quantity": 1,
                                    "confidence": "high/medium/low",
                                }
                            ],
                            "missing_materials": [
                                {
                                    "description": "缺料或建议补充的物料",
                                    "reason": "原因",
                                    "suggested_models": ["型号或搜索词"],
                                    "lcsc_search_keyword": "立创搜索关键词",
                                }
                            ],
                            "substitutes": ["可替代库存或替代方向"],
                            "risk_notes": ["参数、电流、耐压、封装、替代风险"],
                            "pcb_notes": ["PCB 布局布线注意事项"],
                            "purchase_suggestions": ["建议采购的型号/参数/封装"],
                            "confidence": "high/medium/low",
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1800,
        web_search="auto",
    )
    enrich_lcsc_urls(result)
    result["requires_confirmation"] = True
    return result


def component_question(component: dict[str, Any], question: str, context: dict[str, Any] | None = None, web_search: str = "off") -> dict[str, Any]:
    web_search_mode = web_search if web_search in {"off", "auto", "force"} else "off"
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "answer_question_about_one_inventory_component",
                        "component": component,
                        "context": context or {},
                        "question": question,
                        "rules": [
                            "只围绕这个元器件回答，不要把回答扩展成泛泛的选型文章。",
                            "优先使用 component 和 context 中的结构化字段、BOM/EDA/供应商/资料信息作为依据。",
                            "无法确认的数据必须明确说资料不足或需查数据手册，不能编造具体电气参数。",
                            "如果问题涉及封装，区分库存字段 package、BOM Footprint、AD Footprint 和芯片封装，不要混用。",
                            "回答要短，直接给可执行结论。",
                        ],
                        "required_json_schema": {
                            "answer": "中文回答，尽量具体，不超过 500 字",
                            "confidence": "high/medium/low",
                            "evidence": ["用到的字段或依据"],
                            "risks": ["不确定或需核对的风险"],
                            "needs_datasheet_check": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=1200,
        web_search=web_search_mode,
    )
    result["requires_confirmation"] = True
    return result


def _bom_candidate_to_dict(component: Component) -> dict[str, Any]:
    return {
        "id": component.id,
        "name": component.name,
        "model": component.model,
        "category": component.category.name if component.category else None,
        "parameters": component.parameters,
        "package": component.package,
        "quantity": component.quantity,
        "lcsc_number": component.lcsc_number,
        "tags": component.tags,
        "normalized_spec": getattr(component, "normalized_spec", None),
    }


def assist_bom_matches(rows: list[dict[str, Any]], inventory_candidates: list[Component]) -> dict[str, Any]:
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "assist_bom_import_matching",
                        "bom_rows": rows,
                        "inventory_candidates": [_bom_candidate_to_dict(item) for item in inventory_candidates],
                        "rules": [
                            "优先匹配已有库存，哪怕只是低置信候选也要说明原因。",
                            "不能确定时不要强行给 selected_component_id，但要给 role 和 missing_suggestion。",
                            "role 用一句话说明这个 BOM 行在电路中的可能作用。",
                            "缺失物料必须给 lcsc_search_keyword。",
                        ],
                        "required_json_schema": {
                            "rows": [
                                {
                                    "source_row": "BOM 行号",
                                    "role": "可能作用，一句话",
                                    "selected_component_id": "建议库存 id 或 null",
                                    "confidence": "high/medium/low",
                                    "reason": "匹配或不匹配原因",
                                    "missing_suggestion": {
                                        "description": "缺失物料描述",
                                        "reason": "为什么缺",
                                        "lcsc_search_keyword": "立创搜索关键词",
                                    },
                                }
                            ],
                            "requires_confirmation": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=2200,
        web_search="off",
    )
    for row in result.get("rows", []):
        if isinstance(row, dict) and isinstance(row.get("missing_suggestion"), dict):
            keyword = row["missing_suggestion"].get("lcsc_search_keyword") or row["missing_suggestion"].get("description")
            row["missing_suggestion"]["lcsc_search_url"] = lcsc_search_url(keyword)
    result["requires_confirmation"] = True
    return result


def enrich_lcsc_urls(result: dict[str, Any]) -> None:
    for key in ("missing_materials", "purchase_suggestions"):
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            keyword = row.get("lcsc_search_keyword") or row.get("model") or row.get("description")
            models = row.get("suggested_models")
            if not keyword and isinstance(models, list) and models:
                keyword = models[0]
            row["lcsc_search_url"] = lcsc_search_url(keyword)


def image_import_preview(images: list[dict[str, str]], inventory: list[Component], categories: list[str]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "task": "shopping_screenshot_component_import_preview",
                    "instructions": [
                        "识别淘宝、拼多多、1688、立创等购物截图中的可入库电子元器件或小五金。",
                        "如果图片不是购物、订单、商品详情、物料清单或包装标签截图，items 必须返回空数组。",
                        "不要把促销词、店铺名、广告词当作型号。",
                        "优先提取型号、规格、封装、数量、来源平台、可搜索关键词。",
                        "螺丝、螺母、铜柱按机械件识别，并尽量归一化规格如 M2x6、M3螺母。",
                        "风扇、电机、水泵、蜂鸣器、继电器、显示屏、通信模块、传感器模块等可以作为库存物料识别，按 categories 中最贴近的分类给 category_suggestion。",
                        "设备/模块类名称要一眼能看出用途，例如 SHT31 温湿度传感器、VL53L0X TOF测距模块、5V 3010 风扇、0.96寸 OLED 显示模块。",
                        "无法确认字段时留空并降低 confidence。",
                        "只返回预览候选，不声明已经写入库存。",
                    ],
                    "categories": categories,
                    "inventory_candidates": [component_to_dict(item) for item in inventory],
                    "required_json_schema": {
                        "items": [
                            {
                                "name": "物料名称",
                                "model": "型号",
                                "category_suggestion": "分类建议",
                                "parameters": "规格参数",
                                "package": "封装/规格",
                                "quantity": 1,
                                "source": "淘宝/拼多多/1688/立创/未知",
                                "tags": "用途或规格标签",
                                "part_family": "component/module/sensor_module/communication_module/display_module/fan/motor/pump/buzzer/relay/heatsink/enclosure/bracket/cable_assembly/pin_header/screw/nut/standoff/wire/other",
                                "count_mode": "exact/rough/ignore",
                                "normalized_spec": "归一化规格，如 5V 3010、I2C 3.3V、0.96寸 I2C、M2x6",
                                "confidence": "high/medium/low",
                                "evidence_text": "截图中支持该判断的文字",
                                "matched_component_id": "如果明显匹配已有库存则给 id，否则 null",
                                "match_score": "0-100",
                                "lcsc_search_keyword": "立创搜索关键词",
                            }
                        ],
                        "requires_confirmation": True,
                    },
                },
                ensure_ascii=False,
            ),
        }
    ]
    for image in images:
        content.append({"type": "image_url", "image_url": {"url": f"data:{image['content_type']};base64,{image['base64']}"}})
    result = _chat_json(
        [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": content},
        ],
        max_tokens=2400,
        web_search="off",
    )
    for item in result.get("items", []):
        if isinstance(item, dict):
            item["lcsc_search_url"] = lcsc_search_url(item.get("lcsc_search_keyword") or item.get("model") or item.get("name"))
    result["requires_confirmation"] = True
    return result
