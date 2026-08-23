import base64
import html
import io
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET

import qrcode
from qrcode.image.pure import PyPNGImage
from qrcode.image.svg import SvgPathImage

from .branding import APP_BRAND_NAME, APP_SHOW_BRAND_LOGO

LABEL_WIDTH_MM = 52.5
LABEL_HEIGHT_MM = 29.7
LABEL_COLUMN_PITCH_CORRECTION_MM = 0.40
LABEL_FIRST_COLUMN_OFFSET_MM = 0.10
LABEL_FIRST_COLUMN_LEFT_SAFE_INSET_MM = 0.45
LABEL_FIRST_ROW_TOP_SAFE_INSET_MM = 0.45
LABEL_LAST_ROW_BOTTOM_LIFT_MM = 0.65
LABEL_META_BOTTOM_INSET_MM = 1.45
LABEL_PDF_META_TOP_FROM_BOTTOM_MM = 2.85
CUSTOM_FONT_STACKS = {
    "system": '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
    "deyi": '"Smiley Sans", "smiley-sans", "得意黑", "Microsoft YaHei", sans-serif',
    "dingtalk": '"DingTalk JinBuTi", "钉钉进步体", "Microsoft YaHei", sans-serif',
    "misans": '"MiSans", "Microsoft YaHei", sans-serif',
    "noto": '"Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif',
    "mono": '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
}
CSS_PX_PER_MM = 96 / 25.4
FONT_ASSET_ROOT = os.path.join(os.path.dirname(__file__), "assets", "fonts")
FONT_ASSET_WEB_BASE = "/hardware/fonts"
LABEL_LOGO_URL = "/component-warehouse/api/assets/brand-logo-label.png?v=20260702b"
LABEL_LOGO_FILE = os.path.join(os.path.dirname(__file__), "assets", "brand-logo-label.png")
SERVER_RENDER_DPI = 300
DEFAULT_CATEGORY_COLORS = {"#eef6ff", "#eef2f7", "#eff6ff", "#f8fafc", "#ffffff", ""}
CATEGORY_FALLBACK_COLORS = {
    "电阻": "#DBEAFE",
    "电容": "#DCFCE7",
    "电感": "#FEF3C7",
    "二极管": "#FCE7F3",
    "三极管": "#E0E7FF",
    "MOS管": "#FFE4E6",
    "芯片": "#EDE9FE",
    "电源": "#FFEDD5",
    "接口": "#CCFBF1",
    "连接件": "#F5F5F4",
    "时钟源": "#E0F2FE",
    "开关": "#FAE8FF",
    "开发板": "#E5E7EB",
    "设备": "#E2E8F0",
    "功能模块": "#D1FAE5",
    "通信模块": "#CFFAFE",
    "显示模块": "#FDE68A",
    "机电件": "#FEE2E2",
    "散热件": "#E2E8F0",
    "保护器件": "#F5D0FE",
    "传感器": "#D9F99D",
    "结构件": "#E7E5E4",
    "其他": "#E5E7EB",
}
CUSTOM_LABEL_FIELD_PREVIEW_VALUES = {
    "warehouse_code": "RES-00000001",
    "name": "10k 电阻",
    "model": "0805W8F1002T5E",
    "category": "电阻",
    "package": "0805",
    "normalized_spec": "10kΩ",
    "lcsc_number": "C17414",
    "location": "A-01",
    "quantity": "100",
    "first_stocked_at": "2026-07-01",
    "last_stocked_at": "2026-07-01",
    "print_date": "2026-07-01",
    "scan_url": "https://wxy-lab.example/scan/RES-00000001",
}
STANDARD_CATEGORY_LABEL_KIND = "standard_category_group"
KNOWN_CATEGORY_NAMES = set(CATEGORY_FALLBACK_COLORS.keys())
MODEL_SUMMARY_CATEGORY_NAMES = {
    "开发板",
    "设备",
    "功能模块",
    "通信模块",
    "显示模块",
    "机电件",
    "传感器",
    "结构件",
}


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


def normalize_category_label_name(value: object) -> str:
    text = safe_str(value)
    if not text:
        return ""
    normalized = re.sub(r"\s+", "", text)
    for suffix in ("分类标签", "料盒标签", "标签", "分类", "料盒", "盒"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    if normalized in KNOWN_CATEGORY_NAMES:
        return normalized
    for name in sorted(KNOWN_CATEGORY_NAMES, key=len, reverse=True):
        if normalized.startswith(name):
            return name
    return text[:20]


def category_color(record: object, name: str) -> str:
    raw = ""
    category = record_value(record, "category")
    if isinstance(category, dict):
        raw = safe_str(category.get("color"))
    elif category is not None:
        raw = safe_str(record_value(category, "color"))
    raw = raw or safe_str(record_value(record, "category_color"))
    normalized = raw.lower()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", raw or "") or normalized in DEFAULT_CATEGORY_COLORS:
        return CATEGORY_FALLBACK_COLORS.get(name, CATEGORY_FALLBACK_COLORS["其他"])
    return raw


def readable_text_color(background: str) -> str:
    try:
        value = background.lstrip("#")
        red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except Exception:
        return "#1f2937"
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#111827" if luminance > 0.72 else "#ffffff"


def category_pill_style(record: object, name: str) -> str:
    background = category_color(record, name)
    text = readable_text_color(background)
    return f"background:{background};border-color:{background};color:{text};"


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


def is_resistor_record(record: object) -> bool:
    return category_name(record) == "电阻" or safe_str(record_value(record, "warehouse_code")).upper().startswith("RES-")


def normalize_zero_resistor_title(record: object, title: str) -> str:
    if not is_resistor_record(record):
        return title
    normalized = unicodedata.normalize("NFKC", safe_str(title)).strip()
    compact = re.sub(r"\s+", "", normalized).casefold()
    compact = compact.replace("ω", "Ω").replace("ohm", "Ω").replace("欧姆", "Ω").replace("欧", "Ω")
    if re.fullmatch(r"[+-]?0+(?:\.0+)?(?:Ω|r)?", compact):
        return "0Ω"
    return title


def label_title(record: dict) -> str:
    title = safe_str(
        record_value(record, "normalized_spec")
        or record_value(record, "model")
        or record_value(record, "name")
        or record_value(record, "warehouse_code"),
        "未命名器件",
    )[:72]
    return normalize_zero_resistor_title(record, title)


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


def label_logo_markup() -> str:
    if not APP_SHOW_BRAND_LOGO:
        return ""
    return f'<img class="label-logo" src="{LABEL_LOGO_URL}" alt="" loading="eager" decoding="sync" />'


def dingtalk_print_text_markup(value: str, class_name: str, max_chars: int = 24) -> str:
    text = safe_str(value)[: max(1, max_chars)]
    if not text:
        return ""
    safe_class = re.sub(r"[^a-zA-Z0-9_-]+", "", safe_str(class_name)) or "dingtalk-print-text"
    return (
        f'<strong class="{safe_class} dingtalk-print-text" '
        f'aria-label="{html.escape(text, quote=True)}">{html.escape(text)}</strong>'
    )


def _font_css_from_asset(font_key: str, filename: str) -> str:
    path = os.path.join(FONT_ASSET_ROOT, font_key, filename)
    try:
        with open(path, "r", encoding="utf-8") as font_file:
            css = font_file.read()
    except OSError:
        return f"@import url('{FONT_ASSET_WEB_BASE}/{font_key}/{filename}');"

    def absolute_font_url(match: re.Match) -> str:
        raw = safe_str(match.group(1))
        if not raw or raw.startswith(("data:", "http://", "https://", "/")):
            return f"url('{raw}')"
        return f"url('{FONT_ASSET_WEB_BASE}/{font_key}/{raw}')"

    return re.sub(r"url\(['\"]?([^'\")]+)['\"]?\)", absolute_font_url, css)


def custom_font_face_css(font_keys: set[str] | None = None) -> str:
    keys = {safe_str(key) for key in (font_keys or set())}
    faces: list[str] = []
    if "dingtalk" in keys:
        faces.append(_font_css_from_asset("dingtalk", "font.css"))
    if "misans" in keys:
        faces.append(_font_css_from_asset("misans", "MiSans.min.css"))
    if "deyi" in keys:
        faces.append(
            "@font-face { font-family: 'Smiley Sans'; "
            f"src: url('{FONT_ASSET_WEB_BASE}/deyi/SmileySans-Oblique.woff2') format('woff2'); font-display: swap; }}"
        )
        faces.append(
            "@font-face { font-family: 'smiley-sans'; "
            f"src: url('{FONT_ASSET_WEB_BASE}/deyi/SmileySans-Oblique.woff2') format('woff2'); font-display: swap; }}"
        )
        faces.append(
            "@font-face { font-family: '得意黑'; "
            f"src: url('{FONT_ASSET_WEB_BASE}/deyi/SmileySans-Oblique.woff2') format('woff2'); font-display: swap; }}"
        )
    return "\n".join(part for part in faces if part)


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


@lru_cache(maxsize=4096)
def qr_png_data_uri(value: str) -> str:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=1,
    )
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(image_factory=PyPNGImage)
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def component_scan_url(base_url: str, code: str) -> str:
    return f"{base_url.rstrip('/')}/scan/{quote(code)}"


