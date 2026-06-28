import base64
import html
import io
import os
import re
from datetime import datetime
from functools import lru_cache
from urllib.parse import quote
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET

import qrcode
from qrcode.image.svg import SvgPathImage

from .branding import APP_BRAND_NAME, APP_SHOW_BRAND_LOGO


def safe_str(value, fallback: str = "") -> str:
    if value is None:
        return fallback
    try:
        text = str(value).strip()
    except Exception:
        return fallback
    return text or fallback


def record_value(record: object, key: str, fallback=None):
    try:
        if isinstance(record, dict):
            return record.get(key, fallback)
        return getattr(record, key, fallback)
    except Exception:
        return fallback


def category_name(record: object) -> str:
    category = record_value(record, "category")
    if isinstance(category, dict):
        return safe_str(category.get("name"), "元器件")[:12]
    name = record_value(category, "name") if category is not None else None
    if name:
        return safe_str(name, "元器件")[:12]
    return safe_str(category, "元器件")[:12]


def comparable_text(value) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def unique_display_parts(values: list[object], primary: object = "") -> list[str]:
    result: list[str] = []
    seen: list[str] = [comparable_text(primary)] if primary else []
    for raw in values:
        value = safe_str(raw)
        key = comparable_text(value)
        if not key:
            continue
        if any(key == old or key in old or old in key for old in seen if old):
            continue
        result.append(value)
        seen.append(key)
    return result


def component_label_density(*values: object) -> str:
    score = sum(len(safe_str(value)) for value in values)
    if score > 112:
        return "micro"
    if score > 76:
        return "compact"
    return "normal"


def label_title(record: dict) -> str:
    return safe_str(
        record_value(record, "normalized_spec")
        or record_value(record, "model")
        or record_value(record, "name")
        or record_value(record, "warehouse_code"),
        "未命名器件",
    )[:72]


def label_subtitle(record: dict, title: str) -> str:
    return " / ".join(
        unique_display_parts(
            [
                record_value(record, "model"),
                record_value(record, "name"),
                record_value(record, "package"),
                record_value(record, "lcsc_number"),
            ],
            title,
        )[:3]
    )[:110]


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    path = os.path.join(os.path.dirname(__file__), "assets", "brand-logo.png")
    try:
        with open(path, "rb") as logo_file:
            encoded = base64.b64encode(logo_file.read()).decode("ascii")
            return f"data:image/png;base64,{encoded}"
    except OSError:
        return ""


@lru_cache(maxsize=2048)
def qr_svg_markup(value: str) -> str:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=5,
        border=1,
    )
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    markup = buffer.getvalue().decode("utf-8")
    markup = re.sub(r"^\s*<\?xml[^>]*>\s*", "", markup)
    if "preserveAspectRatio=" not in markup:
        markup = markup.replace("<svg ", '<svg preserveAspectRatio="xMidYMid meet" ', 1)
    if "shape-rendering=" not in markup:
        markup = markup.replace("<svg ", '<svg shape-rendering="crispEdges" ', 1)
    return markup


def component_scan_url(base_url: str, code: str) -> str:
    return f"{base_url.rstrip('/')}/scan/{quote(code)}"


def print_timestamp() -> str:
    try:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        now = datetime.now()
    return now.strftime("P:%Y-%m-%d %H:%M")


SAFE_SVG_TAGS = {
    "svg",
    "g",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
    "defs",
    "linearGradient",
    "radialGradient",
    "stop",
}
SAFE_SVG_ATTRS = {
    "viewBox",
    "width",
    "height",
    "x",
    "y",
    "x1",
    "x2",
    "y1",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "d",
    "points",
    "fill",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-miterlimit",
    "opacity",
    "fill-opacity",
    "stroke-opacity",
    "transform",
    "font-size",
    "font-family",
    "font-weight",
    "text-anchor",
    "dominant-baseline",
    "offset",
    "stop-color",
    "stop-opacity",
    "id",
    "class",
}
UNSAFE_VALUE = re.compile(r"(javascript:|data:|url\s*\(|@import|expression\s*\()", re.I)


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _safe_svg_attrs(element: ET.Element) -> str:
    attrs: list[str] = []
    for raw_key, raw_value in element.attrib.items():
        key = _strip_namespace(raw_key)
        if key.startswith("on") or key not in SAFE_SVG_ATTRS:
            continue
        value = safe_str(raw_value)
        if UNSAFE_VALUE.search(value):
            continue
        attrs.append(f'{key}="{html.escape(value, quote=True)}"')
    return (" " + " ".join(attrs)) if attrs else ""


