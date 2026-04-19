from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from click.testing import CliRunner

from profsearch import cli as cli_module
from profsearch.db.models import Professor, ProfessorWork, University, Work
from profsearch.db.vectors import upsert_embedding
from profsearch.embedding.encoder import EmbeddingEncoder
from profsearch.search.evaluation import SearchEvaluationQuery, evaluate_search_queries, load_search_evaluation_queries, summarize_search_evaluation


def test_load_search_evaluation_queries_reads_json(tmp_path: Path) -> None:
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps(
            [
                {
                    "query": "quantum materials",
                    "notes": "spot check",
                    "expected_professors": ["Jane Doe"],
                    "expected_universities": ["Test University"],
                    "minimum_professor_matches": 1,
                    "minimum_university_matches": 1,
                }
            ]
        ),
        encoding="utf-8",
    )

    queries = load_search_evaluation_queries(path)

    assert queries == [
        SearchEvaluationQuery(
            query="quantum materials",
            notes="spot check",
            expected_professors=["Jane Doe"],
            expected_universities=["Test University"],
            minimum_professor_matches=1,
            minimum_university_matches=1,
        )
    ]


def test_evaluate_search_queries_tracks_expectation_hits(session_factory, test_settings) -> None:
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
        session.add(work)
        session.flush()
        session.add(ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="first"))
        session.commit()
        upsert_embedding(session.bind, work.id, encoder.encode_one(f"{work.title} [SEP] {work.abstract}"), encoder.backend)
        session.commit()

        results = evaluate_search_queries(
            session,
            encoder,
            [
                SearchEvaluationQuery(
                    query="quantum materials",
                    expected_professors=["Jane Doe"],
                    expected_universities=["Test University"],
                )
            ],
            result_limit=5,
            work_limit=3,
        )

    summary = summarize_search_evaluation(results)
    assert results[0].hit_at_k is True
    assert results[0].matched_professors == ["Jane Doe"]
    assert results[0].matched_universities == ["Test University"]
    assert summary["queries_with_expected_hits"] == 1
    assert summary["expected_hit_rate"] == 1.0


def test_evaluate_search_queries_respects_minimum_professor_matches(session_factory, test_settings) -> None:
    encoder = EmbeddingEncoder(test_settings)
    with session_factory() as session:
        university = University(name="Test University", domain="example.edu", status="completed")
        session.add(university)
        session.flush()
        for index, name in enumerate(("Jane Doe", "John Doe"), start=1):
            professor = Professor(
                candidate_id=index,
                university_id=university.id,
                department_type="physics",
                name=name,
                normalized_name=name.lower(),
                title="Professor of Physics",
                title_normalized="professor",
                email=f"{index}@example.edu",
                profile_url=f"https://example.edu/{index}",
                source_url="https://example.edu/faculty",
                source_snippet="Professor of Physics",
                verification_status="verified",
                scraped_at=datetime.now(timezone.utc),
            )
            session.add(professor)
            session.flush()
            work = Work(
                openalex_work_id=f"https://openalex.org/W{index}",
                title=f"Quantum materials example {index}",
                abstract="A study of quantum materials and emergent phases.",
                publication_year=2024,
            )
            session.add(work)
            session.flush()
            session.add(ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="first"))
            session.commit()
            upsert_embedding(session.bind, work.id, encoder.encode_one(f"{work.title} [SEP] {work.abstract}"), encoder.backend)
            session.commit()

        results = evaluate_search_queries(
            session,
            encoder,
            [
                SearchEvaluationQuery(
                    query="quantum materials",
                    expected_professors=["Jane Doe", "John Doe", "Missing Person"],
                    minimum_professor_matches=2,
                )
            ],
            result_limit=5,
            work_limit=3,
        )

    summary = summarize_search_evaluation(results)
    assert results[0].matched_professors == ["Jane Doe", "John Doe"]
    assert results[0].missing_professors == ["Missing Person"]
    assert results[0].hit_at_k is True
    assert summary["queries_with_expected_hits"] == 1


def test_evaluate_search_cli_json_output(session_factory, test_settings, monkeypatch, tmp_path: Path) -> None:
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
        work = Work(
            openalex_work_id="https://openalex.org/W10",
            title="Quantum transport in layered systems",
            abstract="Transport signatures in condensed matter systems.",
            publication_year=2023,
        )
        session.add(work)
        session.flush()
        session.add(ProfessorWork(professor_id=professor.id, work_id=work.id, authorship_position="last"))
        session.commit()
        upsert_embedding(session.bind, work.id, encoder.encode_one(f"{work.title} [SEP] {work.abstract}"), encoder.backend)
        session.commit()

    query_file = tmp_path / "queries.json"
    query_file.write_text(json.dumps([{"query": "quantum transport", "expected_professors": ["John Doe"]}]), encoding="utf-8")

    monkeypatch.setattr(cli_module, "get_settings", lambda: test_settings)
    monkeypatch.setattr(cli_module, "_session_factory", lambda: session_factory)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli,
        ["evaluate-search", "--query-file", str(query_file), "--json-output", "--work-limit", "1"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["total_queries"] == 1
    assert payload["summary"]["queries_with_expected_hits"] == 1
    assert payload["results"][0]["minimum_professor_matches"] == 1
    assert payload["results"][0]["hits"][0]["professor_name"] == "John Doe"
    assert payload["results"][0]["hits"][0]["returned_work_count"] == 1
