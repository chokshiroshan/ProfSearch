"""Publication corpus quality audit helpers."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from profsearch.db.models import OpenAlexAuthorMatch, Professor, ProfessorWork, University, Work


AUDIT_KEYWORDS: dict[str, set[str]] = {
    "physics": {
        "physics",
        "quantum",
        "particle",
        "condensed matter",
        "superconduct",
        "photon",
        "optics",
        "spin",
        "semiconductor",
        "materials",
    },
    "applied_physics": {
        "applied physics",
        "photon",
        "laser",
        "optics",
        "nanophotonics",
        "device",
        "materials",
        "quantum",
        "semiconductor",
        "photonics",
    },
    "astronomy": {
        "astronomy",
        "astrophysics",
        "cosmology",
        "galaxy",
        "stellar",
        "planet",
        "exoplanet",
        "supernova",
        "black hole",
        "quasar",
        "gravitational",
        "solar",
        "neutron star",
    },
    "materials_science": {
        "materials",
        "alloy",
        "polymer",
        "battery",
        "catalyst",
        "semiconductor",
        "surface",
        "nanoparticle",
        "electrochem",
        "metall",
    },
}


@dataclass(slots=True)
class PublicationAuditResult:
    professor_id: int
    professor_name: str
    university_name: str
    department_type: str
    total_works: int
    keyword_hit_ratio: float
    profile_alignment_ratio: float | None
    abstract_coverage_ratio: float
    arxiv_ratio: float
    distinct_source_count: int
    suspicious_score: float
    reasons: list[str] = field(default_factory=list)
    profile_terms: list[str] = field(default_factory=list)
    sample_off_topic_titles: list[str] = field(default_factory=list)


TOKEN_RE = re.compile(r"[a-z][a-z0-9-]{2,}")
PROFILE_STOPWORDS = {
    "about",
    "among",
    "assistant",
    "associate",
    "biology",
    "center",
    "centers",
    "current",
    "currently",
    "department",
    "departments",
    "engineering",
    "faculty",
    "focus",
    "focused",
    "focusing",
    "group",
    "includes",
    "including",
    "institute",
    "interests",
    "laboratory",
    "program",
    "programs",
    "professor",
    "research",
    "science",
    "sciences",
    "school",
    "studies",
    "study",
    "their",
    "university",
    "work",
    "works",
}


def _normalize_topics(topics_json: str | None) -> str:
    if not topics_json:
        return ""
    try:
        payload = json.loads(topics_json)
    except json.JSONDecodeError:
        return ""
    names: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("display_name") or item.get("name")
            if isinstance(name, str):
                names.append(name)
    return " ".join(names)


def _blob_for_work(work: Work) -> str:
    return " ".join(
        part.lower()
        for part in [
            work.title or "",
            work.abstract or "",
            work.source_name or "",
            _normalize_topics(work.topics_json),
        ]
        if part
    )


def _hit_for_department(department_types: list[str], blob: str) -> bool:
    keywords = set().union(*(AUDIT_KEYWORDS.get(department_type, set()) for department_type in department_types))
    return any(keyword in blob for keyword in keywords)


def _normalize_term(token: str) -> str:
    if token.endswith("ies") and len(token) > 5:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 5:
        return token[:-1]
    return token


def _informative_terms(text: str | None) -> list[str]:
    if not text:
        return []
    terms: list[str] = []
    for raw in TOKEN_RE.findall(text.lower()):
        token = _normalize_term(raw)
        if len(token) < 4 or token in PROFILE_STOPWORDS:
            continue
        terms.append(token)
    return terms


def _profile_terms(professors: list[Professor]) -> list[str]:
    seed_text = " ".join(
        value
        for professor in professors
        for value in [professor.title or "", professor.source_snippet or "", professor.profile_text or ""]
        if value
    )
    counts = Counter(_informative_terms(seed_text))
    if not counts:
        return []
    return [term for term, _count in counts.most_common(18)]


def _profile_alignment(profile_terms: list[str], blobs: list[str]) -> tuple[float | None, list[str]]:
    if not profile_terms or not blobs:
        return None, []
    profile_term_set = set(profile_terms)
    corpus_terms: set[str] = set()
    hit_counter = Counter()
    work_hits = 0
    for blob in blobs:
        work_terms = set(_informative_terms(blob))
        overlap = profile_term_set & work_terms
        corpus_terms.update(work_terms)
        if overlap:
            work_hits += 1
            hit_counter.update(overlap)
    coverage_ratio = len(profile_term_set & corpus_terms) / len(profile_term_set)
    work_hit_ratio = work_hits / len(blobs)
    return round(max(coverage_ratio, work_hit_ratio), 4), [term for term, _count in hit_counter.most_common(6)]


def _suspicious_score(
    *,
    keyword_hit_ratio: float,
    profile_alignment_ratio: float | None,
    abstract_coverage_ratio: float,
    arxiv_ratio: float,
    distinct_source_count: int,
    total_works: int,
) -> tuple[float, list[str]]:
    alignment_baseline = profile_alignment_ratio if profile_alignment_ratio is not None else keyword_hit_ratio
    score = 1.0 - alignment_baseline
    reasons: list[str] = []
    if total_works >= 20 and profile_alignment_ratio is not None and profile_alignment_ratio < 0.22:
        reasons.append("low_profile_alignment")
        score += 0.45
    if total_works >= 20 and keyword_hit_ratio < 0.55 and (profile_alignment_ratio is None or profile_alignment_ratio < 0.35):
        reasons.append("low_department_alignment")
        score += 0.25 if profile_alignment_ratio is not None else 0.35
    if total_works >= 20 and abstract_coverage_ratio < 0.55:
        reasons.append("low_abstract_coverage")
        score += 0.15
    if distinct_source_count >= 35 and alignment_baseline < 0.7:
        reasons.append("high_venue_diversity")
        score += 0.15
    if total_works >= 20 and arxiv_ratio > 0.85:
        reasons.append("mostly_arxiv")
        score += 0.05
    return round(score, 4), reasons


def audit_publications(
    session: Session,
    *,
    min_works: int = 15,
    limit: int = 25,
) -> list[PublicationAuditResult]:
    rows = session.execute(
        select(Professor, University, OpenAlexAuthorMatch)
        .join(University, University.id == Professor.university_id)
        .join(OpenAlexAuthorMatch, OpenAlexAuthorMatch.professor_id == Professor.id)
        .where(
            Professor.verification_status == "verified",
            Professor.duplicate_of_professor_id.is_(None),
            OpenAlexAuthorMatch.match_status == "matched",
        )
        .order_by(Professor.id)
    ).all()
    results: list[PublicationAuditResult] = []
    for professor, university, _match in rows:
        affiliated_rows = session.scalars(
            select(Professor).where(
                or_(Professor.id == professor.id, Professor.duplicate_of_professor_id == professor.id)
            )
        ).all()
        if not affiliated_rows:
            affiliated_rows = [professor]
        department_types = [row.department_type for row in affiliated_rows]
        works = session.scalars(
            select(Work)
            .join(ProfessorWork, ProfessorWork.work_id == Work.id)
            .where(ProfessorWork.professor_id == professor.id)
        ).all()
        if len(works) < min_works:
            continue
        blobs = [_blob_for_work(work) for work in works]
        hits = [_hit_for_department(department_types, blob) for blob in blobs]
        profile_terms = _profile_terms(affiliated_rows)
        profile_alignment_ratio, matched_profile_terms = _profile_alignment(profile_terms, blobs)
        keyword_hit_ratio = (sum(1 for hit in hits if hit) / len(hits)) if hits else 0.0
        abstract_coverage_ratio = (
            sum(1 for work in works if work.abstract and work.abstract.strip()) / len(works)
            if works
            else 0.0
        )
        arxiv_ratio = (
            sum(1 for work in works if (work.source_name or "").lower().startswith("arxiv")) / len(works)
            if works
            else 0.0
        )
        source_counter = Counter(work.source_name or "" for work in works if work.source_name)
        suspicious_score, reasons = _suspicious_score(
            keyword_hit_ratio=keyword_hit_ratio,
            profile_alignment_ratio=profile_alignment_ratio,
            abstract_coverage_ratio=abstract_coverage_ratio,
            arxiv_ratio=arxiv_ratio,
            distinct_source_count=len(source_counter),
            total_works=len(works),
        )
        if not reasons:
            continue
        off_topic_titles = [
            work.title
            for work, hit in zip(works, hits)
            if not hit and work.title
        ][:5]
        results.append(
            PublicationAuditResult(
                professor_id=professor.id,
                professor_name=professor.name,
                university_name=university.name,
                department_type=professor.department_type,
                total_works=len(works),
                keyword_hit_ratio=round(keyword_hit_ratio, 4),
                profile_alignment_ratio=profile_alignment_ratio,
                abstract_coverage_ratio=round(abstract_coverage_ratio, 4),
                arxiv_ratio=round(arxiv_ratio, 4),
                distinct_source_count=len(source_counter),
                suspicious_score=suspicious_score,
                reasons=reasons,
                profile_terms=matched_profile_terms,
                sample_off_topic_titles=off_topic_titles,
            )
        )
    results.sort(key=lambda item: (item.suspicious_score, item.total_works), reverse=True)
    return results[:limit]
