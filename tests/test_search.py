from __future__ import annotations

import json
from datetime import datetime, timezone

from click.testing import CliRunner

from profsearch.db.models import Professor, ProfessorWork, University, Work
from profsearch.db.vectors import upsert_embedding
from profsearch.embedding.encoder import EmbeddingEncoder
from profsearch import cli as cli_module
from profsearch.search.aggregator import rank_professors


def test_rank_professors_keeps_full_ranked_work_list(session_factory, test_settings) -> None:
    encoder = EmbeddingEncoder(test_settings)
    with session_factory() as session:
        university = University(name="Test University", domain="example.edu", status="completed")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=1,
            university_id=university.id,
            department_type="physics",
            name="Jane Doe",
            normalized_name="jane doe",
            title="Professor of Physics",
            title_normalized="professor",
            email="jane@example.edu",
            profile_url="https://example.edu/jane",
            source_url="https://example.edu/faculty",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        work = Work(
            openalex_work_id="https://openalex.org/W1",
            title="Quantum materials with topological order",
            abstract="A study of quantum materials and emergent phases.",
            publication_year=2024,
        )
        off_topic_work = Work(
            openalex_work_id="https://openalex.org/W2",
            title="Medieval tax records in rural Europe",
            abstract="A historical study of tax ledgers and agrarian policy.",
            publication_year=2022,
        )
        session.add_all([work, off_topic_work])
        session.flush()
        session.add_all(
            [
                ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="first"),
                ProfessorWork(professor_id=professor.id, work_id=off_topic_work.id, authorship_position="middle"),
            ]
        )
        session.commit()
        upsert_embedding(session.bind, work.id, encoder.encode_one(f"{work.title} [SEP] {work.abstract}"), encoder.backend)
        upsert_embedding(
            session.bind,
            off_topic_work.id,
            encoder.encode_one(f"{off_topic_work.title} [SEP] {off_topic_work.abstract}"),
            encoder.backend,
        )
        session.commit()
        hits = rank_professors(session, encoder, "quantum materials", result_limit=5, work_limit=1)
    assert hits
    assert hits[0].professor_name == "Jane Doe"
    assert hits[0].total_work_count == 2
    assert len(hits[0].supporting_works) == 2
    assert hits[0].supporting_works[0]["title"] == "Quantum materials with topological order"
    assert hits[0].supporting_works[1]["title"] == "Medieval tax records in rural Europe"
    assert hits[0].score == hits[0].supporting_works[0]["score"]


