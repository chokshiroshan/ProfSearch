"""Stage 1: load curated university and roster source metadata."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.db.models import DepartmentSource, University
from profsearch.pipeline.base import PipelineStage


class Stage1LoadUniversities(PipelineStage):
    name = "stage1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _validate_source_url(self, url: str, approved_domain: str) -> None:
        hostname = urlparse(url).hostname or ""
        if not (hostname == approved_domain or hostname.endswith(f".{approved_domain}")):
            raise ValueError(f"Roster URL {url} is off-domain for {approved_domain}")

    def _load_seed_data(self) -> list[dict]:
        path = Path(self.settings.seed_path)
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def run(self, session: Session, *, limit: int | None = None) -> dict[str, int]:
        seed_items = self._load_seed_data()
        if self.reporter:
            self.reporter.stage_started(self.name, seed_path=self.settings.seed_path, total_items=len(seed_items))
        if limit is not None:
            seed_items = seed_items[:limit]
        self.mark_started(session, total_items=len(seed_items))
        processed = 0
        for item in seed_items:
            university = session.scalar(select(University).where(University.name == item["name"]))
            if not university:
                university = University(name=item["name"])
                session.add(university)
                university.status = "pending"
            university.short_name = item.get("short_name")
            university.qs_rank_2026 = item.get("qs_rank_2026")
            university.qs_score = item.get("qs_score")
            university.domain = item["domain"]
            university.openalex_id = item.get("openalex_id")
            university.ror_id = item.get("ror_id")
            university.state = item.get("state")
            session.flush()
            for department in item.get("departments", []):
                try:
                    self._validate_source_url(department["roster_url"], university.domain)
                except Exception as exc:
                    if self.reporter:
                        self.reporter.record_stage1_error(
                            {
                                "university": item.get("name"),
                                "department_type": department.get("department_type"),
                                "roster_url": department.get("roster_url"),
                                "domain": university.domain,
                                "error": str(exc),
                            }
                        )
                    raise
                parser_hint = department.get("parser_hint")
                source = session.scalar(
                    select(DepartmentSource).where(
                        DepartmentSource.university_id == university.id,
                        DepartmentSource.department_type == department["department_type"],
                        DepartmentSource.roster_url == department["roster_url"],
                    )
                )
                if not source:
                    source = DepartmentSource(
                        university_id=university.id,
                        department_type=department["department_type"],
                        roster_url=department["roster_url"],
                        status="pending",
                    )
                    session.add(source)
                    university.status = "pending"
                elif source.parser_hint != parser_hint:
                    source.status = "pending"
                    source.error_message = None
                    university.status = "pending"
                source.parser_hint = parser_hint
            if self.reporter:
                self.reporter.record_stage1_university(
                    {
                        "name": university.name,
                        "short_name": university.short_name,
                        "domain": university.domain,
                        "department_count": len(item.get("departments", [])),
                    }
                )
            processed += 1
            self.mark_progress(session, processed, {"last_university": university.name})
        self.mark_completed(session)
        return {"universities_loaded": processed}
