from __future__ import annotations

import pytest

from profsearch.search.aggregator import _discounted_top_k_sum
from profsearch.search.scorer import keyword_overlap, phrase_overlap, tokenize_search_text


def test_tokenize_search_text_normalizes_hyphens_and_plurals() -> None:
    assert tokenize_search_text("Gravitational-wave detectors and galaxies") == [
        "gravitational",
        "wave",
        "detector",
        "and",
        "galaxy",
    ]


def test_keyword_overlap_matches_hyphenated_terms() -> None:
    score = keyword_overlap("gravitational waves", "Quantum noise in a gravitational-wave detector")
    assert score == 1.0


def test_phrase_overlap_matches_normalized_multiword_phrase() -> None:
    assert phrase_overlap("gravitational waves", "Machine learning for gravitational-wave observatories") == 1.0
    assert phrase_overlap("dark matter", "Galaxy formation with wave/fuzzy dark matter") == 1.0
    assert phrase_overlap("nanophotonics", "Inverse design for nanophotonics") == 0.0


def test_discounted_top_k_sum_downweights_later_supporting_works() -> None:
    assert _discounted_top_k_sum([0.9, 0.8, 0.7, 0.6, 0.5], 5) == pytest.approx(1.795)
