"""Name normalization helpers for author matching."""

from __future__ import annotations

import re
import unicodedata

from profsearch.scraping.normalize import normalize_name, normalize_whitespace


HONORIFIC_PREFIXES = {"dr", "dr.", "prof", "prof.", "professor"}
SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
ANNOTATION_KEYWORDS = ("she/her", "he/him", "they/them", "she", "her", "he", "him", "they", "them")


def strip_inline_annotations(name: str) -> str:
    cleaned = normalize_whitespace(name)
    if not cleaned:
        return ""
    for separator in (" | ", " • ", " — ", " – "):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip()
    cleaned = re.sub(r",\s*(she/her|he/him|they/them)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s*[\(\[]([^)\]]+)[\)\]]\s*$",
        lambda match: "" if _looks_like_annotation(match.group(1)) else match.group(0),
        cleaned,
    )
    return normalize_whitespace(cleaned)


def _looks_like_annotation(value: str) -> bool:
    lowered = normalize_whitespace(value).lower()
    return "/" in lowered or any(keyword in lowered for keyword in ANNOTATION_KEYWORDS)


def strip_honorifics(name: str) -> str:
    cleaned = strip_inline_annotations(name)
    if not cleaned:
        return ""
    tokens = cleaned.split()
    while tokens and tokens[0].lower().rstrip(".") in {"dr", "prof", "professor"}:
        tokens = tokens[1:]
    while tokens and tokens[-1].lower().rstrip(".") in {"jr", "sr", "ii", "iii", "iv"}:
        tokens = tokens[:-1]
    return " ".join(tokens)


def normalized_name_tokens(name: str) -> list[str]:
    return normalize_name(strip_honorifics(name)).split()


def normalized_ascii_name(name: str) -> str:
    stripped = strip_honorifics(name)
    ascii_name = unicodedata.normalize("NFKD", stripped)
    ascii_name = "".join(char for char in ascii_name if not unicodedata.combining(char))
    ascii_name = re.sub(r"\s+", " ", ascii_name).strip()
    return ascii_name


def query_name_variants(name: str) -> list[str]:
    base = strip_honorifics(name)
    variants: list[str] = []
    if base:
        variants.append(base)
    tokens = base.split()
    if len(tokens) >= 3:
        variants.append(f"{tokens[0]} {tokens[-1]}")
    ascii_variant = normalized_ascii_name(base)
    if ascii_variant and ascii_variant not in variants:
        variants.append(ascii_variant)
    deduped: list[str] = []
    for variant in variants:
        cleaned = normalize_whitespace(variant)
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped
