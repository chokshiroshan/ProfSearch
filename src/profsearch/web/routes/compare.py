"""Side-by-side professor comparison."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.db.models import (
    OpenAlexAuthorMatch,
    Professor,
    ProfessorWork,
    University,
    Work,
)
from profsearch.web import TEMPLATES
from profsearch.web.deps import get_session

router = APIRouter()

MAX_COMPARE = 4


def _parse_ids(ids_raw: str) -> list[int]:
    out: list[int] = []
    for chunk in ids_raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            continue
        if value > 0 and value not in out:
            out.append(value)
        if len(out) >= MAX_COMPARE:
            break
    return out


@router.get("/compare")
def compare_page(
    request: Request,
    ids: str = Query(default=""),
    session: Session = Depends(get_session),
):
    professor_ids = _parse_ids(ids)

    columns: list[dict] = []
    for prof_id in professor_ids:
        row = session.execute(
            select(Professor, University, OpenAlexAuthorMatch)
            .join(University, University.id == Professor.university_id)
            .outerjoin(OpenAlexAuthorMatch, OpenAlexAuthorMatch.professor_id == Professor.id)
            .where(Professor.id == prof_id)
        ).first()
        if not row:
            continue
        professor, university, match = row

        recent_works = session.execute(
            select(Work)
            .join(ProfessorWork, ProfessorWork.work_id == Work.id)
            .where(ProfessorWork.professor_id == professor.id)
            .order_by(Work.publication_year.desc(), Work.cited_by_count.desc())
            .limit(3)
        ).scalars().all()

        columns.append({
            "professor": professor,
            "university": university,
            "match": match,
            "recent_works": recent_works,
        })

    return TEMPLATES.TemplateResponse(request, "compare.html", {
        "active_page": "compare",
        "columns": columns,
        "requested_ids": professor_ids,
        "max_compare": MAX_COMPARE,
    })
