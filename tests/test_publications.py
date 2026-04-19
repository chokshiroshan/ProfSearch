from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from profsearch.db.models import OpenAlexAuthorMatch, Professor, ProfessorWork, University, Work
from profsearch.pipeline.stage5_publications import Stage5Publications


def test_stage5_only_ingests_for_verified_professors(session_factory, test_settings, monkeypatch) -> None:
    async def fake_fetch_works_with_client(self, client, author_id: str) -> list[dict]:
        return [
            {
                "id": f"https://openalex.org/W-{author_id.rsplit('/', 1)[-1]}",
                "title": f"Paper for {author_id}",
                "abstract_inverted_index": {"soft": [0], "matter": [1]},
                "publication_year": 2025,
                "publication_date": "2025-01-01",
                "doi": None,
                "cited_by_count": 1,
                "primary_location": {"source": {"display_name": "Test Journal"}},
                "type": "article",
                "topics": [],
                "authorships": [
                    {
                        "author": {"id": author_id},
                        "author_position": "first",
                        "is_corresponding": True,
                    }
                ],
            }
        ]

    monkeypatch.setattr(Stage5Publications, "_fetch_works_with_client", fake_fetch_works_with_client)

    with session_factory() as session:
        university = University(name="Publication University", domain="example.edu", status="matched")
        session.add(university)
        session.flush()

        verified_professor = Professor(
            candidate_id=1,
            university_id=university.id,
            department_type="physics",
            name="Verified Example",
            normalized_name="verified example",
            title="Professor of Physics",
            title_normalized="professor",
            email="verified@example.edu",
            profile_url="https://example.edu/verified",
            source_url="https://example.edu/physics",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        ambiguous_professor = Professor(
            candidate_id=2,
            university_id=university.id,
            department_type="physics",
            name="Ambiguous Example",
            normalized_name="ambiguous example",
            title="Visiting Professor of Physics",
            title_normalized="ambiguous",
            email="ambiguous@example.edu",
            profile_url="https://example.edu/ambiguous",
            source_url="https://example.edu/physics",
            source_snippet="Visiting Professor of Physics",
            verification_status="ambiguous",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add_all([verified_professor, ambiguous_professor])
        session.flush()

        session.add_all(
            [
                OpenAlexAuthorMatch(
                    professor_id=verified_professor.id,
                    openalex_author_id="https://openalex.org/A-verified",
                    match_status="matched",
                    match_score=0.95,
                    evidence_json="{}",
                ),
                OpenAlexAuthorMatch(
                    professor_id=ambiguous_professor.id,
                    openalex_author_id="https://openalex.org/A-ambiguous",
                    match_status="matched",
                    match_score=0.91,
                    evidence_json="{}",
                ),
            ]
        )
        session.commit()

        outcome = Stage5Publications(test_settings).run(session)
        session.commit()

        works = session.scalars(select(Work).order_by(Work.id)).all()
        links = session.scalars(select(ProfessorWork).order_by(ProfessorWork.professor_id)).all()

    assert outcome["authors_processed"] == 1
    assert len(works) == 1
    assert len(links) == 1
    assert links[0].professor_id == verified_professor.id


def test_stage5_skips_professors_with_existing_work_links(session_factory, test_settings, monkeypatch) -> None:
    async def fake_fetch_works_with_client(self, client, author_id: str) -> list[dict]:
        return [
            {
                "id": f"https://openalex.org/W-{author_id.rsplit('/', 1)[-1]}",
                "title": f"Fresh paper for {author_id}",
                "abstract_inverted_index": {"quantum": [0]},
                "publication_year": 2025,
                "publication_date": "2025-01-01",
                "doi": None,
                "cited_by_count": 1,
                "primary_location": {"source": {"display_name": "Test Journal"}},
                "type": "article",
                "topics": [],
                "authorships": [
                    {
                        "author": {"id": author_id},
                        "author_position": "first",
                        "is_corresponding": True,
                    }
                ],
            }
        ]

    monkeypatch.setattr(Stage5Publications, "_fetch_works_with_client", fake_fetch_works_with_client)

    with session_factory() as session:
        university = University(name="Incremental Publications University", domain="example.edu", status="matched")
        session.add(university)
        session.flush()

        first = Professor(
            candidate_id=1,
            university_id=university.id,
            department_type="physics",
            name="Existing Corpus Example",
            normalized_name="existing corpus example",
            title="Professor of Physics",
            title_normalized="professor",
            profile_url="https://example.edu/existing",
            source_url="https://example.edu/physics",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        second = Professor(
            candidate_id=2,
            university_id=university.id,
            department_type="physics",
            name="New Corpus Example",
            normalized_name="new corpus example",
            title="Professor of Physics",
            title_normalized="professor",
            profile_url="https://example.edu/new",
            source_url="https://example.edu/physics",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add_all([first, second])
        session.flush()

        existing_work = Work(openalex_work_id="https://openalex.org/W-existing", title="Existing paper")
        session.add(existing_work)
        session.flush()
        session.add(ProfessorWork(professor_id=first.id, work_id=existing_work.id, authorship_position="first"))

        session.add_all(
            [
                OpenAlexAuthorMatch(
                    professor_id=first.id,
                    openalex_author_id="https://openalex.org/A-existing",
                    match_status="matched",
                    match_score=0.95,
                    evidence_json="{}",
                ),
                OpenAlexAuthorMatch(
                    professor_id=second.id,
                    openalex_author_id="https://openalex.org/A-new",
                    match_status="matched",
                    match_score=0.93,
                    evidence_json="{}",
                ),
            ]
        )
        session.commit()

        outcome = Stage5Publications(test_settings).run(session)
        session.commit()

        links = session.scalars(select(ProfessorWork).order_by(ProfessorWork.professor_id, ProfessorWork.work_id)).all()

    assert outcome["authors_processed"] == 1
    assert len(links) == 2
    assert {link.professor_id for link in links} == {first.id, second.id}
