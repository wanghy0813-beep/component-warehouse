import json
import os
import re
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Component
from .component_normalizer import clean_lcsc_keyword


MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1").rstrip("/")
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5")
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
    return _json_from_text(repaired)


def _chat_json(messages: list[dict[str, Any]], max_tokens: int = 1600, web_search: str = "off") -> dict[str, Any]:
    if not MIMO_API_KEY:
        raise MimoNotConfiguredError("MIMO_API_KEY is not configured")

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
        "你是 Component Warehouse 的 PCB 元器件选型助手。"
        f"今天日期是 {today}。"
        "你只能给出建议，不能声明已经修改库存或项目。"
        "优先使用用户已有库存；如果库存没有合适物料，再给出缺失采购建议。"
        "回答必须面向硬件设计决策，不要复述名称、阻值、容值、封装这些用户已经知道的表面信息。"
        "优先给出非显而易见的选型边界、降额、误用场景、布局注意、替代检查项和需要查数据手册的参数。"
        "输出必须是合法 JSON，不要使用 Markdown。"
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
                            "你是唯一的语义分类与命名来源；不要依赖本地规则，必须根据输入字段和工程常识整理。",
                            "normalized_name 要像个人库存里的短名称，不要保留淘宝/拼多多/1688营销标题。",
                            "如果型号明确，名称应突出型号 + 器件类型/关键规格；不要把整段商品标题原样返回。",
                            "分类必须来自 categories。",
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
                            "如果同时含插座类词和接口协议词(如 USB插座、Type-C座)，以协议为准归「接口」。但芯片型号(如 CH340/CP2102/FT232)始终归「芯片」。",
                            "设备/模块类 normalized_name 要一眼能看出用途：型号 + 关键规格 + 类型，例如 SHT31 温湿度传感器、VL53L0X TOF测距模块、5V 3010 风扇、0.96寸 OLED 显示模块。",
                            "设备/模块类 normalized_spec 写最能区分库存的规格组合，例如 5V 3010、I2C 3.3V、0.96寸 I2C、LoRa 433MHz；不确定则留空。",
                            "part_family 可使用 component/module/sensor_module/communication_module/display_module/fan/motor/pump/buzzer/relay/heatsink/enclosure/bracket/cable_assembly/pin_header/screw/nut/standoff/wire/other。",
                            "标签最多 6 个，保留真正帮助检索和选型的词，避免重复封装/型号/分类。",
                            "绝对不要从型号/料号中推测电气参数或封装尺寸，只用 parameters/package 中明确写出的信息。",
                            "不要修改库存数量、位置、立创编号。",
                        ],
                        "required_json_schema": {
                            "normalized_name": "规范库存名称，短而清楚",
                            "category": "分类名称，必须来自 categories",
                            "parameters": "更规范的参数描述；不确定则沿用或留空",
                            "package": "封装或机械规格；不确定则沿用或留空",
                            "tags": ["最多 6 个标签"],
                            "part_family": "component/module/sensor_module/communication_module/display_module/fan/motor/pump/buzzer/relay/heatsink/enclosure/bracket/cable_assembly/pin_header/screw/nut/standoff/wire/other",
                            "count_mode": "exact/rough/ignore",
                            "normalized_spec": "归一化规格，如 0805、100nF、M2x6、2.54mm 1x16P、5V 3010、I2C 3.3V",
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
                            "如果已知立创编号或型号，尝试填写 datasheet_url 为官方或分销商数据手册链接。",
                        ],
                        "web_search_policy": (
                            "off 表示不要联网；auto 表示只有型号或规格不明确时才搜索；force 表示必须联网核对。"
                            "如 known_specs 中包含立创编号、LCSC 编号或商品型号，优先参考立创商城、厂商官网、官方数据手册和可信分销商页面。"
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
