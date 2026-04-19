# ProfSearch Install Prompt

You are helping a user set up ProfSearch inside an ADE such as Claude Code, Codex, or OpenCode.

Work in small deterministic steps and explain what you are doing. If the repo is not already present in the current workspace, ask the user for the clone URL before cloning.

## Goal

Prepare a local ProfSearch workspace that uses:

- `.venv/` for Python dependencies
- `.profsearch/config.toml` for runtime config
- `.env` in the repo root for auto-loaded environment variables

## Rules

- Do not edit checked-in files under `config/`.
- Write runtime files only under `.venv/`, `.profsearch/`, and `.env`.
- Do not ask for OpenAlex keys during install.
- Stop after the doctor report and tell the user to paste `prompts/ade/corpus-setup.md` next.

## Steps

1. Confirm you are at the ProfSearch repo root. If not, clone the repo, enter it, and continue.
2. Create the virtual environment:
   - If `.venv/` already exists, reuse it.
   - Otherwise run: `python3 -m venv .venv`
3. Install ProfSearch with the web and embeddings extras:
   - `.venv/bin/pip install -e ".[web,embeddings]"`
4. Create the local runtime workspace:
   - `.venv/bin/profsearch --config .profsearch/config.toml init`
5. Initialize the local database schema so doctor can report healthy install status:
   - `.venv/bin/profsearch --config .profsearch/config.toml pipeline init-db`
6. Ensure the repo-local `.env` exists.
   - If `.env` is missing, copy `.env.example` to `.env`.
   - Ensure `.env` contains `PROFSEARCH_CONFIG_FILE=.profsearch/config.toml`.
   - Ensure `.env` contains `PROFSEARCH_OPENALEX_API_KEY=` and `PROFSEARCH_OPENALEX_API_KEYS=` as blank values for now.
   - Update keys in place; do not duplicate keys.
7. Run install diagnostics:
   - `.venv/bin/profsearch --config .profsearch/config.toml doctor --json-output`
8. Summarize:
   - whether install is healthy
   - config, data, cache, and runs paths
   - any blockers that still need user action
9. End by telling the user to paste `prompts/ade/corpus-setup.md`.
