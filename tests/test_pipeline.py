from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from profsearch.db.models import DepartmentSource, FacultyCandidate, OpenAlexAuthorMatch, PipelineState, Professor, University
from profsearch.pipeline.stage4_match_openalex import Stage4MatchOpenAlex
from profsearch.pipeline.stage1_universities import Stage1LoadUniversities
from profsearch.pipeline.stage2_scrape_faculty import SourceScrapeResult, Stage2ScrapeFaculty
from profsearch.pipeline.stage3_verify_professors import Stage3VerifyProfessors


def test_stage1_to_stage3_flow(session_factory, test_settings, monkeypatch) -> None:
    seed = [
        {
            "name": "Test University",
            "short_name": "TU",
            "qs_rank_2026": 1,
            "qs_score": 99.0,
            "domain": "example.edu",
            "openalex_id": "https://openalex.org/I123",
            "ror_id": "https://ror.org/abc123",
            "state": "Massachusetts",
            "departments": [
                {
                    "department_type": "physics",
                    "roster_url": "https://physics.example.edu/faculty",
                    "parser_hint": "mit_faculty_cards"
                }
            ]
        }
    ]
    Path(test_settings.app.seed_file).write_text(json.dumps(seed), encoding="utf-8")
    html = Path("tests/fixtures/sample_roster_page.html").read_text(encoding="utf-8")

    async def fake_scrape_source(self, source, approved_domains):
        return SourceScrapeResult(
            final_url=source.roster_url,
            entries=__import__("profsearch.scraping.extractors", fromlist=["extract_roster_entries"]).extract_roster_entries(
                html, source.roster_url, source.parser_hint
            ),
            error=None,
            pages=[],
        )

    monkeypatch.setattr(Stage2ScrapeFaculty, "_scrape_source", fake_scrape_source)

    with session_factory() as session:
        Stage1LoadUniversities(test_settings).run(session)
        session.commit()
        Stage2ScrapeFaculty(test_settings).run(session)
        session.commit()
        Stage3VerifyProfessors().run(session)
        session.commit()

        university = session.scalar(select(University).where(University.name == "Test University"))
        source = session.scalar(select(DepartmentSource))
        candidates = session.scalars(select(FacultyCandidate).order_by(FacultyCandidate.id)).all()
        professors = session.scalars(select(Professor).order_by(Professor.id)).all()

    assert university is not None
    assert source is not None
    assert len(candidates) == 2
    assert len(professors) == 2
    assert professors[0].verification_status == "verified"
    assert professors[1].verification_status == "excluded"


