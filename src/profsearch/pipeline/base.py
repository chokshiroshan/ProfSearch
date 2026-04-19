"""Base pipeline stage helpers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.db.models import PipelineState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PipelineStage(ABC):
    name: str
    reporter = None

    def get_state(self, session: Session) -> PipelineState:
        state = session.scalar(select(PipelineState).where(PipelineState.stage_name == self.name))
        if state:
            return state
        state = PipelineState(stage_name=self.name, status="not_started", processed_items=0)
        session.add(state)
        session.flush()
        return state

    def mark_started(self, session: Session, total_items: int | None = None) -> PipelineState:
        state = self.get_state(session)
        state.status = "in_progress"
        state.total_items = total_items
        state.started_at = utcnow()
        state.completed_at = None
        session.flush()
        return state

    def mark_progress(self, session: Session, processed: int, checkpoint: dict[str, Any] | None = None) -> None:
        state = self.get_state(session)
        state.processed_items = processed
        if checkpoint is not None:
            state.checkpoint_json = json.dumps(checkpoint, sort_keys=True)
        session.flush()

    def mark_completed(self, session: Session) -> None:
        state = self.get_state(session)
        state.status = "completed"
        state.completed_at = utcnow()
        session.flush()

    def mark_failed(self, session: Session, checkpoint: dict[str, Any] | None = None) -> None:
        state = self.get_state(session)
        state.status = "failed"
        if checkpoint is not None:
            state.checkpoint_json = json.dumps(checkpoint, sort_keys=True)
        session.flush()

    @abstractmethod
    def run(self, session: Session, *, limit: int | None = None) -> dict[str, Any]:
        raise NotImplementedError
