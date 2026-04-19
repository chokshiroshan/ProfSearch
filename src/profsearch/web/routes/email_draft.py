"""Web route for the outreach email drafter."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from profsearch.agentic import (
    EmailDraftRequest,
    LLMError,
    UserProfile,
    build_backend,
    draft_outreach_email,
)
from profsearch.web import TEMPLATES
from profsearch.web.deps import get_session

router = APIRouter()


@router.post("/prof/{professor_id}/draft-email")
def draft_email(
    professor_id: int,
    request: Request,
    interest: str = Form(...),
    applicant_name: str = Form(default=""),
    background: str = Form(default=""),
    stage: str = Form(default="phd"),
    llm_backend: str = Form(default=""),
    session: Session = Depends(get_session),
):
    profile = UserProfile(
        interest=interest,
        name=applicant_name,
        background=background,
        stage="postdoc applicant" if stage == "postdoc" else "PhD applicant",
    )
    payload = EmailDraftRequest(professor_id=professor_id, profile=profile)

    try:
        backend = build_backend(llm_backend or None)
        drafted = draft_outreach_email(session, payload, backend=backend)
    except LLMError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "partials/email_draft_error.html",
            {"error": str(exc), "professor_id": professor_id},
            status_code=400,
        )

    return TEMPLATES.TemplateResponse(
        request,
        "partials/email_draft_result.html",
        {"drafted": drafted, "professor_id": professor_id},
    )
