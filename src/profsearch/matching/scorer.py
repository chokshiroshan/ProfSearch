"""Conservative author match scoring."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from profsearch.matching.names import normalized_name_tokens


DEPARTMENT_KEYWORDS: dict[str, set[str]] = {
    "physics": {"physics", "quantum", "particle", "condensed matter"},
    "applied_physics": {"applied physics", "photonics", "optics", "materials"},
    "astronomy": {"astronomy", "astrophysics", "cosmology", "planetary"},
    "materials_science": {"materials", "nanotechnology", "metallurgy", "polymers"},
}


@dataclass(slots=True)
class MatchDecision:
    status: str
    score: float
    selected_candidate: dict | None
    evidence: dict


def _name_similarity(left: str, right: str) -> float:
    left_tokens = normalized_name_tokens(left)
    right_tokens = normalized_name_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    if len(left_tokens) >= 2 and len(right_tokens) >= 2 and left_tokens[-1] == right_tokens[-1]:
        left_first = left_tokens[0]
        right_first = right_tokens[0]
        if left_first == right_first and _middle_tokens_compatible(left_tokens[1:-1], right_tokens[1:-1]):
            return 0.97
        if left_first[0] == right_first[0] and _middle_tokens_compatible(left_tokens[1:-1], right_tokens[1:-1]):
            return 0.89
        if left_first[0] == right_first[0]:
            return 0.84
    return SequenceMatcher(None, " ".join(left_tokens), " ".join(right_tokens)).ratio()


def _token_compatible(left: str, right: str) -> bool:
    return left == right or (len(left) == 1 and right.startswith(left)) or (len(right) == 1 and left.startswith(right))


def _middle_tokens_compatible(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return True
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        if _token_compatible(left[left_index], right[right_index]):
            left_index += 1
            right_index += 1
            continue
        if len(left[left_index]) == 1:
            left_index += 1
            continue
        if len(right[right_index]) == 1:
            right_index += 1
            continue
        return False
    remaining = left[left_index:] + right[right_index:]
    return all(len(token) == 1 for token in remaining)


def _institution_match(candidate: dict, institution_id: str | None) -> float:
    if not institution_id:
        return 0.0
    last_known = candidate.get("last_known_institutions") or []
    institutions = [item.get("id") for item in last_known if item.get("id")]
    return 1.0 if institution_id in institutions else 0.0


def _topic_alignment(candidate: dict, department_type: str) -> float:
    keywords = DEPARTMENT_KEYWORDS.get(department_type, set())
    concepts = []
    for concept in candidate.get("x_concepts") or []:
        display_name = (concept.get("display_name") or "").lower()
        concepts.append(display_name)
    if not keywords or not concepts:
        return 0.0
    return 1.0 if any(keyword in concept for keyword in keywords for concept in concepts) else 0.0


def _recency_score(candidate: dict) -> float:
    years = [item.get("year") for item in candidate.get("counts_by_year") or [] if item.get("works_count")]
    if not years:
        return 0.0
    latest = max(year for year in years if year is not None)
    if latest >= 2025:
        return 1.0
    if latest >= 2023:
        return 0.7
    if latest >= 2021:
        return 0.4
    return 0.1


def score_candidate(professor: dict, candidate: dict, institution_id: str | None) -> tuple[float, dict]:
    name_score = _name_similarity(professor["name"], candidate.get("display_name", ""))
    institution_score = _institution_match(candidate, institution_id)
    topic_score = _topic_alignment(candidate, professor["department_type"])
    recency_score = _recency_score(candidate)
    final = (0.55 * name_score) + (0.25 * institution_score) + (0.1 * topic_score) + (0.1 * recency_score)
    evidence = {
        "name_score": round(name_score, 4),
        "institution_score": round(institution_score, 4),
        "topic_score": round(topic_score, 4),
        "recency_score": round(recency_score, 4),
        "candidate_display_name": candidate.get("display_name"),
        "candidate_id": candidate.get("id"),
    }
    return round(final, 4), evidence


def decide_match(
    professor: dict,
    candidates: list[dict],
    *,
    institution_id: str | None,
    threshold: float,
    ambiguity_margin: float,
) -> MatchDecision:
    scored: list[tuple[float, dict, dict]] = []
    for candidate in candidates:
        score, evidence = score_candidate(professor, candidate, institution_id)
        scored.append((score, candidate, evidence))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return MatchDecision(status="unmatched", score=0.0, selected_candidate=None, evidence={"candidates": []})
    best_score, best_candidate, best_evidence = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
    evidence = {
        "selected": best_evidence,
        "runner_up_score": round(runner_up_score, 4),
        "candidates": [item[2] | {"score": item[0]} for item in scored],
    }
    if best_score < threshold:
        return MatchDecision(status="unmatched", score=best_score, selected_candidate=None, evidence=evidence)
    if best_score - runner_up_score <= ambiguity_margin:
        return MatchDecision(status="ambiguous", score=best_score, selected_candidate=None, evidence=evidence)
    return MatchDecision(status="matched", score=best_score, selected_candidate=best_candidate, evidence=evidence)