def test_search_cli_json_output_paginates_ranked_works(session_factory, test_settings, monkeypatch) -> None:
    encoder = EmbeddingEncoder(test_settings)
    with session_factory() as session:
        university = University(name="Test University", domain="example.edu", status="completed")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=2,
            university_id=university.id,
            department_type="physics",
            name="John Doe",
            normalized_name="john doe",
            title="Professor of Physics",
            title_normalized="professor",
            email="john@example.edu",
            profile_url="https://example.edu/john",
            source_url="https://example.edu/faculty",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        works = [
            Work(
                openalex_work_id="https://openalex.org/W10",
                title="Quantum materials and topology",
                abstract="Quantum materials overview.",
                publication_year=2024,
            ),
            Work(
                openalex_work_id="https://openalex.org/W11",
                title="Quantum transport in layered systems",
                abstract="Transport signatures in condensed matter systems.",
                publication_year=2023,
            ),
        ]
        session.add_all(works)
        session.flush()
        session.add_all(
            [
                ProfessorWork(professor_id=professor.id, work_id=works[0].id, authorship_position="first"),
                ProfessorWork(professor_id=professor.id, work_id=works[1].id, authorship_position="last"),
            ]
        )
        session.commit()
        for work in works:
            upsert_embedding(session.bind, work.id, encoder.encode_one(f"{work.title} [SEP] {work.abstract}"), encoder.backend)
        session.commit()
    monkeypatch.setattr(cli_module, "get_settings", lambda: test_settings)
    monkeypatch.setattr(cli_module, "_session_factory", lambda: session_factory)
    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli,
        ["search", "quantum materials", "--json-output", "--work-limit", "1", "--work-offset", "1"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["professor_name"] == "John Doe"
    assert payload[0]["total_work_count"] == 2
    assert payload[0]["returned_work_count"] == 1
    assert payload[0]["work_offset"] == 1
    assert len(payload[0]["supporting_works"]) == 1


def test_rank_professors_dedupes_preprint_and_published_versions(session_factory, test_settings) -> None:
    encoder = EmbeddingEncoder(test_settings)
    with session_factory() as session:
        university = University(name="Dup Search University", domain="example.edu", status="completed")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=3,
            university_id=university.id,
            department_type="physics",
            name="Alp Example",
            normalized_name="alp example",
            title="Professor of Physics",
            title_normalized="professor",
            email="alp@example.edu",
            profile_url="https://example.edu/alp",
            source_url="https://example.edu/faculty",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        published = Work(
            openalex_work_id="https://openalex.org/W20",
            title="Laser-Induced Spectral Diffusion of T Centers in Silicon Nanophotonic Devices",
            abstract="Laser-induced spectral diffusion in silicon nanophotonic devices for quantum optics.",
            publication_year=2025,
            doi="https://doi.org/10.1103/x2cv-2gcw",
            source_name="PRX Quantum",
        )
        preprint = Work(
            openalex_work_id="https://openalex.org/W21",
            title="Laser-induced spectral diffusion of T centers in silicon nanophotonic devices",
            abstract="Laser-induced spectral diffusion in silicon nanophotonic devices for quantum optics.",
            publication_year=2024,
            doi="https://doi.org/10.48550/arxiv.2504.08898",
            source_name="arXiv (Cornell University)",
        )
        other = Work(
            openalex_work_id="https://openalex.org/W22",
            title="Quantum defects in silicon photonic cavities",
            abstract="Quantum defects in silicon photonic cavities and devices.",
            publication_year=2024,
            source_name="Nature Photonics",
        )
        session.add_all([published, preprint, other])
        session.flush()
        session.add_all(
            [
                ProfessorWork(professor_id=professor.id, work_id=published.id, authorship_position="first"),
                ProfessorWork(professor_id=professor.id, work_id=preprint.id, authorship_position="first"),
                ProfessorWork(professor_id=professor.id, work_id=other.id, authorship_position="first"),
            ]
        )
        session.commit()
        for work in (published, preprint, other):
            upsert_embedding(session.bind, work.id, encoder.encode_one(f"{work.title} [SEP] {work.abstract}"), encoder.backend)
        session.commit()
        hits = rank_professors(session, encoder, "silicon nanophotonic devices", result_limit=5, work_limit=5)

    assert hits
    assert hits[0].professor_name == "Alp Example"
    assert hits[0].total_work_count == 2
    assert len(hits[0].supporting_works) == 2
    assert hits[0].supporting_works[0]["source_name"] == "PRX Quantum"
    assert hits[0].supporting_works[0]["title"] == published.title


def test_rank_professors_dedupes_markup_variants_of_same_title(session_factory, test_settings) -> None:
    encoder = EmbeddingEncoder(test_settings)
    with session_factory() as session:
        university = University(name="Markup University", domain="example.edu", status="completed")
        session.add(university)
        session.flush()
        professor = Professor(
            candidate_id=4,
            university_id=university.id,
            department_type="physics",
            name="Markup Example",
            normalized_name="markup example",
            title="Professor of Physics",
            title_normalized="professor",
            email="markup@example.edu",
            profile_url="https://example.edu/markup",
            source_url="https://example.edu/faculty",
            source_snippet="Professor of Physics",
            verification_status="verified",
            scraped_at=datetime.now(timezone.utc),
        )
        session.add(professor)
        session.flush()
        latex_title = Work(
            openalex_work_id="https://openalex.org/W30",
            title="Purcell enhancement of erbium ions in TiO$_{2}$ on silicon nanocavities",
            abstract="Erbium ions in titanium dioxide on silicon nanocavities.",
            publication_year=2022,
            source_name="PRX Quantum",
        )
        html_title = Work(
            openalex_work_id="https://openalex.org/W31",
            title="Purcell Enhancement of Erbium Ions in TiO<sub>2</sub> on Silicon Nanocavities",
            abstract="Erbium ions in titanium dioxide on silicon nanocavities.",
            publication_year=2022,
            source_name="arXiv (Cornell University)",
        )
        session.add_all([latex_title, html_title])
        session.flush()
        session.add_all(
            [
                ProfessorWork(professor_id=professor.id, work_id=latex_title.id, authorship_position="first"),
                ProfessorWork(professor_id=professor.id, work_id=html_title.id, authorship_position="first"),
            ]
        )
        session.commit()
        for work in (latex_title, html_title):
            upsert_embedding(session.bind, work.id, encoder.encode_one(f"{work.title} [SEP] {work.abstract}"), encoder.backend)
        session.commit()
        hits = rank_professors(session, encoder, "silicon nanocavities", result_limit=5, work_limit=5)

    assert hits
    assert hits[0].total_work_count == 1
    assert len(hits[0].supporting_works) == 1
    assert hits[0].supporting_works[0]["title"] == latex_title.title
