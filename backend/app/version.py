import sys
from pathlib import Path


def _read_version() -> str:
    candidates = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "VERSION")
    current = Path(__file__).resolve()
    candidates.extend((current.parents[2] / "VERSION", current.parents[1] / "VERSION"))
    for version_file in candidates:
        try:
            value = version_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return "1.4.0"


APP_VERSION = _read_version()