def print_timestamp() -> str:
    try:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        now = datetime.now()
    return now.strftime("P:%Y-%m-%d %H:%M")


def date_label(value: object) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    text = safe_str(value)
    if not text:
        return ""
    return text[:10]


def stocked_label(record: object) -> str:
    stocked = date_label(record_value(record, "first_stocked_at")) or date_label(record_value(record, "created_at"))
    return f"入库 {stocked}" if stocked else ""


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


def raster_print_script() -> str:
    return """
    <script>
    (() => {
      const RASTER_SCALE = 2.15;
      const MIME_FALLBACK = 'application/octet-stream';
      const cache = new Map();
      const readAsDataUrl = (blob) => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error || new Error('read failed'));
        reader.readAsDataURL(blob);
      });
      async function resourceToDataUrl(url) {
        if (!url || url.startsWith('data:')) return url;
        const absolute = new URL(url, window.location.href).href;
        if (cache.has(absolute)) return cache.get(absolute);
        const promise = fetch(absolute, { credentials: 'same-origin' })
          .then((response) => {
            if (!response.ok) throw new Error(`resource ${response.status}`);
            return response.blob();
          })
          .then((blob) => readAsDataUrl(blob.type ? blob : new Blob([blob], { type: MIME_FALLBACK })));
        cache.set(absolute, promise);
        return promise;
      }
      async function inlineImages(root) {
        const images = Array.from(root.querySelectorAll('img'));
        await Promise.all(images.map(async (image) => {
          const src = image.getAttribute('src') || '';
          if (!src || src.startsWith('data:')) return;
          image.setAttribute('src', await resourceToDataUrl(src));
        }));
      }
      async function inlineFontUrls(cssText) {
        const urls = [...cssText.matchAll(/url\\(['"]?([^'")]+)['"]?\\)/g)]
          .map((match) => match[1])
          .filter((url) => url && !url.startsWith('data:'));
        const unique = [...new Set(urls)];
        for (const url of unique) {
          try {
            const dataUrl = await resourceToDataUrl(url);
            cssText = cssText.split(url).join(dataUrl);
          } catch (error) {
            console.warn('Font inline failed', url, error);
          }
        }
        return cssText;
      }
      function loadImage(url) {
        return new Promise((resolve, reject) => {
          const image = new Image();
          image.onload = () => resolve(image);
          image.onerror = () => reject(new Error('raster image load failed'));
          image.src = url;
        });
      }
      function serializeSheet(sheet, cssText) {
        const root = document.createElement('div');
        root.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
        const style = document.createElement('style');
        style.textContent = `${cssText}
          body { margin: 0 !important; padding: 0 !important; background: #fff !important; }
          .sheet { margin: 0 !important; box-shadow: none !important; }
          .label-frame { box-shadow: none !important; }`;
        root.appendChild(style);
        root.appendChild(sheet);
        return new XMLSerializer().serializeToString(root);
      }
      async function rasterizeSheet(sheet, cssText, index) {
        const clone = sheet.cloneNode(true);
        await inlineImages(clone);
        const cssWidth = 210 * 96 / 25.4;
        const cssHeight = 297 * 96 / 25.4;
        const pixelWidth = Math.round(cssWidth * RASTER_SCALE);
        const pixelHeight = Math.round(cssHeight * RASTER_SCALE);
        const xhtml = serializeSheet(clone, cssText);
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${pixelWidth}" height="${pixelHeight}" viewBox="0 0 ${cssWidth} ${cssHeight}"><foreignObject width="${cssWidth}" height="${cssHeight}">${xhtml}</foreignObject></svg>`;
        const svgUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
        const image = await loadImage(svgUrl);
        const canvas = document.createElement('canvas');
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
        const context = canvas.getContext('2d', { alpha: false });
        context.fillStyle = '#fff';
        context.fillRect(0, 0, pixelWidth, pixelHeight);
        context.drawImage(image, 0, 0, pixelWidth, pixelHeight);
        const output = document.createElement('img');
        output.className = 'raster-sheet';
        output.alt = `打印图片页 ${index + 1}`;
        output.width = pixelWidth;
        output.height = pixelHeight;
        output.src = canvas.toDataURL('image/png');
        return output;
      }
      async function rasterizeForPrint() {
        const sheets = Array.from(document.querySelectorAll('.sheet'));
        if (!sheets.length || document.body.classList.contains('raster-ready')) return;
        document.body.classList.add('rasterizing');
        const tip = document.querySelector('.print-tip');
        if (tip) tip.dataset.rasterStatus = '正在生成图片打印版...';
        if (document.fonts && document.fonts.ready) await document.fonts.ready;
        await Promise.all(Array.from(document.images).map((image) => image.decode ? image.decode().catch(() => {}) : Promise.resolve()));
        const rawCss = document.getElementById('label-style')?.textContent || '';
        const cssText = await inlineFontUrls(rawCss);
        const output = document.createElement('div');
        output.className = 'raster-output';
        for (let index = 0; index < sheets.length; index += 1) {
          output.appendChild(await rasterizeSheet(sheets[index], cssText, index));
        }
        document.body.appendChild(output);
        document.body.classList.remove('rasterizing');
        document.body.classList.add('raster-ready');
        if (tip) tip.dataset.rasterStatus = '已生成图片打印版，可直接打印。';
      }
      window.__cwRasterizeLabels = rasterizeForPrint;
      window.addEventListener('DOMContentLoaded', () => {
        rasterizeForPrint().catch((error) => {
          document.body.classList.remove('rasterizing');
          document.body.classList.add('raster-failed');
          const tip = document.querySelector('.print-tip');
          if (tip) tip.dataset.rasterStatus = '图片打印版生成失败，已保留普通打印版。';
          console.error(error);
        });
      });
    })();
    </script>
    """


