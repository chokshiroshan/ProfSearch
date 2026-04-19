"""Professor detail page."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.db.models import (
    FacultyCandidate,
    Grant,
    OpenAlexAuthorMatch,
    Professor,
    ProfessorWork,
    University,
    Work,
)
from profsearch.web import TEMPLATES
from profsearch.web.deps import get_session

router = APIRouter()


@router.get("/professor/{professor_id}")
def professor_detail(
    professor_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    row = session.execute(
        select(Professor, University, OpenAlexAuthorMatch)
        .join(University, University.id == Professor.university_id)
        .outerjoin(OpenAlexAuthorMatch, OpenAlexAuthorMatch.professor_id == Professor.id)
        .where(Professor.id == professor_id)
    ).first()

    if not row:
        return HTMLResponse("<h1>Professor not found</h1>", status_code=404)

    professor, university, match = row

    candidate = session.get(FacultyCandidate, professor.candidate_id) if professor.candidate_id else None

    duplicate_of = None
    if professor.duplicate_of_professor_id:
        dup_row = session.execute(
            select(Professor, University)
            .join(University, University.id == Professor.university_id)
            .where(Professor.id == professor.duplicate_of_professor_id)
        ).first()
        if dup_row:
            duplicate_of = {"id": dup_row[0].id, "name": dup_row[0].name, "university": dup_row[1].name}

    works = session.execute(
        select(Work, ProfessorWork)
        .join(ProfessorWork, ProfessorWork.work_id == Work.id)
        .where(ProfessorWork.professor_id == professor.id)
        .order_by(Work.publication_year.desc(), Work.cited_by_count.desc())
    ).all()

    evidence = {}
    if match and match.evidence_json:
        try:
            evidence = json.loads(match.evidence_json)
        except (json.JSONDecodeError, TypeError):
            pass

    # Funding signal
    grants = session.scalars(
        select(Grant).where(Grant.professor_id == professor.id).order_by(Grant.end_date.desc())
    ).all()
    from datetime import date as date_type
    today_str = date_type.today().isoformat()
    actively_funded = any(g.end_date and g.end_date >= today_str for g in grants)
    total_funding = sum(g.amount for g in grants if g.amount is not None)

    return TEMPLATES.TemplateResponse(request, "professor.html", {
        "active_page": "",
        "professor": professor,
        "university": university,
        "candidate": candidate,
        "match": match,
        "evidence": evidence,
        "duplicate_of": duplicate_of,
        "works": works,
        "grants": grants,
        "actively_funded": actively_funded,
        "total_funding": total_funding,
    })
