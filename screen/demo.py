"""Offline demo: screen 100 records end to end without a live model.

This exists because the sandbox has no local claude binary and blocks the source
APIs, so there is no real corpus and no real model here. It builds a synthetic
corpus with a known category mix and screens it with a RULE-BASED SIMULATION of
the two passes. It proves the plumbing: two-pass flow, aggregation, queue
routing, agreement math, caching, and the final report. It says NOTHING about
model quality. Real quality is measured by screen/evals against local Claude
Code on Jamie's machine.

    python -m screen.demo [--n 100] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from search.db import connect as connect_records, upsert_records
from search.model import Record

from . import db as sdb
from .review_queue import build_queue
from .run import screen_records

# --------------------------------------------------------------------------
# synthetic corpus: each template carries phrasing the simulation reads
# --------------------------------------------------------------------------

TEMPLATES = [
    # (weight, category, title, abstract)
    (22, "include",
     "Family income and hippocampal volume in children",
     "In 214 children imaged in vivo with structural MRI, lower family "
     "income-to-needs was associated with smaller hippocampal volume "
     "(beta=0.19). Amygdala volume showed a similar association."),
    (10, "include",
     "Neighborhood deprivation and amygdala volume in adults",
     "Among 512 adults, area-level deprivation (Townsend index) correlated "
     "with amygdala volume from FreeSurfer segmentation in vivo."),
    (12, "animal",
     "Early-life deprivation alters hippocampal volume in rats",
     "We reared rat pups under limited-bedding conditions and measured "
     "hippocampal volume. Deprived rats showed reduced volume."),
    (10, "review",
     "Socioeconomic status and brain structure: a systematic review",
     "This systematic review and meta-analysis summarizes associations between "
     "socioeconomic status and subcortical volumes across 40 studies."),
    (10, "thickness",
     "Income and cortical thickness in adolescence",
     "In 300 adolescents, family income was associated with cortical thickness "
     "in prefrontal regions. No subcortical volumes were analyzed."),
    (8, "nuisance",
     "Screen time and amygdala volume, adjusting for SES",
     "We related screen time to amygdala volume in 180 youth, adjusting for "
     "socioeconomic status as a covariate. SES itself was not examined."),
    (6, "small",
     "Poverty and hippocampal volume: a pilot",
     "In this pilot of 14 participants, we related an income measure to "
     "hippocampal volume in vivo. Results are preliminary."),
    (12, "subcortical_unnamed",
     "Socioeconomic status and subcortical structures",
     "In 260 adults, socioeconomic status was related to subcortical structure "
     "volumes measured in vivo. Specific structures are detailed in the text."),
    (10, "thin",
     "SES and the developing brain (conference abstract)",
     "Conference abstract. We present preliminary findings on SES and brain "
     "development. Methods and sample size to follow."),
]


def build_corpus(conn, n: int, seed: int) -> None:
    rng = random.Random(seed)
    weighted = []
    for w, cat, title, abstract in TEMPLATES:
        weighted += [(cat, title, abstract)] * w
    run_id = "demo:" + datetime.now(timezone.utc).isoformat()
    records = []
    for i in range(n):
        cat, title, abstract = rng.choice(weighted)
        year = rng.randint(2008, 2025)
        records.append(Record(
            title=f"{title}",
            abstract=abstract,
            authors=f"Author{i} A; Coauthor{i} B",
            year=year,
            journal=rng.choice(["NeuroImage", "Dev Sci", "Biol Psychiatry",
                                 "SCAN", "JAMA Psychiatry"]),
            source="demo",
            # unique-ish so ids do not collide across identical templates
            doi=f"10.5555/demo.{seed}.{i}",
            raw_json=json.dumps({"category": cat}),
        ))
    upsert_records(conn, records, run_id)


# --------------------------------------------------------------------------
# simulation client: reads the rendered prompt, returns strict-JSON decisions.
# Framing-aware: the skeptical pass B is stricter on the two borderline
# categories, which is what drives disagreement -> the human queue.
# --------------------------------------------------------------------------

def _is_pass_b(prompt: str) -> bool:
    return "pass B" in prompt or "skeptical" in prompt


def simulate(prompt: str, system=None, model=None) -> str:
    # Only read the record's own text. The prompt instructions mention words like
    # "meta-analysis" and "cortical thickness"; matching the whole prompt would
    # classify every record off the criteria text. Split on the TITLE: marker.
    p = prompt.split("TITLE:")[-1].lower()
    skeptical = _is_pass_b(prompt)

    def out(decision, hits, reason, conf):
        return json.dumps({"decision": decision, "criteria_hit": hits,
                           "reason": reason, "confidence": conf})

    if "rat pups" in p or "rats" in p:
        return out("exclude", ["animal"], "non-human subjects", 0.98)
    if "systematic review" in p or "meta-analysis" in p:
        return out("exclude", ["review_or_meta"], "review, mine references", 0.97)
    if "cortical thickness" in p and "hippocampal volume" not in p and "amygdala volume" not in p:
        # low-confidence exclude on some -> triggers low_confidence_exclude queue
        conf = 0.72 if "prefrontal regions" in p else 0.9
        return out("exclude", ["no_volume_outcome"], "thickness only, no volume", conf)
    if "adjusting for" in p or "as a covariate" in p:
        return out("exclude", ["ses_nuisance_only"], "SES covariate only", 0.9)
    if "pilot of 14" in p or " 14 participants" in p:
        return out("exclude", ["sample_lt_20"], "sample below 20", 0.95)
    if "subcortical structure" in p and "hippocamp" not in p and "amygdala" not in p:
        # borderline: A tolerates, B rules out -> disagreement -> queue
        if skeptical:
            return out("exclude", ["no_volume_outcome"],
                       "structures unnamed, cannot confirm hippo/amygdala", 0.75)
        return out("uncertain", [], "subcortical unnamed, cannot confirm", 0.5)
    if "conference abstract" in p or "to follow" in p:
        return out("uncertain", [], "too thin to judge", 0.4)
    if (("income" in p or "deprivation" in p or "poverty" in p)
            and ("hippocampal volume" in p or "amygdala volume" in p)
            and ("associat" in p or "correlat" in p)):
        return out("include", [], "SES related to hippocampal/amygdala volume", 0.93)
    return out("uncertain", [], "criteria not cleanly resolved", 0.5)


class SimulationClient:
    model_version = "simulation:rule-based-v1"

    def complete(self, prompt: str, *, system=None, model=None) -> str:
        return simulate(prompt, system, model)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Offline screening demo (simulation).")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="screen_demo_"))
    db_path = tmp / "records.db"
    conn = connect_records(db_path)          # creates records + runs tables
    sdb.connect(db_path)                       # adds screen tables to same db
    build_corpus(conn, args.n, args.seed)

    client = SimulationClient()
    report = screen_records(conn, client, limit=args.n, random_sample=True)

    # second pass proves caching: no new model calls
    report2 = screen_records(conn, client, limit=args.n, random_sample=True)

    counts = sdb.status_counts(conn)
    queue_rows = build_queue(conn, tmp / "review_queue.csv")
    refmine_n = len(sdb.refmine_targets(conn))
    rate = report.agreements / report.screened if report.screened else 0.0

    print("=== screening demo report (simulation, not a quality measure) ===")
    print(f"records screened     : {report.screened}")
    print(f"  include            : {counts.get('include', 0)}")
    print(f"  exclude            : {counts.get('exclude', 0)}")
    print(f"  queued (uncertain/ : {counts.get('queued', 0)}")
    print(f"    disagreement)      ")
    print(f"inter-pass agreement : {report.agreements}/{report.screened} ({rate:.0%})")
    print(f"human review queue   : {queue_rows} records -> {tmp/'review_queue.csv'}")
    print(f"refmine targets      : {refmine_n} reviews/metas flagged for mining")
    print(f"model calls (run 1)  : {report.llm_calls}  cached passes: {report.cached}")
    print(f"model calls (run 2)  : {report2.llm_calls}  cached passes: {report2.cached}"
          f"   <- re-run cost nothing" if report2.llm_calls == 0 else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
