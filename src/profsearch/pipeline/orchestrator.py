"""Pipeline orchestration."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.db.session import ensure_indexes
from profsearch.pipeline.stage1_universities import Stage1LoadUniversities
from profsearch.pipeline.stage2_scrape_faculty import Stage2ScrapeFaculty
from profsearch.pipeline.stage3_verify_professors import Stage3VerifyProfessors
from profsearch.pipeline.stage4_match_openalex import Stage4MatchOpenAlex
from profsearch.pipeline.stage5_publications import Stage5Publications
from profsearch.pipeline.stage6_embeddings import Stage6Embeddings
from profsearch.pipeline.stage7_funding import Stage7Funding


@dataclass(slots=True)
class PipelineExecutionError(RuntimeError):
    stage_name: str
    partial_results: list[tuple[str, dict]]
    message: str

    def __str__(self) -> str:
        return self.message


def _build_stages(settings: Settings, reporter=None):
    return OrderedDict(
        (
            ("stage1", Stage1LoadUniversities(settings)),
            ("stage2", Stage2ScrapeFaculty(settings)),
            ("stage3", Stage3VerifyProfessors()),
            ("stage4", Stage4MatchOpenAlex(settings)),
            ("stage5", Stage5Publications(settings)),
            ("stage6", Stage6Embeddings(settings)),
            ("stage7", Stage7Funding(settings)),
        )
    )


STAGE_ORDER = ["stage1", "stage2", "stage3", "stage4", "stage5", "stage6", "stage7"]


def run_pipeline(
    session: Session,
    settings: Settings,
    *,
    from_stage: str | None = None,
    through_stage: str | None = None,
    limit: int | None = None,
    reporter=None,
) -> list[tuple[str, dict]]:
    stages = _build_stages(settings, reporter=reporter)
    active = False if from_stage else True
    results: list[tuple[str, dict]] = []
    for stage_name, stage in stages.items():
        stage.reporter = reporter
        if stage_name == from_stage:
            active = True
        if not active:
            continue
        try:
            if reporter:
                reporter.stage_started(stage_name)
            outcome = stage.run(session, limit=limit)
            session.commit()
            results.append((stage_name, outcome))
            if reporter:
                reporter.stage_completed(stage_name, outcome)
        except Exception as exc:
            session.rollback()
            try:
                stage.mark_failed(session)
                session.commit()
            except Exception:
                session.rollback()
            if reporter:
                reporter.stage_failed(stage_name, str(exc))
            raise PipelineExecutionError(stage_name=stage_name, partial_results=results, message=str(exc)) from exc
        if stage_name == through_stage:
            break
    if session.bind:
        ensure_indexes(session.bind)
    return results
