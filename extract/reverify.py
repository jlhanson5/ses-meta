"""Re-run verification on already-extracted effects.

Verification verdicts are computed at extraction time, but the per-field
provenance is persisted, so a better verifier can be applied to stored rows
WITHOUT paying to re-extract. This reads each effect back, rebuilds it with its
provenance, re-runs the verification pass, and updates verified / needs_review /
review_reason in place. It never changes an extracted value, only its verdict.

Use it after tuning the verification prompt:

    python -m extract.reverify [--db data/db/records.db] [--model opus]

Rows extracted before provenance was persisted have no per-field quotes to
re-check; those fall back to the row's single verbatim_quote and may still
dispute. A clean re-extract is the way to give them full provenance.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from llm.service import LLMClient

from . import db as edb
from .prompts import VERIFY, load_prompt
from .run import DEFAULT_DB, _build_client
from .schema import effect_from_row
from .verify import verify_effect


def reverify_all(conn, client: LLMClient, *, model: Optional[str] = None) -> dict:
    verify_prompt = load_prompt(VERIFY)
    rows = edb.all_effects(conn)
    changed = still_flagged = 0
    for row in rows:
        if row["human_reviewed"]:
            continue                        # human decisions are final
        eff = effect_from_row(row)
        verdict = verify_effect(client, verify_prompt, eff, model=model)
        was = bool(row["needs_review"])
        edb.set_verification(
            conn, row["effect_key"],
            verified="confirmed" if verdict.confirmed else "disputed",
            needs_review=verdict.needs_review, review_reason=verdict.reason)
        if verdict.needs_review != was:
            changed += 1
        if verdict.needs_review:
            still_flagged += 1
    return {"rows": len(rows), "changed": changed, "still_flagged": still_flagged}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Re-verify stored effects.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--model", default=None)
    args = ap.parse_args(argv)
    conn = edb.connect(args.db)
    client = _build_client(args.model)
    result = reverify_all(conn, client, model=args.model)
    from .review_queue import build_queue
    qn = build_queue(conn)
    print(f"re-verified {result['rows']} rows; verdicts changed {result['changed']}; "
          f"still flagged {result['still_flagged']}")
    print(f"review queue rebuilt: {qn} rows -> extract/review_queue.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