def label_sheet_style(offset_x_mm: float, offset_y_mm: float, safe_margin: bool = True, font_keys: set[str] | None = None) -> str:
    logo_display = "block" if APP_SHOW_BRAND_LOGO else "none"
    label_padding = "2.15mm 2.15mm" if safe_margin else "1.75mm 1.75mm"
    outer_x_padding_value = 4.8 if safe_margin else 3.6
    outer_x_padding = f"{outer_x_padding_value:.1f}mm"
    first_column_outer_left_padding = f"{outer_x_padding_value + LABEL_FIRST_COLUMN_LEFT_SAFE_INSET_MM:.2f}mm"
    outer_y_padding_value = 3.4 if safe_margin else 2.7
    outer_y_padding = f"{outer_y_padding_value:.1f}mm"
    first_row_top_padding = f"{outer_y_padding_value + LABEL_FIRST_ROW_TOP_SAFE_INSET_MM:.2f}mm"
    last_row_bottom_padding = f"{outer_y_padding_value + LABEL_LAST_ROW_BOTTOM_LIFT_MM:.1f}mm"
    component_padding = "2.15mm 1.55mm 1.95mm 2.05mm" if safe_margin else "1.9mm 1.3mm 1.75mm 1.75mm"
    first_column_padding = "2.6mm" if safe_margin else "2.05mm"
    first_column_right = "1.25mm" if safe_margin else "1.05mm"
    return f"""
    {custom_font_face_css(font_keys)}
    @page {{ size: A4 portrait; margin: 0; }}
    * {{ box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    body {{ margin: 0; color: #17202a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; background: #fff; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .sheet {{ width: 210mm; height: 297mm; display: grid; grid-template-columns: repeat(4, 52.5mm); grid-template-rows: repeat(10, 29.7mm); gap: 0; align-content: start; break-after: page; page-break-after: always; transform: translate({offset_x_mm:.2f}mm, {offset_y_mm:.2f}mm); transform-origin: top left; overflow: hidden; background: #fff; }}
    .sheet:last-of-type {{ break-after: auto; page-break-after: auto; }}
    .label-card {{ width: 52.5mm; height: 29.7mm; overflow: hidden; padding: {label_padding}; background: #fff; break-inside: avoid; page-break-inside: avoid; }}
    .label-card:nth-child(4n+1) {{ padding-left: {first_column_outer_left_padding}; }}
    .label-card:nth-child(4n) {{ padding-right: {outer_x_padding}; }}
    .label-card:nth-child(-n+4) {{ padding-top: {first_row_top_padding}; }}
    .label-card:nth-last-child(-n+4) {{ padding-bottom: {outer_y_padding}; }}
    .label-card:nth-child(n+37) {{ padding-bottom: {last_row_bottom_padding}; }}
    .label-card:nth-child(4n+1) {{ transform: translateX({LABEL_FIRST_COLUMN_OFFSET_MM:.2f}mm); }}
    .label-card:nth-child(4n+2) {{ transform: translateX(-{LABEL_COLUMN_PITCH_CORRECTION_MM:.2f}mm); }}
    .label-card:nth-child(4n+3) {{ transform: translateX(-{LABEL_COLUMN_PITCH_CORRECTION_MM * 2:.2f}mm); }}
    .label-card:nth-child(4n) {{ transform: translateX(-{LABEL_COLUMN_PITCH_CORRECTION_MM * 3:.2f}mm); }}
    .label-frame {{ position: relative; width: 100%; height: 100%; overflow: hidden; border: .18mm solid #cbd5e1; border-radius: 2mm; background: #fff; }}
    .label-logo {{ display: {logo_display}; position: absolute; z-index: 3; top: .75mm; right: .95mm; width: 10.2mm; height: 3.8mm; object-fit: contain; border: 0; background: transparent; }}
    .label-print-meta {{ position: absolute; z-index: 3; right: 1.25mm; bottom: {LABEL_META_BOTTOM_INSET_MM:.2f}mm; max-width: 22mm; overflow: hidden; color: #64748b; font-size: 3.75pt; font-style: normal; line-height: 1; white-space: nowrap; text-overflow: ellipsis; }}
    .label-stock-meta {{ position: absolute; z-index: 3; left: 1.25mm; bottom: {LABEL_META_BOTTOM_INSET_MM:.2f}mm; max-width: 19mm; overflow: hidden; color: #64748b; font-size: 3.75pt; font-style: normal; line-height: 1; white-space: nowrap; text-overflow: ellipsis; }}
    .component-frame {{ display: grid; grid-template-columns: 13.4mm minmax(0, 1fr); gap: 1.2mm; align-items: center; padding: {component_padding}; }}
    .label-card:nth-child(4n+1) .component-frame {{ gap: 1.05mm; padding-left: {first_column_padding}; padding-right: {first_column_right}; }}
    .component-frame .qr {{ width: 13.2mm; height: 13.2mm; aspect-ratio: 1 / 1; padding: .1mm; background: #fff; }}
    .component-frame .qr img {{ width: 13mm; height: 13mm; aspect-ratio: 1 / 1; display: block; image-rendering: pixelated; }}
    .label-copy {{ min-width: 0; display: grid; align-content: center; gap: .28mm; padding: .65mm .15mm .6mm 0; }}
    .label-copy-header {{ min-width: 0; display: grid; gap: .34mm; }}
    .category-pill {{ justify-self: start; min-width: 0; max-width: 17.2mm; overflow: hidden; padding: .22mm .62mm; border: .18mm solid #bfdbfe; border-radius: 1.2mm; color: #1d4ed8; background: #eff6ff; font-size: 4.1pt; font-weight: 780; line-height: 1; white-space: nowrap; text-overflow: ellipsis; }}
    .label-code {{ display: block; min-width: 0; width: 100%; overflow: visible; color: #000; font-size: 7.2pt; line-height: 1.02; font-weight: 920; letter-spacing: 0; white-space: nowrap; text-overflow: clip; }}
    .dingtalk-print-text {{ font-family: "DingTalk JinBuTi", "钉钉进步体", "Microsoft YaHei", sans-serif; font-synthesis: none; }}
    .label-title {{ overflow: hidden; color: #000; font-size: 6.15pt; line-height: 1.08; font-weight: 860; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }}
    .label-subtitle {{ overflow: hidden; color: #334155; font-size: 4.75pt; line-height: 1.06; font-weight: 650; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }}
    .component-frame.compact .label-copy {{ gap: .22mm; }}
    .component-frame.compact .label-code {{ font-size: 6.9pt; }}
    .component-frame.compact .label-title {{ font-size: 5.6pt; line-height: 1.04; }}
    .component-frame.compact .label-subtitle {{ font-size: 4.45pt; line-height: 1.03; }}
    .component-frame.micro .label-copy {{ gap: .18mm; padding-top: 1.45mm; }}
    .component-frame.micro .label-code {{ font-size: 6.45pt; }}
    .component-frame.micro .label-title {{ font-size: 5.05pt; line-height: 1.02; -webkit-line-clamp: 3; }}
    .component-frame.micro .label-subtitle {{ font-size: 4.1pt; line-height: 1.02; }}
    .custom-label-card {{ padding: {label_padding}; }}
    .custom-frame {{ width: 100%; height: 100%; padding: 0; }}
    .custom-canvas {{ position: absolute; inset: 0; width: 100%; height: 100%; overflow: hidden; padding: 0; }}
    .custom-frame.without-logo .label-logo {{ display: none; }}
    .custom-element {{ position: absolute; min-width: 0; overflow: hidden; overflow-wrap: anywhere; }}
    .custom-element img, .custom-element svg {{ width: 100%; height: 100%; object-fit: contain; display: block; }}
    .custom-text {{ display: flex; width: 100%; height: 100%; align-items: center; justify-content: center; text-align: center; white-space: pre-wrap; line-height: 1.18; }}
    .standard-category-frame {{ display: grid; grid-template-rows: 4.6mm minmax(0, 1fr) 5.8mm; gap: .85mm; padding: 2.15mm 2.55mm 2.05mm; font-family: "DingTalk JinBuTi", "钉钉进步体", "Microsoft YaHei", sans-serif; font-synthesis: none; text-align: center; }}
    .standard-category-kicker {{ display: flex; align-items: center; justify-content: space-between; width: 100%; padding-right: 12.8mm; color: #475569; font-size: 1.95mm; font-weight: 400; line-height: 1; white-space: nowrap; }}
    .standard-category-kicker b {{ color: #111827; font-weight: 400; }}
    .standard-category-title-band {{ display: grid; place-items: center; min-width: 0; min-height: 0; width: 100%; border-top: .18mm solid #d8dee8; border-bottom: .18mm solid #d8dee8; }}
    .standard-category-title {{ max-width: 45.2mm; overflow: hidden; color: #000; font-size: 7.7mm; font-weight: 400; line-height: 1; letter-spacing: 0; white-space: nowrap; text-overflow: ellipsis; }}
    .standard-category-package {{ display: -webkit-box; max-width: 45mm; max-height: 5.7mm; overflow: hidden; align-self: start; justify-self: center; color: #111827; font-size: 2.42mm; font-weight: 400; line-height: 1.12; letter-spacing: 0; white-space: normal; text-overflow: ellipsis; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }}
    .placeholder {{ visibility: hidden; }}
    .calibration-card .label-frame {{ position: relative; display: grid; grid-template-columns: 1fr; place-content: center; text-align: center; border-color: #111; }}
    .calibration-card strong {{ font-size: 10pt; }}
    .calibration-card small {{ font-size: 6pt; }}
    .calibration-cross::before, .calibration-cross::after {{ content: ""; position: absolute; left: 50%; top: 50%; background: #111; transform: translate(-50%, -50%); }}
    .calibration-cross::before {{ width: 12mm; height: .2mm; }}
    .calibration-cross::after {{ width: .2mm; height: 12mm; }}
    .raster-output {{ display: none; }}
    .raster-sheet {{ display: block; width: 210mm; height: 297mm; object-fit: contain; background: #fff; break-after: page; page-break-after: always; }}
    .raster-sheet:last-child {{ break-after: auto; page-break-after: auto; }}
    body.raster-ready .sheet {{ display: none; }}
    body.raster-ready .raster-output {{ display: block; width: 210mm; margin: 0 auto; }}
    .print-tip::after {{ content: attr(data-raster-status); display: block; margin-top: 4px; color: #0f766e; font-weight: 700; }}
    body.raster-failed .print-tip::after {{ color: #b42318; }}
    @media screen {{ body {{ padding: 12px; background: #f1f5f9; }} .sheet, .raster-sheet {{ margin: 0 auto 12px; background: #fff; box-shadow: 0 4px 20px rgba(15,23,42,.15); }} .label-frame {{ box-shadow: inset 0 0 0 .12mm rgba(59,130,246,.18); }} .print-tip {{ max-width: 210mm; margin: 0 auto 10px; color: #475467; font-size: 13px; }} }}
    @media print {{ .print-tip {{ display: none; }} body {{ padding: 0 !important; background: #fff !important; }} body.raster-ready .raster-output {{ width: 210mm; margin: 0; }} body.raster-ready .raster-sheet {{ width: 210mm; height: 297mm; margin: 0; box-shadow: none; }} img, svg {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }} .label-frame {{ border: .18mm solid #cbd5e1; border-radius: 2mm; outline: 0; box-shadow: none; }} .calibration-card .label-frame {{ border-color: #111; outline: .2mm solid #111; }} }}
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


def label_document(title: str, cards: list[str], start_slot: int, offset_x_mm: float, offset_y_mm: float, tip: str, safe_margin: bool = True, font_keys: set[str] | None = None) -> str:
    sheets = paginate_label_cards(cards, start_slot)
    return f"""<!doctype html>
