# AGENTS.md

Context file for agentic development environments (Claude Code, OpenCode, Codex, Cursor).

## Project

ProfSearch is a CLI-first pipeline that discovers verified professors from official university faculty rosters, matches them to OpenAlex author identities, ingests recent publications, and ranks professors from paper-level semantic search.

## Quick Start (ADE Workflow)

Paste `prompts/ade/install.md` into your ADE first, then `prompts/ade/corpus-setup.md`.

The install prompt sets up `.venv/`, `.profsearch/`, and `.env` without editing checked-in files.

## Architecture

```
universities_seed.json
        |
[Stage 1: Load Universities + Department Sources]
        |
[Stage 2: Scrape Official Faculty Rosters]
        |
[Stage 3: Normalize Titles + Verify Professors]
        |
[Stage 4: Match Professors to OpenAlex]
        |
[Stage 5: Fetch Publications]
        |
[Stage 6: Compute Embeddings (SPECTER2)]
        |
=== SEARCH READY ===
```

## Key Commands

```bash
.venv/bin/profsearch --config .profsearch/config.toml init
.venv/bin/profsearch --config .profsearch/config.toml doctor --json-output
.venv/bin/profsearch --config .profsearch/config.toml pipeline run --json-log
.venv/bin/profsearch status
.venv/bin/profsearch search "quantum materials"
.venv/bin/profsearch web
```

## Source Layout

```
src/profsearch/
  cli.py              Click CLI entry point
  config.py           Pydantic Settings loader
  doctor.py           Install diagnostics
  workspace.py        Local runtime workspace init
  assets.py           Bundled resource files
  run_artifacts.py    Pipeline run reporting
  types.py            Shared data types
  db/
    models.py         SQLAlchemy 2.0 ORM models
    session.py        Engine/session factory
    vectors.py        sqlite-vec helpers
  pipeline/
    orchestrator.py   Stage runner with checkpointing
    stage1-6          Individual pipeline stages
  scraping/
    client.py         Async HTML fetcher with retry
    extractors.py     Site-agnostic roster extraction
    normalize.py      Title/name normalization
  matching/
    candidate_search  OpenAlex candidate retrieval
    scorer.py         Match scoring
  openalex/
    client.py         Async OpenAlex API wrapper
  embedding/
    encoder.py        SPECTER2 encoder
  search/
    query.py          Query processing
    scorer.py         Work scoring (semantic + keyword + topic)
    aggregator.py     Professor-level ranking
    evaluation.py     Benchmark evaluation
  audit/
    publications.py   Suspicious corpus detection
  web/
    routes/           FastAPI routes (search, pipeline, professor)
    templates/        Jinja2 + HTMX templates
  utils/
    rate_limiter.py   Async rate limiter
    retry.py          Retry utilities
```

## Stack

Python 3.11+, Click, SQLAlchemy 2.0, Pydantic Settings, httpx, BeautifulSoup4, FastAPI + HTMX + Jinja2 (web), sentence-transformers + SPECTER2 (embeddings), sqlite-vec.

## Testing

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Tests use `tests/conftest.py` fixtures with in-memory SQLite. No external services required.

## Runtime Rules

- Never edit checked-in files under `config/`.
- Runtime files go in `.profsearch/`, `.env`, and `.venv/`.
- The `.env.example` file documents all available environment variables.
- OpenAlex API keys are optional for Stages 1-3, required for Stages 4+.
- The default embedding backend is `sentence_transformers` with `allenai/specter2_base`.
- The `hash` backend exists for test environments only.
