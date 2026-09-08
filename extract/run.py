"""End-to-end extraction orchestrator + CLI.

For each included study: retrieve full text (fetch), extract effects with
provenance (extract), verify the quoted numbers (verify), write rows to the
effects table (db), and export data/effects.csv. Reports retrieval status,
effects per study, null-field rate by field, and rows needing human spot-check.

LLM access routes through the shared llm service (local Claude Code by default).
Pass a different client for tests and offline runs.

    python -m extract.run [--db data/db/records.db] [--limit N] [--model opus]
                          [--email you@inst.edu]

Idempotency: an effect already written under the same prompt hash is not
re-inserted. Changing a prompt creates new rows under the new hash. There is no
flag that overwrites or deletes existing rows; that is deliberate.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from llm.service import LLMClient

from . import cohorts, db as edb
from .extract import extract_study, unrecognized_cohorts
from .fetch import (Retrieval, retrieve_one, live_fetch_pdf_bytes,
                    live_fetch_unpaywall, live_fetch_xml)
from .prompts import EXTRACT, VERIFY, load_prompt
from .schema import PROVENANCE_FIELDS, Effect
from .verify import verify_effect

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "db" / "records.db"
EFFECTS_CSV = Path(__file__).resolve().parents[1] / "data" / "effects.csv"


@dataclass
class RunReport:
    studies: int
    retrieved: int
    unretrieved: list[str] = field(default_factory=list)
    effects_per_study: dict = field(default_factory=dict)
    null_counts: dict = field(default_factory=dict)
    total_rows: int = 0
    needs_review: int = 0
    unrecognized_cohorts: list[str] = field(default_factory=list)


def _fetchers(email: str):
    return dict(fetch_xml=live_fetch_xml(email),
                fetch_unpaywall=live_fetch_unpaywall(email),
                fetch_pdf_bytes=live_fetch_pdf_bytes())


def run_extraction(conn, client: LLMClient, *, fetchers: dict,
                   limit: Optional[int] = None, model: Optional[str] = None,
                   on_progress=None) -> RunReport:
    extract_prompt = load_prompt(EXTRACT)
    verify_prompt = load_prompt(VERIFY)
    studies = edb.included_studies(conn)
    if limit is not None:
        studies = studies[:limit]

    report = RunReport(studies=len(studies), retrieved=0)
    null_counts = {f: 0 for f in PROVENANCE_FIELDS}
    total_numeric_cells = 0

    for idx, rec in enumerate(studies, 1):
        record = dict(rec)
        ret = retrieve_one(record, **fetchers)
        edb.record_retrieval(conn, ret.study_id, ret.status, ret.detail)
        if not ret.ok:
            report.unretrieved.append(ret.study_id)
            if on_progress:
                on_progress(idx, len(studies), ret.study_id, "unretrieved", 0)
            continue
        report.retrieved += 1

        result = extract_study(client, extract_prompt, ret.document, model=model)
        report.unrecognized_cohorts += unrecognized_cohorts(result)
        n_effects = 0
        for eff in result.effects:
            verdict = verify_effect(client, verify_prompt, eff, model=model)
            key = edb.save_effect(
                conn, eff, prompt_hash=extract_prompt.prompt_hash,
                model_version=client.model_version,
                verified="confirmed" if verdict.confirmed else "disputed",
                needs_review=verdict.needs_review, review_reason=verdict.reason)
            edb.set_verification(conn, key, verified=(
                "confirmed" if verdict.confirmed else "disputed"),
                needs_review=verdict.needs_review, review_reason=verdict.reason)
            if verdict.needs_review:
                report.needs_review += 1
            for f in PROVENANCE_FIELDS:
                total_numeric_cells += 1
                if getattr(eff, f) is None:
                    null_counts[f] += 1
            n_effects += 1
        report.effects_per_study[ret.study_id] = n_effects
        report.total_rows += n_effects
        if on_progress:
            on_progress(idx, len(studies), ret.study_id, ret.status, n_effects)

    report.null_counts = null_counts
    report.unrecognized_cohorts = sorted(set(report.unrecognized_cohorts))
    return report


def _print_report(report: RunReport, null_denominator_rows: int) -> None:
    print(f"studies            {report.studies}")
    print(f"  retrieved        {report.retrieved}")
    print(f"  unretrieved      {len(report.unretrieved)}")
    print(f"effect rows        {report.total_rows}")
    if report.effects_per_study:
        avg = report.total_rows / max(1, len(report.effects_per_study))
        print(f"effects/study avg  {avg:.1f}")
    print(f"rows needing review {report.needs_review}")
    if report.unrecognized_cohorts:
        print(f"unrecognized cohorts (assign by hand): "
              f"{', '.join(report.unrecognized_cohorts)}")
    print("null-field rate (numeric fields):")
    denom = max(1, report.total_rows)
    for f, c in report.null_counts.items():
        print(f"  {f:12s} {c}/{denom} ({100*c//denom}%)")


def _build_client(model: Optional[str]):
    from llm.claude_code import ClaudeCodeClient
    return ClaudeCodeClient(default_model=model)


def _progress(i, n, sid, status, n_eff):
    print(f"[{i:4d}/{n}] {status:14s} effects={n_eff:2d}  {sid}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Full-text retrieval + effect extraction.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--email", default="meta-analysis@example.org",
                    help="contact email for Unpaywall")
    args = ap.parse_args(argv)

    conn = edb.connect(args.db)
    client = _build_client(args.model)
    report = run_extraction(conn, client, fetchers=_fetchers(args.email),
                            limit=args.limit, model=args.model, on_progress=_progress)
    from .review_queue import build_queue
    qn = build_queue(conn)
    exported = edb.export_effects_csv(conn, EFFECTS_CSV)
    _print_report(report, report.total_rows)
    print(f"review queue       {qn} rows -> extract/review_queue.csv")
    print(f"effects.csv        {exported} rows -> {EFFECTS_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
