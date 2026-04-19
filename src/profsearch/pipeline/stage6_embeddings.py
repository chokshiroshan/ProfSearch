"""Stage 6: compute embeddings for works missing vectors."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.db.models import Work, WorkEmbedding
from profsearch.db.vectors import upsert_embedding
from profsearch.embedding.encoder import EmbeddingEncoder
from profsearch.pipeline.base import PipelineStage


class Stage6Embeddings(PipelineStage):
    name = "stage6"
    commit_every = 50

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.encoder = EmbeddingEncoder(settings)

    def run(self, session: Session, *, limit: int | None = None) -> dict[str, int]:
        rows = session.execute(
            select(Work)
            .outerjoin(WorkEmbedding, WorkEmbedding.work_id == Work.id)
            .where(
                or_(
                    WorkEmbedding.work_id.is_(None),
                    WorkEmbedding.backend != self.encoder.backend,
                    WorkEmbedding.dimension != self.encoder.dimension,
                )
            )
            .order_by(Work.id)
        ).scalars().all()
        if limit is not None:
            rows = rows[:limit]
        self.mark_started(session, total_items=len(rows))
        session.commit()
        encoded = 0
        for index, work in enumerate(rows, start=1):
            text = f"{work.title} [SEP] {(work.abstract or '')[:1024]}".strip()
            embedding = self.encoder.encode_one(text)
            upsert_embedding(session.connection(), work.id, embedding, self.encoder.backend)
            encoded += 1
            self.mark_progress(session, index, {"last_work_id": work.id})
            if index % self.commit_every == 0:
                session.commit()
        self.mark_completed(session)
        return {"works_encoded": encoded}
