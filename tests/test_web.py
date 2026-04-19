"""Tests for the ProfSearch web UI routes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from profsearch.db.models import (
    FacultyCandidate,
    OpenAlexAuthorMatch,
    PipelineState,
    Professor,
    ProfessorWork,
    University,
    Work,
)
from profsearch.db.vectors import upsert_embedding
from profsearch.embedding.encoder import EmbeddingEncoder
from profsearch.web import create_app
from profsearch.web.deps import get_encoder, get_session, get_settings


@pytest.fixture()
def web_app(test_settings, session_factory):
    app = create_app()
    encoder = EmbeddingEncoder(test_settings)

    def _override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_encoder] = lambda: encoder
    app.dependency_overrides[get_settings] = lambda: test_settings
    return app


@pytest.fixture()
def client(web_app):
    return TestClient(web_app)


@pytest.fixture()
def seeded_db(session_factory, test_settings):
    """Create a university, professor, match, works, and embeddings for testing."""
    encoder = EmbeddingEncoder(test_settings)
    with session_factory() as session:
        university = University(name="MIT", domain="mit.edu", status="completed")
        session.add(university)
        session.flush()

        candidate = FacultyCandidate(
            university_id=university.id,
            department_source_id=0,
            department_type="physics",
            name="Jane Doe",
            normalized_name="jane doe",
            title="Professor of Physics",
            email="jane@mit.edu",
            profile_url="https://mit.edu/jane",
            source_url="https://mit.edu/physics/people",
            scrape_status="captured",
        )
        session.add(candidate)
        session.flush()

        professor = Professor(
            candidate_id=candidate.id,
            university_id=university.id,
            department_type="physics",
            name="Jane Doe",
            normalized_name="jane doe",
            title="Professor of Physics",
            title_normalized="professor",
            email="jane@mit.edu",
            profile_url="https://mit.edu/jane",
            source_url="https://mit.edu/physics/people",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()

        match = OpenAlexAuthorMatch(
            professor_id=professor.id,
            openalex_author_id="A12345",
            match_status="matched",
            match_score=0.95,
            evidence_json='{"selected": {"name": "Jane Doe"}}',
            matched_at=datetime.now(timezone.utc),
        )
        session.add(match)

        works = [
            Work(
                openalex_work_id="https://openalex.org/W100",
                title="Quantum materials with topological order",
                abstract="A study of quantum materials and emergent phases.",
                publication_year=2024,
                doi="10.1234/test1",
                source_name="Physical Review Letters",
                cited_by_count=42,
            ),
            Work(
                openalex_work_id="https://openalex.org/W101",
                title="Spin liquids in frustrated magnets",
                abstract="Quantum spin liquid states in kagome lattice materials.",
                publication_year=2023,
                source_name="Nature Physics",
                cited_by_count=18,
            ),
            Work(
                openalex_work_id="https://openalex.org/W102",
                title="Topological transport in correlated quantum materials",
                abstract="Transport signatures and emergent quasiparticles in quantum materials.",
                publication_year=2022,
                source_name="Science Advances",
                cited_by_count=27,
            ),
            Work(
                openalex_work_id="https://openalex.org/W103",
                title="Neutron scattering constraints on spin-orbit coupled systems",
                abstract="Experimental probes of spin-orbit coupled magnetic phases.",
                publication_year=2021,
                source_name="Physical Review B",
                cited_by_count=14,
            ),
        ]
        session.add_all(works)
        session.flush()

        session.add_all([
            ProfessorWork(professor_id=professor.id, work_id=works[0].id, authorship_position="first", is_corresponding=True),
            ProfessorWork(professor_id=professor.id, work_id=works[1].id, authorship_position="last"),
            ProfessorWork(professor_id=professor.id, work_id=works[2].id, authorship_position="middle"),
            ProfessorWork(professor_id=professor.id, work_id=works[3].id, authorship_position="middle"),
        ])

        pipeline = PipelineState(
            stage_name="stage1",
            status="completed",
            total_items=18,
            processed_items=18,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(pipeline)
        session.commit()

        for work in works:
            upsert_embedding(
                session.bind,
                work.id,
                encoder.encode_one(f"{work.title} [SEP] {work.abstract}"),
                encoder.backend,
            )
        session.commit()

    return {"university_id": university.id, "professor_id": professor.id}


# ── Search page ──


def test_search_page_renders_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Search" in resp.text
    assert 'name="q"' in resp.text
    assert 'hx-get="/"' in resp.text
    assert 'hx-select="#results > *"' in resp.text
    assert 'hx-push-url="true"' in resp.text
    assert 'hx-indicator="#search-loading, #results"' in resp.text


def test_search_results_returns_professors(client, seeded_db):
    resp = client.get("/search/results?q=quantum+materials", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "Jane Doe" in resp.text
    assert "MIT" in resp.text


def test_search_results_sets_canonical_push_url(client, seeded_db):
    resp = client.get(
        "/search/results?q=quantum+materials&university=MIT&department_type=physics&verification=verified&match_status=matched",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert (
        resp.headers["HX-Push-Url"]
        == "/?q=quantum+materials&university=MIT&department_type=physics&verification=verified&match_status=matched"
    )


def test_search_results_empty_query(client, seeded_db):
    resp = client.get("/search/results?q=", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "Jane Doe" not in resp.text


def test_search_results_redirects_to_full_page_when_not_htmx(client, seeded_db):
    resp = client.get("/search/results?q=quantum+materials&university=MIT", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/?q=quantum+materials&university=MIT"


def test_search_full_page_with_query(client, seeded_db):
    resp = client.get("/?q=quantum+materials")
    assert resp.status_code == 200
    assert "Jane Doe" in resp.text
    assert "Quantum materials" in resp.text


def test_search_page_restores_query_and_filters_from_url(client, seeded_db):
    resp = client.get(
        "/?q=quantum+materials&university=MIT&department_type=physics&verification=verified&match_status=matched"
    )
    assert resp.status_code == 200
    assert "Jane Doe" in resp.text
    assert 'name="q" value="quantum materials"' in resp.text
    assert 'id="hf-university" value="MIT"' in resp.text
    assert 'id="hf-department_type" value="physics"' in resp.text
    assert 'id="hf-verification" value="verified"' in resp.text
    assert 'id="hf-match_status" value="matched"' in resp.text


def test_search_results_show_all_works_links_to_professor_page(client, seeded_db):
    resp = client.get("/search/results?q=quantum+materials", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert f'href="/professor/{seeded_db["professor_id"]}"' in resp.text
    assert "Show all 4 ranked works" in resp.text
    assert "/search/works/" not in resp.text


def test_search_with_university_filter(client, seeded_db):
    resp = client.get("/search/results?q=quantum+materials&university=MIT", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "Jane Doe" in resp.text


def test_search_with_nonmatching_filter(client, seeded_db):
    resp = client.get("/search/results?q=quantum+materials&university=Stanford", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "Jane Doe" not in resp.text


# ── Professor detail ──


def test_professor_detail_renders(client, seeded_db):
    resp = client.get(f"/professor/{seeded_db['professor_id']}")
    assert resp.status_code == 200
    assert "Jane Doe" in resp.text
    assert "MIT" in resp.text
    assert "verified" in resp.text
    assert "matched" in resp.text
    assert "A12345" in resp.text
    assert "https://mit.edu/jane" in resp.text
    assert "Quantum materials with topological order" in resp.text


def test_professor_detail_404(client):
    resp = client.get("/professor/999999")
    assert resp.status_code == 404


# ── Pipeline ──


def test_pipeline_status_renders(client, seeded_db):
    resp = client.get("/pipeline")
    assert resp.status_code == 200
    assert "load_seed_universities" in resp.text
    assert "completed" in resp.text
    assert "18" in resp.text


# ── Shortlist & compare ──


def test_shortlist_js_served(client):
    resp = client.get("/static/shortlist.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "profsearch.shortlist.v1" in resp.text
    assert "exportCsv" in resp.text


def test_search_results_include_save_button(client, seeded_db):
    resp = client.get("/search/results?q=quantum+materials", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert f'data-shortlist-toggle="{seeded_db["professor_id"]}"' in resp.text
    assert 'data-name="Jane Doe"' in resp.text


def test_professor_detail_includes_save_button(client, seeded_db):
    resp = client.get(f"/professor/{seeded_db['professor_id']}")
    assert resp.status_code == 200
    assert f'data-shortlist-toggle="{seeded_db["professor_id"]}"' in resp.text


def test_base_layout_renders_shortlist_panel_and_compare_nav(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="shortlist-panel"' in resp.text
    assert 'href="/compare"' in resp.text
    assert '/static/shortlist.js' in resp.text


def test_compare_page_empty(client):
    resp = client.get("/compare")
    assert resp.status_code == 200
    assert "No professors to compare" in resp.text


def test_compare_page_with_one_professor(client, seeded_db):
    resp = client.get(f"/compare?ids={seeded_db['professor_id']}")
    assert resp.status_code == 200
    assert "Jane Doe" in resp.text
    assert "MIT" in resp.text
    assert "Recent works" in resp.text


def test_compare_page_ignores_invalid_ids(client, seeded_db):
    resp = client.get(f"/compare?ids=abc,{seeded_db['professor_id']},,999999")
    assert resp.status_code == 200
    assert "Jane Doe" in resp.text


def test_compare_page_caps_at_four_ids(client, seeded_db):
    resp = client.get("/compare?ids=1,2,3,4,5,6,7")
    assert resp.status_code == 200
    assert "No professors to compare" in resp.text or "compare-col" in resp.text


# ── Static assets ──


def test_static_css_served(client):
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]
