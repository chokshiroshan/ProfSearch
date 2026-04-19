# Contributing to ProfSearch

Thanks for your interest. This project is early-stage and contributions are welcome.

## Getting Started

1. Clone the repo
2. Set up the environment:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e ".[dev,web,embeddings]"
   ```
3. Run tests:
   ```bash
   .venv/bin/pytest
   ```

## ADE Workflow

ProfSearch is designed for agentic development. Paste `prompts/ade/install.md` into your ADE (Claude Code, OpenCode, Codex) to set up the workspace, then `prompts/ade/corpus-setup.md` to configure a corpus.

## Making Changes

- **Runtime files** (`.profsearch/`, `.env`, `.venv/`) should never be committed.
- **Checked-in config** (`config/`) should not be edited for local runtime — use `.profsearch/config.toml` instead.
- **Tests** are required for new pipeline logic. Use `tests/conftest.py` fixtures and in-memory SQLite.
- **Pipeline stages** must be idempotent and resumable via checkpointing.
- **Matching** should optimize for precision over recall.

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with tests
3. Run `pytest` and confirm all tests pass
4. Open a PR with a clear description of the change and why

## Adding a University

The default corpus in `config/universities_seed.json` now contains 38 U.S. schools from the exact-ranked 2026 QS Physics & Astronomy table: 18 scrape-ready entries with curated roster URLs and 20 `ranking_only` scaffold entries that still need vetted department sources. To expand ProfSearch to a new field or geography, add entries to the appropriate template file under [`config/seeds/`](config/seeds/) — `cs.json`, `bio.json`, `bioeng.json`, `eu_general.json`, `asia_general.json`, or propose a new file in the same PR.

See [`config/seeds/README.md`](config/seeds/README.md) for the full entry schema. Minimum required fields:

- `name`, `short_name`, `domain`
- `openalex_id` from <https://api.openalex.org/institutions?search=...>
- `ror_id` from <https://ror.org>
- At least one `departments[*]` entry with a scrape-friendly `roster_url`

Before opening the PR, verify the scrape + normalize path works:

```bash
.venv/bin/profsearch pipeline run \
  --through-stage stage3 \
  --only-university "Your University"
```

Paste the verified-professor count (and any scrape warnings) into the PR description. If the roster is JS-rendered, bot-protected, or behind SSO, flag it — a Playwright-backed scrape backend is planned (see `CHANGELOG.md` → Unreleased) and your entry can wait for that.

The checked-in default seed may include `ranking_only` scaffold rows for coverage and prioritization, but contributed entries in `config/seeds/` should still meet the full scrape-ready requirements above.

Note: as of today the single-file `config/universities_seed.json` is what the pipeline actually loads. Per-field seed merging is a v0.2 item. Entries added to `config/seeds/` stay valid under both the current and the merged loader, so this is the right place to contribute even before the merge lands.

## Reporting Issues

Open a GitHub issue with:
- What you expected
- What happened instead
- Steps to reproduce (including your Python version and OS)
- Relevant `profsearch doctor --json-output` output if applicable

## Code Style

- Python 3.11+ with type hints
- No comments unless explaining non-obvious logic
- Follow the existing patterns in the codebase
