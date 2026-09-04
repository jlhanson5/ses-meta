# SES x subcortical-volume living meta-analysis

Reproducible pipeline for a continuously updating meta-analysis of the
association between socioeconomic status / poverty and hippocampal and amygdala
structural volumes across the lifespan.

Two eventual deliverables: a static site that updates as new papers appear, and
a frozen snapshot for a journal article. This repo currently implements **steps
1 and 2 of 6: automated literature search, and two-pass LLM title/abstract
screening**. Extraction, modeling, and the site are stubs.

## Layout

```
search/     retrieval code                    (built)
llm/        LLM service (local Claude Code)    (built)
screen/     LLM title/abstract screening       (built)
extract/    effect-size extraction             (stub)
analysis/   meta-analysis                      (stub)
site/       static site + snapshot             (stub)
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

Screening (step 2) shells out to the local Claude Code CLI, so `claude` must be
installed and authenticated to run live screening. See `llm/README.md`.

## Configure

API keys and the OpenAlex contact email are read from the environment only and
never written to any file.

```bash
cp .env.example .env      # fill in, then `source .env` or export
export NCBI_API_KEY=...       # optional, raises PubMed rate limit 3/s -> 10/s
export S2_API_KEY=...         # optional, raises Semantic Scholar limit
export OPENALEX_MAILTO=...    # optional, OpenAlex polite pool (better rate limits)
```

## Run

### Search (step 1)

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

### Screen (step 2)

```bash
# screen a random batch of unscreened records with the local model
python -m screen.run --limit 200 --random --model opus

# review the human queue in the terminal (i/e/u/s/q keystrokes)
python -m screen.review

# mine references of flagged reviews/metas back into the queue, then screen them
python -m screen.refmine
python -m screen.run

# offline end-to-end demo on a synthetic corpus (no model needed)
python -m screen.demo --n 100 --seed 7

# eval the real prompts against a hand-labeled gold set
python -m screen.evals.run_eval --client claude --model opus   # real quality
python -m screen.evals.run_eval --client fake                  # harness self-check
```

Screening reports include / exclude / queued counts, inter-pass agreement, and
model calls. Re-runs are free: screened records are skipped, and each model
decision is cached. See `screen/README.md` for the full design.

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

**Screening is two independent passes, combined conservatively.** Each record
gets a pass that argues for inclusion and a skeptical pass that argues for
exclusion, both returning strict JSON. They are aggregated so that disagreement,
either pass uncertain, or a low-confidence exclude routes the record to a human
queue; nothing is excluded on a single low-confidence call. Includes are
provisional and advance to full-text. Criteria live in `screen/criteria.md`;
prompts are versioned files in `screen/prompts/`, never inline strings.

**Model calls route through local Claude Code, not a hosted API.** The `llm/`
service shells out to the `claude` CLI. Every model decision stores model,
prompt version, prompt hash, and timestamp, and is cached on
(record_id, pass, prompt_hash, model), so re-runs cost nothing and changing a
prompt creates new rows rather than overwriting old ones. Human decisions are
final and never overwritten by a later model run. Records with no abstract skip
the model entirely and route straight to the queue. Reviews and meta-analyses
are excluded but flagged for OpenAlex reference mining, which feeds their
citations back into screening.

## Tests and evals

```bash
pytest                     # gate tests: deterministic, offline, fast
```

The search layer has no latent-space component, so it ships gate tests only.
Screening (step 2) introduces LLM calls and ships both gate tests and an eval
suite: `screen/evals/run_eval.py` scores the real prompts against a hand-labeled
gold set (`screen/evals/gold.jsonl`) on accuracy and zero false-excludes. A free
gate test runs the harness with a gold-aligned fake.

## Adding a source

Add a class under `search/sources/` with `name` and
`run(query, date_from, date_to) -> list[Record]`, register it in
`search/sources/__init__.py:SOURCES`, and add a dialect branch in
`search/queries.py:format_for`. Nothing else changes.