def _render_safe_svg_element(element: ET.Element) -> str:
    tag = _strip_namespace(element.tag)
    if tag not in SAFE_SVG_TAGS:
        return "".join(_render_safe_svg_element(child) for child in list(element))
    attrs = _safe_svg_attrs(element)
    text = html.escape(element.text or "")
    children = "".join(_render_safe_svg_element(child) for child in list(element))
    tail = html.escape(element.tail or "")
    if not text and not children:
        return f"<{tag}{attrs}/>{tail}"
    return f"<{tag}{attrs}>{text}{children}</{tag}>{tail}"


def sanitize_svg_markup(markup: str) -> str:
    text = safe_str(markup)
    if not text or len(text.encode("utf-8")) > 256 * 1024:
        return ""
    text = re.sub(r"^\s*<\?xml[^>]*>\s*", "", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ""
    if _strip_namespace(root.tag) != "svg":
        return ""
    rendered = _render_safe_svg_element(root)
    if "<svg" not in rendered:
        return ""
    if "viewBox=" not in rendered:
        rendered = rendered.replace("<svg", '<svg viewBox="0 0 100 100"', 1)
    if "preserveAspectRatio=" not in rendered:
        rendered = rendered.replace("<svg", '<svg preserveAspectRatio="xMidYMid meet"', 1)
    return rendered


def data_uri_from_bytes(mime_type: str, data: bytes) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def label_sheet_style(offset_x_mm: float, offset_y_mm: float, logo_uri: str) -> str:
    logo_display = "block" if APP_SHOW_BRAND_LOGO and logo_uri else "none"
    return f"""
    @page {{ size: A4 portrait; margin: 0; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: #17202a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; background: #fff; }}
    .sheet {{ width: 210mm; height: 297mm; display: grid; grid-template-columns: repeat(4, 52.5mm); grid-template-rows: repeat(10, 29.7mm); gap: 0; align-content: start; break-after: page; page-break-after: always; transform: translate({offset_x_mm:.2f}mm, {offset_y_mm:.2f}mm); transform-origin: top left; overflow: hidden; }}
    .sheet:last-of-type {{ break-after: auto; page-break-after: auto; }}
    .label-card {{ width: 52.5mm; height: 29.7mm; overflow: hidden; padding: 1.22mm 1.32mm; background: #fff; break-inside: avoid; page-break-inside: avoid; }}
    .label-frame {{ position: relative; width: 100%; height: 100%; overflow: hidden; border: .18mm solid #cbd5e1; border-radius: 2mm; background: #fff; }}
    .label-logo {{ display: {logo_display}; position: absolute; z-index: 3; top: 1mm; right: 2.2mm; width: 16.4mm; height: 5.8mm; background: url("{logo_uri}") center / contain no-repeat; }}
    .label-print-meta {{ position: absolute; z-index: 3; right: 2mm; bottom: .9mm; max-width: 30mm; overflow: hidden; color: #98a2b3; font-size: 4.1pt; font-style: normal; line-height: 1; white-space: nowrap; text-overflow: ellipsis; }}
    .component-frame {{ display: grid; grid-template-columns: 17mm minmax(0, 1fr); gap: 2.1mm; align-items: center; padding: 1.9mm 2.2mm 1.9mm 3.7mm; }}
    .label-card:nth-child(4n+1) .component-frame {{ gap: 1.55mm; padding-left: 5.9mm; padding-right: .95mm; }}
    .component-frame .qr {{ width: 16.7mm; height: 16.7mm; aspect-ratio: 1 / 1; padding: .16mm; background: #fff; }}
    .component-frame .qr svg {{ width: 16.38mm; height: 16.38mm; aspect-ratio: 1 / 1; display: block; }}
    .label-copy {{ min-width: 0; display: grid; align-content: center; gap: .42mm; padding: 2.35mm .1mm 2.05mm 0; }}
    .category-pill {{ justify-self: start; max-width: 18.5mm; overflow: hidden; padding: .34mm .82mm; border: .18mm solid #fed7aa; border-radius: 1.35mm; color: #c2410c; background: #fff7ed; font-size: 5pt; font-weight: 750; line-height: 1; white-space: nowrap; text-overflow: ellipsis; }}
    .label-code {{ overflow: hidden; color: #0f172a; font-size: 8.6pt; line-height: 1.02; font-weight: 850; letter-spacing: .02em; white-space: nowrap; text-overflow: ellipsis; }}
    .label-title {{ overflow: hidden; color: #111827; font-size: 6.7pt; line-height: 1.13; font-weight: 800; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }}
    .label-subtitle {{ overflow: hidden; color: #475467; font-size: 5.25pt; line-height: 1.1; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }}
    .component-frame.compact .label-copy {{ gap: .28mm; }}
    .component-frame.compact .label-code {{ font-size: 8pt; }}
    .component-frame.compact .label-title {{ font-size: 6.05pt; line-height: 1.06; }}
    .component-frame.compact .label-subtitle {{ font-size: 4.95pt; line-height: 1.04; }}
    .component-frame.micro .label-copy {{ gap: .2mm; padding-top: 2.15mm; }}
    .component-frame.micro .label-code {{ font-size: 7.3pt; }}
    .component-frame.micro .label-title {{ font-size: 5.45pt; line-height: 1.02; -webkit-line-clamp: 3; }}
    .component-frame.micro .label-subtitle {{ font-size: 4.55pt; line-height: 1.02; }}
    .custom-frame {{ padding: 1.6mm; }}
    .custom-canvas {{ position: relative; width: 100%; height: 100%; overflow: hidden; padding: 5.2mm 1mm 1.9mm; }}
    .custom-element {{ position: absolute; min-width: 0; overflow: hidden; overflow-wrap: anywhere; }}
    .custom-element img, .custom-element svg {{ width: 100%; height: 100%; object-fit: contain; display: block; }}
    .custom-text {{ display: flex; width: 100%; height: 100%; align-items: center; justify-content: center; text-align: center; white-space: pre-wrap; line-height: 1.18; }}
    .placeholder {{ visibility: hidden; }}
    .calibration-card .label-frame {{ position: relative; display: grid; grid-template-columns: 1fr; place-content: center; text-align: center; border-color: #111; }}
    .calibration-card strong {{ font-size: 10pt; }}
    .calibration-card small {{ font-size: 6pt; }}
    .calibration-cross::before, .calibration-cross::after {{ content: ""; position: absolute; left: 50%; top: 50%; background: #111; transform: translate(-50%, -50%); }}
    .calibration-cross::before {{ width: 12mm; height: .2mm; }}
    .calibration-cross::after {{ width: .2mm; height: 12mm; }}
    @media screen {{ body {{ padding: 12px; background: #f1f5f9; }} .sheet {{ margin: 0 auto 12px; background: #fff; box-shadow: 0 4px 20px rgba(15,23,42,.15); }} .label-frame {{ box-shadow: inset 0 0 0 .12mm rgba(59,130,246,.18); }} .print-tip {{ max-width: 210mm; margin: 0 auto 10px; color: #475467; font-size: 13px; }} }}
    @media print {{ .print-tip {{ display: none; }} .label-frame {{ border: .18mm solid #cbd5e1; border-radius: 2mm; outline: 0; box-shadow: none; }} .calibration-card .label-frame {{ border-color: #111; outline: .2mm solid #111; }} }}
    """


def paginate_label_cards(cards: list[str], start_slot: int) -> str:
    slots: list[str] = ['<article class="label-card placeholder"></article>'] * max(0, min(39, start_slot - 1))
    slots.extend(cards)
    sheets = []
    for offset in range(0, len(slots) or 1, 40):
        page = slots[offset: offset + 40]
        page.extend(['<article class="label-card placeholder"></article>'] * (40 - len(page)))
        sheets.append(f'<main class="sheet">{"".join(page)}</main>')
    return "".join(sheets)


def label_document(title: str, cards: list[str], start_slot: int, offset_x_mm: float, offset_y_mm: float, tip: str) -> str:
    logo_uri = logo_data_uri()
    sheets = paginate_label_cards(cards, start_slot)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>{label_sheet_style(offset_x_mm, offset_y_mm, logo_uri)}</style>
</head>
<body>
  <p class="print-tip">{html.escape(tip)}</p>
  {sheets}
</body>
</html>"""


def render_component_label_cards(
    records: list[dict],
    personal_base_url: str,
    *,
    copies: int = 1,
    calibration: bool = False,
    printed_at: str | None = None,
) -> list[str]:
    cards: list[str] = []
    printed_at = printed_at or print_timestamp()
    source_records = records
    if calibration:
        source_records = [
            {
                "warehouse_code": f"CAL-{index:02d}",
                "normalized_spec": f"校准格 {index}",
                "name": "52.5 × 29.7 mm",
                "package": "A4 40格",
                "category": {"name": "校准"},
            }
            for index in range(1, 41)
        ]
        copies = 1
    for record in source_records:
        code = safe_str(record_value(record, "warehouse_code"))
        if not code:
            continue
        title = label_title(record)
        subtitle = label_subtitle(record, title)
        category = category_name(record)
        density = component_label_density(code, title, subtitle)
        qr_svg = qr_svg_markup(component_scan_url(personal_base_url, code))
        card = f"""
            <article class="label-card">
              <div class="label-frame component-frame {density}">
                <i class="label-logo"></i>
                <div class="qr">{qr_svg}</div>
                <div class="label-copy">
                  <span class="category-pill">{html.escape(category)}</span>
                  <strong class="label-code">{html.escape(code)}</strong>
                  <b class="label-title">{html.escape(title)}</b>
                  <small class="label-subtitle">{html.escape(subtitle)}</small>
                </div>
                <em class="label-print-meta">{html.escape(printed_at)}</em>
              </div>
            </article>
            """
        if calibration:
            card = f"""
            <article class="label-card calibration-card">
              <div class="label-frame">
                <div class="calibration-cross"></div>
                <strong>{html.escape(title)}</strong>
                <small>第 {code[-2:]} 格 · 52.5 × 29.7 mm</small>
              </div>
            </article>
            """
        cards.extend([card] * max(1, copies))
    return cards


def render_component_label_sheet(
    records: list[dict],
    personal_base_url: str,
    *,
    start_slot: int = 1,
    copies: int = 1,
    offset_x_mm: float = 0,
    offset_y_mm: float = 0,
    calibration: bool = False,
    appended_cards: list[str] | None = None,
    printed_at: str | None = None,
) -> str:
    printed_at = printed_at or print_timestamp()
    cards = render_component_label_cards(
        records,
        personal_base_url,
        copies=copies,
        calibration=calibration,
        printed_at=printed_at,
    )
    if calibration:
        start_slot = 1
    else:
        cards.extend(appended_cards or [])
    return label_document(
        f"{APP_BRAND_NAME} 器件标签",
        cards,
        start_slot,
        offset_x_mm,
        offset_y_mm,
        f"A4 直角 40 格：52.5 × 29.7 mm，4列×10行。打印请选择“实际大小/100%”、无页边距、关闭页眉页脚，禁止“适合页面”。共 {len(cards)} 个标签。",
    )


def _safe_percent(value: object, fallback: float, low: float = -20, high: float = 120) -> float:
    try:
        number = float(value)
    except Exception:
        return fallback
    return max(low, min(high, number))


def _safe_color(value: object, fallback: str = "#111827") -> str:
    text = safe_str(value, fallback)
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", text):
        return text
    if re.fullmatch(r"rgba?\(\s*[\d.\s,%]+\)", text):
        return text
    return fallback


def custom_label_element_html(element: dict, asset_resolver=None) -> str:
    element_type = safe_str(element.get("type"), "text")
    x = _safe_percent(element.get("x"), 22)
    y = _safe_percent(element.get("y"), 34)
    width = _safe_percent(element.get("width"), 56, 1, 120)
    height = _safe_percent(element.get("height"), 30, 1, 120)
    rotate = max(-180, min(180, _safe_percent(element.get("rotate"), 0, -180, 180)))
    font_size = max(5, min(28, _safe_percent(element.get("font_size"), 13, 5, 28)))
    color = _safe_color(element.get("color"))
    align = safe_str(element.get("align"), "center")
    if align not in {"left", "center", "right"}:
        align = "center"
    style = (
        f"left:{x:.3f}%;top:{y:.3f}%;width:{width:.3f}%;height:{height:.3f}%;"
        f"transform:rotate({rotate:.2f}deg);"
    )
    if element_type == "text":
        text = safe_str(element.get("text"), "自定义标签")
        return (
            f'<div class="custom-element" style="{style}">'
            f'<div class="custom-text" style="font-size:{font_size:.1f}px;color:{color};text-align:{align};justify-content:'
            f'{"flex-start" if align == "left" else "flex-end" if align == "right" else "center"};">'
            f"{html.escape(text)}</div></div>"
        )
    asset_id = safe_str(element.get("asset_id"))
    data_uri = ""
    inline_svg = ""
    if asset_id and asset_resolver:
        asset = asset_resolver(asset_id)
        data_uri = asset.get("data_uri", "") if asset else ""
        inline_svg = asset.get("svg", "") if asset else ""
    elif element_type == "svg":
        inline_svg = sanitize_svg_markup(safe_str(element.get("svg")))
    if inline_svg:
        return f'<div class="custom-element" style="{style}">{inline_svg}</div>'
    if data_uri:
        return f'<div class="custom-element" style="{style}"><img src="{html.escape(data_uri, quote=True)}" alt="" /></div>'
    return ""


def render_custom_label_card(content: dict, asset_resolver=None, printed_at: str | None = None) -> str:
    printed_at = printed_at or print_timestamp()
    elements = content.get("elements") if isinstance(content, dict) else []
    if not isinstance(elements, list) or not elements:
        elements = [{"type": "text", "text": safe_str(content.get("text") if isinstance(content, dict) else "", "自定义标签"), "x": 18, "y": 33, "width": 64, "height": 30, "font_size": 16}]
    element_html = "".join(custom_label_element_html(item, asset_resolver) for item in elements if isinstance(item, dict))
    return f"""
    <article class="label-card">
      <div class="label-frame custom-frame">
        <i class="label-logo"></i>
        <div class="custom-canvas">{element_html}</div>
        <em class="label-print-meta">{html.escape(printed_at)}</em>
      </div>
    </article>
    """


def render_custom_label_cards(
    content: dict,
    *,
    asset_resolver=None,
    copies: int = 1,
    printed_at: str | None = None,
) -> list[str]:
    printed_at = printed_at or print_timestamp()
    card = render_custom_label_card(content or {}, asset_resolver, printed_at)
    return [card] * max(1, copies)


def render_custom_label_sheet(
    content: dict,
    *,
    asset_resolver=None,
    start_slot: int = 1,
    copies: int = 1,
    offset_x_mm: float = 0,
    offset_y_mm: float = 0,
    calibration: bool = False,
) -> str:
    printed_at = print_timestamp()
    if calibration:
        cards = [
            f"""
            <article class="label-card calibration-card">
              <div class="label-frame">
                <div class="calibration-cross"></div>
                <strong>校准格 {index}</strong>
                <small>第 {index:02d} 格 · 52.5 × 29.7 mm</small>
              </div>
            </article>
            """
            for index in range(1, 41)
        ]
        start_slot = 1
    else:
        cards = render_custom_label_cards(content or {}, asset_resolver=asset_resolver, copies=copies, printed_at=printed_at)
    return label_document(
        f"{APP_BRAND_NAME} 自定义标签",
        cards,
        start_slot,
        offset_x_mm,
        offset_y_mm,
        f"A4 直角 40 格自定义标签。打印请选择“实际大小/100%”、无页边距、关闭页眉页脚，禁止“适合页面”。共 {len(cards)} 个标签。",
    )
