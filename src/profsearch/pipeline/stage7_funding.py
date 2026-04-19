"""Stage 7: fetch funding/grants signal from NIH RePORTER and NSF Awards API.

For each verified professor, queries both sources by PI name + institution.
Stores normalised grants in the ``grants`` table. The web UI reads the derived
"actively funded" badge from grant end_dates rather than this stage making
hard claims about availability.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.db.models import Grant, Professor, University
from profsearch.funding.client import RawGrant, fetch_grants
from profsearch.pipeline.base import PipelineStage

logger = logging.getLogger(__name__)


class Stage7Funding(PipelineStage):
    name = "stage7"
    commit_every = 10

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, session: Session, *, limit: int | None = None) -> dict[str, Any]:
        professors = session.scalars(
            select(Professor, University)
            .join(University, University.id == Professor.university_id)
            .where(Professor.verification_status == "verified")
            .order_by(Professor.id)
        ).all()

        total = len(professors)
        state = self.mark_started(session, total_items=total)

        # Resume from checkpoint
        checkpoint = {}
        if state.checkpoint_json:
            try:
                checkpoint = json.loads(state.checkpoint_json)
            except (json.JSONDecodeError, TypeError):
                pass
        last_processed = checkpoint.get("last_professor_id", 0)

        grants_upserted = 0
        professors_queried = 0
        skipped = 0

        for idx, row in enumerate(professors):
            professor = row[0] if isinstance(row, tuple) else row
            university = row[1] if isinstance(row, tuple) else None

            if professor.id <= last_processed:
                skipped += 1
                continue

            if limit is not None and professors_queried >= limit:
                break

            uni_name = university.name if university else ""
            grants = fetch_grants(
                pi_name=professor.name,
                institution=uni_name,
                config=self.settings.funding,
                http_timeout=self.settings.http.timeout_seconds,
            )

            for raw in grants:
                self._upsert_grant(session, professor.id, raw)
                grants_upserted += 1

            professors_queried += 1

            if self.commit_every and (idx + 1) % self.commit_every == 0:
                session.commit()
                self.mark_progress(
                    session,
                    processed=idx + 1,
                    checkpoint={"last_professor_id": professor.id},
                )

        self.mark_completed(session)
        return {
            "professors_queried": professors_queried,
            "grants_upserted": grants_upserted,
            "skipped_resume": skipped,
        }

    @staticmethod
    def _upsert_grant(session: Session, professor_id: int, raw: RawGrant) -> Grant:
        existing = session.scalar(
            select(Grant).where(Grant.source == raw.source, Grant.grant_id == raw.grant_id)
        )
        if existing:
            existing.title = raw.title
            existing.pi_name = raw.pi_name
            existing.amount = raw.amount
            existing.start_date = raw.start_date
            existing.end_date = raw.end_date
            existing.raw_json = raw.raw_json
            return existing

        grant = Grant(
            professor_id=professor_id,
            source=raw.source,
            grant_id=raw.grant_id,
            title=raw.title,
            pi_name=raw.pi_name,
            amount=raw.amount,
            start_date=raw.start_date,
            end_date=raw.end_date,
            raw_json=raw.raw_json,
        )
        session.add(grant)
        return grant
