"""
Task C, revisited: checks whether the fixed confidence thresholds (0.5/0.7 caps, 0.7 main tier,
0.55 graduated tier) are actually supported by real settled data -- not "we don't have any data"
(an earlier, imprecise claim -- see DECISIONS.md), but a real, bounded check using what exists:

- Decisions on 2026-06-10 have 2 real follow-up days (06-11, 06-12) already in the dataset.
- Decisions on 2026-06-11 have 1 real follow-up day (06-12).
- Decisions on 2026-06-12 have ZERO follow-up days -- genuinely excluded from this check, not
  glossed over.

Correctness rule per action (stated as an explicit, simplifying assumption, not a hidden one):
  scale_up   -> correct if the adset's average ROI over the follow-up window stayed >= 0
  scale_down -> correct if it stayed < 0 (the decline that justified the cut was real)
  pause      -> correct if it stayed < 0 (the severity that justified stopping was real)
  keep       -> correct if it didn't swing to the opposite sign of today's settled ROI
  escalate   -> not scored for correctness (no directional claim to check) -- reported separately
                as "how did it resolve" for context only.

This is necessarily a simplification of "was this a good decision" (it checks direction, not
magnitude or realized profit) -- stated explicitly per the same standard applied to every other
assumption in this project.
"""
import json
from db import get_connection

FOLLOWUP_DATES = {
    "2026-06-10": ["2026-06-11", "2026-06-12"],
    "2026-06-11": ["2026-06-12"],
}


def get_followup_avg_roi(con, adset_id, decision_date):
    dates = FOLLOWUP_DATES.get(decision_date)
    if not dates:
        return None
    rows = con.execute(
        "SELECT roi, spend FROM perf WHERE adset_id = ? AND date::VARCHAR = ANY(?)",
        [adset_id, dates],
    ).fetchall()
    real_rows = [r for r in rows if r[0] is not None and r[1] and r[1] > 0]
    if not real_rows:
        return None
    return sum(r[0] for r in real_rows) / len(real_rows)


def is_correct(action, decision_roi_sign_hint, followup_avg_roi):
    if action == "scale_up":
        return followup_avg_roi >= 0
    if action in ("scale_down", "pause"):
        return followup_avg_roi < 0
    if action == "keep":
        today_positive = decision_roi_sign_hint >= 0
        followup_positive = followup_avg_roi >= 0
        return today_positive == followup_positive
    return None


def main():
    con = get_connection()
    decisions = [json.loads(l) for l in open("../out/decisions.jsonl")]
    scoreable = [d for d in decisions if d["decision_date"] in FOLLOWUP_DATES and d["action"] != "escalate" and d["llm_called"]]

    print(f"Scoreable LLM decisions (06-10/06-11 only, non-escalate): {len(scoreable)}")
    print(f"(06-12 decisions excluded -- genuinely no follow-up data exists for them)")
    print()

    results = []
    for d in scoreable:
        followup = get_followup_avg_roi(con, d["adset_id"], d["decision_date"])
        if followup is None:
            continue
        today_roi_hint = 0  # not stored directly on the decision; keep sign-agnostic for 'keep'
        # for 'keep' we need today's settled ROI -- pull it directly
        if d["action"] == "keep":
            row = con.execute("SELECT roi FROM perf WHERE adset_id=? AND date::VARCHAR=?", [d["adset_id"], d["decision_date"]]).fetchone()
            today_roi_hint = row[0] if row and row[0] is not None else 0
        correct = is_correct(d["action"], today_roi_hint, followup)
        results.append({"decision": d, "followup_avg_roi": followup, "correct": correct})

    print(f"Decisions with real follow-up data available: {len(results)}")
    print()

    # the actual question: does confidence predict correctness? bucket by confidence range.
    buckets = [(0.0, 0.5), (0.5, 0.55), (0.55, 0.7), (0.7, 1.01)]
    print("Confidence band -> directional accuracy (this is what the thresholds should track):")
    for lo, hi in buckets:
        bucket = [r for r in results if lo <= r["decision"]["confidence"] < hi]
        if not bucket:
            print(f"  [{lo:.2f}-{hi:.2f}): no decisions")
            continue
        acc = sum(1 for r in bucket if r["correct"]) / len(bucket)
        print(f"  [{lo:.2f}-{hi:.2f}): n={len(bucket):3d}  accuracy={acc:.0%}")

    print()
    print("By action type:")
    for action in ["scale_up", "scale_down", "pause", "keep"]:
        bucket = [r for r in results if r["decision"]["action"] == action]
        if not bucket:
            print(f"  {action}: n=0")
            continue
        acc = sum(1 for r in bucket if r["correct"]) / len(bucket)
        print(f"  {action}: n={len(bucket)}, accuracy={acc:.0%}")

    with open("../out/threshold_validation.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps({
                "adset_id": r["decision"]["adset_id"], "decision_date": r["decision"]["decision_date"],
                "action": r["decision"]["action"], "confidence": r["decision"]["confidence"],
                "followup_avg_roi": r["followup_avg_roi"], "correct": r["correct"],
            }) + "\n")
    print("\nFull scored set written to out/threshold_validation.jsonl")


if __name__ == "__main__":
    main()
