"""
Task C: the deterministic path for adsets below the minimum data floor -- no LLM call, per
ARCHITECTURE.md sec2 ("below the floor, the only autonomous output is keep or escalate") and the
reasoning in DECISIONS.md (this isn't primarily a cost-saving measure -- an adset this early
doesn't have enough information for any reasoner, human or AI, to produce a trustworthy judgment,
so deciding it in code removes that risk by construction rather than hoping a prompted model
self-regulates).

REVISED after the first full run: split by stakes, not just age. The original version forced
`escalate` for every adset under 2 settled days regardless of how much was actually riding on it
-- this alone accounted for 1,089 of the 1,621 deterministic decisions (67%) in the first run,
the single biggest contributor to a system that only decided anything at all 29.6% of the time.
A 1-day-old adset with $0.50 spent has nothing real at stake; treating it identically to one that
already has real budget behind it was the actual bug, not the floor concept itself.

Three sub-cases now:
- Brand new AND real stakes already committed (age < 2 days, spend >= the $5 floor): escalate.
  This is the genuine R04/buyer-mistake shape -- thin history *and* real money on the line.
- Brand new but negligible stakes (age < 2 days, spend < $5): keep. Nothing to protect against
  either direction yet -- decisive and low-risk, not a guess.
- Established but persistently tiny (age >= 2 days, spend < $5): keep, as before.

REVISED AGAIN after the v2 comparison run: `keep` carried a fixed confidence of 0.3, which made
these 1,605 decisions (78% of the whole 2,064-decision run) permanently ineligible for the
autonomous tier even at the lenient 0.55 graduated bar (guardrail_check.py) -- the single reason
system-wide autonomous was only 2.9% despite the LLM-scored path already clearing that bar 50% of
the time it committed to an action. 0.3 was measuring the wrong thing: confidence in a *market
prediction* ("is this the right call given how the adset will perform"), when `keep` here isn't a
prediction at all -- it's a defined, auditable policy applied specifically when age/stakes are too
low for any prediction to mean anything. The agent is 100% certain of *why* it's doing this; that
certainty was never reflected in the number. DETERMINISTIC_KEEP_CONFIDENCE is deliberately set
above the 0.55 graduated bar but below the 0.7 main bar -- clears the low-consequence tier, still
short of "high-stakes autonomous," since a no-op is genuinely lower-risk than a budget change.
`escalate` (the real-stakes-but-thin-history branch) is untouched -- 0.1 there still correctly
means "we don't know, and it matters."
"""
from context_compressor import MIN_DATA_FLOOR_DAYS, MIN_DATA_FLOOR_SPEND

DETERMINISTIC_KEEP_CONFIDENCE = 0.65


def deterministic_decision(context: dict) -> dict:
    age_days = context["age_days"]
    total_spend = sum(d["spend"] for d in context["trailing_daily"] if d["spend"] is not None)
    is_new = age_days is None or age_days < MIN_DATA_FLOOR_DAYS
    has_real_stakes = total_spend >= MIN_DATA_FLOOR_SPEND

    if is_new and has_real_stakes:
        action, confidence, reasoning = (
            "escalate", 0.1,
            f"Adset has {age_days if age_days is not None else 0} settled day(s) of history "
            f"(minimum {MIN_DATA_FLOOR_DAYS} required), AND ${total_spend:.2f} in real spend "
            f"already committed -- thin history with genuine stakes. Deferring to human review "
            f"rather than guess from a single day's figures.",
        )
    else:
        reason = (
            f"only {age_days if age_days is not None else 0} settled day(s) of history, "
            f"but negligible spend so far (${total_spend:.2f})" if is_new else
            f"{age_days} settled days but only ${total_spend:.2f} total trailing spend, below "
            f"the ${MIN_DATA_FLOOR_SPEND:.0f} minimum-data floor"
        )
        action, confidence, reasoning = (
            "keep", DETERMINISTIC_KEEP_CONFIDENCE,
            f"Adset has {reason}. Too small a sample to assess a real trend, and negligible "
            f"stakes either way -- defaulting to no change is both the safe and the decisive "
            f"answer here, not a guess.",
        )

    return {
        "adset_id": context["adset_id"],
        "decision_date": context["decision_date"],
        "action": action,
        "amount": None,
        "confidence": confidence,
        "raw_model_confidence": None,
        "confidence_caps_applied": [],
        "reasoning": reasoning,
        "data_quality_flags": context["data_quality_flags"],
        "expected_profit_impact": None,
        "escalated_to_sonnet": False,
        "model_used": "none (deterministic, below minimum data floor)",
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "llm_called": False,
    }
