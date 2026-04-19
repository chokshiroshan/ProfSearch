"""Click CLI for ProfSearch."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import click
from sqlalchemy import delete
from sqlalchemy import func, select

from profsearch.assets import bundled_profile_names
from profsearch.audit import audit_publications
from profsearch.config import configure_runtime, get_settings
from profsearch.db.models import FacultyCandidate, OpenAlexAuthorMatch, PipelineState, Professor, ProfessorWork, University, Work
from profsearch.db.session import create_session_factory, initialize_database
from profsearch.doctor import build_doctor_report
from profsearch.embedding.encoder import EmbeddingEncoder
from profsearch.pipeline import PipelineExecutionError, STAGE_ORDER, run_pipeline
from profsearch.run_artifacts import PipelineRunReporter, RunArtifacts
from profsearch.search.aggregator import rank_professors
from profsearch.search.evaluation import evaluate_search_queries, load_search_evaluation_queries, summarize_search_evaluation
from profsearch.types import SearchHit
from profsearch.workspace import initialize_workspace


def _emit_json(payload: object) -> None:
    click.echo(json.dumps(payload, indent=2, sort_keys=True))


def _session_factory(settings=None):
    settings = settings or get_settings()
    initialize_database(settings)
    return create_session_factory(settings)


def _resolve_professor_rows(session, *, professor_id: int | None, name: str | None):
    query = (
        select(Professor, University, OpenAlexAuthorMatch)
        .join(University, University.id == Professor.university_id)
        .outerjoin(OpenAlexAuthorMatch, OpenAlexAuthorMatch.professor_id == Professor.id)
        .order_by(Professor.name, Professor.id)
    )
    if professor_id is not None:
        query = query.where(Professor.id == professor_id)
    elif name:
        query = query.where(Professor.name.ilike(f"%{name}%"))
    else:
        raise click.ClickException("Provide --professor-id or --name.")
    return list(session.execute(query).all())


def _window_supporting_works(
    hit: SearchHit,
    *,
    work_offset: int,
    display_work_limit: int | None,
    all_works: bool,
) -> list[dict]:
    works = hit.supporting_works[work_offset:]
    if all_works or display_work_limit is None:
        return works
    return works[:display_work_limit]


def _serialize_search_hits(
    hits: list[SearchHit],
    *,
    work_offset: int,
    display_work_limit: int | None,
    all_works: bool,
) -> list[dict]:
    payload: list[dict] = []
    for hit in hits:
        item = asdict(hit)
        works = _window_supporting_works(
            hit,
            work_offset=work_offset,
            display_work_limit=display_work_limit,
            all_works=all_works,
        )
        item["supporting_works"] = works
        item["work_offset"] = work_offset
        item["returned_work_count"] = len(works)
        payload.append(item)
    return payload


def _resolve_local_path(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str((get_settings().project_root / candidate).resolve())


_AUTO_PORT_SCAN_LIMIT = 100


def _socket_family(host: str) -> socket.AddressFamily:
    return socket.AF_INET6 if ":" in host else socket.AF_INET


def _is_port_available(host: str, port: int) -> bool:
    family = _socket_family(host)
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _find_next_available_port(host: str, start_port: int, scan_limit: int = _AUTO_PORT_SCAN_LIMIT) -> int | None:
    for candidate in range(start_port, start_port + scan_limit + 1):
        if _is_port_available(host, candidate):
            return candidate
    return None


def _run_pipeline_with_artifacts(
    settings,
    *,
    from_stage: str | None,
    through_stage: str | None,
    limit: int | None,
    command_name: str,
) -> tuple[dict[str, object], bool]:
    artifacts = RunArtifacts(settings, command_name)
    reporter = PipelineRunReporter(artifacts)
    session_factory = _session_factory(settings)
    with session_factory() as session:
        try:
            results = run_pipeline(
                session,
                settings,
                from_stage=from_stage,
                through_stage=through_stage,
                limit=limit,
                reporter=reporter,
            )
        except PipelineExecutionError as exc:
            summary = reporter.finalize(
                success=False,
                results=exc.partial_results,
                failed_stage=exc.stage_name,
                error=str(exc),
            )
            return summary, False
    summary = reporter.finalize(success=True, results=results)
    return summary, True


@click.group()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None, help="Path to a ProfSearch config file.")
@click.option("--profile", type=click.Choice(bundled_profile_names()), default=None, help="Bundled settings profile to overlay.")
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None, profile: str | None) -> None:
    """ProfSearch CLI."""
    config_value = str(config_path) if config_path else None
    configure_runtime(config_path=config_value, profile=profile)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_value
    ctx.obj["profile"] = profile


@cli.command("init")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing starter config and seed files.")
@click.option("--json-output", is_flag=True, default=False)
def init_command(force: bool, json_output: bool) -> None:
    """Create user-owned config, data, cache, and starter seed files."""
    settings = get_settings()
    payload = initialize_workspace(settings, force=force)
    if json_output:
        _emit_json(payload)
        return
    click.echo(f"Config dir: {payload['config_dir']}")
    click.echo(f"Data dir: {payload['data_dir']}")
    click.echo(f"Cache dir: {payload['cache_dir']}")
    click.echo(f"Config file: {payload['config_file']}")
    click.echo(f"Seed file: {payload['seed_file']}")


@cli.command("doctor")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Emit a machine-readable JSON report.")
def doctor_command(json_output: bool) -> None:
    """Run deterministic install and runtime checks."""
    settings = get_settings()
    report = build_doctor_report(settings)
    if json_output:
        _emit_json(report)
        return
    status = "OK" if report["ok"] else "ATTENTION NEEDED"
    click.echo(f"Doctor status: {status}")
    for item in report["checks"]:
        click.echo(f"{item['status']:>5}  {item['name']}: {item['detail']}")
        if item.get("hint"):
            click.echo(f"       hint: {item['hint']}")


@cli.group()
def pipeline() -> None:
    """Run ingestion stages."""


@pipeline.command("init-db")
def init_db() -> None:
    """Create the database schema."""
    settings = get_settings()
    initialize_database(settings)
    click.echo(f"Initialized database at {settings.db_path}")


@pipeline.command("run")
@click.option("--from-stage", "from_stage", type=click.Choice(STAGE_ORDER))
@click.option("--through-stage", "through_stage", type=click.Choice(STAGE_ORDER))
@click.option("--limit", type=int, default=None)
@click.option("--json-log", is_flag=True, default=False, help="Emit a machine-readable run summary JSON.")
def pipeline_run(from_stage: str | None, through_stage: str | None, limit: int | None, json_log: bool) -> None:
    """Run pipeline stages with deterministic run artifacts."""
    settings = get_settings()
    summary, success = _run_pipeline_with_artifacts(
        settings,
        from_stage=from_stage,
        through_stage=through_stage,
        limit=limit,
        command_name="pipeline-run",
    )
    if json_log:
        _emit_json(summary)
        if not success:
            raise SystemExit(1)
        return
    if not success:
        raise click.ClickException(
            f"Pipeline failed at {summary['failed_stage']}: {summary['error']}\nArtifacts: {summary['artifact_dir']}"
        )
    click.echo(f"Artifacts: {summary['artifact_dir']}")
    for item in summary["results"]:
        click.echo(f"{item['stage']}: {json.dumps(item['outcome'], sort_keys=True)}")


@cli.command("status")
def status() -> None:
    """Show pipeline and data status."""
    session_factory = _session_factory()
    with session_factory() as session:
        pipeline_rows = session.scalars(select(PipelineState).order_by(PipelineState.stage_name)).all()
        click.echo("Pipeline state:")
        for row in pipeline_rows:
            click.echo(f"  {row.stage_name}: {row.status} ({row.processed_items or 0}/{row.total_items or 0})")
        counts = {
            "universities": session.scalar(select(func.count()).select_from(University)) or 0,
            "faculty_candidates": session.scalar(select(func.count()).select_from(FacultyCandidate)) or 0,
            "professors": session.scalar(select(func.count()).select_from(Professor)) or 0,
            "verified_professors": session.scalar(
                select(func.count())
                .select_from(Professor)
                .where(Professor.verification_status == "verified", Professor.duplicate_of_professor_id.is_(None))
            )
            or 0,
            "duplicate_professors": session.scalar(
                select(func.count()).select_from(Professor).where(Professor.duplicate_of_professor_id.is_not(None))
            )
            or 0,
            "matched_authors": session.scalar(
                select(func.count()).select_from(OpenAlexAuthorMatch).where(OpenAlexAuthorMatch.match_status == "matched")
            )
            or 0,
            "works": session.scalar(select(func.count()).select_from(Work)) or 0,
        }
        click.echo("Counts:")
        for label, value in counts.items():
            click.echo(f"  {label}: {value}")


@cli.command("search")
@click.argument("query")
@click.option("--result-limit", type=click.IntRange(min=1), default=None, help="Override the number of professors returned.")
@click.option("--work-offset", type=click.IntRange(min=0), default=0, show_default=True, help="Offset into each professor's ranked work list.")
@click.option(
    "--work-limit",
    "display_work_limit",
    type=click.IntRange(min=1),
    default=None,
    help="Number of ranked works to show per professor. Defaults to the search.work_limit setting.",
)
@click.option("--all-works", is_flag=True, default=False, help="Show the full ranked work list for each returned professor.")
@click.option("--json-output", is_flag=True, default=False)
def search(
    query: str,
    result_limit: int | None,
    work_offset: int,
    display_work_limit: int | None,
    all_works: bool,
    json_output: bool,
) -> None:
    """Search ranked professors by topic."""
    settings = get_settings()
    session_factory = _session_factory()
    encoder = EmbeddingEncoder(settings)
    result_limit = result_limit or settings.search.result_limit
    display_work_limit = None if all_works else (display_work_limit or settings.search.work_limit)
    with session_factory() as session:
        hits = rank_professors(
            session,
            encoder,
            query,
            result_limit=result_limit,
            work_limit=settings.search.work_limit,
        )
    if json_output:
        _emit_json(
            _serialize_search_hits(
                hits,
                work_offset=work_offset,
                display_work_limit=display_work_limit,
                all_works=all_works,
            )
        )
        return
    if not hits:
        click.echo("No results found.")
        return
    for index, hit in enumerate(hits, start=1):
        works = _window_supporting_works(
            hit,
            work_offset=work_offset,
            display_work_limit=display_work_limit,
            all_works=all_works,
        )
        click.echo(
            f"{index}. {hit.professor_name} ({hit.university_name}) "
            f"score={hit.score:.4f} works={len(works)}/{hit.total_work_count}"
        )
        if not works:
            click.echo("   - No works in the requested window.")
            continue
        for work in works:
            click.echo(f"   - {work['title']} [{work.get('publication_year') or 'n/a'}] score={work['score']:.4f}")


@cli.command("evaluate-search")
@click.option("--query-file", default="config/pilot_search_eval.json", show_default=True, help="JSON file containing spot-check search queries.")
@click.option("--result-limit", type=click.IntRange(min=1), default=5, show_default=True, help="Number of professors to keep per query.")
@click.option(
    "--work-limit",
    "display_work_limit",
    type=click.IntRange(min=1),
    default=2,
    show_default=True,
    help="Number of ranked works to show per professor in the evaluation output.",
)
@click.option("--json-output", is_flag=True, default=False)
def evaluate_search_command(query_file: str, result_limit: int, display_work_limit: int, json_output: bool) -> None:
    """Run a repeatable spot-check query set against the current search index."""
    settings = get_settings()
    session_factory = _session_factory()
    encoder = EmbeddingEncoder(settings)
    query_path = Path(_resolve_local_path(query_file))
    if not query_path.exists():
        raise click.ClickException(f"Query file does not exist: {query_path}")
    try:
        queries = load_search_evaluation_queries(query_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    with session_factory() as session:
        results = evaluate_search_queries(
            session,
            encoder,
            queries,
            result_limit=result_limit,
            work_limit=settings.search.work_limit,
        )
    summary = summarize_search_evaluation(results)
    if json_output:
        payload = {
            "query_file": str(query_path),
            "summary": summary,
            "results": [
                {
                    "query": item.query,
                    "notes": item.notes,
                    "expected_professors": item.expected_professors,
                    "expected_universities": item.expected_universities,
                    "minimum_professor_matches": item.minimum_professor_matches,
                    "minimum_university_matches": item.minimum_university_matches,
                    "matched_professors": item.matched_professors,
                    "missing_professors": item.missing_professors,
                    "matched_universities": item.matched_universities,
                    "missing_universities": item.missing_universities,
                    "hit_at_k": item.hit_at_k,
                    "hits": _serialize_search_hits(
                        item.hits,
                        work_offset=0,
                        display_work_limit=display_work_limit,
                        all_works=False,
                    ),
                }
                for item in results
            ],
        }
        _emit_json(payload)
        return
    click.echo(
        "Summary: "
        f"queries={summary['total_queries']} "
        f"labeled={summary['labeled_queries']} "
        f"expected_hits={summary['queries_with_expected_hits']} "
        f"expected_misses={summary['queries_with_expected_misses']} "
        f"hit_rate={summary['expected_hit_rate'] if summary['expected_hit_rate'] is not None else 'n/a'}"
    )
    for item in results:
        click.echo(f"\nQuery: {item.query}")
        if item.notes:
            click.echo(f"  Notes: {item.notes}")
        if item.hit_at_k is not None:
            click.echo(
                "  Expectations: "
                f"matched={len(item.matched_professors)}/{item.minimum_professor_matches or 0} professors, "
                f"{len(item.matched_universities)}/{item.minimum_university_matches or 0} universities | "
                f"missing={', '.join(item.missing_professors + item.missing_universities) or 'none'} | "
                f"hit_at_k={item.hit_at_k}"
            )
        if not item.hits:
            click.echo("  No results found.")
            continue
        for index, hit in enumerate(item.hits, start=1):
            works = _window_supporting_works(
                hit,
                work_offset=0,
                display_work_limit=display_work_limit,
                all_works=False,
            )
            click.echo(
                f"  {index}. {hit.professor_name} ({hit.university_name}) "
                f"score={hit.score:.4f} works={len(works)}/{hit.total_work_count}"
            )
            for work in works:
                click.echo(
                    f"     - {work['title']} [{work.get('publication_year') or 'n/a'}] "
                    f"score={work['score']:.4f}"
                )


@cli.group()
def inspect() -> None:
    """Inspect records."""


@inspect.command("professor")
@click.option("--name", "name", required=True)
def inspect_professor(name: str) -> None:
    """Inspect a professor record and any linked match."""
    session_factory = _session_factory()
    with session_factory() as session:
        rows = session.execute(
            select(Professor, University, OpenAlexAuthorMatch)
            .join(University, University.id == Professor.university_id)
            .outerjoin(OpenAlexAuthorMatch, OpenAlexAuthorMatch.professor_id == Professor.id)
            .where(Professor.name.ilike(f"%{name}%"))
            .order_by(Professor.name)
        ).all()
        if not rows:
            click.echo("No matching professors found.")
            return
        for professor, university, match in rows:
            click.echo(f"{professor.name} | {university.name} | {professor.verification_status} | {professor.title or 'n/a'}")
            if professor.duplicate_of_professor_id:
                click.echo(f"  Duplicate of professor_id={professor.duplicate_of_professor_id} ({professor.duplicate_reason})")
            if match:
                click.echo(f"  OpenAlex: {match.match_status} score={match.match_score or 0:.4f} author={match.openalex_author_id}")


@inspect.command("match")
@click.option("--name", "name")
@click.option("--professor-id", type=int)
@click.option("--work-limit", type=int, default=8, show_default=True)
def inspect_match(name: str | None, professor_id: int | None, work_limit: int) -> None:
    """Inspect match evidence plus sample ingested works for one professor."""
    session_factory = _session_factory()
    with session_factory() as session:
        rows = _resolve_professor_rows(session, professor_id=professor_id, name=name)
        if not rows:
            click.echo("No matching professors found.")
            return
        if len(rows) > 1 and professor_id is None:
            click.echo("Multiple professors matched; rerun with --professor-id:")
            for professor, university, _match in rows[:20]:
                click.echo(f"  {professor.id}: {professor.name} | {university.name} | {professor.department_type}")
            return
        professor, university, match = rows[0]
        click.echo(
            f"{professor.id}: {professor.name} | {university.name} | {professor.department_type} | "
            f"{professor.verification_status} | {professor.title or 'n/a'}"
        )
        if professor.duplicate_of_professor_id:
            click.echo(f"Duplicate of professor_id={professor.duplicate_of_professor_id} ({professor.duplicate_reason})")
        if not match:
            click.echo("No OpenAlex match row.")
            return
        click.echo(
            f"OpenAlex: {match.match_status} | score={match.match_score or 0:.4f} | "
            f"author={match.openalex_author_id or 'n/a'}"
        )
        evidence = json.loads(match.evidence_json) if match.evidence_json else {}
        selected = evidence.get("selected")
        if selected:
            click.echo(f"Selected candidate: {json.dumps(selected, sort_keys=True)}")
        candidates = evidence.get("candidates") or []
        if candidates:
            click.echo("Top candidates:")
            for candidate in candidates[:5]:
                click.echo(f"  {json.dumps(candidate, sort_keys=True)}")
        works = session.execute(
            select(Work)
            .join(ProfessorWork, ProfessorWork.work_id == Work.id)
            .where(ProfessorWork.professor_id == professor.id)
            .order_by(Work.publication_year.desc(), Work.id.desc())
            .limit(work_limit)
        ).scalars().all()
        if works:
            click.echo("Sample works:")
            for work in works:
                click.echo(f"  {work.publication_year or 'n/a'} | {work.source_name or 'n/a'} | {work.title}")


@cli.command("review-matches")
def review_matches() -> None:
    """List unresolved author matches."""
    session_factory = _session_factory()
    with session_factory() as session:
        rows = session.execute(
            select(Professor, University, OpenAlexAuthorMatch)
            .join(University, University.id == Professor.university_id)
            .join(OpenAlexAuthorMatch, OpenAlexAuthorMatch.professor_id == Professor.id)
            .where(OpenAlexAuthorMatch.match_status.in_(["ambiguous", "unmatched"]))
            .order_by(OpenAlexAuthorMatch.match_status, Professor.name)
        ).all()
        if not rows:
            click.echo("No review queue entries.")
            return
        for professor, university, match in rows:
            click.echo(f"{match.match_status}: {professor.name} | {university.name} | score={match.match_score or 0:.4f}")


@cli.command("resolve-match")
@click.option("--name", "name")
@click.option("--professor-id", type=int)
@click.option("--status", "status", required=True, type=click.Choice(["matched", "ambiguous", "unmatched", "manual_override"]))
@click.option("--author-id", "author_id")
@click.option("--reason", "reason", default="", help="Short note for the manual review decision.")
def resolve_match(name: str | None, professor_id: int | None, status: str, author_id: str | None, reason: str) -> None:
    """Apply a manual match decision for one professor."""
    session_factory = _session_factory()
    with session_factory() as session:
        rows = _resolve_professor_rows(session, professor_id=professor_id, name=name)
        if not rows:
            raise click.ClickException("No matching professors found.")
        if len(rows) > 1 and professor_id is None:
            lines = [f"{professor.id}: {professor.name} | {university.name} | {professor.department_type}" for professor, university, _ in rows[:20]]
            raise click.ClickException("Multiple professors matched; rerun with --professor-id.\n" + "\n".join(lines))
        professor, university, match = rows[0]
        if status in {"matched", "manual_override"} and not author_id:
            raise click.ClickException("--author-id is required for matched/manual_override.")
        if not match:
            match = OpenAlexAuthorMatch(professor_id=professor.id, match_status=status)
            session.add(match)
        match.match_status = status
        match.openalex_author_id = author_id if status in {"matched", "manual_override"} else None
        match.reviewed_at = datetime.now(timezone.utc)
        match.matched_at = datetime.now(timezone.utc)
        if status == "manual_override":
            match.match_score = 1.0
        elif status != "matched":
            match.match_score = None
        match.evidence_json = json.dumps(
            {
                "manual_review": True,
                "reason": reason,
                "status": status,
                "author_id": match.openalex_author_id,
                "reviewed_at": match.reviewed_at.isoformat(),
            },
            sort_keys=True,
        )
        if status not in {"matched", "manual_override"}:
            session.execute(delete(ProfessorWork).where(ProfessorWork.professor_id == professor.id))
        session.commit()
        click.echo(f"Updated {professor.id}: {professor.name} | {university.name} -> {status}")


@cli.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address.")
@click.option("--port", default=8000, show_default=True, help="Port number.")
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on file changes.")
@click.option(
    "--auto-port/--no-auto-port",
    default=True,
    show_default=True,
    help="Auto-select a nearby free port when the requested --port is unavailable.",
)
@click.option("--read-only", "read_only", is_flag=True, default=False, help="Disable write routes and pipeline commands (hosted demo mode).")
def web_command(host: str, port: int, reload: bool, auto_port: bool, read_only: bool) -> None:
    """Start the internal web UI."""
    try:
        import uvicorn
    except ImportError:
        raise click.ClickException("Install the web extra: pip install 'profsearch[web]'")
    root_obj = click.get_current_context().find_root().obj or {}
    config_path = root_obj.get("config_path")
    profile = root_obj.get("profile")
    if config_path:
        os.environ["PROFSEARCH_CONFIG_FILE"] = config_path
    if profile:
        os.environ["PROFSEARCH_PROFILE"] = profile
    if read_only:
        os.environ["PROFSEARCH_READ_ONLY"] = "1"

    selected_port = port
    if not _is_port_available(host, port):
        if not auto_port:
            raise click.ClickException(
                f"Port {port} is already in use on {host}. "
                "Retry with --auto-port or provide a different --port."
            )
        fallback_port = _find_next_available_port(host, port + 1)
        if fallback_port is None:
            raise click.ClickException(
                f"Port {port} is in use on {host}, and no free port was found in the "
                f"range {port + 1}-{port + _AUTO_PORT_SCAN_LIMIT}."
            )
        selected_port = fallback_port
        click.echo(f"Port {port} is in use on {host}; using free port {selected_port}.")
        click.echo(f"Web UI: http://{host}:{selected_port}")
    uvicorn.run("profsearch.web:create_app", host=host, port=selected_port, reload=reload, factory=True)


@cli.command("audit-publications")
@click.option("--min-works", type=int, default=15, show_default=True)
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--json-output", is_flag=True, default=False)
def audit_publications_command(min_works: int, limit: int, json_output: bool) -> None:
    """Flag suspicious matched-author corpora before embeddings."""
    session_factory = _session_factory()
    with session_factory() as session:
        findings = audit_publications(session, min_works=min_works, limit=limit)
    if json_output:
        _emit_json([asdict(item) for item in findings])
        return
    if not findings:
        click.echo("No suspicious publication corpora found.")
        return
    for item in findings:
        profile_alignment = f"{item.profile_alignment_ratio:.2f}" if item.profile_alignment_ratio is not None else "n/a"
        click.echo(
            f"{item.professor_name} | {item.university_name} | {item.department_type} | "
            f"works={item.total_works} | keyword_hit_ratio={item.keyword_hit_ratio:.2f} | "
            f"profile_alignment={profile_alignment} | "
            f"abstract_coverage={item.abstract_coverage_ratio:.2f} | sources={item.distinct_source_count} | "
            f"score={item.suspicious_score:.2f} | reasons={','.join(item.reasons)}"
        )
        if item.profile_terms:
            click.echo(f"  profile_terms={', '.join(item.profile_terms[:5])}")
        for title in item.sample_off_topic_titles[:3]:
            click.echo(f"  - {title}")


@cli.command("draft-email")
@click.option("--prof-id", "professor_id", type=int, required=True, help="Target professor id (see `profsearch search`).")
@click.option("--interest", required=True, help="Your research interest — a sentence or two.")
@click.option("--your-name", "applicant_name", default="", help="Your name for the signature.")
@click.option("--background", default="", help="Optional one-line about your experience or current program.")
@click.option("--stage", type=click.Choice(["phd", "postdoc"]), default="phd", show_default=True, help="Applicant stage — tunes the ask.")
@click.option("--llm-backend", "llm_backend", default=None, help="LLM backend: anthropic (default), echo, or fake. Env: PROFSEARCH_LLM_BACKEND.")
@click.option("--model", "llm_model", default=None, help="Override LLM model. Env: PROFSEARCH_LLM_MODEL.")
@click.option("--paper-count", type=int, default=2, show_default=True, help="How many of the professor's top recent papers to ground the email in.")
@click.option("--json-output", is_flag=True, default=False, help="Emit a JSON payload with body + referenced_works.")
def draft_email_command(
    professor_id: int,
    interest: str,
    applicant_name: str,
    background: str,
    stage: str,
    llm_backend: str | None,
    llm_model: str | None,
    paper_count: int,
    json_output: bool,
) -> None:
    """Draft a personalized outreach email grounded in a professor's recent work."""
    from profsearch.agentic import (
        EmailDraftRequest,
        LLMError,
        UserProfile,
        build_backend,
        draft_outreach_email,
    )

    profile = UserProfile(
        interest=interest,
        name=applicant_name,
        background=background,
        stage="postdoc applicant" if stage == "postdoc" else "PhD applicant",
    )
    request = EmailDraftRequest(
        professor_id=professor_id,
        profile=profile,
        paper_count=paper_count,
    )
    try:
        backend = build_backend(llm_backend, model=llm_model)
    except LLMError as exc:
        raise click.ClickException(str(exc))

    session_factory = _session_factory()
    with session_factory() as session:
        try:
            drafted = draft_outreach_email(session, request, backend=backend)
        except LLMError as exc:
            raise click.ClickException(str(exc))

    if json_output:
        _emit_json({
            "professor_id": drafted.professor_id,
            "professor_name": drafted.professor_name,
            "university_name": drafted.university_name,
            "backend": drafted.backend,
            "model": drafted.model,
            "body": drafted.body,
            "referenced_works": drafted.referenced_works,
        })
        return

    click.echo(f"--- Draft email for {drafted.professor_name} ({drafted.university_name}) ---")
    click.echo(f"[backend: {drafted.backend} · model: {drafted.model}]")
    click.echo("")
    click.echo(drafted.body)
    click.echo("")
    click.echo("Referenced works:")
    for work in drafted.referenced_works:
        year = work.get("year") or "n/a"
        venue = work.get("source_name") or "n/a"
        click.echo(f"  · [{year}] {work['title']}  — {venue}")


if __name__ == "__main__":
    cli()
