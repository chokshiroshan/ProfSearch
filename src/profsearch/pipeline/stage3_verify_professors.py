"""Stage 3: normalize titles and verify professor records."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.db.models import FacultyCandidate, Professor
from profsearch.pipeline.base import PipelineStage
from profsearch.scraping.normalize import classify_title


class Stage3VerifyProfessors(PipelineStage):
    name = "stage3"

    @staticmethod
    def _canonical_priority(professor: Professor) -> tuple[int, int, int, int]:
        return (
            1 if professor.profile_url else 0,
            len(professor.name or ""),
            len(professor.title or ""),
            -professor.id,
        )

    def _mark_same_name_duplicates(self, session: Session) -> None:
        professors = session.scalars(
            select(Professor)
            .where(Professor.verification_status == "verified")
            .order_by(Professor.university_id, Professor.normalized_name, Professor.id)
        ).all()
        for professor in professors:
            if professor.duplicate_reason == "same_university_name":
                professor.duplicate_of_professor_id = None
                professor.duplicate_reason = None
        groups: dict[tuple[int, str], list[Professor]] = {}
        for professor in professors:
            key = (professor.university_id, professor.normalized_name)
            groups.setdefault(key, []).append(professor)
        for duplicates in groups.values():
            if len(duplicates) < 2:
                continue
            canonical = max(duplicates, key=self._canonical_priority)
            for professor in duplicates:
                if professor.id == canonical.id:
                    professor.duplicate_of_professor_id = None
                    if professor.duplicate_reason == "same_university_name":
                        professor.duplicate_reason = None
                    continue
                professor.duplicate_of_professor_id = canonical.id
                professor.duplicate_reason = "same_university_name"

    def run(self, session: Session, *, limit: int | None = None) -> dict[str, int]:
        candidates = session.scalars(select(FacultyCandidate).order_by(FacultyCandidate.id)).all()
        if limit is not None:
            candidates = candidates[:limit]
        self.mark_started(session, total_items=len(candidates))
        verified = 0
        for index, candidate in enumerate(candidates, start=1):
            decision = classify_title(candidate.title)
            professor = session.scalar(select(Professor).where(Professor.candidate_id == candidate.id))
            if not professor:
                professor = Professor(
                    candidate_id=candidate.id,
                    university_id=candidate.university_id,
                    department_type=candidate.department_type,
                    name=candidate.name,
                    normalized_name=candidate.normalized_name,
                    source_url=candidate.source_url,
                    verification_status=decision.status,
                    title_normalized=decision.normalized_title,
                )
                session.add(professor)
            professor.department_type = candidate.department_type
            professor.name = candidate.name
            professor.normalized_name = candidate.normalized_name
            professor.title = candidate.title
            professor.title_normalized = decision.normalized_title
            professor.email = candidate.email
            professor.profile_url = candidate.profile_url
            professor.profile_text = candidate.profile_text
            professor.source_url = candidate.source_url
            professor.source_snippet = candidate.source_snippet
            professor.verification_status = decision.status
            if decision.status != "verified" and professor.duplicate_reason == "same_university_name":
                professor.duplicate_of_professor_id = None
                professor.duplicate_reason = None
            professor.scraped_at = candidate.scraped_at
            if decision.status == "verified":
                verified += 1
            self.mark_progress(session, index, {"last_candidate_id": candidate.id, "last_status": decision.status})
        self._mark_same_name_duplicates(session)
        self.mark_completed(session)
        return {"candidates_processed": len(candidates), "verified_professors": verified}
