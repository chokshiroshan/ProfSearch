"""Normalization helpers for names, titles, and departments."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


WHITESPACE_RE = re.compile(r"\s+")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")

DEPARTMENT_ALIASES: dict[str, str] = {
    "physics": "physics",
    "applied physics": "applied_physics",
    "particle physics and astrophysics": "astronomy",
    "astronomy": "astronomy",
    "astrophysics": "astronomy",
    "astrophysical sciences": "astronomy",
    "materials science": "materials_science",
    "materials science and engineering": "materials_science",
}

EXCLUDED_TITLE_PATTERNS = [
    "postdoc",
    "post-doctoral",
    "post doctoral",
    "graduate student",
    "student",
    "doctoral candidate",
    "staff",
    "administrator",
    "technician",
    "research scientist",
    "researcher",
    "lecturer",
    "instructor",
]

AMBIGUOUS_TITLE_PATTERNS = [
    "courtesy",
    "adjunct",
    "emeritus",
    "visiting",
    "research professor",
    "professor by courtesy",
]

VERIFIED_TITLE_PATTERNS: dict[str, str] = {
    "assistant professor": "assistant_professor",
    "associate professor": "associate_professor",
    "professor": "professor",
}


@dataclass(slots=True)
class TitleDecision:
    normalized_title: str
    status: str
    reason: str


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return WHITESPACE_RE.sub(" ", value).strip()


def normalize_name(name: str) -> str:
    clean = normalize_whitespace(name)
    clean = unicodedata.normalize("NFKD", clean)
    clean = "".join(character for character in clean if not unicodedata.combining(character))
    clean = re.sub(r"[^A-Za-z0-9\s-]", "", clean)
    return clean.lower()


def normalize_email(text: str | None) -> str | None:
    if not text:
        return None
    match = EMAIL_RE.search(text)
    return match.group(0).lower() if match else None


def classify_title(title: str | None) -> TitleDecision:
    raw = normalize_whitespace(title).lower()
    if not raw:
        return TitleDecision(normalized_title="ambiguous", status="ambiguous", reason="missing_title")
    for pattern in EXCLUDED_TITLE_PATTERNS:
        if pattern in raw:
            return TitleDecision(normalized_title="excluded", status="excluded", reason=pattern)
    for pattern in AMBIGUOUS_TITLE_PATTERNS:
        if pattern in raw:
            return TitleDecision(normalized_title="ambiguous", status="ambiguous", reason=pattern)
    for pattern, canonical in VERIFIED_TITLE_PATTERNS.items():
        if pattern in raw:
            return TitleDecision(normalized_title=canonical, status="verified", reason=pattern)
    return TitleDecision(normalized_title="ambiguous", status="ambiguous", reason="unrecognized_title")


def normalize_department_type(value: str) -> str:
    raw = normalize_whitespace(value).lower()
    for alias, canonical in DEPARTMENT_ALIASES.items():
        if alias in raw:
            return canonical
    return raw.replace(" ", "_")
