"""
Task C follow-up: quantify the $ impact of the agent's committed (non-keep, non-escalate)
decisions using the same settled-follow-up-window methodology as validate_thresholds.py and
Task A's impact_estimate.py -- and, for the subset with a matched real historical action, compare
the agent's implied $ impact against what the real action implied, using the SAME observed
follow-up ROI for both. This is a single-world approximation, stated explicitly: it assumes the
realized ROI path over the follow-up window would have been roughly the same regardless of which
action was taken, so it isolates "was this decision's direction and size aligned with what
actually happened next," not a true two-world causal counterfactual. Same limitation Task A's
impact_estimate.py already carries, applied consistently here.

Scope, and why: only scale_up/scale_down/pause decisions carry a real $ impact under this method
-- `keep` is a no-op by definition (its counterfactual IS the baseline, so its impact is $0 by
construction, not omitted data) and `escalate` defers to a human with no committed number to
evaluate. Restricted to decisions on 2026-06-10/06-11 (the only dates with real follow-up days in
this snapshot -- see validate_thresholds.py; 06-12 decisions have none and are excluded, not
glossed over).
"""
import json
from datetime import date
from db import get_connection
from context_compressor import build_context
from validate_thresholds import get_followup_avg_roi, FOLLOWUP_DATES


def get_real_budget_deltas(con):
    """(adset_id, date) -> (old_budget, new_budget) for the LAST real rule/buyer action that day."""
    real = {}
    rule_rows = con.execute("""
        SELECT adset_id, action_date, action_time, old_budget, new_budget
        FROM rule_exec
        WHERE response = 'SUCCESS' AND action_date IN (DATE '2026-06-10', DATE '2026-06-11')
        ORDER BY action_time
    """).fetchall()
    for adset_id, d, t, old_b, new_b in rule_rows:
        real[(adset_id, str(d))] = (old_b, new_b)
    buyer_rows = con.execute("""
        SELECT adset_id, action_time::DATE AS d, action_time, old_budget, new_budget
        FROM buyer
        WHERE adset_id IS NOT NULL AND adset_id != ''
          AND action_time::DATE IN (DATE '2026-06-10', DATE '2026-06-11')
        ORDER BY action_time
    """).fetchall()
    for adset_id, d, t, old_b, new_b in buyer_rows:
        real[(adset_id, str(d))] = (old_b, new_b)
    return real


def main():
    con = get_connection()
    decisions = [json.loads(l) for l in open("../supporting/out/decisions.jsonl")]
    real_deltas = get_real_budget_deltas(con)

    eligible = [
        d for d in decisions
        if d["llm_called"] and d["action"] in ("scale_up", "scale_down", "pause")
        and d["decision_date"] in FOLLOWUP_DATES
    ]
    print(f"Committed scale_up/scale_down/pause decisions on 06-10/06-11: {len(eligible)}")

    rows = []
    for d in eligible:
        followup = get_followup_avg_roi(con, d["adset_id"], d["decision_date"])
        if followup is None:
            continue
        ctx = build_context(con, d["adset_id"], date.fromisoformat(d["decision_date"]))
        current_budget = ctx["current_budget"]
        new_effective = 0.0 if d["action"] == "pause" else d["amount"]
        our_impact = (new_effective - current_budget) * followup

        real_impact = None
        real_action_label = None
        key = (d["adset_id"], d["decision_date"])
        if key in real_deltas:
            old_b, new_b = real_deltas[key]
            if old_b is not None and new_b is not None:
                real_impact = (new_b - old_b) * followup
                real_action_label = f"{old_b}->{new_b}"

        rows.append({
            "adset_id": d["adset_id"], "date": d["decision_date"], "action": d["action"],
            "current_budget": current_budget, "new_effective": new_effective,
            "followup_avg_roi": followup, "our_impact": our_impact,
            "real_impact": real_impact, "real_delta": real_action_label,
        })

    print(f"Decisions with usable settled follow-up data: {len(rows)}")
    print()

    total_our = sum(r["our_impact"] for r in rows)
    print(f"Total estimated $ impact of our committed decisions (n={len(rows)}): ${total_our:,.2f}")
    by_action = {}
    for r in rows:
        by_action.setdefault(r["action"], []).append(r["our_impact"])
    for a, vals in by_action.items():
        print(f"  {a}: n={len(vals)}, sum=${sum(vals):,.2f}, avg=${sum(vals)/len(vals):,.2f}")

    print()
    head_to_head = [r for r in rows if r["real_impact"] is not None]
    print(f"Head-to-head vs. the REAL action on the same adset-day (same follow-up ROI both sides): n={len(head_to_head)}")
    if head_to_head:
        our_sum = sum(r["our_impact"] for r in head_to_head)
        real_sum = sum(r["real_impact"] for r in head_to_head)
        we_better = sum(1 for r in head_to_head if r["our_impact"] > r["real_impact"])
        print(f"  Our total: ${our_sum:,.2f}   Real total: ${real_sum:,.2f}   Delta (ours - real): ${our_sum - real_sum:,.2f}")
        print(f"  We beat the real action's implied impact in {we_better}/{len(head_to_head)} cases")
        print()
        for r in sorted(head_to_head, key=lambda r: r["our_impact"] - r["real_impact"]):
            print(f"  {r['adset_id']} {r['date']}: WE={r['action']} (${r['our_impact']:+.2f}) "
                  f"vs REAL {r['real_delta']} (${r['real_impact']:+.2f})  [followup_roi={r['followup_avg_roi']:.3f}]")

    with open("../supporting/out/money_impact.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print("\nFull detail written to out/money_impact.jsonl")


if __name__ == "__main__":
    main()
