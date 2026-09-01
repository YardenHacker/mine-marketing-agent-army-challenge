"""
Task C, C3: confidence must be earned, not asserted (ARCHITECTURE.md sec2). The model's
self-reported confidence is capped deterministically based on which data_quality_flags are
present -- this is enforced in code, never left to the model to self-regulate, for the same
reason the pre-filter exists: a prompted "be careful" instruction is not a guarantee, and we
already have one real, dated case in this data (the buyer's "3 straight green days" claim on a
1-day-old adset) of that exact failure.

Caps are per-flag, not identical across flags -- different flags represent different kinds and
severities of uncertainty:

- insufficient_history: the adset has almost no data at all (<2 settled days or <$5 total spend).
  This is the most severe case -- there is categorically not enough information for any
  reasoner to be confident. Cap: 0.5.
- near_dataset_edge (added per user direction after reviewing the compressor's output -- 2 of
  the 3 target decision dates trigger this for the MAJORITY of adsets, since both 06-11 and
  06-12 fall within the revenue-delay window found in INVESTIGATION.md sec1.4): the adset may
  have plenty of trailing history, but the most recent day's figures may still be under-settled.
  A real but generally less severe uncertainty than having almost no data -- distinct cap: 0.7.
- Multiple flags present: the tightest applicable cap wins (min), not a compounding penalty --
  compounding would need a justified interaction model this data doesn't support.

budget_scale_uncertain and cohort_too_small do NOT get a confidence cap here -- out of scope
for this specific fix (the user asked about near_dataset_edge specifically). Both already affect
the decision in other ways (current_budget is never sourced from the uncertain field; the
cohort field is just absent), so they don't need a second, separate confidence penalty on top.
"""

CONFIDENCE_CAPS = {
    "insufficient_history": 0.5,
    "near_dataset_edge": 0.7,
}


def apply_confidence_cap(raw_confidence: float, data_quality_flags: list[str]) -> tuple[float, list[str]]:
    """Returns (capped_confidence, which_caps_actually_bound). Never raises confidence, only
    lowers it. `applied` is only non-empty when the cap actually reduced the value -- a flag
    being present with a cap that the raw confidence was already under does not count as
    "applied"; reporting it as applied would misleadingly imply the cap changed something."""
    applicable = [CONFIDENCE_CAPS[f] for f in data_quality_flags if f in CONFIDENCE_CAPS]
    if not applicable:
        return raw_confidence, []
    tightest = min(applicable)
    if raw_confidence <= tightest:
        return raw_confidence, []  # cap present but didn't bind -- model was already appropriately humble
    applied = [f for f in data_quality_flags if f in CONFIDENCE_CAPS and CONFIDENCE_CAPS[f] == tightest]
    return tightest, applied


if __name__ == "__main__":
    cases = [
        (0.95, ["insufficient_history", "budget_scale_uncertain"]),
        (0.90, ["near_dataset_edge"]),
        (0.85, ["insufficient_history", "near_dataset_edge"]),
        (0.80, ["budget_scale_uncertain", "cohort_too_small"]),
        (0.60, []),
    ]
    for raw, flags in cases:
        capped, applied = apply_confidence_cap(raw, flags)
        print(f"raw={raw:.2f}  flags={flags}  -> capped={capped:.2f}  (cap applied: {applied or 'none'})")
