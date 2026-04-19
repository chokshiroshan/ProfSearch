"""Tests for funding module: Grant model, client parsers, stage7, and web UI."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from profsearch.agentic.backends import FakeBackend
from profsearch.config import Settings
from profsearch.db.models import (
    FacultyCandidate,
    Grant,
    OpenAlexAuthorMatch,
    Professor,
    ProfessorWork,
    University,
    Work,
)
from profsearch.funding.client import RawGrant, _parse_nih_grant, _parse_nsf_grant
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
def professor_with_grants(session_factory):
    """Seed a professor with grants for testing the funding badge."""
    with session_factory() as session:
        uni = University(name="MIT", domain="mit.edu", status="completed")
        session.add(uni)
        session.flush()

        cand = FacultyCandidate(
            university_id=uni.id,
            department_source_id=0,
            department_type="physics",
            name="Jane Doe",
            normalized_name="jane doe",
            source_url="https://mit.edu/physics",
            scrape_status="captured",
        )
        session.add(cand)
        session.flush()

        professor = Professor(
            candidate_id=cand.id,
            university_id=uni.id,
            department_type="physics",
            name="Jane Doe",
            normalized_name="jane doe",
            title="Professor of Physics",
            title_normalized="professor",
            source_url="https://mit.edu/physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()

        match = OpenAlexAuthorMatch(
            professor_id=professor.id,
            openalex_author_id="A123",
            match_status="matched",
            match_score=0.95,
            matched_at=datetime.now(timezone.utc),
        )
        session.add(match)

        grants = [
            Grant(
                professor_id=professor.id,
                source="nih",
                grant_id="R01-12345",
                title="Quantum Error Correction in Topological Codes",
                pi_name="Jane Doe",
                amount=500000.0,
                start_date="2024-06-01",
                end_date="2028-05-31",
                raw_json='{"fake": true}',
            ),
            Grant(
                professor_id=professor.id,
                source="nsf",
                grant_id="PHY-23456",
                title="Emergent Phenomena in Frustrated Magnets",
                pi_name="Jane Doe",
                amount=350000.0,
                start_date="2022-01-01",
                end_date="2025-12-31",
                raw_json='{"fake": true}',
            ),
        ]
        session.add_all(grants)
        session.commit()

        return {"professor_id": professor.id, "university_id": uni.id}


# ── NIH parser ──


class TestNIHParser:
    def test_parses_project(self):
        item = {
            "project_num": "R01GM123456",
            "project_title": "Advancing Quantum Computing",
            "award_amount": 450000,
            "project_start_date": "2024-07-01",
            "project_end_date": "2028-06-30",
            "principal_investigators": [{"full_name": "Jane Doe"}],
        }
        grant = _parse_nih_grant(item)
        assert grant.source == "nih"
        assert grant.grant_id == "R01GM123456"
        assert grant.title == "Advancing Quantum Computing"
        assert grant.amount == 450000.0
        assert grant.start_date == "2024-07-01"
        assert grant.end_date == "2028-06-30"
        assert grant.pi_name == "Jane Doe"

    def test_handles_missing_fields(self):
        item = {}
        grant = _parse_nih_grant(item)
        assert grant.source == "nih"
        assert grant.grant_id == ""
        assert grant.amount is None
        assert grant.pi_name == ""


# ── NSF parser ──


class TestNSFParser:
    def test_parses_award(self):
        item = {
            "id": "1234567",
            "title": "CAREER: Quantum Information",
            "fundsObligatedAmt": 550000,
            "startDate": "2023-08-01",
            "expDate": "2028-07-31",
            "piFirstName": "Jane",
            "piLastName": "Doe",
        }
        grant = _parse_nsf_grant(item)
        assert grant.source == "nsf"
        assert grant.grant_id == "1234567"
        assert grant.title == "CAREER: Quantum Information"
        assert grant.amount == 550000.0
        assert grant.pi_name == "Jane Doe"

    def test_handles_missing_fields(self):
        item = {}
        grant = _parse_nsf_grant(item)
        assert grant.source == "nsf"
        assert grant.grant_id == ""
        assert grant.amount is None
        assert grant.pi_name == ""


# ── Grant model ──


class TestGrantModel:
    def test_insert_and_query(self, session_factory):
        with session_factory() as session:
            uni = University(name="Test U", domain="test.edu", status="completed")
            session.add(uni)
            session.flush()
            cand = FacultyCandidate(
                university_id=uni.id,
                department_source_id=0,
                department_type="physics",
                name="Test Prof",
                normalized_name="test prof",
                source_url="https://test.edu",
                scrape_status="captured",
            )
            session.add(cand)
            session.flush()
            prof = Professor(
                candidate_id=cand.id,
                university_id=uni.id,
                department_type="physics",
                name="Test Prof",
                normalized_name="test prof",
                title_normalized="professor",
                source_url="https://test.edu",
                verification_status="verified",
                scraped_at=datetime.now(timezone.utc),
            )
            session.add(prof)
            session.flush()

            grant = Grant(
                professor_id=prof.id,
                source="nih",
                grant_id="R01-TEST",
                title="Test Grant",
                amount=100000.0,
                start_date="2025-01-01",
                end_date="2027-12-31",
            )
            session.add(grant)
            session.commit()

        with session_factory() as session:
            grants = session.query(Grant).all()
            assert len(grants) == 1
            assert grants[0].source == "nih"
            assert grants[0].title == "Test Grant"
            assert grants[0].professor_id == prof.id


# ── Web UI: funding badge on professor detail ──


class TestFundingWebUI:
    def test_professor_detail_shows_funded_badge(self, client, professor_with_grants):
        pid = professor_with_grants["professor_id"]
        resp = client.get(f"/professor/{pid}")
        assert resp.status_code == 200
        assert "actively funded" in resp.text
        assert "$850,000" in resp.text  # 500k + 350k
        assert "Show grants" in resp.text

    def test_professor_detail_shows_no_grants(self, client, session_factory):
        with session_factory() as session:
            uni = University(name="NoGrants U", domain="nogrants.edu", status="completed")
            session.add(uni)
            session.flush()
            cand = FacultyCandidate(
                university_id=uni.id,
                department_source_id=0,
                department_type="physics",
                name="No Grants",
                normalized_name="no grants",
                source_url="https://nogrants.edu",
                scrape_status="captured",
            )
            session.add(cand)
            session.flush()
            prof = Professor(
                candidate_id=cand.id,
                university_id=uni.id,
                department_type="physics",
                name="No Grants",
                normalized_name="no grants",
                title_normalized="unknown",
                source_url="https://nogrants.edu",
                verification_status="verified",
                scraped_at=datetime.now(timezone.utc),
            )
            session.add(prof)
            session.commit()
            pid = prof.id

        resp = client.get(f"/professor/{pid}")
        assert resp.status_code == 200
        assert "No grants found" in resp.text
        assert "actively funded" not in resp.text

    def test_professor_detail_shows_past_grants(self, client, session_factory):
        with session_factory() as session:
            uni = University(name="PastGrants U", domain="past.edu", status="completed")
            session.add(uni)
            session.flush()
            cand = FacultyCandidate(
                university_id=uni.id,
                department_source_id=0,
                department_type="physics",
                name="Past Grants",
                normalized_name="past grants",
                source_url="https://past.edu",
                scrape_status="captured",
            )
            session.add(cand)
            session.flush()
            prof = Professor(
                candidate_id=cand.id,
                university_id=uni.id,
                department_type="physics",
                name="Past Grants",
                normalized_name="past grants",
                title_normalized="unknown",
                source_url="https://past.edu",
                verification_status="verified",
                scraped_at=datetime.now(timezone.utc),
            )
            session.add(prof)
            session.flush()

            grant = Grant(
                professor_id=prof.id,
                source="nsf",
                grant_id="OLD-001",
                title="Expired Grant",
                amount=100000.0,
                start_date="2020-01-01",
                end_date="2023-12-31",
            )
            session.add(grant)
            session.commit()
            pid = prof.id

        resp = client.get(f"/professor/{pid}")
        assert resp.status_code == 200
        assert "grants (past)" in resp.text
        assert "no active grants" in resp.text
        assert "actively funded" not in resp.text
