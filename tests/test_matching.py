from __future__ import annotations

import json
from pathlib import Path

from profsearch.matching.names import query_name_variants
from profsearch.matching.scorer import decide_match


def test_decide_match_prefers_precise_institution_match() -> None:
    payload = json.loads(Path("tests/fixtures/sample_openalex_response.json").read_text(encoding="utf-8"))
    decision = decide_match(
        {"name": "Jane Doe", "department_type": "physics"},
        payload["results"],
        institution_id="https://openalex.org/I123",
        threshold=0.82,
        ambiguity_margin=0.05,
    )
    assert decision.status == "matched"
    assert decision.selected_candidate is not None
    assert decision.selected_candidate["id"] == "https://openalex.org/A123"


def test_decide_match_returns_unmatched_below_threshold() -> None:
    decision = decide_match(
        {"name": "Completely Different", "department_type": "materials_science"},
        [{"id": "https://openalex.org/A1", "display_name": "Jane Doe", "counts_by_year": []}],
        institution_id=None,
        threshold=0.9,
        ambiguity_margin=0.05,
    )
    assert decision.status == "unmatched"


def test_decide_match_handles_initial_based_author_names() -> None:
    decision = decide_match(
        {"name": "Ernest Moniz", "department_type": "physics"},
        [
            {
                "id": "https://openalex.org/A1",
                "display_name": "E. J. Moniz",
                "last_known_institutions": [{"id": "https://openalex.org/I123"}],
                "x_concepts": [{"display_name": "Physics"}],
                "counts_by_year": [{"year": 2025, "works_count": 4}],
            }
        ],
        institution_id="https://openalex.org/I123",
        threshold=0.82,
        ambiguity_margin=0.05,
    )
    assert decision.status == "matched"


def test_query_name_variants_strip_honorifics_and_middle_names() -> None:
    assert query_name_variants("Dr. Philip H. Bucksbaum") == [
        "Philip H. Bucksbaum",
        "Philip Bucksbaum",
    ]


def test_query_name_variants_strip_pronoun_annotations() -> None:
    assert query_name_variants("Smadar Naoz | She/Her") == ["Smadar Naoz"]
    assert query_name_variants("Taylor Example (they/them)") == ["Taylor Example"]
