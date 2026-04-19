# ProfSearch Architecture

## Overview

ProfSearch constructs a verified database of professors from physics and adjacent departments at top U.S. research universities, links those professors to OpenAlex author profiles, ingests their recent publications, and provides paper-level semantic search with professor-level ranking.

**Key decision**: Official university faculty rosters are the source of truth for who is a professor. OpenAlex is used only for author matching and publication enrichment.

## Pipeline Stages

### Stage 1: Load Universities + Department Sources

- **Input**: `config/universities_seed.json`
- Upserts `universities` and `department_sources` tables
- Validates that all configured URLs are on approved university domains
- Idempotent; no runtime institution guessing

### Stage 2: Scrape Official Faculty Rosters

- Fetches each official roster page
- Extracts candidate faculty entries: name, title, profile_url, email, source_url
- Restricts scraping to approved university domains
- Stores errors per source without blocking other universities

### Stage 3: Normalize Titles + Verify Professors

- Normalizes names and titles
- Classifies as `verified`, `ambiguous`, or `excluded`:
  - **Verified**: Assistant Professor, Associate Professor, Professor
  - **Ambiguous**: Adjunct, Emeritus, Visiting, Research Professor, courtesy titles
  - **Excluded**: Students, Postdocs, Staff, Lecturers, Research Scientists
- Only `verified` professors are eligible for search

### Stage 4: Match Professors to OpenAlex

- Candidate generation by name search with institution filtering
- Scoring signals: name similarity (0.45), institution match (0.25), topic alignment (0.15), recency (0.10), extra evidence (0.05)
- Outcomes: `matched`, `ambiguous`, `unmatched`, `manual_override`
- Ambiguous and unmatched records stay out of the searchable corpus

### Stage 5: Fetch Publications

- Fetches recent works for matched authors from OpenAlex
- Reconstructs abstracts from inverted index
- Deduplicates works by OpenAlex work ID
- Stores many-to-many professor-work links

### Stage 6: Compute Embeddings

- Encodes `"{title} [SEP] {abstract[:256]}"` via SPECTER2
- Stores 768-dim vectors in sqlite-vec

## Search Architecture

### Query Processing
1. Normalize query text
2. Compute query embedding via SPECTER2
3. Extract keywords

### Work Scoring
Three signals per work:

| Signal | Weight | Method |
|--------|--------|--------|
| Semantic similarity | 0.50 | Cosine similarity via sqlite-vec KNN |
| Keyword matching | 0.30 | Term matching against title + abstract |
| Topic overlap | 0.20 | Query keywords vs OpenAlex topics |

### Professor Aggregation
- Groups scored works by professor
- Default method: `top_k_sum` with k=5
- Returns ranked professors with top contributing works

## Data Model

Seven tables in SQLite:

- `universities` — Institution metadata with OpenAlex and ROR IDs
- `department_sources` — Per-department roster URLs with scrape status
- `professors` — Verified faculty with normalized names and titles
- `openalex_author_matches` — Author linkage with evidence JSON
- `works` — Deduplicated publications
- `professor_works` — Many-to-many authorship edges
- `work_embeddings` — sqlite-vec 768-dim vectors
- `pipeline_state` — Stage checkpointing for resumability

## Duplicate Handling

Two rules:
1. Same university + same normalized name → treated as same person / joint appointment
2. Same university + same OpenAlex author ID → canonical + duplicates

Known limitation: two distinct people with the same normalized name at the same university need manual review.
