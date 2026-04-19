"""Work-level scoring helpers."""

from __future__ import annotations

import math
import re


TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize_search_token(token: str) -> str:
    token = token.lower()
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize_search_text(text: str) -> list[str]:
    return [_normalize_search_token(token) for token in TOKEN_RE.findall(text.lower())]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def keyword_overlap(query: str, text: str) -> float:
    query_terms = {part for part in tokenize_search_text(query) if len(part) > 2}
    text_terms = set(tokenize_search_text(text))
    if not query_terms:
        return 0.0
    return len(query_terms & text_terms) / len(query_terms)


def phrase_overlap(query: str, text: str) -> float:
    query_terms = [part for part in tokenize_search_text(query) if len(part) > 2]
    if len(query_terms) < 2:
        return 0.0
    query_phrase = " ".join(query_terms)
    text_phrase = " ".join(tokenize_search_text(text))
    return 1.0 if query_phrase and query_phrase in text_phrase else 0.0
