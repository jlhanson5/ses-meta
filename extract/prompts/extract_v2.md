You extract effect sizes for a meta-analysis of the association between
socioeconomic status (SES) / poverty and hippocampal or amygdala volume. You are
given the full text of one study, split into locatable segments. Each segment
starts with its locator in double brackets, for example [[p.4]] or [[Table 2]].

Report only values printed in the text, tables, or figure captions. Do not
compute, infer, or estimate. Do not convert or standardize effect sizes. If a
value is absent, return null.

Extract ONE ROW PER EFFECT, not per study. A study that reports hippocampus and
amygdala, or left and right, or more than one SES measure, yields multiple rows.

For EVERY numeric field you report (n, mean_age, pct_female, effect_value,
se_or_ci, p_value), you MUST supply, in the provenance object, the locator it
came from and a verbatim quote (25 words or fewer) containing that number. A
numeric value you cannot tie to a locator and a quote MUST be null. Never guess.

Age is a moderator in this meta-analysis, so mean_age and age_range are required
with provenance, exactly like the effect size. Demographics (mean_age,
age_range, pct_female) are often reported once for the whole sample, in the
Methods or a sample-characteristics table, not in the results row the effect
came from. When that is the case, attach the sample-level value to EVERY effect
row, citing that Methods/table locator and quote for it. The locator for a
demographic field may differ from the locator for the effect value; that is
expected. Only leave a demographic field null if the paper does not state it
anywhere.

Return ONLY a single JSON object, no prose, no code fence:
{
  "effects": [
    {
      "cohort_name": "<verbatim sample/cohort name or null>",
      "n": <number or null>,
      "mean_age": <number or null>,
      "age_range": "<as reported or null>",
      "pct_female": <number or null>,
      "sample_type": "community|clinical|high-risk|null",
      "ses_construct": "income|income-to-needs|parental education|composite|neighborhood|subjective|material deprivation|null",
      "ses_timing": "concurrent|early childhood|retrospective|null",
      "roi": "hippocampus|amygdala",
      "hemisphere": "left|right|bilateral|mean|null",
      "volume_pipeline": "<FreeSurfer version / FSL FIRST / VBM / manual tracing or null>",
      "icv_adjustment": "none|covariate|proportion|residual|null",
      "covariates": ["<covariate>", "..."],
      "effect_type": "r|partial r|beta|d|t|F|raw group means|null",
      "effect_value": <number or null>,
      "se_or_ci": "<standard error or CI as reported, or null>",
      "p_value": <number or null>,
      "direction_coded_positive_means_higher_SES_larger_volume": <true|false|null>,
      "page_number": "<locator for the effect_value, e.g. p.5 or Table 2>",
      "verbatim_quote": "<=25 words containing the effect_value>",
      "extraction_confidence": <0.0-1.0>,
      "provenance": {
        "n": {"page": "<locator>", "quote": "<=25 words>"},
        "mean_age": {"page": "<locator, may be Methods/Table 1>", "quote": "<=25 words>"},
        "age_range": {"page": "<locator>", "quote": "<=25 words>"},
        "pct_female": {"page": "<locator>", "quote": "<=25 words>"},
        "effect_value": {"page": "<locator>", "quote": "<=25 words>"},
        "p_value": {"page": "<locator>", "quote": "<=25 words>"}
      }
    }
  ]
}

If the study reports no usable SES-to-volume effect, return {"effects": []}.

STUDY FULL TEXT:
{fulltext}
