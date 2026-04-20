"""Professor ranking from work-level signals."""

from __future__ import annotations

from collections import defaultdict
import html
import re

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from profsearch.db.models import Professor, ProfessorWork, University, Work
from profsearch.db.vectors import fetch_embeddings
from profsearch.embedding.encoder import EmbeddingEncoder
from profsearch.search.query import normalize_query_text
from profsearch.search.scorer import cosine_similarity, keyword_overlap, phrase_overlap, tokenize_search_text
from profsearch.types import SearchHit


TOP_WORK_WEIGHTS = (1.0, 0.6, 0.35, 0.2, 0.1)
HTML_TAG_RE = re.compile(r"<[^>]+>")


def _discounted_top_k_sum(values: list[float], k: int) -> float:
    top_values = sorted(values, reverse=True)[:k]
    return sum(score * weight for score, weight in zip(top_values, TOP_WORK_WEIGHTS))


def _normalized_title_key(title: str | None) -> str:
    sanitized = html.unescape(title or "")
    sanitized = HTML_TAG_RE.sub(" ", sanitized)
    tokens = tokenize_search_text(sanitized)
    return " ".join(tokens)


def _is_preprint_source(payload: dict) -> bool:
    source_name = (payload.get("source_name") or "").lower()
    doi = (payload.get("doi") or "").lower()
    return "arxiv" in source_name or "10.48550/arxiv" in doi


def _dedupe_scored_works(scored_works: list[tuple[float, dict]]) -> list[tuple[float, dict]]:
    deduped: dict[str, tuple[float, dict]] = {}
    for score, payload in scored_works:
        title_key = _normalized_title_key(payload.get("title"))
        key = title_key or str(payload["work_id"])
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = (score, payload)
            continue
        existing_score, existing_payload = existing
        candidate_priority = (
            0 if _is_preprint_source(payload) else 1,
            score,
            len(payload.get("title") or ""),
            -payload["work_id"],
        )
        existing_priority = (
            0 if _is_preprint_source(existing_payload) else 1,
            existing_score,
            len(existing_payload.get("title") or ""),
            -existing_payload["work_id"],
        )
        if candidate_priority > existing_priority:
            deduped[key] = (score, payload)
    return sorted(deduped.values(), key=lambda item: item[0], reverse=True)


def _search_base_query() -> Select[tuple[Professor, University, Work]]:
    return (
        select(Professor, University, Work)
        .join(University, University.id == Professor.university_id)
        .join(ProfessorWork, ProfessorWork.professor_id == Professor.id)
        .join(Work, Work.id == ProfessorWork.work_id)
        .where(Professor.verification_status == "verified", Professor.duplicate_of_professor_id.is_(None))
    )


def rank_professors(
    session: Session,
    encoder: EmbeddingEncoder,
    query: str,
    *,
    result_limit: int | None,
    work_limit: int,
) -> list[SearchHit]:
    normalized_query = normalize_query_text(query)
    query_embedding = encoder.encode_one(normalized_query)
    rows = session.execute(_search_base_query()).all()
    work_ids = {work.id for _, _, work in rows}
    embedding_map = fetch_embeddings(session.bind, work_ids) if session.bind else {}
    per_professor_scores: dict[int, list[tuple[float, dict]]] = defaultdict(list)
    professor_names: dict[int, tuple[str, str]] = {}
    for professor, university, work in rows:
        embedding = embedding_map.get(work.id)
        if not embedding:
            continue
        semantic = cosine_similarity(query_embedding, embedding)
        title_lexical = keyword_overlap(normalized_query, work.title or "")
        abstract_lexical = keyword_overlap(normalized_query, work.abstract or "")
        phrase = max(
            phrase_overlap(normalized_query, work.title or ""),
            0.5 * phrase_overlap(normalized_query, work.abstract or ""),
        )
        score = (0.65 * semantic) + (0.2 * title_lexical) + (0.1 * abstract_lexical) + (0.05 * phrase)
        professor_names[professor.id] = (professor.name, university.name)
        per_professor_scores[professor.id].append(
            (
                score,
                {
                    "work_id": work.id,
                    "title": work.title,
                    "publication_year": work.publication_year,
                    "doi": work.doi,
                    "source_name": work.source_name,
                    "score": round(score, 4),
                },
            )
        )
    hits: list[SearchHit] = []
    for professor_id, scored_works in per_professor_scores.items():
        ranked_scored_works = _dedupe_scored_works(scored_works)
        overall = _discounted_top_k_sum([item[0] for item in ranked_scored_works], work_limit)
        works = [payload for _, payload in ranked_scored_works]
        professor_name, university_name = professor_names[professor_id]
        hits.append(
            SearchHit(
                professor_id=professor_id,
                professor_name=professor_name,
                university_name=university_name,
                score=round(overall, 4),
                supporting_works=works,
                total_work_count=len(works),
            )
        )
    hits.sort(key=lambda item: item.score, reverse=True)
    return hits if result_limit is None else hits[:result_limit]
