#!/usr/bin/env python3
"""Validate a Gerber manufacturing ZIP locally without writing application data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.fabrication_parser import (  # noqa: E402
    FabricationParseError,
    parse_fabrication_package_isolated,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="安全验证制造包并输出脱敏解析摘要")
    parser.add_argument("package", type=Path)
    parser.add_argument("--allow-ai", action="store_true", help="允许现有 AI 服务辅助表格列映射")
    args = parser.parse_args()
    try:
        result = parse_fabrication_package_isolated(args.package.resolve(), allow_ai=args.allow_ai)
    except FabricationParseError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    output = {
        "ok": True,
        "profile": result["profile"],
        "mapping_required": result["mapping_required"],
        "ai_assisted": result["ai_assisted"],
        "summary": result["summary"],
        "bounds": result["bounds"],
        "mapping": {
            "bom_file": result["mapping"].get("bom_file"),
            "cpl_file": result["mapping"].get("cpl_file"),
            "units": result["mapping"].get("units"),
            "columns": result["mapping"].get("columns"),
        },
        "layers": [
            {
                "source_name": item["source_name"],
                "role": item["role"],
                "side": item["side"],
                "has_svg": bool(item.get("svg_markup")),
                "bounds": item.get("bounds"),
            }
            for item in result["layers"]
        ],
        "warnings": result["warnings"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
