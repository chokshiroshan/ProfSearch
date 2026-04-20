"""Search page and HTMX partials."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.db.models import Professor, ProfessorWork, University, Work
from profsearch.embedding.encoder import EmbeddingEncoder
from profsearch.search.aggregator import rank_professors
from profsearch.web import TEMPLATES
from profsearch.web.deps import get_encoder, get_session, get_settings

router = APIRouter()


def _filter_options(session: Session) -> dict:
    universities = session.scalars(
        select(University.name).order_by(University.name)
    ).all()
    dept_types = session.scalars(
        select(Professor.department_type)
        .where(Professor.department_type.is_not(None))
        .group_by(Professor.department_type)
        .order_by(Professor.department_type)
    ).all()
    return {
        "universities": list(universities),
        "department_types": list(dept_types),
    }


def _canonical_search_url(
    *,
    q: str,
    result_limit: int,
    university: str,
    department_type: str,
    verification: str,
    match_status: str,
) -> str:
    params: list[tuple[str, str]] = []
    query = q.strip()
    if query:
        params.append(("q", query))
    if university:
        params.append(("university", university))
    if department_type:
        params.append(("department_type", department_type))
    if verification:
        params.append(("verification", verification))
    if match_status:
        params.append(("match_status", match_status))
    if result_limit > 0:
        params.append(("result_limit", str(result_limit)))
    if not params:
        return "/"
    return f"/?{urlencode(params)}"


@router.get("/")
def search_page(
    request: Request,
    q: str = "",
    session: Session = Depends(get_session),
    encoder: EmbeddingEncoder = Depends(get_encoder),
    settings: Settings = Depends(get_settings),
    result_limit: int = Query(default=0),
    university: str = Query(default=""),
    department_type: str = Query(default=""),
    verification: str = Query(default=""),
    match_status: str = Query(default=""),
):
    filters = _filter_options(session)
    hits = []
    effective_limit = result_limit if result_limit > 0 else settings.search.result_limit  # None = no limit

    if q.strip():
        hits = rank_professors(
            session,
            encoder,
            q.strip(),
            result_limit=effective_limit,
            work_limit=settings.search.work_limit,
        )
        hits = _apply_filters(session, hits, university, department_type, verification, match_status)

    return TEMPLATES.TemplateResponse(request, "search.html", {
        "active_page": "search",
        "query": q,
        "hits": hits,
        "filters": filters,
        "selected_university": university,
        "selected_department_type": department_type,
        "selected_verification": verification,
        "selected_match_status": match_status,
        "result_limit": effective_limit,
        "default_work_display": 3,
    })


@router.get("/search/results")
def search_results(
    request: Request,
    q: str = "",
    session: Session = Depends(get_session),
    encoder: EmbeddingEncoder = Depends(get_encoder),
    settings: Settings = Depends(get_settings),
    result_limit: int = Query(default=0),
    university: str = Query(default=""),
    department_type: str = Query(default=""),
    verification: str = Query(default=""),
    match_status: str = Query(default=""),
):
    canonical_url = _canonical_search_url(
        q=q,
        result_limit=result_limit,
        university=university,
        department_type=department_type,
        verification=verification,
        match_status=match_status,
    )
    if request.headers.get("HX-Request") != "true":
        return RedirectResponse(url=canonical_url, status_code=307)

    hits = []
    effective_limit = result_limit if result_limit > 0 else settings.search.result_limit  # None = no limit

    if q.strip():
        hits = rank_professors(
            session,
            encoder,
            q.strip(),
            result_limit=effective_limit,
            work_limit=settings.search.work_limit,
        )
        hits = _apply_filters(session, hits, university, department_type, verification, match_status)

    response = TEMPLATES.TemplateResponse(request, "partials/search_results.html", {
        "query": q,
        "hits": hits,
        "default_work_display": 3,
    })
    response.headers["HX-Push-Url"] = canonical_url
    return response


@router.get("/search/works/{professor_id}")
def professor_works(
    professor_id: int,
    request: Request,
    q: str = "",
    session: Session = Depends(get_session),
    encoder: EmbeddingEncoder = Depends(get_encoder),
    settings: Settings = Depends(get_settings),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
):
    works = []
    total = 0
    if q.strip():
        hits = rank_professors(
            session,
            encoder,
            q.strip(),
            result_limit=settings.search.result_limit,
            work_limit=settings.search.work_limit,
        )
        for hit in hits:
            if hit.professor_id == professor_id:
                total = hit.total_work_count
                works = hit.supporting_works[offset:offset + limit]
                break

    return TEMPLATES.TemplateResponse(request, "partials/work_list.html", {
        "works": works,
        "professor_id": professor_id,
        "query": q,
        "offset": offset,
        "limit": limit,
        "total": total,
    })


def _apply_filters(
    session: Session,
    hits: list,
    university: str,
    department_type: str,
    verification: str,
    match_status: str,
) -> list:
    if not any([university, department_type, verification, match_status]):
        return hits

    professor_ids = [h.professor_id for h in hits]
    if not professor_ids:
        return hits

    from profsearch.db.models import OpenAlexAuthorMatch

    query = (
        select(Professor.id)
        .where(Professor.id.in_(professor_ids))
    )
    if university:
        query = query.join(University, University.id == Professor.university_id).where(University.name == university)
    if department_type:
        query = query.where(Professor.department_type == department_type)
    if verification:
        query = query.where(Professor.verification_status == verification)
    if match_status:
        query = (
            query
            .join(OpenAlexAuthorMatch, OpenAlexAuthorMatch.professor_id == Professor.id)
            .where(OpenAlexAuthorMatch.match_status == match_status)
        )

    allowed_ids = set(session.scalars(query).all())
    return [h for h in hits if h.professor_id in allowed_ids]
