You are verifying numbers a first pass extracted for a meta-analysis. You are
given a list of claims. Each claim has a field name, the value that was
extracted, the locator it was said to come from, and the verbatim quote the
first pass supplied. Judge ONLY from the quote.

For each claim, decide:
  - "confirm" if the quote plainly contains that value for that field.
  - "dispute" if the quote does not contain the value, contains a different
    value, or does not support that field.

Do not use outside knowledge. Do not compute or infer. If the quote is empty or
does not contain the number, dispute it.

Return ONLY a single JSON object, no prose, no code fence:
{
  "verdicts": [
    {"index": <claim index>, "verdict": "confirm|dispute", "confidence": 0.0-1.0,
     "note": "<=15 words"}
  ]
}

CLAIMS:
{claims}
