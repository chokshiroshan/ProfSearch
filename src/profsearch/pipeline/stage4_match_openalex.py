"""Stage 4: match verified professors to OpenAlex author identities."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.db.models import OpenAlexAuthorMatch, Professor, University
from profsearch.matching.candidate_search import build_candidates
from profsearch.matching.scorer import decide_match
from profsearch.openalex.client import OpenAlexClient
from profsearch.pipeline.base import PipelineStage


class Stage4MatchOpenAlex(PipelineStage):
    name = "stage4"
    commit_every = 5

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _needs_matching(match: OpenAlexAuthorMatch | None) -> bool:
        if match is None:
            return True
        if match.match_status in {"unmatched", "ambiguous"}:
            return True
        if match.match_status == "matched" and not match.openalex_author_id:
            return True
        return False

    @staticmethod
    def _canonical_priority(professor: Professor, match: OpenAlexAuthorMatch | None) -> tuple[float, int, int, int, int]:
        return (
            match.match_score or 0.0,
            1 if professor.profile_url else 0,
            len(professor.name or ""),
            len(professor.title or ""),
            -professor.id,
        )

    def _reset_openalex_duplicates(self, session: Session) -> None:
        professors = session.scalars(select(Professor).where(Professor.duplicate_reason == "same_openalex_author")).all()
        for professor in professors:
            professor.duplicate_of_professor_id = None
            professor.duplicate_reason = None
            match = session.scalar(select(OpenAlexAuthorMatch).where(OpenAlexAuthorMatch.professor_id == professor.id))
            if match and match.match_status == "duplicate":
                match.match_status = "unmatched"
                match.openalex_author_id = None
                match.match_score = None
                match.evidence_json = json.dumps({"reset": True, "reason": "same_openalex_author"}, sort_keys=True)

    def _sync_known_duplicates(self, session: Session) -> None:
        rows = session.scalars(select(Professor).where(Professor.duplicate_of_professor_id.is_not(None))).all()
        for professor in rows:
            match = session.scalar(select(OpenAlexAuthorMatch).where(OpenAlexAuthorMatch.professor_id == professor.id))
            if not match:
                continue
            match.match_status = "duplicate"
            match.evidence_json = json.dumps(
                {
                    "duplicate_of_professor_id": professor.duplicate_of_professor_id,
                    "reason": professor.duplicate_reason,
                },
                sort_keys=True,
            )

    def _mark_author_duplicates(self, session: Session) -> int:
        rows = session.execute(
            select(OpenAlexAuthorMatch, Professor)
            .join(Professor, Professor.id == OpenAlexAuthorMatch.professor_id)
            .where(
                OpenAlexAuthorMatch.match_status == "matched",
                OpenAlexAuthorMatch.openalex_author_id.is_not(None),
                Professor.duplicate_of_professor_id.is_(None),
            )
            .order_by(Professor.university_id, OpenAlexAuthorMatch.openalex_author_id, Professor.id)
        ).all()
        groups: dict[tuple[int, str], list[tuple[OpenAlexAuthorMatch, Professor]]] = {}
        for match, professor in rows:
            key = (professor.university_id, match.openalex_author_id)
            groups.setdefault(key, []).append((match, professor))
        duplicates_marked = 0
        for group in groups.values():
            if len(group) < 2:
                continue
            canonical_match, canonical_professor = max(group, key=lambda item: self._canonical_priority(item[1], item[0]))
            for match, professor in group:
                if professor.id == canonical_professor.id:
                    continue
                professor.duplicate_of_professor_id = canonical_professor.id
                professor.duplicate_reason = "same_openalex_author"
                match.match_status = "duplicate"
                match.evidence_json = json.dumps(
                    {
                        "duplicate_of_professor_id": canonical_professor.id,
                        "openalex_author_id": match.openalex_author_id,
                        "reason": "same_openalex_author",
                    },
                    sort_keys=True,
                )
                duplicates_marked += 1
        return duplicates_marked

    async def _match_with_client(
        self,
        client: OpenAlexClient,
        professor: Professor,
        university: University,
    ) -> tuple[list[dict], dict]:
        candidates = await build_candidates(client, professor.name, self.settings)
        decision = decide_match(
            {"name": professor.name, "department_type": professor.department_type},
            candidates,
            institution_id=university.openalex_id,
            threshold=self.settings.matching.threshold,
            ambiguity_margin=self.settings.matching.ambiguity_margin,
        )
        return candidates, {
            "status": decision.status,
            "score": decision.score,
            "selected_candidate": decision.selected_candidate,
            "evidence": decision.evidence,
        }

    async def _match_batch(self, batch: list[tuple[Professor, University]]) -> list[tuple[int, dict]]:
        client = OpenAlexClient(self.settings)
        try:
            results: list[tuple[int, dict]] = []
            for professor, university in batch:
                _, result = await self._match_with_client(client, professor, university)
                results.append((professor.id, result))
            return results
        finally:
            await client.aclose()

    def _resume_checkpoint(self, session: Session) -> tuple[int, int | None]:
        state = self.get_state(session)
        if state.status != "in_progress" or not state.checkpoint_json:
            return 0, None
        try:
            checkpoint = json.loads(state.checkpoint_json)
        except json.JSONDecodeError:
            return 0, None
        last_professor_id = checkpoint.get("last_professor_id")
        if not isinstance(last_professor_id, int):
            return 0, None
        return state.processed_items or 0, last_professor_id

    def run(self, session: Session, *, limit: int | None = None) -> dict[str, int]:
        self._reset_openalex_duplicates(session)
        self._sync_known_duplicates(session)
        rows = session.execute(
            select(Professor, University, OpenAlexAuthorMatch)
            .join(University, University.id == Professor.university_id)
            .outerjoin(OpenAlexAuthorMatch, OpenAlexAuthorMatch.professor_id == Professor.id)
            .where(
                Professor.verification_status == "verified",
                Professor.duplicate_of_professor_id.is_(None),
            )
            .order_by(Professor.id)
        ).all()
        rows = [
            (professor, university)
            for professor, university, match in rows
            if self._needs_matching(match)
        ]
        if limit is not None:
            rows = rows[:limit]
        processed_offset, last_professor_id = self._resume_checkpoint(session)
        if last_professor_id is not None:
            rows = [(professor, university) for professor, university in rows if professor.id > last_professor_id]
        total_items = processed_offset + len(rows)
        state = self.mark_started(session, total_items=total_items)
        state.processed_items = processed_offset
        session.commit()
        for batch_start in range(0, len(rows), self.commit_every):
            batch = rows[batch_start : batch_start + self.commit_every]
            batch_results = dict(asyncio.run(self._match_batch(batch)))
            for index, (professor, university) in enumerate(batch, start=processed_offset + batch_start + 1):
                result = batch_results[professor.id]
                match = session.scalar(select(OpenAlexAuthorMatch).where(OpenAlexAuthorMatch.professor_id == professor.id))
                if not match:
                    match = OpenAlexAuthorMatch(professor_id=professor.id, match_status=result["status"])
                    session.add(match)
                match.match_status = result["status"]
                match.match_score = result["score"]
                match.evidence_json = json.dumps(result["evidence"], sort_keys=True)
                match.matched_at = datetime.now(timezone.utc)
                selected = result["selected_candidate"]
                match.openalex_author_id = selected.get("id") if selected else None
                if result["status"] != "matched":
                    professor.duplicate_of_professor_id = None
                    if professor.duplicate_reason == "same_openalex_author":
                        professor.duplicate_reason = None
                if result["status"] == "matched":
                    university.status = "matched"
                self.mark_progress(session, index, {"last_professor_id": professor.id, "last_status": result["status"]})
            session.commit()
        duplicates_marked = self._mark_author_duplicates(session)
        self.mark_completed(session)
        matched_count = session.scalar(
            select(func.count())
            .select_from(OpenAlexAuthorMatch)
            .join(Professor, Professor.id == OpenAlexAuthorMatch.professor_id)
            .where(OpenAlexAuthorMatch.match_status == "matched", Professor.duplicate_of_professor_id.is_(None))
        ) or 0
        return {
            "professors_processed": len(rows),
            "matched_professors": matched_count,
            "duplicates_marked": duplicates_marked,
        }
