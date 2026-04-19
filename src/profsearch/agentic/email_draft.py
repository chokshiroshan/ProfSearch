"""Personalized outreach email drafter for PhD / postdoc applicants.

Grounded in two data sources:
  - the professor's 2 top-matching recent works (title + abstract, truncated)
  - the applicant's research interest (required) and optional bio snippet

No fabrication: the prompt instructs the model to only cite the provided papers
and never invent co-authors, funding status, or lab details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from profsearch.agentic.backends import LLMBackend, LLMError, LLMResponse, build_backend
from profsearch.db.models import Professor, ProfessorWork, University, Work

MAX_ABSTRACT_CHARS = 900
DEFAULT_PAPER_COUNT = 2


@dataclass
class UserProfile:
    """Applicant-side input. Interest is required; everything else is optional."""

    interest: str
    name: str = ""
    background: str = ""
    stage: str = "PhD applicant"  # or "postdoc applicant"


@dataclass
class EmailDraftRequest:
    professor_id: int
    profile: UserProfile
    paper_count: int = DEFAULT_PAPER_COUNT


@dataclass
class DraftedEmail:
    professor_id: int
    professor_name: str
    university_name: str
    backend: str
    model: str
    body: str
    referenced_works: list[dict] = field(default_factory=list)


SYSTEM_PROMPT = """You are a writing assistant for PhD and postdoc applicants drafting a first outreach email to a prospective faculty supervisor.

Rules:
- Write a single email, no alternatives, no meta-commentary.
- Tight and specific: 130–170 words including subject line.
- Open with one concrete observation tied to a specific provided paper — reference the title or a specific claim from its abstract.
- One sentence on how the applicant's stated interest or background connects.
- One soft ask: whether the group is taking students/postdocs for the upcoming cycle, and offer to share CV + research statement.
- Sign off with the applicant's name (or "[Your name]" if not provided).
- NEVER invent co-authors, funding, awards, lab members, or details not present in the inputs.
- NEVER speculate on the professor's availability, grant status, or personality.
- Plain text output. Structure: `Subject: ...\\n\\nDear Professor <LastName>,\\n\\n<body>\\n\\nBest regards,\\n<Name>`.
"""


def _truncate(text: str, limit: int = MAX_ABSTRACT_CHARS) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _load_professor_context(session: Session, professor_id: int, paper_count: int):
    row = session.execute(
        select(Professor, University)
        .join(University, University.id == Professor.university_id)
        .where(Professor.id == professor_id)
    ).first()
    if not row:
        raise LLMError(f"Professor id {professor_id} not found in database.")
    professor, university = row

    works = session.execute(
        select(Work)
        .join(ProfessorWork, ProfessorWork.work_id == Work.id)
        .where(ProfessorWork.professor_id == professor_id)
        .order_by(Work.publication_year.desc().nulls_last(), Work.cited_by_count.desc().nulls_last())
        .limit(paper_count)
    ).scalars().all()

    return professor, university, works


def _render_user_message(
    *,
    professor: Professor,
    university: University,
    works: Iterable[Work],
    profile: UserProfile,
) -> str:
    lines = [
        f"Professor name: {professor.name}",
        f"Professor title: {professor.title or 'unknown'}",
        f"Institution: {university.name}",
        f"Department: {professor.department_type or 'unknown'}",
        "",
        "Top recent publications (ground your paper reference in exactly these — do not cite anything else):",
    ]
    for idx, work in enumerate(works, start=1):
        lines.append(f"- Paper {idx} title: \"{work.title}\"")
        lines.append(f"  Paper {idx} year: {work.publication_year or 'n/a'}")
        lines.append(f"  Paper {idx} venue: {work.source_name or 'n/a'}")
        lines.append(f"  Paper {idx} abstract: {_truncate(work.abstract or '')}")
    lines.extend([
        "",
        f"Applicant name: {profile.name or '[Your name]'}",
        f"Applicant stage: {profile.stage}",
        f"Applicant research interest: {profile.interest}",
    ])
    if profile.background:
        lines.append(f"Applicant background: {profile.background}")
    lines.extend([
        "",
        "Now write the outreach email following all rules. Output only the email.",
    ])
    return "\n".join(lines)


def draft_outreach_email(
    session: Session,
    request: EmailDraftRequest,
    *,
    backend: LLMBackend | None = None,
    max_tokens: int = 700,
) -> DraftedEmail:
    if not request.profile.interest.strip():
        raise LLMError("Applicant research interest is required.")

    professor, university, works = _load_professor_context(
        session, request.professor_id, request.paper_count
    )
    if not works:
        raise LLMError(
            f"Professor {professor.name} has no ingested works — cannot ground an email. "
            "Run stages 4–6 of the pipeline first."
        )

    prompt = _render_user_message(
        professor=professor,
        university=university,
        works=works,
        profile=request.profile,
    )

    llm = backend or build_backend()
    response: LLMResponse = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=max_tokens)

    return DraftedEmail(
        professor_id=professor.id,
        professor_name=professor.name,
        university_name=university.name,
        backend=response.backend,
        model=response.model,
        body=response.text,
        referenced_works=[
            {
                "title": work.title,
                "year": work.publication_year,
                "source_name": work.source_name,
                "doi": work.doi,
            }
            for work in works
        ],
    )
