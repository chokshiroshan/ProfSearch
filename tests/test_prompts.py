from __future__ import annotations

from pathlib import Path


def test_install_prompt_keeps_runtime_local_and_deterministic() -> None:
    prompt = Path("prompts/ade/install.md").read_text(encoding="utf-8")

    assert "# ProfSearch Install Prompt" in prompt
    assert '.venv/bin/pip install -e "[web,embeddings]"' not in prompt
    assert '.venv/bin/pip install -e ".[web,embeddings]"' in prompt
    assert ".venv/bin/profsearch --config .profsearch/config.toml init" in prompt
    assert ".venv/bin/profsearch --config .profsearch/config.toml pipeline init-db" in prompt
    assert (
        ".venv/bin/profsearch --config .profsearch/config.toml doctor --json-output"
        in prompt
    )
    assert "PROFSEARCH_CONFIG_FILE=.profsearch/config.toml" in prompt
    assert "PROFSEARCH_OPENALEX_API_KEY=" in prompt
    assert "PROFSEARCH_OPENALEX_API_KEYS=" in prompt
    assert "Do not edit checked-in files under `config/`." in prompt


def test_corpus_setup_prompt_covers_existing_and_custom_flows() -> None:
    prompt = Path("prompts/ade/corpus-setup.md").read_text(encoding="utf-8")

    assert "# ProfSearch Corpus Setup Prompt" in prompt
    assert "`Use existing corpus`" in prompt
    assert "`Build my own corpus`" in prompt
    assert "PROFSEARCH_DB_PATH=<absolute path to the sqlite file in .profsearch/data/>" in prompt
    assert "Detect a local SQLite corpus candidate" in prompt
    assert "Any `*.db` under `.profsearch/data/`." in prompt
    assert "Any `*.db` under `data/`." in prompt
    assert "copy it to `.profsearch/data/profsearch.db`" in prompt
    assert "auto-select a free port" in prompt
    assert "pipeline run --through-stage stage1 --json-log" in prompt
    assert "pipeline run --through-stage stage2 --json-log" in prompt
    assert (
        "pipeline run --from-stage stage4 --through-stage stage6 --json-log" in prompt
    )
    assert "universities_seed.json" in prompt
