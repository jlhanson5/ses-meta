# Screening criteria (title/abstract stage)

Version: v1
Scope: title and abstract only. Full-text screening is a later step. Judge only
from the text provided. If the abstract does not state something, do not infer
it. When the rules below do not cleanly resolve a record, return `uncertain`.

## The one rule everything reduces to

INCLUDE a record if the study reports a quantitative association between a
socioeconomic status / poverty indicator and hippocampal or amygdala volume,
measured in vivo in humans.

All criteria below operationalize that sentence.

## INCLUDE

A record is includable when all four hold, as stated in the abstract:

1. Humans, in vivo. Living human participants imaged in vivo.
2. SES/poverty exposure. At least one socioeconomic indicator is measured:
   income, income-to-needs, parental or own education, occupation or
   occupational prestige, a composite SES index (Hollingshead, Barratt),
   subjective social status, area-level deprivation (ADI, IMD, Townsend),
   poverty-threshold status, material hardship, or public-assistance receipt.
3. Volume outcome. Hippocampal volume and/or amygdala volume from structural
   MRI (automated segmentation or manual tracing). Subfield/subnucleus volumes
   count as a volume outcome.
4. Reported association. The paper reports, or gives enough to compute, a
   quantitative association between the SES indicator and the volume (for
   example a correlation, regression coefficient, group contrast, or effect
   size with variance). A number connecting the two must be present or derivable.

## EXCLUDE

Any one of these excludes the record:

- Animal study. Non-human subjects.
- Review or meta-analysis. Narrative review, systematic review, or prior
  meta-analysis. STORE these anyway: they are reference-mining targets. Tag
  `review_or_meta`.
- Case report. Single-case or small case series with no group analysis.
- No volume outcome. The only brain measures are non-volumetric (cortical
  thickness, surface area, DTI/white-matter, functional MRI, connectivity,
  perfusion) and no hippocampal or amygdala volume is reported.
- SES as nuisance only. SES appears solely as a control/covariate with no
  reported SES-to-volume association. Adjusting for SES is not the same as
  estimating its association.
- Under-powered. Analytic sample below N = 20.

Tag the governing criterion on every exclude (for example `animal`,
`review_or_meta`, `case_report`, `no_volume_outcome`, `ses_nuisance_only`,
`sample_lt_20`).

## UNCERTAIN

Return `uncertain`, never a guess, when the abstract does not resolve inclusion:

- Cannot tell whether a volume outcome was measured (for example "subcortical
  structures" with no specifics).
- Cannot tell whether an SES-to-volume association was reported versus SES only
  adjusted for.
- Cannot tell the sample size, or it is not stated and could plausibly be under
  20.
- Conference abstract or truncated text too thin to judge.
- Any other case the rules above do not cleanly resolve.

## Notes that keep the project honest

- Maltreatment, institutional rearing, general adverse-childhood-experience
  scores, and trauma exposure are adjacent constructs, not SES. They do not
  satisfy criterion 2 on their own. Include only if a separable SES indicator is
  also measured and related to volume.
- "Subcortical volume" that does not name hippocampus or amygdala is
  `uncertain` at abstract stage, not an automatic include.
- Adjacent outcomes (thickness, function, connectivity) alongside a hippocampal
  or amygdala volume still include; the volume is what qualifies.
