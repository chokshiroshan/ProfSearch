"""Tests for the agentic email drafter: backends, core logic, CLI, and web route."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from profsearch.agentic import (
    EmailDraftRequest,
    LLMError,
    UserProfile,
    build_backend,
    draft_outreach_email,
)
from profsearch.agentic.backends import AnthropicBackend, EchoBackend, FakeBackend, LLMResponse
from profsearch.cli import cli
from profsearch.db.models import (
    FacultyCandidate,
    OpenAlexAuthorMatch,
    Professor,
    ProfessorWork,
    University,
    Work,
)
from profsearch.web import create_app
from profsearch.web.deps import get_session, get_settings


# ── Fixtures ──


@pytest.fixture()
def web_app(test_settings, session_factory):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session_factory()
    app.dependency_overrides[get_settings] = lambda: test_settings
    return app


@pytest.fixture()
def client(web_app):
    return TestClient(web_app)


@pytest.fixture()
def professor_with_works(session_factory):
    """Seed a professor with works so the drafter has context to ground an email."""
    with session_factory() as session:
        uni = University(name="Stanford University", domain="stanford.edu", status="completed")
        session.add(uni)
        session.flush()

        candidate = FacultyCandidate(
            university_id=uni.id,
            department_source_id=0,
            department_type="physics",
            name="Alice Park",
            normalized_name="alice park",
            title="Associate Professor of Physics",
            email="apark@stanford.edu",
            profile_url="https://stanford.edu/~apark",
            source_url="https://stanford.edu/physics/people",
            scrape_status="captured",
        )
        session.add(candidate)
        session.flush()

        professor = Professor(
            candidate_id=candidate.id,
            university_id=uni.id,
            department_type="physics",
            name="Alice Park",
            normalized_name="alice park",
            title="Associate Professor of Physics",
            title_normalized="associate professor",
            email="apark@stanford.edu",
            profile_url="https://stanford.edu/~apark",
            source_url="https://stanford.edu/physics/people",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()

        match = OpenAlexAuthorMatch(
            professor_id=professor.id,
            openalex_author_id="A99999",
            match_status="matched",
            match_score=0.97,
            evidence_json='{"selected": {"name": "Alice Park"}}',
            matched_at=datetime.now(timezone.utc),
        )
        session.add(match)

        works = [
            Work(
                openalex_work_id="https://openalex.org/W200",
                title="Tensor network approaches to quantum error correction",
                abstract="We present a tensor network framework for simulating surface codes.",
                publication_year=2025,
                doi="10.1234/tn-qec",
                source_name="Nature Physics",
                cited_by_count=30,
            ),
            Work(
                openalex_work_id="https://openalex.org/W201",
                title="Topological phases in Rydberg atom arrays",
                abstract="Emergent topological order observed in programmable Rydberg platforms.",
                publication_year=2024,
                source_name="Science",
                cited_by_count=22,
            ),
        ]
        session.add_all(works)
        session.flush()

        session.add_all([
            ProfessorWork(
                professor_id=professor.id,
                work_id=works[0].id,
                authorship_position="first",
                is_corresponding=True,
            ),
            ProfessorWork(
                professor_id=professor.id,
                work_id=works[1].id,
                authorship_position="last",
            ),
        ])
        session.commit()

        return {
            "professor_id": professor.id,
            "university_id": uni.id,
            "work_ids": [w.id for w in works],
        }


# ── Backend unit tests ──


class TestFakeBackend:
    def test_returns_deterministic_response(self):
        backend = FakeBackend()
        resp = backend.complete("system prompt", "user prompt")
        assert resp.backend == "fake"
        assert resp.model == "fake"
        assert isinstance(resp.text, str)
        assert len(resp.text) > 0

    def test_extracts_interest_from_prompt(self):
        backend = FakeBackend()
        resp = backend.complete(
            "sys",
            "Professor name: Alice Park\nApplicant research interest: quantum error correction\nApplicant name: Bob",
        )
        assert "quantum error correction" in resp.text

    def test_extracts_paper_title_from_prompt(self):
        backend = FakeBackend()
        resp = backend.complete(
            "sys",
            '- Paper 1 title: "My Cool Paper"\nApplicant research interest: stuff\nProfessor name: Alice Park',
        )
        assert "My Cool Paper" in resp.text

    def test_custom_reply(self):
        backend = FakeBackend(reply="Custom reply text")
        resp = backend.complete("sys", "user")
        assert resp.text == "Custom reply text"


class TestEchoBackend:
    def test_returns_rendered_prompt(self):
        backend = EchoBackend()
        resp = backend.complete("SYS", "USER")
        assert "[system]" in resp.text
        assert "SYS" in resp.text
        assert "[user]" in resp.text
        assert "USER" in resp.text
        assert resp.backend == "echo"


class TestBuildBackend:
    def test_default_is_anthropic(self):
        backend = build_backend()
        assert isinstance(backend, AnthropicBackend)

    def test_fake(self):
        assert isinstance(build_backend("fake"), FakeBackend)

    def test_echo(self):
        assert isinstance(build_backend("echo"), EchoBackend)

    def test_unknown_raises(self):
        with pytest.raises(LLMError, match="Unknown LLM backend"):
            build_backend("nonexistent")


# ── Core draft logic ──


class TestDraftOutreachEmail:
    def test_returns_drafted_email(self, session_factory, professor_with_works):
        with session_factory() as session:
            req = EmailDraftRequest(
                professor_id=professor_with_works["professor_id"],
                profile=UserProfile(
                    interest="quantum error correction with tensor networks",
                    name="Jordan Lee",
                    background=" undergrad at MIT",
                    stage="PhD applicant",
                ),
            )
            result = draft_outreach_email(session, req, backend=FakeBackend())

        assert result.professor_name == "Alice Park"
        assert result.university_name == "Stanford University"
        assert result.backend == "fake"
        assert "Jordan Lee" in result.body
        assert len(result.referenced_works) == 2
        assert result.referenced_works[0]["title"] == "Tensor network approaches to quantum error correction"

    def test_empty_interest_raises(self, session_factory, professor_with_works):
        with session_factory() as session:
            req = EmailDraftRequest(
                professor_id=professor_with_works["professor_id"],
                profile=UserProfile(interest="   "),
            )
            with pytest.raises(LLMError, match="interest is required"):
                draft_outreach_email(session, req, backend=FakeBackend())

    def test_missing_professor_raises(self, session_factory):
        with session_factory() as session:
            req = EmailDraftRequest(
                professor_id=999999,
                profile=UserProfile(interest="something"),
            )
            with pytest.raises(LLMError, match="not found"):
                draft_outreach_email(session, req, backend=FakeBackend())

    def test_no_works_raises(self, session_factory):
        with session_factory() as session:
            uni = University(name="Empty U", domain="empty.edu", status="completed")
            session.add(uni)
            session.flush()
            cand = FacultyCandidate(
                university_id=uni.id,
                department_source_id=0,
                department_type="physics",
                name="No Works",
                normalized_name="no works",
                source_url="https://example.edu/physics",
                scrape_status="captured",
            )
            session.add(cand)
            session.flush()
            prof = Professor(
                candidate_id=cand.id,
                university_id=uni.id,
                department_type="physics",
                name="No Works",
                normalized_name="no works",
                title_normalized="unknown",
                source_url="https://example.edu/physics",
                verification_status="verified",
                scraped_at=datetime.now(timezone.utc),
            )
            session.add(prof)
            session.commit()
            pid = prof.id

        with session_factory() as session:
            req = EmailDraftRequest(professor_id=pid, profile=UserProfile(interest="stuff"))
            with pytest.raises(LLMError, match="no ingested works"):
                draft_outreach_email(session, req, backend=FakeBackend())


# ── CLI draft-email command ──


class TestDraftEmailCLI:
    def test_fake_backend_output(self, session_factory, professor_with_works, monkeypatch, tmp_path):
        db_path = tmp_path / "data" / "profsearch.db"
        monkeypatch.setenv("PROFSEARCH_DB_PATH", str(db_path))
        monkeypatch.setenv("PROFSEARCH_DATA_DIR", str(tmp_path / "data"))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "draft-email",
                "--prof-id",
                str(professor_with_works["professor_id"]),
                "--interest",
                "quantum error correction",
                "--your-name",
                "Test User",
                "--llm-backend",
                "fake",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert "Alice Park" in result.output
        assert "Stanford" in result.output
        assert "Test User" in result.output


# ── Web route POST /prof/{id}/draft-email ──


class TestDraftEmailWebRoute:
    def test_returns_result_fragment(self, client, professor_with_works):
        pid = professor_with_works["professor_id"]
        resp = client.post(
            f"/prof/{pid}/draft-email",
            data={
                "interest": "topological phases in Rydberg arrays",
                "applicant_name": "Sam Rivera",
                "background": "",
                "stage": "phd",
                "llm_backend": "fake",
            },
        )
        assert resp.status_code == 200
        assert "email-draft-result" in resp.text
        assert "Sam Rivera" in resp.text
        assert "Copy to clipboard" in resp.text

    def test_empty_interest_returns_error(self, client, professor_with_works):
        pid = professor_with_works["professor_id"]
        resp = client.post(
            f"/prof/{pid}/draft-email",
            data={
                "interest": "",
                "llm_backend": "fake",
            },
        )
        # FastAPI Form(...) rejects empty required fields with 422
        assert resp.status_code == 422

    def test_unknown_professor_returns_error(self, client):
        resp = client.post(
            "/prof/999999/draft-email",
            data={
                "interest": "something",
                "llm_backend": "fake",
            },
        )
        assert resp.status_code == 400
        assert "email-draft-error" in resp.text
