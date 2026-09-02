You are screening a study for a meta-analysis on the association between
socioeconomic status (SES) / poverty and hippocampal or amygdala volume in
humans. This is pass A. Your framing: identify whether this study qualifies to
be included.

Judge ONLY from the title and abstract provided. If the abstract does not state
it, do not infer it. Return "uncertain" rather than guessing.

INCLUDE only if all of these are stated:
1. Living humans imaged in vivo.
2. At least one SES/poverty indicator is measured (income, income-to-needs,
   education, occupation, a composite SES index, subjective social status,
   area-level deprivation, poverty status, material hardship, or assistance
   receipt).
3. Hippocampal and/or amygdala VOLUME from structural MRI (subfield volumes
   count).
4. A quantitative association between the SES indicator and that volume is
   reported or derivable (correlation, regression, group contrast, effect size).

EXCLUDE if any of these is true (tag the reason):
- animal study -> "animal"
- review or meta-analysis -> "review_or_meta"  (still useful downstream)
- single case report -> "case_report"
- only non-volume brain measures (thickness, surface area, DTI, fMRI,
  connectivity) with no hippocampal/amygdala volume -> "no_volume_outcome"
- SES used only as a control covariate with no reported SES-to-volume
  association -> "ses_nuisance_only"
- analytic sample below N=20 -> "sample_lt_20"

UNCERTAIN when the abstract does not resolve it: cannot tell if a volume outcome
was measured, cannot tell if an SES-to-volume association was reported versus
merely adjusted for, sample size not stated and possibly under 20, or text too
thin to judge. Maltreatment / ACEs / trauma alone are NOT SES.

Return ONLY a single JSON object, no prose, no code fence:
{"decision": "include|exclude|uncertain", "criteria_hit": ["..."], "reason": "<=25 words", "confidence": 0.0-1.0}

TITLE:
{title}

ABSTRACT:
{abstract}
