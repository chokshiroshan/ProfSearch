"""Candidate generation for OpenAlex author matching."""

from __future__ import annotations

from profsearch.config import Settings
from profsearch.matching.names import query_name_variants
from profsearch.openalex.client import OpenAlexClient


async def build_candidates(client: OpenAlexClient, professor_name: str, settings: Settings) -> list[dict]:
    variants = query_name_variants(professor_name)
    seen_ids: set[str] = set()
    merged: list[dict] = []
    for variant in variants:
        results = await client.search_authors(variant, per_page=settings.openalex.max_candidates)
        for candidate in results:
            candidate_id = candidate.get("id")
            if candidate_id and candidate_id in seen_ids:
                continue
            if candidate_id:
                seen_ids.add(candidate_id)
            merged.append(candidate)
            if len(merged) >= settings.openalex.max_candidates:
                return merged
    return merged[: settings.openalex.max_candidates]
