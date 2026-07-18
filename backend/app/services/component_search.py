import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass(frozen=True)
class _UnitDefinition:
    dimension: str
    suffix: str
    pattern: re.Pattern[str]
    prefix_exponents: dict[str, int]


@dataclass(frozen=True)
class _UnitToken:
    start: int
    end: int
    raw: str
    number: Decimal
    prefix: str
    definition: _UnitDefinition

    @property
    def base_value(self) -> Decimal:
        exponent = self.definition.prefix_exponents[self.prefix]
        return self.number * (Decimal(10) ** exponent)


_CAPACITANCE = _UnitDefinition(
    dimension="capacitance",
    suffix="F",
    pattern=re.compile(
        r"(?<![\w.])(?P<number>(?:\d+(?:\.\d*)?|\.\d+))\s*(?P<prefix>[pPnNuUµμm]?)\s*[fF](?![A-Za-z])"
    ),
    prefix_exponents={"p": -12, "n": -9, "u": -6, "m": -3, "": 0},
)
_INDUCTANCE = _UnitDefinition(
    dimension="inductance",
    suffix="H",
    pattern=re.compile(
        r"(?<![\w.])(?P<number>(?:\d+(?:\.\d*)?|\.\d+))\s*(?P<prefix>[nNuUµμm]?)\s*[hH](?![A-Za-z])"
    ),
    prefix_exponents={"n": -9, "u": -6, "m": -3, "": 0},
)
_RESISTANCE = _UnitDefinition(
    dimension="resistance",
    suffix="Ω",
    pattern=re.compile(
        r"(?<![\w.])(?P<number>(?:\d+(?:\.\d*)?|\.\d+))\s*(?P<prefix>[mMkK]?)\s*(?:Ω|ohms?|R)(?![A-Za-z])",
        flags=re.IGNORECASE,
    ),
    prefix_exponents={"m": -3, "": 0, "k": 3, "M": 6},
)
_UNIT_DEFINITIONS = (_CAPACITANCE, _INDUCTANCE, _RESISTANCE)
_DIMENSION_LABELS = {
    "capacitance": "电容",
    "inductance": "电感",
    "resistance": "电阻",
}


def _normalized_prefix(prefix: str, definition: _UnitDefinition) -> str:
    if prefix in {"µ", "μ", "U"}:
        return "u"
    if definition is _RESISTANCE:
        if prefix in {"k", "K"}:
            return "k"
        return prefix
    return prefix.lower()


def _unit_tokens(value: str) -> list[_UnitToken]:
    tokens: list[_UnitToken] = []
    occupied: list[tuple[int, int]] = []
    for definition in _UNIT_DEFINITIONS:
        for match in definition.pattern.finditer(value):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            try:
                number = Decimal(match.group("number"))
            except InvalidOperation:
                continue
            prefix = _normalized_prefix(match.group("prefix") or "", definition)
            if prefix not in definition.prefix_exponents:
                continue
            tokens.append(
                _UnitToken(
                    start=match.start(),
                    end=match.end(),
                    raw=match.group(0),
                    number=number,
                    prefix=prefix,
                    definition=definition,
                )
            )
            occupied.append((match.start(), match.end()))
    return sorted(tokens, key=lambda item: item.start)


def _format_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _prefix_aliases(prefix: str) -> tuple[str, ...]:
    if prefix == "u":
        return ("u", "µ", "μ")
    return (prefix,)


def _unit_aliases(definition: _UnitDefinition) -> tuple[str, ...]:
    if definition is _RESISTANCE:
        return ("Ω", "ohm", "R")
    return (definition.suffix,)


def _renderings(token: _UnitToken) -> list[tuple[str, str, bool]]:
    """Return (query spelling, concise display spelling, is converted) candidates."""
    candidates: list[tuple[str, str, bool]] = []
    exponents = sorted(token.definition.prefix_exponents.items(), key=lambda item: item[1], reverse=True)

    preferred: list[tuple[str, int]] = []
    fallback: list[tuple[str, int]] = []
    for prefix, exponent in exponents:
        scaled = token.base_value / (Decimal(10) ** exponent)
        bucket = preferred if Decimal(1) <= abs(scaled) < Decimal(1000) else fallback
        bucket.append((prefix, exponent))

    for prefix, exponent in preferred + fallback:
        scaled = token.base_value / (Decimal(10) ** exponent)
        number = _format_decimal(scaled)
        display_prefix = "µ" if prefix == "u" else prefix
        display = f"{number}{display_prefix}{token.definition.suffix}"
        for prefix_alias in _prefix_aliases(prefix):
            for unit_alias in _unit_aliases(token.definition):
                for separator in ("", " "):
                    spelling = f"{number}{separator}{prefix_alias}{unit_alias}"
                    converted = prefix != token.prefix
                    candidates.append((spelling, display, converted))
    return candidates


def _text_key(value: object) -> str:
    return str(value or "").replace("µ", "u").replace("μ", "u").casefold()


def keyword_unit_variants(keyword: str | None) -> list[str]:
    """Expand an electronics search term into equivalent R/L/C unit spellings."""
    text = str(keyword or "").strip()
    if not text:
        return []

    variants: list[str] = []
    seen: set[str] = set()

    def append(value: str) -> None:
        if value and value not in seen:
            variants.append(value)
            seen.add(value)

    append(text)
    append(text.replace("µ", "u").replace("μ", "u"))
    for token in _unit_tokens(text)[:3]:
        for spelling, _, _ in _renderings(token):
            append(f"{text[:token.start]}{spelling}{text[token.end:]}")
            if len(variants) >= 64:
                return variants
    return variants


def find_unit_conversion_match(
    keyword: str | None,
    candidate_values: Iterable[object],
) -> dict[str, str] | None:
    """Describe a converted-unit match only when the typed spelling did not match directly."""
    text = str(keyword or "").strip()
    if not text:
        return None
    tokens = _unit_tokens(text)
    if not tokens:
        return None

    haystacks = [_text_key(value) for value in candidate_values if value is not None]
    direct_variants = {
        _text_key(text),
        _text_key(text.replace("µ", "u").replace("μ", "u")),
    }
    if any(variant in haystack for variant in direct_variants for haystack in haystacks):
        return None

    for token in tokens:
        for spelling, display, converted in _renderings(token):
            if not converted:
                continue
            variant = f"{text[:token.start]}{spelling}{text[token.end:]}"
            if any(_text_key(variant) in haystack for haystack in haystacks):
                query_value = token.raw.strip()
                return {
                    "query_value": query_value,
                    "matched_value": display,
                    "dimension": token.definition.dimension,
                    "dimension_label": _DIMENSION_LABELS[token.definition.dimension],
                    "label": f"{query_value} = {display}",
                }
    return None
