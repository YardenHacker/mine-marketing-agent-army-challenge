"""
Task C: the Guardian's bounds-check layer (ARCHITECTURE.md sec2's decision logic), applied to
every decision AFTER the Analyst (or the deterministic path) has produced one -- layer 2 of the
three-layer "where hard limits actually live" design. This was missing entirely until a direct
question exposed the gap: the budget-step mechanism in llm_decision.py structurally caps
magnitude (layer 1), but nothing was enforcing cooldown, the unreconciled-action block, or
routing to an explicit autonomous/approval/forbidden tier (layer 2).

What's implemented here, and what's structurally not needed:
- FORBIDDEN: an unreconciled prior action on this adset (a prior rule/buyer action whose outcome
  isn't confirmed -- the exact R09 shape). Overrides whatever action was proposed to `escalate`.
- REQUIRES APPROVAL: below the applicable confidence threshold (see graduated tier below), OR a
  same-day-or-recent prior action exists (the cooldown proxy -- see note below).
- AUTONOMOUS: everything else.
- Budget-size-based forbidden/approval tiers (>50% / 20-50%) are NOT checked here because
  they're structurally unreachable: llm_decision.py's budget_step can never exceed +/-20% by
  construction (the tool schema doesn't offer larger steps), so there's nothing for this layer
  to catch on that axis. This is deliberate -- catching it upstream is stronger than checking it
  downstream -- not an oversight.

GRADUATED AUTONOMOUS TIER (added after the first full run found only 2.3% of all decisions were
both actionable and fully autonomous): a flat 0.7 bar for every action treats a $0-risk `keep`
and a small, capped +/-10% nudge identically to a full +/-20% swing or an outright `pause`. That's
not proportionate to actual risk. Lower-stakes actions get a lower bar:
- `keep`: nothing changes either way -- eligible at GRADUATED_THRESHOLD.
- `scale_up`/`scale_down` at the SMALL step (+/-10%, not +/-20%): a capped, reversible nudge --
  eligible at GRADUATED_THRESHOLD.
- Everything else (`pause`, the full +/-20% step): still requires MAIN_THRESHOLD (0.7) -- these
  carry more consequence and don't get the lower bar.
These two thresholds are still fixed constants, not validated against outcomes -- see
`validate_thresholds.py` for the first real check against this run's own settled data, and
RESULTS.md sec7 for the honest limits of what that validation can and can't confirm.

Cooldown adaptation for a backtest: ARCHITECTURE.md's live design is a 4-hour minimum between
automated actions, meaningful at a 30-minute cycle cadence. This backtest makes one decision per
adset per day, not per 30-minute cycle, so a literal 4-hour check doesn't map cleanly. The proxy
used here: if `recent_actions` (already computed by the context compressor) contains an action on
this adset dated the same day as decision_date, treat it as within cooldown -- a same-day prior
touch is the backtest-scale equivalent of "we just did something to this adset very recently."
"""


MAIN_THRESHOLD = 0.7
GRADUATED_THRESHOLD = 0.55


def _is_small_step(decision: dict, context: dict) -> bool:
    if decision["action"] == "keep":
        return True
    if decision["action"] in ("scale_up", "scale_down") and decision["amount"] is not None:
        current = context.get("current_budget") or 0
        if current > 0:
            step_fraction = abs(decision["amount"] / current - 1)
            return step_fraction <= 0.125  # +/-10% step, with a little float tolerance
    return False


def apply_guardrails(decision: dict, context: dict) -> dict:
    """Adds `tier` ("autonomous" | "requires_approval" | "forbidden") and `guardrail_reason` to
    a decision dict, mutating the action to "escalate" if forbidden. Does not touch confidence,
    amount, or reasoning otherwise -- this is a check layer, not a second judgment layer."""

    if "unreconciled_prior_action" in decision["data_quality_flags"]:
        decision["tier"] = "forbidden"
        decision["guardrail_reason"] = (
            "A prior action on this adset failed or was never confirmed to take effect "
            "(unreconciled_prior_action). No new automated action until that's reconciled -- "
            "this is the exact R09 failure shape from INVESTIGATION.md Case 1."
        )
        if decision["action"] != "escalate":
            decision["guardrail_reason"] += f" Overrode proposed action '{decision['action']}' to 'escalate'."
            decision["action"] = "escalate"
            decision["amount"] = None
        return decision

    same_day_prior_action = any(
        a["time"][:10] == decision["decision_date"] for a in context["recent_actions"]
    )
    if same_day_prior_action:
        decision["tier"] = "requires_approval"
        decision["guardrail_reason"] = (
            "A prior action on this adset is already dated the same day as this decision -- "
            "cooldown proxy for a backtest run at daily granularity (see module docstring). "
            "Routed to human approval rather than compounding a same-day change."
        )
        return decision

    threshold = GRADUATED_THRESHOLD if _is_small_step(decision, context) else MAIN_THRESHOLD
    if decision["confidence"] < threshold:
        decision["tier"] = "requires_approval"
        decision["guardrail_reason"] = (
            f"Confidence {decision['confidence']:.2f} is below the "
            f"{'graduated' if threshold == GRADUATED_THRESHOLD else 'main'} "
            f"{threshold:.2f} autonomous threshold for this action."
        )
        return decision

    decision["tier"] = "autonomous"
    decision["guardrail_reason"] = None
    return decision


if __name__ == "__main__":
    # sanity check against the two worked examples' actual shapes
    ctx_no_recent = {"recent_actions": [], "data_quality_flags": []}
    d1 = {"action": "scale_up", "amount": 113.5, "confidence": 0.62, "data_quality_flags": [], "decision_date": "2026-06-11"}
    print(apply_guardrails(dict(d1), ctx_no_recent))

    ctx_same_day = {"recent_actions": [{"time": "2026-06-11 10:46:34"}], "data_quality_flags": []}
    d2 = {"action": "escalate", "amount": None, "confidence": 0.15, "data_quality_flags": [], "decision_date": "2026-06-11"}
    print(apply_guardrails(dict(d2), ctx_same_day))

    ctx_unreconciled = {"recent_actions": [], "data_quality_flags": ["unreconciled_prior_action"]}
    d3 = {"action": "pause", "amount": None, "confidence": 0.8, "data_quality_flags": ["unreconciled_prior_action"], "decision_date": "2026-06-11"}
    print(apply_guardrails(dict(d3), ctx_unreconciled))
