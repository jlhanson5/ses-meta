"""Offline end-to-end extraction demo.

The sandbox has no network (no full-text fetch) and no claude binary (no live
model), so this builds a synthetic corpus of study full texts and runs the real
pipeline (fetch shim -> extract -> verify -> write -> export) with a RULE-BASED
SIMULATION of the model. It proves the plumbing: provenance enforcement, the
verification pass, cohort assignment, idempotent writes, the review queue, and
the report. It says nothing about extraction quality; that is measured by
extract/evals against local Claude Code on the researcher's machine.

    python -m extract.demo [--n 10] [--seed 5]
"""
from __future__ import annotations

import argparse
import json
import random
import tempfile
from pathlib import Path

from search.db import connect as connect_records, upsert_records
from search.model import Record

from . import cohorts, db as edb
from .document import Document, Segment, from_tagged
from .prompts import EXTRACT, VERIFY, load_prompt
from .review_queue import build_queue
from .schema import PROVENANCE_FIELDS
from .extract import extract_study
from .verify import verify_effect

# synthetic studies: (cohort, roi/measure text with numbers, known-overlap?)
COHORT_POOL = ["ABCD", "UK Biobank", "Generation R", "ALSPAC", "NCANDA",
               "the Springfield Youth Study",  # unknown -> flagged
               "HCP-D", "PING", "Dunedin", "a local convenience sample"]


def _full_text(cohort: str, effect: float, n: int, p: float, roi: str) -> str:
    results = (
        f"[[Table 2]]\n"
        f"In the {cohort} sample (N = {n}), income-to-needs was associated with "
        f"{roi} volume, r = {effect}, p = {p}. FreeSurfer 6.0 segmentation, "
        f"adjusted for intracranial volume as a covariate."
    )
    methods = (
        f"[[Methods]]\n"
        f"Participants were drawn from {cohort}. Mean age 10.2 years, 52% female."
    )
    return methods + "\n\n" + results


def build_corpus(conn, n: int, seed: int) -> None:
    rng = random.Random(seed)
    run_id = "extract-demo"
    records = []
    for i in range(n):
        cohort = COHORT_POOL[i % len(COHORT_POOL)]
        roi = "hippocampus" if i % 2 == 0 else "amygdala"
        eff = round(rng.uniform(0.1, 0.3), 2)
        nn = rng.randint(80, 900)
        p = round(rng.uniform(0.001, 0.049), 3)
        text = _full_text(cohort, eff, nn, p, roi)
        records.append(Record(
            doi=f"10.5555/extract.{seed}.{i}",
            title=f"SES and {roi} volume in {cohort}",
            abstract="see full text",
            authors=f"Author{i} A",
            year=2000 + i,
            journal="Demo Journal",
            source="extract-demo",
            raw_json=json.dumps({"fulltext": text, "cohort": cohort}),
        ))
    upsert_records(conn, records, run_id)
    # mark them all included so the extractor picks them up
    from screen.db import connect as sconnect, upsert_status
    sconnect(conn_path_for(conn))
    for rec in records:
        upsert_status(conn, rec.id, "include", False, None, "model", False)


def conn_path_for(conn) -> Path:
    (row,) = conn.execute("PRAGMA database_list").fetchall()[:1]
    return Path(row[2])


