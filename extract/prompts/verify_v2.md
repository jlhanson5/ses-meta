You are verifying numbers a first pass extracted for a meta-analysis. You are
given a list of claims. Each claim has a field name, the value that was
extracted, the locator it was said to come from, and the verbatim quote the
first pass supplied. Judge ONLY from the quote.

For each claim, decide:
  - "confirm" if the quote contains the value. Match on the NUMBERS in the
    value, not their formatting. Ignore punctuation, spacing, dash style
    (- vs en/em dash), connectives ("to", "-", "and", "or"), and leading labels
    ("P", "=", "95% CI,", "beta =", "aged", "years"). The rule is simple: a
    value is confirmed when every number it contains appears in the quote.
      * one number: "0.06" is confirmed by "beta = 0.06" or "b = .06".
      * a p-value: "< .001" is confirmed by "P < .001" or "<.001".
      * a range: "9 to 10" is confirmed by "aged 9 and 10 years"; "8-12" by
        "8 to 12 years" (both endpoints present).
      * a CI: "0.05 to 0.08" is confirmed by "95% CI, 0.05 to 0.08".
  - "dispute" if a number in the value is missing from the quote, or the quote
    shows a different number.

Do not use outside knowledge. Do not compute or infer. If the quote is empty or
a number in the value is genuinely absent or different, dispute it.

Return ONLY a single JSON object, no prose, no code fence:
{
  "verdicts": [
    {"index": <claim index>, "verdict": "confirm|dispute", "confidence": 0.0-1.0,
     "note": "<=15 words"}
  ]
}

CLAIMS:
{claims}
