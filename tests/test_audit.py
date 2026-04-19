from __future__ import annotations

from datetime import datetime, timezone

from profsearch.audit import audit_publications
from profsearch.db.models import OpenAlexAuthorMatch, Professor, ProfessorWork, University, Work


def test_audit_publications_flags_low_alignment_corpus(session_factory) -> None:
    with session_factory() as session:
        university = University(name="Audit University", domain="example.edu", status="matched")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=1,
            university_id=university.id,
            department_type="astronomy",
            name="Casey Example",
            normalized_name="casey example",
            title="Assistant Professor of Astronomy",
            title_normalized="assistant_professor",
            email="casey@example.edu",
            profile_url="https://example.edu/casey",
            profile_text="Casey studies exoplanets, cosmology, and stellar dynamics.",
            source_url="https://example.edu/faculty",
            source_snippet="Assistant Professor of Astronomy",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        session.add(
            OpenAlexAuthorMatch(
                professor_id=professor.id,
                openalex_author_id="https://openalex.org/A1",
                match_status="matched",
                match_score=1.0,
                evidence_json="{}",
            )
        )
        for idx in range(20):
            work = Work(
                openalex_work_id=f"https://openalex.org/W{idx}",
                title=f"Hybrid attention model for assisted driving {idx}",
                abstract="A machine learning paper about lane detection and image processing.",
                publication_year=2025,
                source_name="Journal of Automotive AI",
            )
            session.add(work)
            session.flush()
            session.add(ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="first"))
        session.commit()

        findings = audit_publications(session, min_works=15, limit=10)

    assert findings
    assert findings[0].professor_name == "Casey Example"
    assert "low_profile_alignment" in findings[0].reasons
    assert "low_department_alignment" in findings[0].reasons


def test_audit_publications_uses_profile_alignment_to_avoid_false_flags(session_factory) -> None:
    with session_factory() as session:
        university = University(name="Profile University", domain="example.edu", status="matched")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=2,
            university_id=university.id,
            department_type="applied_physics",
            name="Jordan Example",
            normalized_name="jordan example",
            title="Assistant Professor of Applied Physics",
            title_normalized="assistant_professor",
            email="jordan@example.edu",
            profile_url="https://example.edu/jordan",
            profile_text="Jordan develops neural imaging systems and studies cortical circuits in behaving animals.",
            source_url="https://example.edu/faculty",
            source_snippet="Assistant Professor of Applied Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        session.add(
            OpenAlexAuthorMatch(
                professor_id=professor.id,
                openalex_author_id="https://openalex.org/A2",
                match_status="matched",
                match_score=1.0,
                evidence_json="{}",
            )
        )
        for idx in range(22):
            work = Work(
                openalex_work_id=f"https://openalex.org/P{idx}",
                title=f"Neural circuit dynamics during social behavior {idx}",
                abstract="Two-photon imaging resolves cortical population activity in behaving animals.",
                publication_year=2025,
                source_name="Neuron",
            )
            session.add(work)
            session.flush()
            session.add(ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="first"))
        session.commit()

        findings = audit_publications(session, min_works=15, limit=10)

    assert not any(item.professor_name == "Jordan Example" for item in findings)


def test_audit_publications_uses_duplicate_affiliation_context(session_factory) -> None:
    with session_factory() as session:
        university = University(name="Joint Appointment University", domain="example.edu", status="matched")
        session.add(university)
        session.flush()
        canonical = Professor(
            candidate_id=3,
            university_id=university.id,
            department_type="physics",
            name="Taylor Example",
            normalized_name="taylor example",
            title="Professor of Physics",
            title_normalized="professor",
            email="taylor@example.edu",
            profile_url="https://example.edu/taylor-physics",
            source_url="https://example.edu/physics",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(canonical)
        session.flush()
        session.add(
            Professor(
                candidate_id=4,
                university_id=university.id,
                department_type="applied_physics",
                name="Taylor Example",
                normalized_name="taylor example",
                title="Professor of Applied Physics",
                title_normalized="professor",
                email="taylor@example.edu",
                profile_url="https://example.edu/taylor-ap",
                profile_text="Taylor develops laser imaging systems and nanophotonic devices.",
                source_url="https://example.edu/applied-physics",
                source_snippet="Professor of Applied Physics",
                verification_status="verified",
                duplicate_of_professor_id=canonical.id,
                duplicate_reason="same_university_name",
                scraped_at=datetime.now(timezone.utc),
            )
        )
        session.flush()
        session.add(
            OpenAlexAuthorMatch(
                professor_id=canonical.id,
                openalex_author_id="https://openalex.org/A3",
                match_status="matched",
                match_score=1.0,
                evidence_json="{}",
            )
        )
        for idx in range(20):
            work = Work(
                openalex_work_id=f"https://openalex.org/J{idx}",
                title=f"Nanophotonic imaging with tunable laser arrays {idx}",
                abstract="Optical devices improve high-resolution laser imaging in compact photonic systems.",
                publication_year=2025,
                source_name="Applied Physics Letters",
            )
            session.add(work)
            session.flush()
            session.add(ProfessorWork(professor_id=canonical.id, work_id=work.id, authorship_position="first"))
        session.commit()

        findings = audit_publications(session, min_works=15, limit=10)

    assert not any(item.professor_name == "Taylor Example" for item in findings)
