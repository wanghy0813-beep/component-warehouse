import json
import os
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import httpx


LCSC_PRODUCT_BASE = "https://www.lcsc.com/product-detail"
LCSC_LOOKUP_TIMEOUT_SECONDS = float(os.getenv("LCSC_LOOKUP_TIMEOUT_SECONDS", "12"))
LCSC_MAX_HTML_BYTES = int(os.getenv("LCSC_MAX_HTML_BYTES", str(1024 * 1024)))
LCSC_COPY_LABELS = {
    "名称": "copied_name",
    "型号": "model",
    "品牌": "manufacturer",
    "厂商": "manufacturer",
    "封装": "package",
    "编号": "lcsc_number",
    "立创编号": "lcsc_number",
    "立创id": "lcsc_number",
    "lcsc": "lcsc_number",
}


class LcscLookupError(RuntimeError):
    pass


class LcscProductNotFound(LcscLookupError):
    pass


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capturing = False
        self._chunks: list[str] = []
        self.documents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        values = {str(key).lower(): str(value or "").lower() for key, value in attrs}
        if values.get("type") == "application/ld+json":
            self._capturing = True
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._capturing:
            return
        self.documents.append("".join(self._chunks).strip())
        self._capturing = False
        self._chunks = []


def normalize_lcsc_number(value: str | None) -> str | None:
    text = str(value or "").strip()
    match = re.search(r"(?i)(?<![A-Z0-9])C\s*(\d{3,})(?!\d)", text)
    return f"C{match.group(1)}" if match else None


def _clean_copy_value(value: str | None) -> str | None:
    text = str(value or "").strip().strip("\"'“”‘’ ")
    return text or None


def parse_lcsc_copy_text(raw_text: str) -> dict[str, str | None]:
    result: dict[str, str | None] = {
        "copied_name": None,
        "model": None,
        "manufacturer": None,
        "package": None,
        "lcsc_number": None,
    }
    for raw_line in str(raw_text or "").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^\s*([^:：]{1,12})\s*[:：]\s*(.*?)\s*$", line)
        if not match:
            continue
        label = match.group(1).strip().lower()
        field = LCSC_COPY_LABELS.get(label)
        if not field:
            continue
        value = _clean_copy_value(match.group(2))
        if field == "lcsc_number":
            value = normalize_lcsc_number(value)
        if value:
            result[field] = value
    result["lcsc_number"] = result.get("lcsc_number") or normalize_lcsc_number(raw_text)
    return result


def product_url(lcsc_number: str) -> str:
    normalized = normalize_lcsc_number(lcsc_number)
    if not normalized:
        raise LcscLookupError("未识别到有效的立创编号")
    return f"{LCSC_PRODUCT_BASE}/{normalized}.html"


