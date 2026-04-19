from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner
from sqlalchemy import select

from profsearch.cli import cli
from profsearch.db.models import (
    DepartmentSource,
    Professor,
    ProfessorWork,
    University,
    Work,
)
from profsearch.db.session import create_session_factory, initialize_database
from profsearch.db.vectors import upsert_embedding
from profsearch.doctor import build_doctor_report
from profsearch.embedding.encoder import EmbeddingEncoder


def _write_config(
    tmp_path: Path, *, seed_path: Path, db_path: Path | None = None
) -> Path:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    config_dir = tmp_path / "config-dir"
    data_dir.mkdir(exist_ok=True)
    cache_dir.mkdir(exist_ok=True)
    config_dir.mkdir(exist_ok=True)
    config_path.write_text(
        f"""
[app]
seed_file = "{seed_path}"
config_dir = "{config_dir}"
data_dir = "{data_dir}"
cache_dir = "{cache_dir}"
runs_dir = "runs"

[database]
path = "{db_path or (data_dir / "profsearch.db")}"

[embeddings]
backend = "hash"
model_name = "hash"
dimension = 64
""".strip(),
        encoding="utf-8",
    )
    return config_path


def test_init_command_creates_workspace_files(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = tmp_path / "custom.toml"

    result = runner.invoke(cli, ["--config", str(config_path), "init", "--json-output"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert Path(payload["config_file"]).exists()
    assert Path(payload["seed_file"]).exists()
    assert Path(payload["runs_dir"]).exists()


def test_doctor_report_flags_missing_optional_dependencies(
    test_settings, monkeypatch
) -> None:
    monkeypatch.setattr("profsearch.doctor._module_available", lambda name: False)

    report = build_doctor_report(test_settings)

    checks = {item["name"]: item for item in report["checks"]}
    assert checks["web_extra"]["status"] == "error"
    assert checks["embeddings"]["status"] == "ok"


def test_prebuilt_corpus_flow_uses_repo_local_dotenv_for_status_search_and_web(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime_dir = project_root / ".profsearch"
    runtime_dir.mkdir()
    config_path = runtime_dir / "config.toml"
    db_path = runtime_dir / "data" / "curated-physics.db"
    config_path.write_text(
        """
[embeddings]
backend = "hash"
model_name = "hash"
dimension = 64
""".strip(),
        encoding="utf-8",
    )
    (project_root / ".env").write_text(
        f"""
PROFSEARCH_CONFIG_FILE=.profsearch/config.toml
PROFSEARCH_DB_PATH={db_path}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)
    from profsearch.config import configure_runtime, load_settings

    configure_runtime(config_path=None, profile=None)
    settings = load_settings()
    initialize_database(settings)

    runner = CliRunner()
    status_result = runner.invoke(cli, ["status"])
    search_result = runner.invoke(cli, ["search", "quantum materials", "--json-output"])

    assert status_result.exit_code == 0, status_result.output
    assert "Pipeline state:" in status_result.output
    assert search_result.exit_code == 0, search_result.output
    assert json.loads(search_result.output) == []

    called: dict[str, object] = {}

    def fake_run(app, host, port, reload, factory):
        called.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "factory": factory,
            }
        )

    import profsearch.cli as cli_module

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    monkeypatch.setattr(cli_module, "_is_port_available", lambda host, port: True)
    web_result = runner.invoke(cli_module.cli, ["web", "--port", "8123"])

    assert web_result.exit_code == 0, web_result.output
    assert called == {
        "app": "profsearch.web:create_app",
        "host": "127.0.0.1",
        "port": 8123,
        "reload": False,
        "factory": True,
    }


def test_web_command_auto_port_falls_back_when_requested_port_is_busy(monkeypatch) -> None:
    runner = CliRunner()
    called: dict[str, object] = {}

    def fake_run(app, host, port, reload, factory):
        called.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "factory": factory,
            }
        )

    import profsearch.cli as cli_module

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    monkeypatch.setattr(cli_module, "_is_port_available", lambda host, port: port != 8000)
    monkeypatch.setattr(cli_module, "_find_next_available_port", lambda host, start_port, scan_limit=100: 8001)

    result = runner.invoke(cli_module.cli, ["web", "--port", "8000"])

    assert result.exit_code == 0, result.output
    assert "Port 8000 is in use on 127.0.0.1; using free port 8001." in result.output
    assert "Web UI: http://127.0.0.1:8001" in result.output
    assert called["port"] == 8001


def test_web_command_no_auto_port_exits_with_clear_error(monkeypatch) -> None:
    runner = CliRunner()
    called: dict[str, object] = {}

    def fake_run(app, host, port, reload, factory):
        called.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "factory": factory,
            }
        )

    import profsearch.cli as cli_module

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    monkeypatch.setattr(cli_module, "_is_port_available", lambda host, port: False)

    result = runner.invoke(cli_module.cli, ["web", "--port", "8000", "--no-auto-port"])

    assert result.exit_code != 0
    assert "Port 8000 is already in use on 127.0.0.1." in result.output
    assert "Retry with --auto-port or provide a different --port." in result.output
    assert called == {}


def test_web_command_auto_port_errors_when_no_free_port_found(monkeypatch) -> None:
    runner = CliRunner()
    called: dict[str, object] = {}

    def fake_run(app, host, port, reload, factory):
        called.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "factory": factory,
            }
        )

    import profsearch.cli as cli_module

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    monkeypatch.setattr(cli_module, "_is_port_available", lambda host, port: False)
    monkeypatch.setattr(cli_module, "_find_next_available_port", lambda host, start_port, scan_limit=100: None)

    result = runner.invoke(cli_module.cli, ["web", "--port", "8000", "--auto-port"])

    assert result.exit_code != 0
    assert "Port 8000 is in use on 127.0.0.1, and no free port was found in the range 8001-8100." in result.output
    assert called == {}


def test_pipeline_stage1_loads_single_university_seed(tmp_path: Path) -> None:
    runner = CliRunner()
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "Single University",
                    "domain": "example.edu",
                    "departments": [
                        {
                            "department_type": "physics",
                            "roster_url": "https://physics.example.edu/faculty",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_config(tmp_path, seed_path=seed_path)

    result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "pipeline",
            "run",
            "--through-stage",
            "stage1",
            "--json-log",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["success"] is True
    assert summary["results"][0]["outcome"]["universities_loaded"] == 1


def test_pipeline_stage1_loads_multiple_universities_and_departments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROFSEARCH_CONFIG_FILE", raising=False)
    monkeypatch.delenv("PROFSEARCH_DB_PATH", raising=False)
    runner = CliRunner()
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "University One",
                    "domain": "one.edu",
                    "departments": [
                        {
                            "department_type": "physics",
                            "roster_url": "https://physics.one.edu/faculty",
                        },
                        {
                            "department_type": "astronomy",
                            "roster_url": "https://astro.one.edu/people/faculty",
                        },
                    ],
                },
                {
                    "name": "University Two",
                    "domain": "two.edu",
                    "departments": [
                        {
                            "department_type": "physics",
                            "roster_url": "https://physics.two.edu/faculty",
                        },
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_config(tmp_path, seed_path=seed_path)
    runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "pipeline",
            "run",
            "--through-stage",
            "stage1",
            "--json-log",
        ],
    )

    from profsearch.config import load_settings

    settings = load_settings(config_path)
    session_factory = create_session_factory(settings)
    with session_factory() as session:
        universities = session.scalars(
            select(University).order_by(University.name)
        ).all()
        sources = session.scalars(
            select(DepartmentSource).order_by(DepartmentSource.id)
        ).all()

    assert [item.name for item in universities] == ["University One", "University Two"]
    assert len(sources) == 3


def test_pipeline_json_log_captures_stage1_failure_artifacts(tmp_path: Path) -> None:
    runner = CliRunner()
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "Broken University",
                    "domain": "example.edu",
                    "departments": [
                        {
                            "department_type": "physics",
                            "roster_url": "https://offdomain.invalid/faculty",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_config(tmp_path, seed_path=seed_path)

    result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "pipeline",
            "run",
            "--through-stage",
            "stage1",
            "--json-log",
        ],
    )

    assert result.exit_code == 1, result.output
    summary = json.loads(result.output)
    artifact_dir = Path(summary["artifact_dir"])
    stage1_payload = json.loads(
        (artifact_dir / "stage1.json").read_text(encoding="utf-8")
    )
    assert summary["failed_stage"] == "stage1"
    assert "off-domain" in stage1_payload["errors"][0]["error"]


def test_pipeline_json_log_captures_stage2_fetch_failures(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "Fetch University",
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
        ),
        encoding="utf-8",
    )
    config_path = _write_config(tmp_path, seed_path=seed_path)

    class FakeClient:
        async def fetch(self, url, approved_domains):
            raise RuntimeError("fetch failed")

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "profsearch.pipeline.stage2_scrape_faculty.AsyncHtmlClient",
        lambda settings: FakeClient(),
    )

    result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "pipeline",
            "run",
            "--through-stage",
            "stage2",
            "--json-log",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    stage2_payload = json.loads(
        (Path(summary["artifact_dir"]) / "stage2.json").read_text(encoding="utf-8")
    )
    assert stage2_payload["sources"][0]["status"] == "error"
    assert stage2_payload["sources"][0]["error"] == "fetch failed"


def test_pipeline_json_log_captures_stage2_page_excerpt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "Excerpt University",
                    "domain": "example.edu",
                    "departments": [
                        {
                            "department_type": "physics",
                            "roster_url": "https://physics.example.edu/faculty",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_config(tmp_path, seed_path=seed_path)
    html = "<html><body><div>No faculty cards here yet</div></body></html>"

    class FakeClient:
        async def fetch(self, url, approved_domains):
            return SimpleNamespace(url=url, text=html, status_code=200)

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "profsearch.pipeline.stage2_scrape_faculty.AsyncHtmlClient",
        lambda settings: FakeClient(),
    )

    result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "pipeline",
            "run",
            "--through-stage",
            "stage2",
            "--json-log",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    stage2_payload = json.loads(
        (Path(summary["artifact_dir"]) / "stage2.json").read_text(encoding="utf-8")
    )
    assert stage2_payload["sources"][0]["entries_found"] == 0
    assert stage2_payload["sources"][0]["pages"][0]["html_excerpt"].startswith("<html>")


def test_custom_corpus_flow_can_continue_to_search_ready_pipeline(
    session_factory, test_settings, monkeypatch
) -> None:
    encoder = EmbeddingEncoder(test_settings)
    with session_factory() as session:
        university = University(
            name="Search University", domain="example.edu", status="completed"
        )
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
        session.add(
            ProfessorWork(
                professor_id=professor.id, work_id=work.id, authorship_position="first"
            )
        )
        session.commit()
        upsert_embedding(
            session.bind,
            work.id,
            encoder.encode_one(f"{work.title} [SEP] {work.abstract}"),
            encoder.backend,
        )
        session.commit()

    import profsearch.cli as cli_module

    monkeypatch.setattr(cli_module, "get_settings", lambda: test_settings)
    monkeypatch.setattr(
        cli_module, "_session_factory", lambda settings=None: session_factory
    )
    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli, ["search", "quantum materials", "--json-output"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["professor_name"] == "Jane Doe"
