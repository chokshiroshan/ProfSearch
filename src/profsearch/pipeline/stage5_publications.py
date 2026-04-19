"""Stage 5: ingest recent works for matched authors."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.db.models import OpenAlexAuthorMatch, Professor, ProfessorWork, University, Work
from profsearch.openalex.client import OpenAlexClient, reconstruct_abstract
from profsearch.pipeline.base import PipelineStage


class Stage5Publications(PipelineStage):
    name = "stage5"
    commit_every = 1
    fetch_batch_size = 5

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _fetch_works_with_client(self, client: OpenAlexClient, author_id: str) -> list[dict]:
        works = []
        async for item in client.iter_author_works(author_id, self.settings.publications.start_year):
            works.append(item)
        return works

    async def _fetch_batch(self, batch: list[tuple[OpenAlexAuthorMatch, Professor, University]]) -> list[tuple[int, list[dict]]]:
        client = OpenAlexClient(self.settings)
        try:
            results: list[tuple[int, list[dict]]] = []
            for match, professor, _ in batch:
                works = []
                if match.openalex_author_id:
                    works = await self._fetch_works_with_client(client, match.openalex_author_id)
                results.append((professor.id, works))
            return results
        finally:
            await client.aclose()

    def _authorship_position(self, work: dict, author_id: str) -> tuple[str, bool | None]:
        for authorship in work.get("authorships") or []:
            author = authorship.get("author") or {}
            if author.get("id") != author_id:
                continue
            position = authorship.get("author_position") or "unknown"
            return position, authorship.get("is_corresponding")
        return "unknown", None

    def run(self, session: Session, *, limit: int | None = None) -> dict[str, int]:
        existing_links = select(ProfessorWork.professor_id.label("professor_id")).distinct().subquery()
        rows = session.execute(
            select(OpenAlexAuthorMatch, Professor, University)
            .join(Professor, Professor.id == OpenAlexAuthorMatch.professor_id)
            .join(University, University.id == Professor.university_id)
            .outerjoin(existing_links, existing_links.c.professor_id == Professor.id)
            .where(
                OpenAlexAuthorMatch.match_status.in_(["matched", "manual_override"]),
                Professor.verification_status == "verified",
                Professor.duplicate_of_professor_id.is_(None),
                existing_links.c.professor_id.is_(None),
            )
            .order_by(OpenAlexAuthorMatch.professor_id)
        ).all()
        if limit is not None:
            rows = rows[:limit]
        self.mark_started(session, total_items=len(rows))
        session.commit()
        total_works = 0
        for batch_start in range(0, len(rows), self.fetch_batch_size):
            batch = rows[batch_start : batch_start + self.fetch_batch_size]
            batch_works = dict(asyncio.run(self._fetch_batch(batch)))
            for index, (match, professor, university) in enumerate(batch, start=batch_start + 1):
                works = batch_works[professor.id]
                for payload in works:
                    work = session.scalar(select(Work).where(Work.openalex_work_id == payload["id"]))
                    if not work:
                        work = Work(openalex_work_id=payload["id"], title=payload.get("title") or "")
                        session.add(work)
                        session.flush()
                    work.title = payload.get("title") or ""
                    work.abstract = reconstruct_abstract(payload.get("abstract_inverted_index")) or None
                    work.publication_year = payload.get("publication_year")
                    work.publication_date = payload.get("publication_date")
                    work.doi = payload.get("doi")
                    work.cited_by_count = payload.get("cited_by_count")
                    primary_location = payload.get("primary_location") or {}
                    source = primary_location.get("source") or {}
                    work.source_name = source.get("display_name")
                    work.type = payload.get("type")
                    work.topics_json = json.dumps(payload.get("concepts") or payload.get("topics") or [], sort_keys=True)
                    work.fetched_at = datetime.now(timezone.utc)
                    session.flush()
                    position, is_corresponding = self._authorship_position(payload, match.openalex_author_id)
                    link = session.get(ProfessorWork, {"professor_id": professor.id, "work_id": work.id})
                    if not link:
                        link = ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position=position)
                        session.add(link)
                    link.authorship_position = position
                    link.is_corresponding = is_corresponding
                    total_works += 1
                university.status = "completed"
                self.mark_progress(session, index, {"last_professor_id": professor.id, "works_seen": total_works})
                if index % self.commit_every == 0:
                    session.commit()
        self.mark_completed(session)
        return {"authors_processed": len(rows), "works_processed": total_works}
