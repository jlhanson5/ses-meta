"""Screening orchestrator + CLI.

For each unscreened record: run pass A and pass B through the LLM contract,
each cached by (record_id, pass_name, prompt_hash, model) so re-runs cost
nothing, parse each into a Decision, aggregate the two into a final routing,
and write the model decisions plus the status roll-up. Records that disagree,
go uncertain, or draw a low-confidence exclude are routed to the human queue.

LLM access goes through the llm service (local Claude Code by default). Pass a
different client (llm.fake.ScriptedClient) for tests and offline runs.

CLI:
    python -m screen.run --limit 100 [--random] [--model sonnet]
                         [--db data/db/records.db]

Re-screening safety: this never overwrites a decision. A cached model row is
reused; a human row is authoritative and untouched. Changing a prompt file
changes its hash, which creates new rows under the new hash rather than
overwriting the old ones. There is no --force overwrite path by design.
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from llm.service import LLMClient, LLMError, complete_json, JSONError

from . import db as sdb
from .aggregate import aggregate, agreement
from .prompts import Prompt, load_all
from .schema import Decision, DecisionError, parse_decision

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "db" / "records.db"


@dataclass
class RunReport:
    screened: int
    include: int
    exclude: int
    queued: int
    no_abstract: int           # records queued without a model call (empty abstract)
    uncertain_passes: int      # count of individual passes that returned uncertain
    agreements: int            # records where A and B matched
    llm_calls: int             # actual model calls made (cache misses)
    cached: int                # passes served from cache


def _screen_one_pass(conn, client: LLMClient, record, pass_name: str,
                     prompt: Prompt, model_arg: Optional[str],
                     counters: dict) -> Decision:
    rid = record["id"]
    model_id = client.model_version
    cached = sdb.get_model_decision(conn, rid, pass_name, prompt.prompt_hash, model_id)
    if cached is not None:
        counters["cached"] += 1
        return cached

    rendered = prompt.render(record["title"] or "", record["abstract"] or "")
    counters["llm_calls"] += 1
    try:
        obj = complete_json(client, rendered, model=model_arg)
        decision = parse_decision(obj)
    except (LLMError, JSONError, DecisionError) as exc:
        # A malformed or failed call is not an exclude. Record it as uncertain
        # so the record routes to a human rather than vanishing.
        decision = Decision(decision="uncertain", criteria_hit=["parse_error"],
                            reason=f"unparseable model reply: {str(exc)[:80]}",
                            confidence=0.0)
    sdb.save_model_decision(
        conn, rid, pass_name, decision,
        model=model_id, model_version=model_id,
        prompt_version=prompt.version, prompt_hash=prompt.prompt_hash,
    )
    return decision


def screen_records(conn: sqlite3.Connection, client: LLMClient, *,
                   limit: Optional[int] = None, random_sample: bool = False,
                   model_arg: Optional[str] = None,
                   on_progress: Optional[Callable[[dict], None]] = None) -> RunReport:
    prompts = load_all()
    rows = sdb.unscreened_records(conn, limit=limit, random_sample=random_sample)
    total = len(rows)
    counters = {"llm_calls": 0, "cached": 0}
    inc = exc = queued = no_abstract = uncertain_passes = agreements = 0
    started = time.monotonic()

    for idx, record in enumerate(rows, start=1):
        # No abstract means nothing to screen on. Route straight to the human
        # queue with a clear reason and spend zero model calls. Never let a
        # title-only record be excluded by the model.
        if not (record["abstract"] or "").strip():
            sdb.upsert_status(conn, record["id"], "queued", True, "no_abstract",
                              resolved_by="rule", is_refmine_target=False)
            queued += 1
            no_abstract += 1
            final = "queued"
        else:
            da = _screen_one_pass(conn, client, record, "A", prompts["A"], model_arg, counters)
            db_ = _screen_one_pass(conn, client, record, "B", prompts["B"], model_arg, counters)
            uncertain_passes += (da.decision == "uncertain") + (db_.decision == "uncertain")
            if agreement(da, db_):
                agreements += 1
            agg = aggregate(da, db_)
            sdb.upsert_status(
                conn, record["id"], agg.final, agg.routed_to_queue, agg.queue_reason,
                resolved_by="model", is_refmine_target=agg.is_refmine_target,
            )
            final = agg.final
            if final == "include":
                inc += 1
            elif final == "exclude":
                exc += 1
            else:
                queued += 1

        if on_progress is not None:
            on_progress({
                "index": idx, "total": total, "record_id": record["id"],
                "final": final, "elapsed": time.monotonic() - started,
                "llm_calls": counters["llm_calls"], "cached": counters["cached"],
            })

    return RunReport(
        screened=total, include=inc, exclude=exc, queued=queued,
        no_abstract=no_abstract, uncertain_passes=uncertain_passes,
        agreements=agreements, llm_calls=counters["llm_calls"],
        cached=counters["cached"],
    )


def _fmt_eta(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:d}:{s:02d}"


def _make_progress_printer(every: int) -> Callable[[dict], None]:
    def printer(ev: dict) -> None:
        idx, total = ev["index"], ev["total"]
        if every > 1 and idx % every != 0 and idx != total:
            return
        elapsed = ev["elapsed"]
        rate = idx / elapsed if elapsed > 0 else 0.0
        eta = (total - idx) / rate if rate > 0 else 0.0
        print(f"[{idx:>4}/{total}] {ev['final']:8s} "
              f"calls={ev['llm_calls']} cached={ev['cached']} "
              f"{rate:.1f}/s eta {_fmt_eta(eta)}  {ev['record_id']}",
              flush=True)
    return printer


def _build_client(model: Optional[str]):
    """Default production client: local Claude Code. Never a hosted API."""
    from llm.claude_code import ClaudeCodeClient
    return ClaudeCodeClient(default_model=model)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Two-pass title/abstract screening.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--random", action="store_true",
                    help="sample records at random rather than in id order")
    ap.add_argument("--model", default=None,
                    help="model passed to the local claude CLI (e.g. sonnet, opus)")
    ap.add_argument("--progress-every", type=int, default=1,
                    help="print a progress line every N records (default 1)")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-record progress lines")
    args = ap.parse_args(argv)

    conn = sdb.connect(args.db)
    client = _build_client(args.model)
    progress = None if args.quiet else _make_progress_printer(args.progress_every)
    report = screen_records(conn, client, limit=args.limit,
                            random_sample=args.random, model_arg=args.model,
                            on_progress=progress)
    rate = (report.agreements / report.screened) if report.screened else 0.0
    print(f"screened          {report.screened}")
    print(f"  include         {report.include}")
    print(f"  exclude         {report.exclude}")
    print(f"  queued (human)  {report.queued}")
    print(f"    of which no-abstract  {report.no_abstract}")
    print(f"inter-pass agree  {report.agreements}/{report.screened} ({rate:.0%})")
    print(f"llm calls         {report.llm_calls}  (cached passes: {report.cached})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
