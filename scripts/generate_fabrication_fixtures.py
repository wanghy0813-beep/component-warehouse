#!/usr/bin/env python3
"""Build deterministic, redistributable Gerber/BOM/CPL ZIP fixtures."""

from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "fabrication"
PACKAGES = {
    "jlc": "jlc-easyeda-v1.zip",
    "kicad": "kicad-v1.zip",
    "altium": "altium-v1.zip",
}


def build(source_name: str, output_name: str) -> None:
    source = ROOT / source_name
    output = ROOT / output_name
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


if __name__ == "__main__":
    for source_name, output_name in PACKAGES.items():
        build(source_name, output_name)
