# SES x subcortical-volume living meta-analysis

Reproducible pipeline for a continuously updating meta-analysis of the
association between socioeconomic status / poverty and hippocampal and amygdala
structural volumes across the lifespan.

Two eventual deliverables: a static site that updates as new papers appear, and
a frozen snapshot for a journal article. This repo currently implements **step 1
of 6: repository scaffold + automated literature search**. Screening, extraction,
modeling, and the site are stubs.

## Layout

```
search/     retrieval code (built)
screen/     LLM screening            (stub)
extract/    effect-size extraction   (stub)
analysis/   meta-analysis            (stub)
site/       static site + snapshot   (stub)
data/raw/   immutable API responses, one JSON per query per run, ISO-dated
data/db/    SQLite records.db
logs/       run log + dedup audit (dedup.jsonl)
```

## Install

Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # or: uv pip install -r requirements.txt
```

## Configure

API keys are read from the environment only and never written to any file.

```bash
cp .env.example .env      # fill in, then `source .env` or export
export NCBI_API_KEY=...    # optional, raises PubMed rate limit 3/s -> 10/s
export S2_API_KEY=...      # optional, raises Semantic Scholar limit
```

## Run

```bash
# incremental from the last run (or 30 days back on a fresh DB)
python -m search.run

# explicit window
python -m search.run --since 2026-08-01 --until 2026-08-31

# a subset of sources
python -m search.run --sources pubmed europepmc
```

Output per run: records per source, duplicates merged, unique this run, new to
database, total in database.

## Smoke test

```bash
python -m search.smoke --offline        # fixtures, no network (CI-safe)
python -m search.smoke --live --days 30 # real APIs, last 30 days
```

The offline smoke exercises parse -> dedup -> DB against a bundled corpus with
known overlaps. Expected: pubmed 3, europepmc 2, openalex 2, semanticscholar 2;
4 duplicates merged; 5 unique.

## Design decisions

**Query set is generated, not hardcoded.** `search/queries.yaml` holds three
blocks (brain, ses, method). `search/queries.py` expands the cross product
brain x ses x method into the canonical query set and formats each triple into
each source's dialect. PubMed and Europe PMC are boolean databases (phrase
quoting, `[tiab]` field tags, wildcards). OpenAlex and Semantic Scholar are
relevance keyword engines, so triples render as space-joined phrases with
wildcards stripped. Overlap between blocks (a pipeline name in `brain`, a method
term in `method`) is harmless: duplicates merge in dedup.

**Idempotency is structural, not checked after the fact.** Every record gets a
deterministic id: the normalized DOI when present, otherwise a hash of
normalized-title + first-author-last + year (`search/model.compute_id`). Inserts
are `INSERT OR IGNORE` on that id, so re-running a window inserts nothing new and
never overwrites an existing row's `first_seen_run`. `n_new` is computed by
diffing incoming ids against ids already in the DB, so the count stays exact even
though the write is a no-op for known rows.

**Raw responses are cached and immutable.** One JSON per (run_date, source,
query) under `data/raw`, written atomically and never overwritten. A re-run on
the same day reads the cache and never re-hits an API.

**Dedup is DOI-first, then a guarded fuzzy fallback.** Exact normalized-DOI match
first. Records without a DOI fall back to title similarity (rapidfuzz
token_sort_ratio >= 92) gated on identical publication year AND identical
first-author last name, so near-identical titles from different years or authors
do not collapse. Every merge is logged to `logs/dedup.jsonl` with the reason and
(for fuzzy) the score.

**Rate limits and backoff.** Each source has its own min-interval limiter.
`search/http.py` retries 429/5xx with Retry-After when present, else exponential
backoff capped at 30s.

## Tests

```bash
pytest                     # gate tests: deterministic, offline, fast
```

No eval suite ships in step 1: there is no latent-space (LLM) component in the
search layer, so there is nothing to eval. Screening (step 2) introduces LLM
calls and will ship with evals then.

## Adding a source

Add a class under `search/sources/` with `name` and
`run(query, date_from, date_to) -> list[Record]`, register it in
`search/sources/__init__.py:SOURCES`, and add a dialect branch in
`search/queries.py:format_for`. Nothing else changes.
