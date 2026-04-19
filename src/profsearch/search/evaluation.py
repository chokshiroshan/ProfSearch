"""Helpers for repeatable search quality spot checks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from profsearch.embedding.encoder import EmbeddingEncoder
from profsearch.search.aggregator import rank_professors
from profsearch.types import SearchHit


@dataclass(slots=True)
class SearchEvaluationQuery:
    query: str
    notes: str = ""
    expected_professors: list[str] = field(default_factory=list)
    expected_universities: list[str] = field(default_factory=list)
    minimum_professor_matches: int | None = None
    minimum_university_matches: int | None = None


@dataclass(slots=True)
class SearchEvaluationResult:
    query: str
    notes: str = ""
    expected_professors: list[str] = field(default_factory=list)
    expected_universities: list[str] = field(default_factory=list)
    minimum_professor_matches: int | None = None
    minimum_university_matches: int | None = None
    matched_professors: list[str] = field(default_factory=list)
    missing_professors: list[str] = field(default_factory=list)
    matched_universities: list[str] = field(default_factory=list)
    missing_universities: list[str] = field(default_factory=list)
    hit_at_k: bool | None = None
    hits: list[SearchHit] = field(default_factory=list)


def load_search_evaluation_queries(path: str | Path) -> list[SearchEvaluationQuery]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Search evaluation file must be a JSON array.")
    queries: list[SearchEvaluationQuery] = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("query"):
            raise ValueError("Each search evaluation entry must include a non-empty 'query'.")
        queries.append(
            SearchEvaluationQuery(
                query=str(item["query"]),
                notes=str(item.get("notes", "")),
                expected_professors=[str(value) for value in item.get("expected_professors", [])],
                expected_universities=[str(value) for value in item.get("expected_universities", [])],
                minimum_professor_matches=(
                    int(item["minimum_professor_matches"])
                    if item.get("minimum_professor_matches") is not None
                    else None
                ),
                minimum_university_matches=(
                    int(item["minimum_university_matches"])
                    if item.get("minimum_university_matches") is not None
                    else None
                ),
            )
        )
    return queries


def _required_match_count(expected: list[str], explicit_minimum: int | None) -> int:
    if explicit_minimum is not None:
        return max(explicit_minimum, 0)
    return 1 if expected else 0


def _match_patterns(patterns: list[str], values: list[str]) -> tuple[list[str], list[str]]:
    normalized_values = [value.lower() for value in values]
    matched: list[str] = []
    missing: list[str] = []
    for pattern in patterns:
        normalized_pattern = pattern.lower()
        if any(normalized_pattern in value for value in normalized_values):
            matched.append(pattern)
        else:
            missing.append(pattern)
    return matched, missing


def evaluate_search_queries(
    session: Session,
    encoder: EmbeddingEncoder,
    queries: list[SearchEvaluationQuery],
    *,
    result_limit: int,
    work_limit: int,
) -> list[SearchEvaluationResult]:
    results: list[SearchEvaluationResult] = []
    for query in queries:
        hits = rank_professors(
            session,
            encoder,
            query.query,
            result_limit=result_limit,
            work_limit=work_limit,
        )
        professor_names = [hit.professor_name for hit in hits]
        university_names = [hit.university_name for hit in hits]
        matched_professors, missing_professors = _match_patterns(query.expected_professors, professor_names)
        matched_universities, missing_universities = _match_patterns(query.expected_universities, university_names)
        has_expectations = bool(query.expected_professors or query.expected_universities)
        required_professors = _required_match_count(query.expected_professors, query.minimum_professor_matches)
        required_universities = _required_match_count(query.expected_universities, query.minimum_university_matches)
        professor_requirement_met = len(matched_professors) >= required_professors
        university_requirement_met = len(matched_universities) >= required_universities
        results.append(
            SearchEvaluationResult(
                query=query.query,
                notes=query.notes,
                expected_professors=query.expected_professors,
                expected_universities=query.expected_universities,
                minimum_professor_matches=required_professors if query.expected_professors else 0,
                minimum_university_matches=required_universities if query.expected_universities else 0,
                matched_professors=matched_professors,
                missing_professors=missing_professors,
                matched_universities=matched_universities,
                missing_universities=missing_universities,
                hit_at_k=((professor_requirement_met and university_requirement_met) if has_expectations else None),
                hits=hits,
            )
        )
    return results


def summarize_search_evaluation(results: list[SearchEvaluationResult]) -> dict[str, int | float | None]:
    labeled = [item for item in results if item.hit_at_k is not None]
    labeled_hits = sum(1 for item in labeled if item.hit_at_k)
    labeled_misses = len(labeled) - labeled_hits
    hit_rate = round(labeled_hits / len(labeled), 4) if labeled else None
    return {
        "total_queries": len(results),
        "labeled_queries": len(labeled),
        "queries_with_expected_hits": labeled_hits,
        "queries_with_expected_misses": labeled_misses,
        "expected_hit_rate": hit_rate,
    }