<html lang="zh-CN" translate="no" class="notranslate">
<head>
  <meta charset="utf-8" />
  <meta name="google" content="notranslate" />
  <title>{html.escape(title)}</title>
  <style id="label-style">{label_sheet_style(offset_x_mm, offset_y_mm, safe_margin=safe_margin, font_keys=font_keys)}</style>
</head>
<body class="notranslate" translate="no">
  <p class="print-tip">{html.escape(tip)}</p>
  {sheets}
  {raster_print_script()}
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
        category_style = category_pill_style(record, category)
        density = component_label_density(code, title, subtitle)
        qr_uri = qr_png_data_uri(component_scan_url(personal_base_url, code))
        stocked = stocked_label(record)
        code_markup = dingtalk_print_text_markup(code, "label-code", 24) or f'<strong class="label-code">{html.escape(code)}</strong>'
        card = f"""
            <article class="label-card">
              <div class="label-frame component-frame {density}">
                {label_logo_markup()}
                <div class="qr"><img src="{html.escape(qr_uri, quote=True)}" alt="" /></div>
                <div class="label-copy">
                  <span class="label-copy-header">
                    <span class="category-pill" style="{html.escape(category_style, quote=True)}">{html.escape(category)}</span>
                    {code_markup}
                  </span>
                  <b class="label-title">{html.escape(title)}</b>
                  <small class="label-subtitle">{html.escape(subtitle)}</small>
                </div>
                <em class="label-stock-meta">{html.escape(stocked)}</em>
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


def _mm(value: float, dpi: int = SERVER_RENDER_DPI) -> int:
    return int(round(value * dpi / 25.4))


def _label_column_left_mm(col: int, offset_x_mm: float = 0) -> float:
    return offset_x_mm + col * (LABEL_WIDTH_MM - LABEL_COLUMN_PITCH_CORRECTION_MM)


@lru_cache(maxsize=32)
def _pdf_font_from_path(path: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(path, size=size)


@lru_cache(maxsize=1)
def _server_font_paths() -> dict[str, str]:
    paths: dict[str, str] = {}
    cache_dir = Path(tempfile.gettempdir()) / "cw-label-font-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dingtalk_ttf = cache_dir / "DingTalk-JinBuTi-merged.ttf"
    dingtalk_parts = sorted((Path(FONT_ASSET_ROOT) / "dingtalk").glob("*.woff2"))
    symbol_font = Path(FONT_ASSET_ROOT) / "misans" / "MiSans.73.woff2"
    if dingtalk_parts and not dingtalk_ttf.exists():
        try:
            from fontTools.merge import Merger

            font = Merger().merge([str(path) for path in dingtalk_parts])
            font.flavor = None
            font.save(str(dingtalk_ttf))
        except Exception:
            pass
    if dingtalk_ttf.exists():
        paths["dingtalk"] = str(dingtalk_ttf)
        paths["default"] = str(dingtalk_ttf)
        paths["bold"] = str(dingtalk_ttf)
    if symbol_font.exists():
        symbol_ttf = cache_dir / "MiSans-symbols.ttf"
        if not symbol_ttf.exists():
            try:
                from fontTools.ttLib import TTFont

                font = TTFont(str(symbol_font))
                font.flavor = None
                font.save(str(symbol_ttf))
            except Exception:
                pass
        if symbol_ttf.exists():
            paths["symbol"] = str(symbol_ttf)
    return paths


def _server_font(size: int, *, bold: bool = False, dingtalk: bool = False):
    paths = _server_font_paths()
    if dingtalk and paths.get("dingtalk"):
        return _pdf_font_from_path(paths["dingtalk"], size)
    if bold and paths.get("bold"):
        return _pdf_font_from_path(paths["bold"], size)
    if paths.get("default"):
        return _pdf_font_from_path(paths["default"], size)
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


PDF_SYMBOL_FONT_CHARS = {"Ω", "Ω"}


def _native_text_size(draw, text: str, font) -> tuple[int, int]:
    if not text:
        return (0, 0)
    box = draw.textbbox((0, 0), text, font=font)
    return (max(0, box[2] - box[0]), max(0, box[3] - box[1]))


def _pdf_symbol_font(font):
    paths = _server_font_paths()
    if paths.get("symbol"):
        return _pdf_font_from_path(paths["symbol"], getattr(font, "size", 10))
    return font


def _pdf_symbol_font_char(char: str) -> str:
    return "Ω" if char == "Ω" else char


def _text_size(draw, text: str, font) -> tuple[int, int]:
    if not text:
        return (0, 0)
    if not any(char in PDF_SYMBOL_FONT_CHARS for char in text):
        return _native_text_size(draw, text, font)
    width = 0
    height = 0
    chunk = ""
    symbol_font = _pdf_symbol_font(font)
    for char in text:
        if char in PDF_SYMBOL_FONT_CHARS:
            if chunk:
                chunk_w, chunk_h = _native_text_size(draw, chunk, font)
                width += chunk_w
                height = max(height, chunk_h)
                chunk = ""
            symbol_w, symbol_h = _native_text_size(draw, _pdf_symbol_font_char(char), symbol_font)
            width += symbol_w
            height = max(height, symbol_h)
        else:
            chunk += char
    if chunk:
        chunk_w, chunk_h = _native_text_size(draw, chunk, font)
        width += chunk_w
        height = max(height, chunk_h)
    return (width, height)


def _draw_pdf_text(draw, xy: tuple[int, int], text: str, font, fill: str):
    if not any(char in PDF_SYMBOL_FONT_CHARS for char in safe_str(text)):
        draw.text(xy, text, font=font, fill=fill)
        return
    x, y = xy
    chunk = ""
    symbol_font = _pdf_symbol_font(font)
    for char in safe_str(text):
        if char in PDF_SYMBOL_FONT_CHARS:
            if chunk:
                draw.text((x, y), chunk, font=font, fill=fill)
                x += _native_text_size(draw, chunk, font)[0]
                chunk = ""
            symbol_char = _pdf_symbol_font_char(char)
            draw.text((x, y), symbol_char, font=symbol_font, fill=fill)
            x += _native_text_size(draw, symbol_char, symbol_font)[0]
        else:
            chunk += char
    if chunk:
        draw.text((x, y), chunk, font=font, fill=fill)


def _line_advance(font, factor: float = 1.08) -> int:
    return max(1, int(round(getattr(font, "size", 10) * factor)))


def _fit_text(text: str, max_width: int, draw, font, suffix: str = "...") -> str:
    text = safe_str(text)
    if _text_size(draw, text, font)[0] <= max_width:
        return text
    suffix_width = _text_size(draw, suffix, font)[0]
    result = ""
    for char in text:
        if _text_size(draw, result + char, font)[0] + suffix_width > max_width:
            break
        result += char
    return (result.rstrip() + suffix) if result else suffix


def _wrap_lines(text: str, max_width: int, max_lines: int, draw, font) -> list[str]:
    text = safe_str(text)
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_size(draw, candidate, font)[0] > max_width:
            lines.append(current.rstrip())
            current = char
            if len(lines) >= max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current.rstrip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines and _text_size(draw, lines[-1], font)[0] > max_width:
        lines[-1] = _fit_text(lines[-1], max_width, draw, font)
    elif len(lines) == max_lines and len("".join(lines)) < len(text):
        lines[-1] = _fit_text(lines[-1], max_width, draw, font)
    return lines


@lru_cache(maxsize=1024)
def _qr_pdf_image(value: str, size_px: int):
    from PIL import Image

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1, box_size=8)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return image.resize((size_px, size_px), Image.Resampling.NEAREST)


def _prepare_pdf_print_page(page):
    from PIL import ImageEnhance

    page = ImageEnhance.Contrast(page).enhance(1.18)
    page = ImageEnhance.Sharpness(page).enhance(1.25)
    return page


@lru_cache(maxsize=1)
def _logo_pdf_image():
    try:
        from PIL import Image

        return Image.open(LABEL_LOGO_FILE).convert("RGBA")
    except Exception:
        return None


def _draw_component_pdf_card(draw, page, record: dict, personal_base_url: str, bounds: tuple[int, int, int, int], printed_at: str):
    from PIL import Image

    left, top, right, bottom = bounds
    radius = _mm(2)
    draw.rounded_rectangle((left, top, right, bottom), radius=radius, fill="white", outline="#cbd5e1", width=max(1, _mm(.18)))

    logo = _logo_pdf_image()
    if APP_SHOW_BRAND_LOGO and logo:
        logo_w, logo_h = _mm(10.2), _mm(3.8)
        logo_img = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        page.paste(logo_img, (right - _mm(.95) - logo_w, top + _mm(.75)), logo_img)

    code = safe_str(record_value(record, "warehouse_code"))
    title = label_title(record)
    subtitle = label_subtitle(record, title)
    category = category_name(record)
    category_bg = category_color(record, category)
    category_fg = readable_text_color(category_bg)
    stocked = stocked_label(record)

    content_left = left + _mm(2.25)
    content_right = right - _mm(1.85)
    qr_size = _mm(13.45)
    qr_x = content_left
    qr_y = top + ((bottom - top) - qr_size) // 2
    page.paste(_qr_pdf_image(component_scan_url(personal_base_url, code), qr_size), (qr_x, qr_y))

    text_x = qr_x + qr_size + _mm(1.45)
    text_right = content_right
    text_width = max(1, text_right - text_x)

    small_font = _server_font(max(7, _mm(1.55)), bold=True)
    code_font = _server_font(max(9, _mm(2.05)), dingtalk=True)
    title_font = _server_font(max(12, _mm(2.75)), bold=True)
    subtitle_font = _server_font(max(7, _mm(1.55)), bold=True)
    meta_font = _server_font(max(5, _mm(1.1)))

    pill_text = _fit_text(category, _mm(17.2), draw, small_font)
    pill_w = _text_size(draw, pill_text, small_font)[0] + _mm(1.25)
    pill_h = _mm(2.65)
    title_lines = _wrap_lines(title, text_width, 2, draw, title_font)
    subtitle_lines = _wrap_lines(subtitle, text_width, 2, draw, subtitle_font)
    code_line = _fit_text(code, text_width, draw, code_font)
    text_block_height = (
        pill_h
        + _mm(.42)
        + _line_advance(code_font, 1.03)
        + _mm(.25)
        + len(title_lines) * _line_advance(title_font, 1.06)
        + (max(0, len(title_lines) - 1) * _mm(.08))
        + (len(subtitle_lines) * _line_advance(subtitle_font, 1.02) if subtitle_lines else 0)
    )
    available_top = top + _mm(4.7)
    available_bottom = bottom - _mm(3.0)
    y = max(available_top, top + ((bottom - top) - text_block_height) // 2 - _mm(.6))
    if y + text_block_height > available_bottom:
        y = max(available_top, available_bottom - text_block_height)
    draw.rounded_rectangle((text_x, y, text_x + pill_w, y + pill_h), radius=_mm(.8), fill=category_bg, outline=category_bg)
    draw.text((text_x + _mm(.55), y + _mm(.34)), pill_text, font=small_font, fill=category_fg)
    y += pill_h + _mm(.42)

    draw.text((text_x, y), code_line, font=code_font, fill="#000000")
    y += _line_advance(code_font, 1.03) + _mm(.25)

    for line in title_lines:
        _draw_pdf_text(draw, (text_x, y), line, font=title_font, fill="#000000")
        y += _line_advance(title_font, 1.06) + _mm(.08)
    for line in subtitle_lines:
        if y > bottom - _mm(4.4):
            break
        draw.text((text_x, y), line, font=subtitle_font, fill="#334155")
        y += _line_advance(subtitle_font, 1.02)

    draw.text((left + _mm(1.25), bottom - _mm(LABEL_PDF_META_TOP_FROM_BOTTOM_MM)), _fit_text(stocked, _mm(19), draw, meta_font), font=meta_font, fill="#64748b")
    meta = _fit_text(printed_at, _mm(22), draw, meta_font)
    meta_w = _text_size(draw, meta, meta_font)[0]
    draw.text((right - _mm(1.25) - meta_w, bottom - _mm(LABEL_PDF_META_TOP_FROM_BOTTOM_MM)), meta, font=meta_font, fill="#64748b")


def _draw_standard_category_pdf_card(draw, page, item: dict, bounds: tuple[int, int, int, int], printed_at: str):
    from PIL import Image

    left, top, right, bottom = bounds
    draw.rounded_rectangle((left, top, right, bottom), radius=_mm(2), fill="white", outline="#cbd5e1", width=max(1, _mm(.18)))
    logo = _logo_pdf_image()
    if APP_SHOW_BRAND_LOGO and logo:
        logo_w, logo_h = _mm(10.2), _mm(3.8)
        logo_img = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        page.paste(logo_img, (right - _mm(.95) - logo_w, top + _mm(.75)), logo_img)

    category = safe_str(item.get("category"), "元器件")
    packages = safe_str(item.get("packages"))
    summary_label = safe_str(item.get("summary_label"), "封装")
    kicker_font = _server_font(max(7, _mm(1.75)), bold=True)
    title_font = _server_font(max(24, _mm(6.9)), dingtalk=True)
    package_font = _server_font(max(8, _mm(1.82)), bold=True)
    meta_font = _server_font(max(5, _mm(1.1)))

    inner_left = left + _mm(2.6)
    inner_right = right - _mm(2.6)
    draw.text((inner_left, top + _mm(2.55)), "分类标签", font=kicker_font, fill="#475569")
    right_text = "常用料盒"
    right_w = _text_size(draw, right_text, kicker_font)[0]
    draw.text((right - _mm(13.2) - right_w, top + _mm(2.55)), right_text, font=kicker_font, fill="#475569")

    band_top = top + _mm(8.0)
    band_bottom = bottom - _mm(7.9)
    draw.line((inner_left, band_top, inner_right, band_top), fill="#d8dee8", width=max(1, _mm(.18)))
    draw.line((inner_left, band_bottom, inner_right, band_bottom), fill="#d8dee8", width=max(1, _mm(.18)))
    title = _fit_text(category, inner_right - inner_left, draw, title_font)
    title_w, title_h = _text_size(draw, title, title_font)
    draw.text((left + ((right - left) - title_w) // 2, band_top + ((band_bottom - band_top) - title_h) // 2 - _mm(.25)), title, font=title_font, fill="#000000")

    package_text = _wrap_lines(f"{summary_label} {packages}", inner_right - inner_left - _mm(2.0), 2, draw, package_font)
    max_package_bottom = bottom - _mm(3.65)
    line_height = _line_advance(package_font, .96)
    package_height = len(package_text) * line_height
    y = min(band_bottom + _mm(.75), max_package_bottom - package_height)
    y = max(band_bottom + _mm(.45), y)
    for line in package_text:
        line_w = _text_size(draw, line, package_font)[0]
        draw.text((left + ((right - left) - line_w) // 2, y), line, font=package_font, fill="#111827")
        y += line_height

    meta = _fit_text(printed_at, _mm(22), draw, meta_font)
    meta_w = _text_size(draw, meta, meta_font)[0]
    draw.text((right - _mm(1.25) - meta_w, bottom - _mm(LABEL_PDF_META_TOP_FROM_BOTTOM_MM)), meta, font=meta_font, fill="#64748b")


def _draw_basic_custom_pdf_card(draw, page, item: dict, bounds: tuple[int, int, int, int], printed_at: str):
    from PIL import Image

    left, top, right, bottom = bounds
    draw.rounded_rectangle((left, top, right, bottom), radius=_mm(2), fill="white", outline="#cbd5e1", width=max(1, _mm(.18)))
    logo = _logo_pdf_image()
    if APP_SHOW_BRAND_LOGO and logo and item.get("show_logo", True):
        logo_w, logo_h = _mm(10.2), _mm(3.8)
        logo_img = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        page.paste(logo_img, (right - _mm(.95) - logo_w, top + _mm(.75)), logo_img)
    title_font = _server_font(max(18, _mm(4.8)), dingtalk=True)
    small_font = _server_font(max(9, _mm(2.05)), bold=True)
    meta_font = _server_font(max(5, _mm(1.1)))
    title = _fit_text(safe_str(item.get("title"), "自定义标签"), right - left - _mm(6), draw, title_font)
    detail = _fit_text(safe_str(item.get("detail")), right - left - _mm(6), draw, small_font)
    title_w, title_h = _text_size(draw, title, title_font)
    y = top + ((bottom - top) - title_h - ( _line_advance(small_font) if detail else 0)) // 2
    draw.text((left + ((right - left) - title_w) // 2, y), title, font=title_font, fill="#000000")
    if detail:
        y += _line_advance(title_font, 1.05)
        detail_w = _text_size(draw, detail, small_font)[0]
        draw.text((left + ((right - left) - detail_w) // 2, y), detail, font=small_font, fill="#334155")
    meta = _fit_text(printed_at, _mm(22), draw, meta_font)
    meta_w = _text_size(draw, meta, meta_font)[0]
    draw.text((right - _mm(1.25) - meta_w, bottom - _mm(LABEL_PDF_META_TOP_FROM_BOTTOM_MM)), meta, font=meta_font, fill="#64748b")


def render_standard_category_label_pdf_items(content: dict, package_summary: dict[str, str], *, copies: int = 1) -> list[dict]:
    styles = content.get("styles") if isinstance(content, dict) else []
    if not isinstance(styles, list) or not styles:
        styles = [{"category_name": "元器件"}]
    items: list[dict] = []
    for style in styles:
        if not isinstance(style, dict):
            continue
        category = style_category_name(style) or "元器件"
        packages = package_summary.get(category)
        if not packages:
            continue
        summary_label = "型号" if category in MODEL_SUMMARY_CATEGORY_NAMES else "封装"
        item = {"type": "standard_category", "category": category, "packages": packages, "summary_label": summary_label}
        items.extend([item] * max(1, copies))
    return items


def render_basic_custom_label_pdf_items(content: dict, *, copies: int = 1) -> list[dict]:
    elements = content.get("elements") if isinstance(content, dict) else []
    title = ""
    detail = ""
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_type = safe_str(element.get("type"), "text")
            text = safe_str(element.get("text"))
            if element_type == "text" and text and not title:
                title = text
            elif element_type in {"text", "field", "category_badge"} and text and not detail:
                detail = text
    item = {"type": "basic_custom", "title": title or safe_str(content.get("name"), "自定义标签"), "detail": detail, "show_logo": content.get("show_logo", True)}
    return [item] * max(1, copies)


def render_component_label_pdf(
    records: list[dict],
    personal_base_url: str,
    *,
    start_slot: int = 1,
    copies: int = 1,
    offset_x_mm: float = 0,
    offset_y_mm: float = 0,
    calibration: bool = False,
    printed_at: str | None = None,
    safe_margin: bool = True,
    appended_items: list[dict] | None = None,
) -> bytes:
    from PIL import Image, ImageDraw

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
        start_slot = 1

    items: list[dict | None] = [None] * max(0, min(39, start_slot - 1))
    for record in source_records:
        if not safe_str(record_value(record, "warehouse_code")):
            continue
        items.extend([{"type": "component", "record": record}] * max(1, copies))
    if not calibration:
        items.extend(appended_items or [])
    if not items:
        items.append(None)

    page_w = _mm(210)
    page_h = _mm(297)
    cell_w = _mm(LABEL_WIDTH_MM)
    cell_h = _mm(LABEL_HEIGHT_MM)
    label_padding = 2.15 if safe_margin else 1.75
    outer_x_padding = 4.8 if safe_margin else 3.6
    outer_y_padding = 3.4 if safe_margin else 2.7
    first_column_left_padding = outer_x_padding + LABEL_FIRST_COLUMN_LEFT_SAFE_INSET_MM
    first_row_top_padding = outer_y_padding + LABEL_FIRST_ROW_TOP_SAFE_INSET_MM
    last_row_bottom_padding = outer_y_padding + LABEL_LAST_ROW_BOTTOM_LIFT_MM

    pages = []
    for page_start in range(0, len(items), 40):
        page = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(page)
        page_items = items[page_start: page_start + 40]
        for index, record in enumerate(page_items):
            if record is None:
                continue
            row = index // 4
            col = index % 4
            cell_left = _mm(_label_column_left_mm(col, offset_x_mm))
            cell_top = _mm(offset_y_mm) + row * cell_h
            pad_left = first_column_left_padding if col == 0 else label_padding
            pad_right = outer_x_padding if col == 3 else label_padding
            pad_top = first_row_top_padding if row == 0 else label_padding
            pad_bottom = last_row_bottom_padding if row == 9 else label_padding
            bounds = (
                cell_left + _mm(pad_left),
                cell_top + _mm(pad_top),
                cell_left + cell_w - _mm(pad_right),
                cell_top + cell_h - _mm(pad_bottom),
            )
            if calibration:
                draw.rectangle(bounds, outline="#111111", width=max(1, _mm(.2)))
                continue
            item_type = safe_str(record.get("type"), "component")
            if item_type == "standard_category":
                _draw_standard_category_pdf_card(draw, page, record, bounds, printed_at)
            elif item_type == "basic_custom":
                _draw_basic_custom_pdf_card(draw, page, record, bounds, printed_at)
            else:
                _draw_component_pdf_card(draw, page, record.get("record", record), personal_base_url, bounds, printed_at)
        pages.append(_prepare_pdf_print_page(page))

    output = io.BytesIO()
    first, rest = pages[0], pages[1:]
    first.save(
        output,
        format="PDF",
        resolution=SERVER_RENDER_DPI,
        save_all=bool(rest),
        append_images=rest,
        quality=95,
    )
    return output.getvalue()


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
    safe_margin: bool = True,
    font_keys: set[str] | None = None,
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
    effective_font_keys = {safe_str(key) for key in (font_keys or set()) if safe_str(key)}
    if not calibration:
        effective_font_keys.add("dingtalk")
    return label_document(
        f"{APP_BRAND_NAME} 器件标签",
        cards,
        start_slot,
        offset_x_mm,
        offset_y_mm,
        f"A4 直角 40 格：52.5 × 29.7 mm，4列×10行。打印请选择“实际大小/100%”、无页边距、关闭页眉页脚，禁止“适合页面”。如边缘被吃掉，请开启安全边距或调整偏移。共 {len(cards)} 个标签。",
        safe_margin=safe_margin,
        font_keys=effective_font_keys,
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


def _safe_font_family(value: object) -> str:
    key = safe_str(value, "system")
    return CUSTOM_FONT_STACKS.get(key, CUSTOM_FONT_STACKS["system"])


def _field_value(record: dict | None, field: str, base_url: str = "") -> str:
    field = safe_str(field)
    if not record:
        return CUSTOM_LABEL_FIELD_PREVIEW_VALUES.get(field, field)
    if field == "warehouse_code":
        return safe_str(record_value(record, "warehouse_code"))
    if field == "name":
        return safe_str(record_value(record, "name"))
    if field == "model":
        return safe_str(record_value(record, "model"))
    if field == "category":
        return category_name(record)
    if field == "package":
        return safe_str(record_value(record, "package"))
    if field == "normalized_spec":
        return safe_str(record_value(record, "normalized_spec"))
    if field == "lcsc_number":
        return safe_str(record_value(record, "lcsc_number"))
    if field == "location":
        return safe_str(record_value(record, "location"))
    if field == "quantity":
        return safe_str(record_value(record, "quantity"))
    if field == "available_quantity":
        return safe_str(record_value(record, "available_quantity"))
    if field == "first_stocked_at":
        return date_label(record_value(record, "first_stocked_at"))
    if field == "last_stocked_at":
        return date_label(record_value(record, "last_stocked_at"))
    if field == "print_date":
        return date_label(datetime.now())
    if field == "scan_url":
        code = safe_str(record_value(record, "warehouse_code"))
        return component_scan_url(base_url, code) if code and base_url else ""
    return safe_str(record_value(record, field))


def _element_box_style(element: dict) -> str:
    if any(key in element for key in ("x_mm", "y_mm", "width_mm", "height_mm")):
        x = max(-2, min(LABEL_WIDTH_MM, _safe_percent(element.get("x_mm"), 10, -2, LABEL_WIDTH_MM)))
        y = max(-2, min(LABEL_HEIGHT_MM, _safe_percent(element.get("y_mm"), 8, -2, LABEL_HEIGHT_MM)))
        width = max(1, min(LABEL_WIDTH_MM, _safe_percent(element.get("width_mm"), 24, 1, LABEL_WIDTH_MM)))
        height = max(1, min(LABEL_HEIGHT_MM, _safe_percent(element.get("height_mm"), 8, 1, LABEL_HEIGHT_MM)))
        unit = "mm"
    else:
        x = _safe_percent(element.get("x"), 22)
        y = _safe_percent(element.get("y"), 34)
        width = _safe_percent(element.get("width"), 56, 1, 120)
        height = _safe_percent(element.get("height"), 30, 1, 120)
        unit = "%"
    rotate = max(-180, min(180, _safe_percent(element.get("rotate"), 0, -180, 180)))
    return (
        f"left:{x:.3f}{unit};top:{y:.3f}{unit};width:{width:.3f}{unit};height:{height:.3f}{unit};"
        f"transform:rotate({rotate:.2f}deg);"
    )


def custom_label_element_html(element: dict, asset_resolver=None, record: dict | None = None, base_url: str = "") -> str:
    element_type = safe_str(element.get("type"), "text")
    style = _element_box_style(element)
    font_size = max(5, min(28, _safe_percent(element.get("font_size"), 13, 5, 28)))
    font_size_mm = font_size / CSS_PX_PER_MM
    color = _safe_color(element.get("color"))
    font_family = _safe_font_family(element.get("font_family"))
    align = safe_str(element.get("align"), "center")
    if align not in {"left", "center", "right"}:
        align = "center"
    if element_type in {"text", "field", "category_badge"}:
        text = safe_str(element.get("text"), "自定义标签") if element_type == "text" else _field_value(record, safe_str(element.get("field"), "name"), base_url)
        if element.get("prefix"):
            text = f"{str(element.get('prefix') or '')[:80]}{text}"
        if element_type == "category_badge":
            color = _safe_color(element.get("color"), "#c2410c")
        font_weight = 800 if element_type in {"field", "category_badge"} else max(300, min(950, int(_safe_percent(element.get("font_weight"), 400, 300, 950))))
        return (
            f'<div class="custom-element" style="{style}">'
            f'<div class="custom-text" style="font-family:{font_family};font-size:{font_size_mm:.3f}mm;font-weight:{font_weight};color:{color};text-align:{align};justify-content:'
            f'{"flex-start" if align == "left" else "flex-end" if align == "right" else "center"};">'
            f"{html.escape(text)}</div></div>"
        )
    if element_type == "qr":
        qr_value = _field_value(record, "scan_url", base_url) or safe_str(element.get("value"))
        if not qr_value:
            return ""
        return f'<div class="custom-element" style="{style}"><img src="{html.escape(qr_png_data_uri(qr_value), quote=True)}" alt="" /></div>'
    if element_type == "shape":
        fill = _safe_color(element.get("fill"), "#eff6ff")
        stroke = _safe_color(element.get("stroke"), "#93c5fd")
        radius = max(0, min(8, _safe_percent(element.get("radius"), 1, 0, 8)))
        return f'<div class="custom-element" style="{style}background:{fill};border:.18mm solid {stroke};border-radius:{radius:.2f}mm;"></div>'
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


def active_custom_label_content(content: dict) -> dict:
    if not isinstance(content, dict):
        return {}
    styles = content.get("styles")
    if not isinstance(styles, list) or not styles:
        return content
    active_id = safe_str(content.get("active_style_id"))
    selected = None
    for style in styles:
        if isinstance(style, dict) and active_id and safe_str(style.get("id")) == active_id:
            selected = style
            break
    if selected is None:
        selected = next((style for style in styles if isinstance(style, dict)), None)
    if not isinstance(selected, dict):
        return content
    merged = dict(content)
    merged["elements"] = selected.get("elements") if isinstance(selected.get("elements"), list) else []
    return merged


def custom_label_font_keys(content: dict) -> set[str]:
    keys: set[str] = set()
    if is_standard_category_label_group(content):
        keys.add("dingtalk")
    for item in custom_label_style_contents(content, include_all_styles=True):
        elements = item.get("elements") if isinstance(item, dict) else []
        if not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, dict):
                continue
            key = safe_str(element.get("font_family"), "system")
            if key in {"deyi", "dingtalk", "misans"}:
                keys.add(key)
    return keys


def style_category_name(style: dict) -> str:
    if not isinstance(style, dict):
        return ""
    explicit = normalize_category_label_name(style.get("category_name"))
    if explicit:
        return explicit
    elements = style.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            if safe_str(element.get("role")) == "category_title" or safe_str(element.get("type")) == "text":
                text = normalize_category_label_name(element.get("text"))
                if text:
                    return text
    return normalize_category_label_name(style.get("name"))


def category_style_keyword_hit(style: dict) -> bool:
    if not isinstance(style, dict):
        return False
    haystack = [safe_str(style.get("name")), safe_str(style.get("category_name"))]
    elements = style.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            haystack.extend(
                [
                    safe_str(element.get("text")),
                    safe_str(element.get("prefix")),
                    safe_str(element.get("field")),
                    safe_str(element.get("role")),
                ]
            )
    text = " ".join(item for item in haystack if item)
    return any(keyword in text for keyword in ("分类", "料盒", "封装", "category_title", "package"))


def is_standard_category_label_group(content: dict) -> bool:
    if not isinstance(content, dict):
        return False
    if safe_str(content.get("kind")) == STANDARD_CATEGORY_LABEL_KIND:
        return True
    styles = content.get("styles")
    if not isinstance(styles, list) or not styles:
        return False
    valid_styles = [style for style in styles if isinstance(style, dict)]
    if not valid_styles:
        return False
    if any(safe_str(style.get("category_name")) for style in valid_styles):
        return True
    recognized = [style for style in valid_styles if style_category_name(style) in KNOWN_CATEGORY_NAMES]
    keyword_hits = sum(1 for style in recognized if category_style_keyword_hit(style))
    return len(recognized) >= 2 and keyword_hits >= 1


def custom_label_style_contents(content: dict, *, include_all_styles: bool = False) -> list[dict]:
    if not isinstance(content, dict):
        return [{}]
    styles = content.get("styles")
    if include_all_styles and isinstance(styles, list) and styles:
        result: list[dict] = []
        for style in styles:
            if not isinstance(style, dict):
                continue
            merged = dict(content)
            merged["elements"] = style.get("elements") if isinstance(style.get("elements"), list) else []
            merged["active_style_id"] = style.get("id")
            result.append(merged)
        return result or [active_custom_label_content(content)]
    return [active_custom_label_content(content)]


def package_sort_key(value: str) -> tuple[int, str]:
    text = safe_str(value).upper()
    preferred = [
        "0201",
        "0402",
        "0603",
        "0805",
        "1206",
        "1210",
        "1812",
        "2010",
        "2512",
        "SOD-123",
        "SOD-323",
        "SOT-23",
        "SOT-223",
        "SOP",
        "SOIC",
        "TSSOP",
        "QFN",
        "QFP",
        "DIP",
    ]
    for index, item in enumerate(preferred):
        if item in text:
            return (index, text)
    return (len(preferred), text)


def category_label_summary_entry(record: dict) -> str:
    category = category_name(record)
    package = safe_str(record_value(record, "package"))
    model = safe_str(record_value(record, "model"))
    normalized_spec = safe_str(record_value(record, "normalized_spec"))
    name = safe_str(record_value(record, "name"))
    if category in MODEL_SUMMARY_CATEGORY_NAMES:
        parts = unique_display_parts([model, normalized_spec, package, name])
        return parts[0] if parts else package
    return package or model or normalized_spec or name


def category_package_summary_from_records(records: list[dict] | None) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        category = category_name(record)
        summary = category_label_summary_entry(record)
        if not category or not summary:
            continue
        bucket = grouped.setdefault(category, [])
        normalized = summary.strip()
        if normalized and all(normalized.casefold() != item.casefold() for item in bucket):
            bucket.append(normalized)
    result: dict[str, str] = {}
    for category, packages in grouped.items():
        ordered = sorted(packages, key=package_sort_key)
        visible = ordered[:6]
        suffix = " / 等" if len(ordered) > len(visible) else ""
        result[category] = " / ".join(visible) + suffix
    return result


def render_standard_category_label_cards(
    content: dict,
    package_summary: dict[str, str],
    *,
    copies: int = 1,
    printed_at: str | None = None,
) -> list[str]:
    printed_at = printed_at or print_timestamp()
    styles = content.get("styles") if isinstance(content, dict) else []
    if not isinstance(styles, list) or not styles:
        styles = [{"category_name": "元器件"}]
    cards: list[str] = []
    for style in styles:
        if not isinstance(style, dict):
            continue
        category = style_category_name(style) or "元器件"
        packages = package_summary.get(category)
        if not packages:
            continue
        summary_label = "型号" if category in MODEL_SUMMARY_CATEGORY_NAMES else "封装"
        title_markup = dingtalk_print_text_markup(category, "standard-category-title", 16) or f'<strong class="standard-category-title">{html.escape(category)}</strong>'
        card = f"""
        <article class="label-card custom-label-card">
          <div class="label-frame standard-category-frame">
            {label_logo_markup()}
            <span class="standard-category-kicker"><b>分类标签</b><span>常用料盒</span></span>
            <span class="standard-category-title-band">{title_markup}</span>
            <span class="standard-category-package">{html.escape(summary_label)} {html.escape(packages)}</span>
            <em class="label-print-meta">{html.escape(printed_at)}</em>
          </div>
        </article>
        """
        cards.extend([card] * max(1, copies))
    return cards


def render_custom_label_card(content: dict, asset_resolver=None, printed_at: str | None = None, record: dict | None = None, base_url: str = "") -> str:
    printed_at = printed_at or print_timestamp()
    elements = content.get("elements") if isinstance(content, dict) else []
    if not isinstance(elements, list) or not elements:
        elements = [{"type": "text", "text": safe_str(content.get("text") if isinstance(content, dict) else "", "自定义标签"), "x": 18, "y": 33, "width": 64, "height": 30, "font_size": 16}]
    element_html = "".join(custom_label_element_html(item, asset_resolver, record=record, base_url=base_url) for item in elements if isinstance(item, dict))
    show_logo = not isinstance(content, dict) or content.get("show_logo") is not False
    frame_class = "label-frame custom-frame" if show_logo else "label-frame custom-frame without-logo"
    logo_markup = label_logo_markup() if show_logo else ""
    return f"""
    <article class="label-card custom-label-card">
      <div class="{frame_class}">
        {logo_markup}
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
    records: list[dict] | None = None,
    base_url: str = "",
    include_all_styles: bool = False,
) -> list[str]:
    printed_at = printed_at or print_timestamp()
    contents = custom_label_style_contents(content or {}, include_all_styles=include_all_styles)
    if records:
        cards: list[str] = []
        for item in contents:
            for record in records:
                card = render_custom_label_card(item, asset_resolver, printed_at, record=record, base_url=base_url)
                cards.extend([card] * max(1, copies))
        return cards
    cards: list[str] = []
    for item in contents:
        card = render_custom_label_card(item, asset_resolver, printed_at)
        cards.extend([card] * max(1, copies))
    return cards


def render_custom_label_sheet(
    content: dict,
    *,
    asset_resolver=None,
    start_slot: int = 1,
    copies: int = 1,
    offset_x_mm: float = 0,
    offset_y_mm: float = 0,
    calibration: bool = False,
    safe_margin: bool = True,
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
        safe_margin=safe_margin,
        font_keys=custom_label_font_keys(content or {}),
    )