def test_stage3_marks_same_name_duplicates(session_factory) -> None:
    with session_factory() as session:
        university = University(name="Dup University", domain="example.edu", status="faculty_scraped")
        session.add(university)
        session.flush()
        first = FacultyCandidate(
            university_id=university.id,
            department_source_id=1,
            department_type="physics",
            name="Aharon Kapitulnik",
            normalized_name="aharon kapitulnik",
            title="Professor of Physics",
            profile_url="https://example.edu/a",
            source_url="https://example.edu/physics",
            source_snippet="Professor of Physics",
            scraped_at=datetime.now(timezone.utc),
        )
        second = FacultyCandidate(
            university_id=university.id,
            department_source_id=2,
            department_type="applied_physics",
            name="Aharon Kapitulnik",
            normalized_name="aharon kapitulnik",
            title="Professor of Applied Physics",
            profile_url="https://example.edu/b",
            source_url="https://example.edu/ap",
            source_snippet="Professor of Applied Physics",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add_all([first, second])
        session.commit()
        Stage3VerifyProfessors().run(session)
        session.commit()
        professors = session.scalars(select(Professor).order_by(Professor.id)).all()
    assert len(professors) == 2
    duplicates = [professor for professor in professors if professor.duplicate_of_professor_id is not None]
    assert len(duplicates) == 1
    assert duplicates[0].duplicate_reason == "same_university_name"


def test_stage3_copies_profile_text_to_professor(session_factory) -> None:
    with session_factory() as session:
        university = University(name="Profile Copy University", domain="example.edu", status="faculty_scraped")
        session.add(university)
        session.flush()
        candidate = FacultyCandidate(
            university_id=university.id,
            department_source_id=1,
            department_type="physics",
            name="Morgan Example",
            normalized_name="morgan example",
            title="Assistant Professor of Physics",
            profile_url="https://example.edu/morgan",
            profile_text="Morgan studies quantum optics and ultracold atoms.",
            source_url="https://example.edu/physics",
            source_snippet="Assistant Professor of Physics",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(candidate)
        session.commit()
        Stage3VerifyProfessors().run(session)
        session.commit()
        professor = session.scalar(select(Professor).where(Professor.candidate_id == candidate.id))
    assert professor is not None
    assert professor.profile_text == "Morgan studies quantum optics and ultracold atoms."


def test_stage4_resumes_after_checkpoint(session_factory, test_settings, monkeypatch) -> None:
    processed_professor_ids: list[int] = []

    async def fake_match_with_client(self, client, professor, university):
        processed_professor_ids.append(professor.id)
        return [], {
            "status": "matched",
            "score": 0.95,
            "selected_candidate": {"id": f"https://openalex.org/A{professor.id}"},
            "evidence": {"source": "test"},
        }

    monkeypatch.setattr(Stage4MatchOpenAlex, "_match_with_client", fake_match_with_client)

    with session_factory() as session:
        university = University(
            name="Resume University",
            domain="example.edu",
            openalex_id="https://openalex.org/I123",
            status="faculty_scraped",
        )
        session.add(university)
        session.flush()
        candidates: list[FacultyCandidate] = []
        for index in range(3):
            candidate = FacultyCandidate(
                university_id=university.id,
                department_source_id=index + 1,
                department_type="physics",
                name=f"Professor {index} Example",
                normalized_name=f"professor {index} example",
                title="Professor of Physics",
                profile_url=f"https://example.edu/{index}",
                source_url="https://example.edu/physics",
                source_snippet="Professor of Physics",
                scraped_at=datetime.now(timezone.utc),
            )
            session.add(candidate)
            session.flush()
            candidates.append(candidate)
            session.add(
                Professor(
                    candidate_id=candidate.id,
                    university_id=university.id,
                    department_type="physics",
                    name=candidate.name,
                    normalized_name=candidate.normalized_name,
                    title=candidate.title,
                    title_normalized="professor",
                    profile_url=candidate.profile_url,
                    source_url=candidate.source_url,
                    source_snippet=candidate.source_snippet,
                    verification_status="verified",
                )
            )
        session.flush()
        professors = session.scalars(select(Professor).order_by(Professor.id)).all()
        session.add(
            OpenAlexAuthorMatch(
                professor_id=professors[0].id,
                match_status="matched",
                openalex_author_id=f"https://openalex.org/A{professors[0].id}",
            )
        )
        session.add(
            OpenAlexAuthorMatch(
                professor_id=professors[1].id,
                match_status="unmatched",
            )
        )
        session.add(
            PipelineState(
                stage_name="stage4",
                status="in_progress",
                total_items=3,
                processed_items=2,
                checkpoint_json=json.dumps({"last_professor_id": professors[1].id}),
            )
        )
        session.commit()

        outcome = Stage4MatchOpenAlex(test_settings).run(session)
        session.commit()
        state = session.scalar(select(PipelineState).where(PipelineState.stage_name == "stage4"))

    assert processed_professor_ids == [professors[2].id]
    assert outcome["professors_processed"] == 1
    assert state is not None
    assert state.status == "completed"
    assert state.processed_items == 3


def test_stage4_only_processes_professors_needing_matches(session_factory, test_settings, monkeypatch) -> None:
    processed_professor_ids: list[int] = []

    async def fake_match_with_client(self, client, professor, university):
        processed_professor_ids.append(professor.id)
        return [], {
            "status": "matched",
            "score": 0.95,
            "selected_candidate": {"id": f"https://openalex.org/A{professor.id}"},
            "evidence": {"source": "test"},
        }

    monkeypatch.setattr(Stage4MatchOpenAlex, "_match_with_client", fake_match_with_client)

    with session_factory() as session:
        university = University(
            name="Incremental Match University",
            domain="example.edu",
            openalex_id="https://openalex.org/I456",
            status="faculty_scraped",
        )
        session.add(university)
        session.flush()
        professor_ids: list[int] = []
        for index in range(4):
            candidate = FacultyCandidate(
                university_id=university.id,
                department_source_id=index + 1,
                department_type="physics",
                name=f"Professor {index} Match",
                normalized_name=f"professor {index} match",
                title="Professor of Physics",
                profile_url=f"https://example.edu/match/{index}",
                source_url="https://example.edu/physics",
                source_snippet="Professor of Physics",
                scraped_at=datetime.now(timezone.utc),
            )
            session.add(candidate)
            session.flush()
            professor = Professor(
                candidate_id=candidate.id,
                university_id=university.id,
                department_type="physics",
                name=candidate.name,
                normalized_name=candidate.normalized_name,
                title=candidate.title,
                title_normalized="professor",
                profile_url=candidate.profile_url,
                source_url=candidate.source_url,
                source_snippet=candidate.source_snippet,
                verification_status="verified",
            )
            session.add(professor)
            session.flush()
            professor_ids.append(professor.id)
        session.add_all(
            [
                OpenAlexAuthorMatch(
                    professor_id=professor_ids[0],
                    match_status="matched",
                    openalex_author_id=f"https://openalex.org/A{professor_ids[0]}",
                ),
                OpenAlexAuthorMatch(
                    professor_id=professor_ids[1],
                    match_status="manual_override",
                    openalex_author_id=f"https://openalex.org/A{professor_ids[1]}",
                ),
                OpenAlexAuthorMatch(
                    professor_id=professor_ids[2],
                    match_status="unmatched",
                ),
            ]
        )
        session.commit()

        outcome = Stage4MatchOpenAlex(test_settings).run(session)
        session.commit()

    assert processed_professor_ids == [professor_ids[2], professor_ids[3]]
    assert outcome["professors_processed"] == 2


def test_stage2_upserts_existing_candidate_by_profile_url(session_factory, test_settings) -> None:
    with session_factory() as session:
        university = University(name="Upsert University", domain="example.edu", status="pending")
        session.add(university)
        session.flush()
        source = DepartmentSource(
            university_id=university.id,
            department_type="physics",
            roster_url="https://example.edu/faculty",
            status="pending",
        )
        session.add(source)
        session.flush()
        stale = FacultyCandidate(
            university_id=university.id,
            department_source_id=source.id,
            department_type="physics",
            name="Edward Blucher Edward Blucher Professor",
            normalized_name="edward blucher edward blucher professor",
            title="Professor",
            profile_url="https://example.edu/edward",
            source_url="https://example.edu/edward",
            source_snippet="Professor",
        )
        session.add(stale)
        session.commit()

        stage = Stage2ScrapeFaculty(test_settings)
        entry = __import__("profsearch.scraping.extractors", fromlist=["RosterEntry"]).RosterEntry(
            name="Edward Blucher",
            title="Professor",
            email=None,
            profile_url="https://example.edu/edward",
            profile_text=None,
            source_url="https://example.edu/edward",
            source_snippet="Professor",
        )
        stage._upsert_candidate(session, source, university, entry)
        session.commit()
        candidates = session.scalars(select(FacultyCandidate).where(FacultyCandidate.department_source_id == source.id)).all()

    assert len(candidates) == 1
    assert candidates[0].name == "Edward Blucher"
    assert candidates[0].normalized_name == "edward blucher"


def test_stage1_preserves_existing_source_status_when_seed_entry_is_unchanged(session_factory, test_settings) -> None:
    seed = [
        {
            "name": "Stable University",
            "short_name": "SU",
            "qs_rank_2026": 12,
            "qs_score": 88.1,
            "domain": "example.edu",
            "departments": [
                {
                    "department_type": "physics",
                    "roster_url": "https://physics.example.edu/faculty",
                    "parser_hint": "mit_faculty_cards",
                }
            ],
        }
    ]
    Path(test_settings.app.seed_file).write_text(json.dumps(seed), encoding="utf-8")

    with session_factory() as session:
        university = University(name="Stable University", domain="example.edu", status="matched_openalex")
        session.add(university)
        session.flush()
        source = DepartmentSource(
            university_id=university.id,
            department_type="physics",
            roster_url="https://physics.example.edu/faculty",
            parser_hint="mit_faculty_cards",
            status="scraped",
        )
        session.add(source)
        session.commit()

        Stage1LoadUniversities(test_settings).run(session)
        session.commit()

        university = session.scalar(select(University).where(University.name == "Stable University"))
        source = session.scalar(select(DepartmentSource).where(DepartmentSource.university_id == university.id))

    assert university is not None
    assert source is not None
    assert university.status == "matched_openalex"
    assert source.status == "scraped"


def test_stage1_requeues_existing_source_when_parser_hint_changes(session_factory, test_settings) -> None:
    seed = [
        {
            "name": "Parser University",
            "short_name": "PU",
            "qs_rank_2026": 20,
            "qs_score": 82.0,
            "domain": "example.edu",
            "departments": [
                {
                    "department_type": "physics",
                    "roster_url": "https://physics.example.edu/faculty",
                    "parser_hint": "new_parser",
                }
            ],
        }
    ]
    Path(test_settings.app.seed_file).write_text(json.dumps(seed), encoding="utf-8")

    with session_factory() as session:
        university = University(name="Parser University", domain="example.edu", status="matched_openalex")
        session.add(university)
        session.flush()
        source = DepartmentSource(
            university_id=university.id,
            department_type="physics",
            roster_url="https://physics.example.edu/faculty",
            parser_hint="old_parser",
            status="scraped",
        )
        session.add(source)
        session.commit()

        Stage1LoadUniversities(test_settings).run(session)
        session.commit()

        university = session.scalar(select(University).where(University.name == "Parser University"))
        source = session.scalar(select(DepartmentSource).where(DepartmentSource.university_id == university.id))

    assert university is not None
    assert source is not None
    assert university.status == "pending"
    assert source.status == "pending"
    assert source.parser_hint == "new_parser"


def test_stage2_disables_bogus_princeton_pagination(test_settings, monkeypatch) -> None:
    html = """
    <html><body>
      <div class="content-list-item">
        <div class="content-list-item-details">
          <span class="field field--name-title"><a href="/people/dmitry-abanin">Dmitry Abanin</a></span>
          <div class="field field--name-field-ps-people-position field__item">Professor of Physics</div>
        </div>
      </div>
    </body></html>
    """

    class FakeClient:
        async def fetch(self, url, approved_domains):
            assert url == "https://phy.princeton.edu/people/faculty"
            return SimpleNamespace(url=url, text=html, status_code=200)

        async def aclose(self) -> None:
            return None

    stage = Stage2ScrapeFaculty(test_settings)
    source = SimpleNamespace(roster_url="https://phy.princeton.edu/people/faculty", parser_hint="princeton_content_list")
    monkeypatch.setattr("profsearch.pipeline.stage2_scrape_faculty.AsyncHtmlClient", lambda settings: FakeClient())
    monkeypatch.setattr(
        "profsearch.pipeline.stage2_scrape_faculty.extract_pagination_urls",
        lambda html, url: ["https://phy.princeton.edu/people/faculty?pager_id=0&page=1"],
    )

    result = asyncio.run(stage._scrape_source(source, {"princeton.edu"}))

    assert result.error is None
    assert result.final_url == "https://phy.princeton.edu/people/faculty"
    assert len(result.entries) == 1
    assert result.entries[0].title == "Professor of Physics"
