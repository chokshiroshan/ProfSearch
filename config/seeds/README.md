# Seed Templates

These files are **contribution templates** for expanding ProfSearch beyond the default physics-adjacent corpus in [`../universities_seed.json`](../universities_seed.json).

They are **not loaded by default** — the current pipeline still reads the single-file seed specified by `seed_file` in `config.toml`. Merging these per-field files into the runtime seed is planned for v0.2 (see `CHANGELOG.md` → Unreleased).

Until then, treat these as staging ground: contribute entries here, and once the loader merge lands, they activate automatically.

## Files

| File | Scope | Status |
|------|-------|--------|
| `cs.json` | Computer Science, ECE, AI / ML departments | Template — empty |
| `bio.json` | Biology, Molecular Biology, Neuroscience | Template — empty |
| `bioeng.json` | Biomedical / Bioengineering, Chemical Engineering | Template — empty |
| `eu_general.json` | European universities (any field) | Template — empty |
| `asia_general.json` | Asian universities (any field) | Template — empty |

## Entry Shape

Each file is a JSON array of university objects. The schema matches the entries in `universities_seed.json`:

```json
{
  "name": "Full Official University Name",
  "short_name": "Display Name",
  "qs_rank_2026": 42,
  "qs_score": 80.0,
  "domain": "example.edu",
  "openalex_id": "https://openalex.org/I12345678",
  "ror_id": "https://ror.org/0abcdefgh",
  "state": "State or Country",
  "departments": [
    {
      "department_type": "computer_science",
      "roster_url": "https://cs.example.edu/people/faculty",
      "parser_hint": "generic_faculty_cards"
    }
  ]
}
```

### Required fields

- `name`, `short_name`, `domain`
- `openalex_id` — find it at <https://api.openalex.org/institutions?search=your+university>
- `ror_id` — find it at <https://ror.org>
- At least one entry in `departments` with a working `roster_url`

### Picking a `parser_hint`

If the roster page has a structure similar to an existing supported school, reuse its hint (see `src/profsearch/scraping/` for the registered parsers). Otherwise use `generic_faculty_cards` and open an issue — we may need to add a new parser.

## Testing a new entry

```bash
.venv/bin/profsearch pipeline run \
  --through-stage stage3 \
  --only-university "Your University"
```

A non-empty, plausible verified-professor count means the scrape + normalize path works. Include that output in your PR.
