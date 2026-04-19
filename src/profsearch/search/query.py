"""Query normalization for semantic search."""

from __future__ import annotations

from profsearch.scraping.normalize import normalize_whitespace


SYNONYM_MAP = {
    "qm": "quantum materials",
    "cmb": "condensed matter",
    "astro": "astrophysics",
}


def normalize_query_text(query: str) -> str:
    normalized = normalize_whitespace(query).lower()
    for short, expanded in SYNONYM_MAP.items():
        normalized = normalized.replace(short, expanded)
    return normalized
