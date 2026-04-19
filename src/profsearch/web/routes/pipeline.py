"""Pipeline status page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from profsearch.db.models import (
    FacultyCandidate,
    OpenAlexAuthorMatch,
    PipelineState,
    Professor,
    University,
    Work,
)
from profsearch.web import TEMPLATES
from profsearch.web.deps import get_session

router = APIRouter()

STAGE_DISPLAY_NAMES: dict[str, str] = {
    "stage1": "load_seed_universities",
    "stage2": "scrape_faculty",
    "stage3": "verify_professors",
    "stage4": "match_openalex",
    "stage5": "ingest_publications",
    "stage6": "generate_embeddings",
}

ALL_STAGES = ["stage1", "stage2", "stage3", "stage4", "stage5", "stage6"]


def _get_counts(session: Session) -> dict[str, int]:
    return {
        "universities": session.scalar(select(func.count()).select_from(University)) or 0,
        "faculty_candidates": session.scalar(select(func.count()).select_from(FacultyCandidate)) or 0,
        "professors": session.scalar(select(func.count()).select_from(Professor)) or 0,
        "verified": session.scalar(
            select(func.count())
            .select_from(Professor)
            .where(Professor.verification_status == "verified", Professor.duplicate_of_professor_id.is_(None))
        ) or 0,
        "duplicates": session.scalar(
            select(func.count()).select_from(Professor).where(Professor.duplicate_of_professor_id.is_not(None))
        ) or 0,
        "matched": session.scalar(
            select(func.count()).select_from(OpenAlexAuthorMatch).where(OpenAlexAuthorMatch.match_status == "matched")
        ) or 0,
        "works": session.scalar(select(func.count()).select_from(Work)) or 0,
    }


@router.get("/pipeline")
def pipeline_status(request: Request, session: Session = Depends(get_session)):
    rows = session.scalars(select(PipelineState).order_by(PipelineState.stage_name)).all()
    stage_map = {row.stage_name: row for row in rows}

    stages = []
    for key in ALL_STAGES:
        row = stage_map.get(key)
        stages.append({
            "key": key,
            "name": STAGE_DISPLAY_NAMES.get(key, key),
            "status": row.status if row else "not_started",
            "processed": row.processed_items or 0 if row else 0,
            "total": row.total_items or 0 if row else 0,
            "started_at": row.started_at if row else None,
            "completed_at": row.completed_at if row else None,
        })

    counts = _get_counts(session)

    return TEMPLATES.TemplateResponse(request, "pipeline.html", {
        "active_page": "pipeline",
        "stages": stages,
        "counts": counts,
    })
