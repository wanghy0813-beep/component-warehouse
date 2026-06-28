from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "frontend" / "src",
    ROOT / "frontend" / "public",
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs",
]
PATH_TARGETS = {
    ROOT / "frontend" / "src",
    ROOT / "frontend" / "public",
}
FORBIDDEN = [
    "".join(["W", "XYLAB"]),
    " ".join(["W" + "XY", "LAB"]) + " 器件管理系统",
    "竞赛库",
    "赛事库",
    "默认 CW",
    "默认CW",
    "个人 CW",
]
SUFFIXES = {".vue", ".js", ".css", ".html", ".json", ".webmanifest", ".md"}
FORBIDDEN_PATH_PATTERNS = [
    re.compile(r"""["'`]\/personal\/"""),
    re.compile(r"""["'`]\/team\/"""),
    re.compile(r"https://example-private-domain\.invalid/(?:personal|team)(?:/|$)"),
]


def files():
    for target in TARGETS:
        if target.is_file():
            yield target
        elif target.exists():
            yield from (
                path for path in target.rglob("*")
                if path.is_file() and path.suffix in SUFFIXES
            )


violations = []
for path in files():
    text = path.read_text(encoding="utf-8")
    for phrase in FORBIDDEN:
        if phrase in text:
            violations.append(f"{path.relative_to(ROOT)}: {phrase}")
    if any(target in path.parents for target in PATH_TARGETS):
        for pattern in FORBIDDEN_PATH_PATTERNS:
            if pattern.search(text):
                violations.append(f"{path.relative_to(ROOT)}: root-level app path")

if violations:
    raise SystemExit("发现废弃产品文案：\n" + "\n".join(violations))

print("文案检查通过")
