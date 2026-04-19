"""Shared typed structures used across the project."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SearchHit:
    professor_id: int
    professor_name: str
    university_name: str
    score: float
    supporting_works: list[dict[str, Any]] = field(default_factory=list)
    total_work_count: int = 0
