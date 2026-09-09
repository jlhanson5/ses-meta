# extract/ — full-text retrieval and effect-size extraction (step 3 of 6)

Retrieves the full text of every included study, extracts one row per effect with
mandatory provenance, verifies each number against its quote, and writes an
effects table plus `data/effects.csv`.

## Pipeline

1. Retrieve (`fetch.py`): for each included study, try Europe PMC open-access
   XML, then a publisher PDF via Unpaywall, then a manual drop at
   `data/pdfs/manual/<study_id>.pdf`. Every study gets a retrieval status;
   unretrievable studies go to a report, never silence.
2. Extract (`extract.py`, `prompts/extract_v1.md`): the full text is split into
   locator-tagged segments (`[[p.4]]`, `[[Table 2]]`) and sent to the model,
   which returns one row per effect. The prompt forbids computing, inferring, or
   estimating: report only printed values, else null.
3. Enforce provenance (`schema.py`): every numeric field (n, mean_age,
   pct_female, effect_value, se_or_ci, p_value) must carry a locator and a
   verbatim quote. A value without both is forced to null in code, not left to
   the model. A row whose effect_value is null gets confidence 0.
4. Verify (`verify.py`, `prompts/verify_v1.md`): a second call re-reads ONLY the
   quoted spans and confirms or disputes each number. A dispute, or a row below
   confidence 0.9, routes to `extract/review_queue.csv` for human spot-check.
5. Cohort overlap (`cohorts.py`): `sample_overlap_group` is assigned from a
   registry of known shared cohorts (ABCD, HCP-D, HBN, NCANDA, PING, UK Biobank,
   Generation R, ALSPAC, Dunedin). An unrecognized cohort is flagged for a human,
   never guessed.
6. Persist and export (`db.py`): rows go to the `effects` table in records.db and
   `data/effects.csv` is written on every run.

## No conversion here

Effect sizes are extracted exactly as reported. Nothing in this step standardizes
or converts them; the `effect_type` field records what was reported (r, partial r,
beta, d, t, F, raw group means). Conversion happens in step 4 in R, where it is
auditable.

## Provenance is a property, not a hope

The rule "no locatable source means null, never a guess" is enforced
deterministically in `schema.py`, then independently checked by the verification
pass. The extraction prompt also states it. Three layers, because a fabricated
number in a meta-analysis is the worst failure mode.

## Idempotency

Each effect has a deterministic `effect_key` over
(study_id, roi, hemisphere, ses_construct, ses_timing, effect_type, prompt_hash).
Writes are INSERT OR IGNORE, so re-running extracts nothing new. Changing a prompt
changes the hash and creates new rows rather than overwriting. There is no flag
that overwrites or deletes existing rows or PDFs; that is deliberate.

## LLM access: local Claude Code, not a hosted API

Extraction and verification route through the `llm/` service, which shells out to
the local `claude` CLI. Live retrieval needs network and live extraction needs the
CLI, so real runs happen on the researcher's machine; the sandbox uses fakes and a
labeled simulation.

## Commands

    # retrieve, extract, verify, write, export
    python -m extract.run --limit 10 --model opus --email you@inst.edu

    # offline end-to-end demo on a synthetic corpus (no model, no network)
    python -m extract.demo --n 10 --seed 5

    # eval the real prompt against a hand-labeled gold set
    python -m extract.evals.run_eval --client claude --model opus   # real quality
    python -m extract.evals.run_eval --client fake                  # harness self-check

## Outputs

    effects table in data/db/records.db     one row per effect, with provenance
    data/effects.csv                        exported every run
    extract/review_queue.csv                rows needing human spot-check
    retrieval_status table                  per-study retrieval outcome

## Tests and evals

- Gate tests (`tests/`): schema/provenance enforcement, cohort assignment,
  document parsing, retrieval tier order, DB idempotency, extract + verify
  orchestration, and the eval harness self-check. Deterministic and free.
- Evals (`evals/`): `run_eval.py` scores the real prompt against `gold.jsonl` on
  field accuracy and zero fabrications, run against local Claude Code.

## Files

    schema.json / schema.py    the effect-row schema and provenance enforcement
    fetch.py                   three-tier full-text retrieval
    document.py                locator-tagged full-text segments (PDF, JATS)
    cohorts.py                 known-cohort overlap registry
    prompts/                   versioned extraction + verification prompts
    prompts.py                 load / hash / render
    extract.py                 extraction orchestrator
    verify.py                  second-pass verification
    db.py                      effects table, retrieval status, CSV export
    review_queue.py            side-by-side human review CSV
    run.py                     end-to-end CLI
    demo.py                    offline simulation
    evals/                     gold set + eval harness

## Human review editor (curate)

The auto-generated `review_queue.csv` is read-only; human decisions go through
the curate round-trip, which writes them back to the effects table immutably:

    python -m extract.curate export            # -> extract/review_edit.csv
    # open in Excel: correct any field, assign sample_overlap_group for
    # unrecognized cohorts, set review_action per row (keep / edit / drop),
    # add notes. Do not edit effect_key.
    python -m extract.curate import extract/review_edit.csv

Import writes changes as human decisions: verified='human', human_reviewed=1,
needs_review cleared. A human-reviewed row is never re-verified or overwritten by
a later model run or `reverify` (immutable, like a human screening decision).
review_action='drop' marks a row excluded from the analysis dataset without
deleting it. Rows with a blank review_action are left untouched, so review can
span several sittings. Cohort overlap assignment is folded in via the
sample_overlap_group column. `data/effects.csv` gains verified / human_reviewed /
excluded columns so step 4 can filter.
