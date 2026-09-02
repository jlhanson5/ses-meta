# screen/ — title/abstract screening (step 2 of 6)

Two-pass LLM screening over `data/db/records.db`. Each record gets two
independent model passes with different framings; the two are combined into a
final routing of include, exclude, or human-review. Every model decision is
cached and auditable. Reviews and meta-analyses are excluded from the analysis
but harvested for their references.

## What it does

1. Reads unscreened records from the search layer's `records` table.
2. Runs two passes per record through the LLM contract (`llm/`):
   - pass A (`prompts/screen_pass_a_v1.md`) argues for inclusion
   - pass B (`prompts/screen_pass_b_v1.md`) is skeptical and argues for exclusion
   Both return strict JSON: `{decision, criteria_hit, reason, confidence}`.
3. Records with no abstract skip the model entirely and route straight to the
   human queue (`no_abstract`). A title-only record is never model-excluded.
4. Aggregates the two into a final decision (`aggregate.py`):
   - passes disagree -> human queue (`pass_disagreement`)
   - both uncertain -> human queue (`model_uncertain`)
   - agreed exclude but either confidence < 0.8 -> human queue (`low_confidence_exclude`)
   - agreed exclude, both confident -> exclude
   - agreed include -> include (provisional; advances to full-text screening)
   Nothing is excluded on a single low-confidence call.
4. Writes decisions and a status roll-up to `records.db`, and rebuilds the human
   queue CSV.
5. Reviews/metas that are excluded get flagged for reference mining.

## Criteria

`criteria.md` is the human-readable, testable rule set. INCLUDE requires all of:
living humans in vivo, an SES/poverty indicator, hippocampal or amygdala volume,
and a reported SES-to-volume association. The prompts operationalize exactly
those rules and instruct the model to judge only from the title and abstract and
to return `uncertain` rather than guess. Exclude tags are pinned to a fixed
vocabulary: `schema.normalize_tags` maps off-schema tags the model invents to the
canonical set (or `other`), so exclude analytics stay clean regardless of
prompt wording. `screen.run` prints per-record progress (rate and ETA); use
`--progress-every N` to thin it or `--quiet` to silence it.

## Reproducibility and caching

Every model decision stores model, model_version, prompt_version, prompt_hash,
and timestamp. A model decision is unique on
`(record_id, pass_name, prompt_hash, model)`. `run.py` checks for that row
before calling the model, so:

- Re-running screens nothing already screened (records carry a status row).
- Even if a record is re-visited (for example after reference mining re-adds
  it), the decision cache answers with zero model calls.
- Changing a prompt file changes its sha256 hash, which creates new rows under
  the new hash. It never overwrites the old decision. There is no force-overwrite
  path.

Human decisions are final. A human row is unique per record, model runs never
touch it, and the status roll-up always lets a human decision win.

## LLM access: local Claude Code, not a hosted API

Model calls route through `llm/`, which shells out to the local Claude Code CLI.
Nothing here calls an Anthropic/OpenAI HTTP endpoint. See `llm/README.md`. Live
screening needs the `claude` CLI on the machine; this sandbox has none, so live
runs happen on Jamie's box.

## Commands

    # screen 100 random unscreened records with the local model
    python -m screen.run --limit 100 --random --model sonnet

    # review the human queue in the terminal (i/e/u/s/q keystrokes)
    python -m screen.review

    # mine references of flagged reviews/metas, then screen the new records
    python -m screen.refmine
    python -m screen.run

    # offline end-to-end demo on a synthetic corpus (no model needed)
    python -m screen.demo --n 100 --seed 7

    # eval: real prompts vs a hand-labeled gold set
    python -m screen.evals.run_eval --client claude --model sonnet   # real quality
    python -m screen.evals.run_eval --client fake                    # harness self-check

## Tests and evals

- Gate tests (`tests/`): deterministic, free, run on every commit. Schema,
  prompts, aggregation truth table, DB idempotency and human-wins, queue CSV,
  reference mining (offline fixtures), the full cached run, and the review loop.
- Evals (`evals/`): the paid lane. `run_eval.py` runs the real prompts against
  local Claude Code and scores against `gold.jsonl`. Pass gate: accuracy
  >= threshold AND zero false-excludes (a gold include that got excluded is the
  costly error). A free gate test runs the harness with a gold-aligned fake to
  prove the scoring plumbing.

## Files

    criteria.md            the testable inclusion/exclusion rules (v1)
    prompts/               versioned prompt files (never inline strings)
    prompts.py             load + hash + render prompts
    schema.py              decision schema and strict JSON validation
    aggregate.py           two-pass routing truth table
    db.py                  screen_decisions, screen_status, screen_refmine
    run.py                 orchestrator + CLI
    review_queue.py        builds review_queue.csv from DB state
    review.py              terminal human review command
    refmine.py             OpenAlex reference mining
    demo.py                offline 100-record simulation
    evals/                 gold set + eval harness
