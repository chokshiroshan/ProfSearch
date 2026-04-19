# ProfSearch Corpus Setup Prompt

You are helping a user choose and prepare a ProfSearch corpus inside an ADE such as Claude Code, Codex, or OpenCode.

Start by asking the user to choose one of these two modes:

- `Use existing corpus`
- `Build my own corpus`

Use `.venv/bin/profsearch` for all commands and keep runtime edits inside `.profsearch/` and `.env`.

## Shared rules

- Do not edit checked-in files under `config/`.
- Use `.profsearch/universities_seed.json` for custom sources.
- Use `--json-log` for pipeline runs and inspect the emitted artifact directory on failure.
- If you need to write `PROFSEARCH_DB_PATH` into `.env`, resolve it to an absolute path first.

## If the user chooses `Use existing corpus`

1. Detect a local SQLite corpus candidate before asking for downloads, in this order:
   - `PROFSEARCH_DB_PATH` from `.env` if set and exists.
   - Any `*.db` under `.profsearch/data/`.
   - Any `*.db` under `data/`.
2. If a local DB is found outside `.profsearch/data/`, copy it to `.profsearch/data/profsearch.db` (or another deterministic filename) and use that canonical runtime path.
3. If no local DB candidate is found, ask for the GitHub Release asset URL for the current curated U.S. physics SQLite corpus and download it into `.profsearch/data/`.
4. Write `PROFSEARCH_DB_PATH=<absolute path to the sqlite file in .profsearch/data/>` into `.env`.
5. Verify the corpus:
   - `.venv/bin/profsearch status`
   - `.venv/bin/profsearch search "quantum materials"`
6. Offer optional embedding warmup (user opt-in) to reduce first-search latency:
   - `.venv/bin/profsearch search "quantum materials"`
7. Offer the optional web UI and mention port fallback:
   - `.venv/bin/profsearch web`
   - If port 8000 is occupied, `profsearch web` can auto-select a free port and print the URL.
8. Describe the corpus honestly as the current curated U.S. physics corpus, not as a guaranteed top-20-complete dataset.

## If the user chooses `Build my own corpus`

1. Ask for one or more universities and departments.
2. Edit `.profsearch/universities_seed.json` with:
   - official university domain
   - OpenAlex institution ID and ROR ID (look these up on openalex.org)
   - one or more department entries with official roster URLs
   - parser hints only when clearly justified
5. Run Stage 1:
   - `.venv/bin/profsearch --config .profsearch/config.toml pipeline run --through-stage stage1 --json-log`
6. If Stage 1 fails, inspect the reported artifact directory, summarize the issue from `summary.json` and `stage1.json`, fix the seed, and rerun Stage 1.
7. Run Stage 2:
   - `.venv/bin/profsearch --config .profsearch/config.toml pipeline run --through-stage stage2 --json-log`
8. If Stage 2 fails, inspect the reported artifact directory, summarize the issue from `summary.json`, `stage2.json`, and `events.jsonl`, fix the smallest deterministic cause, and rerun Stage 2.
9. Run Stage 3:
   - `.venv/bin/profsearch --config .profsearch/config.toml pipeline run --from-stage stage3 --through-stage stage3 --json-log`
10. Ask the user whether they want to continue into OpenAlex matching, publication ingest, and embeddings.
11. Only if they say yes, ask for either:
    - `PROFSEARCH_OPENALEX_API_KEY`
    - or `PROFSEARCH_OPENALEX_API_KEYS`
12. Write the provided key or key pool into `.env`, then continue:
    - `.venv/bin/profsearch --config .profsearch/config.toml pipeline run --from-stage stage4 --through-stage stage6 --json-log`
13. Finish with:
    - `.venv/bin/profsearch status`
    - `.venv/bin/profsearch search "<user query or quantum materials>"`