def _is_product(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    item_type = value.get("@type")
    if isinstance(item_type, list):
        return any(str(item).lower() == "product" for item in item_type)
    return str(item_type or "").lower() == "product"


def _walk_products(value: Any):
    if _is_product(value):
        yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_products(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_products(child)


def extract_product_json_ld(html: str, expected_lcsc_number: str) -> dict[str, Any]:
    expected = normalize_lcsc_number(expected_lcsc_number)
    if not expected:
        raise LcscLookupError("未识别到有效的立创编号")
    parser = _JsonLdParser()
    parser.feed(str(html or ""))
    mismatched: list[str] = []
    for document in parser.documents:
        if not document:
            continue
        try:
            payload = json.loads(document)
        except json.JSONDecodeError:
            continue
        for product in _walk_products(payload):
            sku = normalize_lcsc_number(product.get("sku"))
            if sku == expected:
                return product
            if sku:
                mismatched.append(sku)
    if mismatched:
        raise LcscLookupError(f"立创商品编号不一致：请求 {expected}，页面返回 {mismatched[0]}")
    raise LcscProductNotFound(f"立创商品页未提供 {expected} 的结构化商品数据")


def fetch_lcsc_product(lcsc_number: str, client: httpx.Client | None = None) -> dict[str, Any]:
    normalized = normalize_lcsc_number(lcsc_number)
    if not normalized:
        raise LcscLookupError("未识别到有效的立创编号")
    url = product_url(normalized)
    owns_client = client is None
    http = client or httpx.Client(
        follow_redirects=False,
        timeout=LCSC_LOOKUP_TIMEOUT_SECONDS,
        trust_env=False,
        headers={"User-Agent": "ComponentWarehouse/1.0 (+https://wxylab.ltd/)"},
    )
    try:
        response = http.get(url)
        if response.status_code == 404:
            raise LcscProductNotFound(f"立创未找到商品 {normalized}")
        response.raise_for_status()
        if len(response.content) > LCSC_MAX_HTML_BYTES:
            raise LcscLookupError("立创商品页响应过大，已停止解析")
        return extract_product_json_ld(response.text, normalized)
    except LcscLookupError:
        raise
    except httpx.HTTPError as exc:
        raise LcscLookupError(f"立创商品查询失败：{exc}") from exc
    finally:
        if owns_client:
            http.close()


def _brand_name(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    return _clean_copy_value(value)


def _document_url(value: Any) -> str | None:
    candidates = value if isinstance(value, list) else [value]
    for item in candidates:
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            return url[:1000]
    return None


def _property_rows(product: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    properties = product.get("additionalProperty") or []
    if isinstance(properties, dict):
        properties = [properties]
    for item in properties:
        if not isinstance(item, dict):
            continue
        name = _clean_copy_value(item.get("name"))
        value = _clean_copy_value(item.get("value"))
        if name and value:
            rows.append({"name": name[:120], "value": value[:200]})
    return rows


def _package_from_properties(rows: list[dict[str, str]]) -> str | None:
    for item in rows:
        if item["name"].strip().lower() == "package":
            return item["value"][:120]
    return None


def _type_hint(category: str | None, description: str | None) -> str | None:
    text = f"{category or ''} {description or ''}".lower()
    mappings = (
        (("low drop out", "dropout regulator", "linear voltage regulator"), "LDO"),
        (("mosfet",), "MOS管"),
        (("operational amplifier", "op amp"), "运放"),
        (("microcontroller",), "MCU"),
        (("resistor",), "电阻"),
        (("capacitor",), "电容"),
        (("inductor",), "电感"),
        (("diode",), "二极管"),
        (("connector",), "连接器"),
    )
    for needles, label in mappings:
        if any(needle in text for needle in needles):
            return label
    return None


def default_inventory_name(draft: dict[str, Any], category: str | None = None) -> str:
    model = _clean_copy_value(draft.get("model"))
    rows = draft.get("official_properties") or []
    preferred = (
        "output voltage",
        "output current",
        "resistance",
        "capacitance",
        "inductance",
        "operating voltage",
    )
    specs: list[str] = []
    for key in preferred:
        for item in rows:
            if str(item.get("name") or "").strip().lower() == key and item.get("value"):
                value = str(item["value"]).strip()
                if value not in specs:
                    specs.append(value)
                break
        if len(specs) >= 2:
            break
    type_hint = _type_hint(category, draft.get("description"))
    parts = [model, *specs, type_hint]
    name = " ".join(str(part).strip() for part in parts if part and str(part).strip())
    return (name or model or draft.get("copied_name") or draft.get("lcsc_number") or "未命名物料")[:120]


def official_product_draft(product: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    lcsc_number = normalize_lcsc_number(product.get("sku")) or parsed.get("lcsc_number")
    rows = _property_rows(product)
    package = _package_from_properties(rows) or _clean_copy_value(parsed.get("package"))
    parameters = "；".join(
        f"{item['name']} {item['value']}"
        for item in rows
        if item["name"].strip().lower() != "package"
    )
    offers = product.get("offers") if isinstance(product.get("offers"), dict) else {}
    fixed_product_url = product_url(lcsc_number)
    offered_url = offers.get("url") if isinstance(offers, dict) else None
    if isinstance(offered_url, str):
        host = (urlsplit(offered_url).hostname or "").lower()
        if host not in {"lcsc.com", "www.lcsc.com"}:
            offered_url = None
    draft: dict[str, Any] = {
        "name": "",
        "model": _clean_copy_value(product.get("mpn")) or parsed.get("model"),
        "manufacturer": _brand_name(product.get("brand")) or parsed.get("manufacturer"),
        "description": _clean_copy_value(product.get("description")),
        "parameters": parameters[:4000] or parsed.get("copied_name"),
        "package": package,
        "quantity": 0,
        "source": "立创",
        "lcsc_number": lcsc_number,
        "tags": "",
        "source_title": _clean_copy_value(product.get("name")) or parsed.get("copied_name"),
        "status": "in_stock",
        "datasheet_url": _document_url(product.get("subjectOf")),
        "buy_url": (offered_url or fixed_product_url)[:500],
        "official_category": _clean_copy_value(product.get("category")),
        "official_properties": rows,
        "copied_name": parsed.get("copied_name"),
    }
    draft["name"] = default_inventory_name(draft, draft.get("official_category"))
    return draft


def parsed_copy_draft(parsed: dict[str, Any]) -> dict[str, Any]:
    lcsc_number = parsed.get("lcsc_number")
    draft = {
        "name": parsed.get("model") or parsed.get("copied_name") or lcsc_number or "未命名物料",
        "model": parsed.get("model"),
        "manufacturer": parsed.get("manufacturer"),
        "description": None,
        "parameters": parsed.get("copied_name"),
        "package": parsed.get("package"),
        "quantity": 0,
        "source": "立创",
        "lcsc_number": lcsc_number,
        "tags": "",
        "source_title": parsed.get("copied_name"),
        "status": "in_stock",
        "datasheet_url": None,
        "buy_url": product_url(lcsc_number) if lcsc_number else None,
        "official_category": None,
        "official_properties": [],
        "copied_name": parsed.get("copied_name"),
    }
    draft["name"] = default_inventory_name(draft)
    return draft


def local_category_from_text(value: str | None) -> str | None:
    text = str(value or "").lower()
    mappings = (
        (("resistor", "电阻"), "电阻"),
        (("capacitor", "电容"), "电容"),
        (("inductor", "ferrite bead", "电感", "磁珠"), "电感"),
        (("mosfet", "mos管"), "MOS管"),
        (("diode", "二极管"), "二极管"),
        (("transistor", "三极管"), "三极管"),
        (("voltage regulator", "power management", "电源", "ldo"), "电源"),
        (("connector", "连接器", "排针", "排母", "端子"), "连接件"),
        (("sensor", "传感器"), "传感器"),
        (("switch", "开关"), "开关"),
        (("crystal", "oscillator", "晶振"), "时钟源"),
        (("interface", "接口"), "接口"),
        (("integrated circuit", "microcontroller", "amplifier", "芯片", "运放", "mcu"), "芯片"),
    )
    for needles, category in mappings:
        if any(needle in text for needle in needles):
            return category
    return None


def exact_lcsc_source_present(sources: list[dict[str, Any]], lcsc_number: str) -> bool:
    target = str(lcsc_number or "").upper()
    for source in sources or []:
        url = str(source.get("url") or "")
        host = (urlsplit(url).hostname or "").lower()
        if host not in {"lcsc.com", "www.lcsc.com", "szlcsc.com", "item.szlcsc.com"}:
            continue
        evidence = " ".join(
            str(source.get(key) or "") for key in ("url", "title", "summary")
        ).upper()
        if target and target in evidence:
            return True
    return False
