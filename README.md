# ProfSearch

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Tests](https://github.com/chokshiroshan/ProfSearch/actions/workflows/test.yml/badge.svg)](https://github.com/chokshiroshan/ProfSearch/actions/workflows/test.yml)

ProfSearch discovers verified professors from official university faculty rosters, matches them to [OpenAlex](https://openalex.org) author identities, ingests their recent publications, and ranks them by research relevance using semantic search.

It is designed as a **CLI-first pipeline** that can be driven entirely from an agentic development environment (Claude Code, OpenCode, Codex) or used directly from the command line. A built-in web UI is also available.

## How It Works

```
universities_seed.json  (curated department roster URLs)
        |
[Stage 1] Load Universities + Department Sources
        |
[Stage 2] Scrape Official Faculty Rosters
        |
[Stage 3] Normalize Titles + Verify Professors
        |
[Stage 4] Match Professors to OpenAlex Authors
        |
[Stage 5] Fetch Publications
        |
[Stage 6] Compute Embeddings (SPECTER2)
        |
=== SEARCH READY ===
```

Key design principle: **official university faculty pages are the source of truth** for professor status. OpenAlex is used only for author matching and publication enrichment.

## Quick Start

### Option A: ADE Workflow (Recommended)

If you use Claude Code, OpenCode, Codex, or another agentic development environment:

1. Clone the repo
2. Paste `prompts/ade/install.md` into your ADE
3. After install completes, paste `prompts/ade/corpus-setup.md`

This sets up `.venv/`, `.profsearch/`, and `.env` without editing any checked-in files.

### Option B: Manual Setup

```bash
# Clone and enter the repo
git clone https://github.com/chokshiroshan/ProfSearch.git
cd ProfSearch

# Create virtual environment and install
python3 -m venv .venv
.venv/bin/pip install -e ".[web,embeddings]"

# Initialize workspace
.venv/bin/profsearch --config .profsearch/config.toml init

# Initialize DB schema so doctor can report healthy install status
.venv/bin/profsearch --config .profsearch/config.toml pipeline init-db

# Copy and edit environment config
cp .env.example .env
# Edit .env to set PROFSEARCH_CONFIG_FILE=.profsearch/config.toml

# Run diagnostics
.venv/bin/profsearch --config .profsearch/config.toml doctor --json-output
```

### Using a Pre-built Corpus

ProfSearch corpus setup should canonicalize runtime data into `.profsearch/data/`:

1. Reuse an existing local DB from `PROFSEARCH_DB_PATH`, `.profsearch/data/*.db`, or `data/*.db` (in that order) when available.
2. If the DB is outside `.profsearch/data/`, copy it into `.profsearch/data/` and point `.env` at the copied absolute path.
3. Only download from [GitHub Releases](https://github.com/chokshiroshan/ProfSearch/releases) when no local DB candidate exists.

## Usage

### CLI

```bash
# Pipeline operations
.venv/bin/profsearch pipeline run --json-log              # Run all stages
.venv/bin/profsearch pipeline run --through-stage stage3   # Run stages 1-3 only

# Search
.venv/bin/profsearch search "quantum materials"
.venv/bin/profsearch search "topological insulators" --json-output

# Inspect data
.venv/bin/profsearch status
.venv/bin/profsearch inspect professor --name "John Doe"
.venv/bin/profsearch inspect match --name "John Doe"

# Review and resolve ambiguous matches
.venv/bin/profsearch review-matches
.venv/bin/profsearch resolve-match --professor-id 42 --status manual_override --author-id A12345

# Web UI
.venv/bin/profsearch web
```

### Web UI

```bash
.venv/bin/profsearch web
```

By default, this starts at `http://127.0.0.1:8000`. If port 8000 is occupied, `profsearch web` auto-selects a nearby free port and prints the URL.

Use `--no-auto-port` to fail fast instead of choosing a fallback port.

Opens a local web interface with:
- Semantic search with university/department/match-status filters
- Professor detail pages with ranked publications
- Pipeline status monitoring

## Corpus

The default seed file now contains 38 U.S. universities from the exact-ranked portion of the 2026 QS Physics & Astronomy table.

18 entries are scrape-ready and include curated Physics, Applied Physics, Astronomy, or Materials Science roster URLs:

MIT, Harvard, Stanford, UC Berkeley, Caltech, Princeton, UCLA, UChicago, Cornell, Yale, UCSB, UIUC, Penn, Maryland, Washington, Georgia Tech, Northwestern, Wisconsin.

20 additional entries are included as ranking scaffolds and are tagged with `seed_status: "ranking_only"` plus empty `departments` until we verify official faculty roster URLs:

Columbia, UT Austin, Michigan, UCSD, Colorado, Penn State, Johns Hopkins, Purdue, Stony Brook, Carnegie Mellon, Michigan State, Rice, BU, Arizona, NYU, Texas A&M, Ohio State, Duke, Rochester, Brown.

These ranking-only entries reflect schools whose current faculty sources are blocked, JS-rendered, or otherwise not yet scrape-ready for the pipeline.

### Custom Corpus

Edit `.profsearch/universities_seed.json` to add your own universities and department roster URLs. Each entry needs:

- University name and domain
- OpenAlex institution ID and ROR ID
- One or more department entries with official roster URLs

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full data model, pipeline stage details, matching strategy, and search architecture.

## Stack

| Concern | Technology |
|---------|-----------|
| CLI | [Click](https://click.palletsprojects.com/) |
| Database | SQLite + [sqlite-vec](https://github.com/asg017/sqlite-vec) |
| ORM | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) |
| Config | [Pydantic Settings](https://docs.pydantic.dev/) |
| HTTP | [httpx](https://www.python-httpx.org/) (async) |
| HTML Parsing | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) |
| Embeddings | [SPECTER2](https://huggingface.co/allenai/specter2_base) via sentence-transformers |
| Web UI | [FastAPI](https://fastapi.tiangolo.com/) + [HTMX](https://htmx.org/) + [Jinja2](https://jinja.palletsprojects.com/) |
| Testing | [pytest](https://docs.pytest.org/) |

## Configuration

All configuration is through environment variables (prefix `PROFSEARCH_`) or a TOML config file. See `.env.example` for the full list of options.

Key settings:

| Variable | Purpose |
|----------|---------|
| `PROFSEARCH_CONFIG_FILE` | Path to config TOML |
| `PROFSEARCH_DB_PATH` | Path to SQLite database |
| `PROFSEARCH_OPENALEX_API_KEY` | Single OpenAlex API key |
| `PROFSEARCH_OPENALEX_API_KEYS` | Comma-separated key pool |
| `PROFSEARCH_EMBEDDING_BACKEND` | `sentence_transformers` (default) or `hash` (testing) |
| `PROFSEARCH_EMBEDDING_MODEL` | Default: `allenai/specter2_base` |

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Tests use in-memory SQLite with no external service dependencies.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
