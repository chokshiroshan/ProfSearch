from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from profsearch.db.models import Professor, ProfessorWork, University, Work, WorkEmbedding
from profsearch.db.vectors import fetch_embeddings
from profsearch.pipeline.stage6_embeddings import Stage6Embeddings


def test_stage6_embeddings_writes_missing_vectors(session_factory, test_settings) -> None:
    with session_factory() as session:
        university = University(name="Embedding University", domain="example.edu", status="completed")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=1,
            university_id=university.id,
            department_type="physics",
            name="Embedding Example",
            normalized_name="embedding example",
            title="Professor of Physics",
            title_normalized="professor",
            email="embedding@example.edu",
            profile_url="https://example.edu/embedding",
            source_url="https://example.edu/faculty",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        work = Work(
            openalex_work_id="https://openalex.org/W-embed-1",
            title="Soft matter in frustrated quantum systems",
            abstract="A study of soft matter behavior and emergent phases.",
            publication_year=2025,
        )
        session.add(work)
        session.flush()
        session.add(ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="first"))
        session.commit()

        outcome = Stage6Embeddings(test_settings).run(session)
        session.commit()

        embeddings = fetch_embeddings(session.bind, [work.id]) if session.bind is not None else {}
        stored_work = session.scalar(select(Work).where(Work.id == work.id))

    assert stored_work is not None
    assert outcome["works_encoded"] == 1
    assert work.id in embeddings
    assert len(embeddings[work.id]) == test_settings.embeddings.dimension


def test_stage6_reencodes_backend_mismatch(session_factory, test_settings) -> None:
    with session_factory() as session:
        university = University(name="Reencode University", domain="example.edu", status="completed")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=2,
            university_id=university.id,
            department_type="physics",
            name="Reencode Example",
            normalized_name="reencode example",
            title="Professor of Physics",
            title_normalized="professor",
            email="reencode@example.edu",
            profile_url="https://example.edu/reencode",
            source_url="https://example.edu/faculty",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        work = Work(
            openalex_work_id="https://openalex.org/W-embed-2",
            title="Quantum matter and soft interfaces",
            abstract="A study of soft matter and quantum interfaces.",
            publication_year=2025,
        )
        session.add(work)
        session.flush()
        session.add(ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="first"))
        session.add(
            WorkEmbedding(
                work_id=work.id,
                dimension=test_settings.embeddings.dimension,
                embedding_json="[0.0, 1.0]",
                backend="hash",
            )
        )
        session.commit()

        stage = Stage6Embeddings(test_settings)
        stage.encoder.backend = "sentence_transformers"
        stage.encoder.dimension = test_settings.embeddings.dimension
        stage.encoder.encode_one = lambda text: [0.25] * test_settings.embeddings.dimension

        outcome = stage.run(session)
        session.commit()

        refreshed = session.scalar(select(WorkEmbedding).where(WorkEmbedding.work_id == work.id))

    assert outcome["works_encoded"] == 1
    assert refreshed is not None
    assert refreshed.backend == "sentence_transformers"


def test_stage6_reacquires_connection_after_commit_boundary(session_factory, test_settings) -> None:
    with session_factory() as session:
        university = University(name="Commit Boundary University", domain="example.edu", status="completed")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=3,
            university_id=university.id,
            department_type="physics",
            name="Commit Boundary Example",
            normalized_name="commit boundary example",
            title="Professor of Physics",
            title_normalized="professor",
            email="boundary@example.edu",
            profile_url="https://example.edu/boundary",
            source_url="https://example.edu/faculty",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        works: list[Work] = []
        for index in range(3):
            work = Work(
                openalex_work_id=f"https://openalex.org/W-embed-boundary-{index}",
                title=f"Boundary work {index}",
                abstract="A study of connection handling across commit boundaries.",
                publication_year=2025,
            )
            session.add(work)
            session.flush()
            session.add(ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="first"))
            works.append(work)
        session.commit()

        stage = Stage6Embeddings(test_settings)
        stage.commit_every = 2
        stage.encoder.encode_one = lambda text: [0.5] * test_settings.embeddings.dimension

        outcome = stage.run(session)
        session.commit()

        embeddings = fetch_embeddings(session.bind, [work.id for work in works]) if session.bind is not None else {}

    assert outcome["works_encoded"] == 3
    assert set(embeddings) == {work.id for work in works}
