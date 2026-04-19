## Summary

<!-- One or two sentences: what does this change and why. -->

## Type of change

<!-- Check all that apply. -->

- [ ] Bug fix
- [ ] New feature
- [ ] Pipeline stage or matching change
- [ ] Seed data (adding / updating a university or department)
- [ ] Docs / contributor tooling
- [ ] Refactor (no behavior change)

## Changes

<!-- Bullet list of the concrete edits. Link to files or modules when useful. -->

-

## Testing

- [ ] `pytest` passes locally
- [ ] New tests cover new logic (or rationale provided for why not)
- [ ] If seed data changed: ran `profsearch pipeline run --through-stage stage3` against the updated roster URL and confirmed non-empty, plausible output
- [ ] If web UI changed: loaded the affected route(s) in a browser and verified the flow end-to-end

## Checklist

- [ ] No runtime files committed (`.env`, `.profsearch/`, `.venv/`, local SQLite DBs)
- [ ] No accidental edits to checked-in `config/` for local-runtime purposes (use `.profsearch/config.toml` for that)
- [ ] Pipeline stages remain idempotent and resumable
- [ ] Matching changes preserve "precision over recall" (see `CONTRIBUTING.md`)
- [ ] `CHANGELOG.md` updated under `## [Unreleased]` if user-visible
- [ ] Docs updated (README, `docs/architecture.md`, or ADE prompts) if the change affects install or usage

## Screenshots / output

<!-- For web UI or CLI output changes, paste a screenshot or the relevant terminal snippet. -->
