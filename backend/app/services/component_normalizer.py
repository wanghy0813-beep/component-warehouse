import re
from typing import Any

def compact_spaces(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def clean_component_name(name: str | None, model: str | None = None, fallback: str | None = None) -> str:
    raw = compact_spaces(name)
    model_text = compact_spaces(model)
    return (raw or model_text or compact_spaces(fallback) or "未命名物料")[:120]


def clean_lcsc_keyword(keyword: str | None) -> str:
    text = compact_spaces(keyword)
    if not text:
        return ""
    lcsc_match = re.search(r"\bC\d{3,}\b", text, re.IGNORECASE)
    if lcsc_match:
        return lcsc_match.group(0).upper()

    model_match = re.search(r"\b[A-Z0-9][A-Z0-9._-]{2,}(?:-[A-Z0-9._]+)*\b", text, re.IGNORECASE)
    if model_match and len(text) > 28:
        return model_match.group(0)

    text = compact_spaces(text)
    parts = [part for part in re.split(r"[,，;；\s]+", text) if part]
    return " ".join(parts[:4])[:80]


def normalize_tag_text(value: str | None, package: str | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in re.split(r"[,，;；\s]+", str(value or "")):
        tag = raw.strip()
        if not tag:
            continue
        dedupe_key = re.sub(r"\s+", "", tag).lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append(tag[:40])
        if len(result) >= 8:
            break
    return result


def normalize_component_values(values: dict[str, Any]) -> dict[str, Any]:
    result = dict(values)
    source_title = result.get("source_title")
    cleaned_name = clean_component_name(result.get("name"), result.get("model"), result.get("lcsc_number"))
    if result.get("name") and cleaned_name != compact_spaces(result.get("name")):
        result.setdefault("source_title", source_title or result.get("name"))
        result["name"] = cleaned_name
    elif not result.get("name"):
        result["name"] = cleaned_name

    tags = normalize_tag_text(result.get("tags"), result.get("package"))
    if tags:
        result["tags"] = ",".join(tags)
    return result
