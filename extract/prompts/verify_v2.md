You are verifying numbers a first pass extracted for a meta-analysis. You are
given a list of claims. Each claim has a field name, the value that was
extracted, the locator it was said to come from, and the verbatim quote the
first pass supplied. Judge ONLY from the quote.

For each claim, decide:
  - "confirm" if the quote contains that value for that field. Match on the
    NUMBER itself, not its formatting. Ignore differences in punctuation,
    spacing, dash style (- vs en/em dash), leading labels ("P", "=", "95% CI,",
    "beta ="), and how a p-value is written ("< .001", "<.001", "P < .001" all
    match the value "< .001"). A value like "< .001" is confirmed by a quote
    that shows "P < .001".
  - "dispute" if the quote does not contain the value, shows a different number,
    or does not support that field.

Do not use outside knowledge. Do not compute or infer. If the quote is empty or
the number is genuinely absent or different, dispute it.

Return ONLY a single JSON object, no prose, no code fence:
{
  "verdicts": [
    {"index": <claim index>, "verdict": "confirm|dispute", "confidence": 0.0-1.0,
     "note": "<=15 words"}
  ]
}

CLAIMS:
{claims}
