# Changelog

All notable changes to ProfSearch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned (v0.2 — applicant-facing reimagining)

- Applicant-facing web UX: research-interest capture (text / paste-abstract / CV upload), ranked professor cards, side-by-side compare, localStorage shortlist with CSV export. Existing admin views move under `/admin/*`.
- Personalized outreach email drafter (`src/profsearch/agentic/`) with a pluggable BYO-key LLM backend (Anthropic / OpenAI / Ollama). Exposed via CLI (`profsearch draft-email`) and a web route that returns an HTMX fragment.
- Funding / grants signal: new `stage7_funding` pipeline stage + `Grant` model, fed by NIH RePORTER and NSF Awards. Powers an "actively funded" badge on professor cards as a reachability proxy.
- Broader seed data: `config/seeds/` directory with per-field files (physics, CS, bio, bioengineering, EU, Asia). Optional Playwright scrape backend behind `PROFSEARCH_SCRAPE_BACKEND=playwright` for JS-rendered rosters.
- Zero-install hosted demo: `--read-only` flag on `profsearch web`, pre-built DB snapshots published on tagged GitHub Releases, `pipx install profsearch[web,embeddings]` as the primary install path.
- Open-source hygiene: `SECURITY.md`, richer PR template, web-route tests under `tests/web/`.

### Added (landed on main)

- `SECURITY.md` with private vulnerability reporting process.
- Expanded PR template with type-of-change, seed-data testing checklist, and changelog reminder.

## [0.1.0] - 2025-04-14

### Added
- Six-stage pipeline: seed, scrape, verify, match, ingest, embed
- CLI with `init`, `doctor`, `pipeline run`, `status`, `search`, `inspect`, `review-matches`, `resolve-match`, `web`, `audit-publications`, `evaluate-search`
- Web UI with FastAPI, HTMX, and Jinja2 templates
- Semantic search via SPECTER2 embeddings and sqlite-vec
- OpenAlex client with API key pool rotation and rate limiting
- Deterministic run artifacts with JSON logging
- ADE install prompts for Claude Code / OpenCode / Codex
- Curated seed file for 18 U.S. physics-adjacent universities
- Professor verification from official university faculty rosters
- Conservative OpenAlex author matching with evidence JSON
- Publication ingestion with deduplication
- Duplicate professor detection (same-name + same-university)
- Pipeline checkpointing for resumability

### Known Limitations
- Publication ingest uses a fixed `start_year` rather than a rolling window
- Same-name professors at the same university need manual review
- Some top U.S. schools excluded (Columbia 403, Texas SSO, UCSD JS-rendered)