class SimulationClient:
    """Rule-based stand-in for the extraction and verification model."""
    model_version = "simulation:extract-v1"

    def complete(self, prompt: str, *, system=None, model=None) -> str:
        if "CLAIMS:" in prompt:
            return self._verify(prompt)
        return self._extract(prompt)

    def _extract(self, prompt: str) -> str:
        body = prompt.split("STUDY FULL TEXT:")[-1]
        cohort = "unknown"
        for c in COHORT_POOL:
            if c in body:
                cohort = c
                break
        roi = "hippocampus" if "hippocampus" in body else "amygdala"
        import re
        r = re.search(r"r = ([0-9.]+)", body)
        n = re.search(r"N = (\d+)", body)
        p = re.search(r"p = ([0-9.]+)", body)
        def num(m):
            return float(m.group(1).rstrip(".")) if m else None
        rv = num(r)
        pv = num(p)
        quote = f"income-to-needs was associated with {roi} volume, r = {r.group(1) if r else '?'}"
        eff = {
            "cohort_name": cohort, "n": int(n.group(1)) if n else None,
            "mean_age": 10.2, "pct_female": 52, "sample_type": "community",
            "ses_construct": "income-to-needs", "ses_timing": "concurrent",
            "roi": roi, "hemisphere": "bilateral", "volume_pipeline": "FreeSurfer 6.0",
            "icv_adjustment": "covariate", "covariates": ["intracranial volume"],
            "effect_type": "r", "effect_value": rv,
            "se_or_ci": None, "p_value": pv,
            "direction_coded_positive_means_higher_SES_larger_volume": True,
            "page_number": "Table 2", "verbatim_quote": quote,
            "extraction_confidence": 0.95,
            "provenance": {
                "n": {"page": "Table 2", "quote": f"N = {n.group(1) if n else '?'}"},
                "effect_value": {"page": "Table 2", "quote": quote},
                "p_value": {"page": "Table 2", "quote": f"p = {p.group(1) if p else '?'}"},
                "mean_age": {"page": "Methods", "quote": "Mean age 10.2 years"},
                "pct_female": {"page": "Methods", "quote": "52% female"},
            },
        }
        return json.dumps({"effects": [eff]})

    def _verify(self, prompt: str) -> str:
        claims = json.loads(prompt.split("CLAIMS:")[-1].strip())
        verdicts = []
        for c in claims:
            # confirm when the quote contains the value; the demo quotes do
            ok = str(c["value"]).rstrip("0").rstrip(".") in c["quote"] or c["field"] in ("mean_age", "pct_female")
            verdicts.append({"index": c["index"],
                             "verdict": "confirm" if ok else "dispute",
                             "confidence": 0.95, "note": "demo"})
        return json.dumps({"verdicts": verdicts})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Offline extraction demo (simulation).")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="extract_demo_"))
    db_path = tmp / "records.db"
    conn = connect_records(db_path)
    edb.connect(db_path)
    build_corpus(conn, args.n, args.seed)

    client = SimulationClient()
    extract_prompt = load_prompt(EXTRACT)
    verify_prompt = load_prompt(VERIFY)

    studies = edb.included_studies(conn)
    null_counts = {f: 0 for f in PROVENANCE_FIELDS}
    per_study = {}
    needs_review = 0
    total_rows = 0
    flagged = []

    for rec in studies:
        record = dict(rec)
        text = json.loads(record["raw_json"])["fulltext"]
        doc = from_tagged(text, study_id=record["id"], source="demo")
        result = extract_study(client, extract_prompt, doc)
        for eff in result.effects:
            if eff.cohort_name and eff.sample_overlap_group is None:
                flagged.append(eff.cohort_name)
            v = verify_effect(client, verify_prompt, eff)
            key = edb.save_effect(conn, eff, prompt_hash=extract_prompt.prompt_hash,
                                  model_version=client.model_version,
                                  verified="confirmed" if v.confirmed else "disputed",
                                  needs_review=v.needs_review, review_reason=v.reason)
            if v.needs_review:
                needs_review += 1
            for f in PROVENANCE_FIELDS:
                if getattr(eff, f) is None:
                    null_counts[f] += 1
            total_rows += 1
        per_study[record["id"]] = len(result.effects)

    qn = build_queue(conn, tmp / "review_queue.csv")
    exported = edb.export_effects_csv(conn, tmp / "effects.csv")

    print("=== extraction demo (simulation, not a quality measure) ===")
    print(f"studies              {len(studies)}")
    print(f"effect rows          {total_rows}")
    print(f"effects/study        {total_rows/max(1,len(per_study)):.1f}")
    print(f"rows needing review  {needs_review}")
    print(f"unrecognized cohorts {sorted(set(flagged))}")
    print("null-field rate (numeric):")
    for f, c in null_counts.items():
        print(f"  {f:12s} {c}/{max(1,total_rows)} ({100*c//max(1,total_rows)}%)")
    print(f"review_queue.csv     {qn} rows")
    print(f"effects.csv          {exported} rows")
    return 0


def _segments(text: str):
    # split "[[loc]]\nbody" blocks, keep the bracket for Segment(*split)
    parts = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("[["):
            parts.append(block[2:])       # "loc]]\nbody"
    return parts


if __name__ == "__main__":
    raise SystemExit(main())
