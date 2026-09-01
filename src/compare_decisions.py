"""
Task C5: compare the agent's 2,064 decisions against what the auto-rules and human buyers
actually did on the same adset-days. Builds an agreement matrix and surfaces the interesting
disagreement cases with evidence, per the brief's explicit ask: "where do you disagree with the
humans -- and who do you think was right?"

Ground truth for "what actually happened" on a given adset-day: any SUCCESS'd rule_exec row or
any buyer row dated that day, on that adset. Mapped to the same action vocabulary as the agent
(scale_up/scale_down/keep/pause/escalate) so they're comparable -- "no action recorded" maps to
"keep" (the human/rule system's default when nothing fires is to leave it alone, same as ours).
"""
import json
from db import get_connection


def classify_real_action(old_budget, new_budget, event_type_or_rule_action):
    """Maps a real historical action to our vocabulary."""
    action_text = (event_type_or_rule_action or "").lower()
    if "off" in action_text or "pause" in action_text:
        return "pause"
    if "on" in action_text and "turn" in action_text:
        return "scale_up"  # reactivation -- closest analogue
    if old_budget is not None and new_budget is not None and old_budget > 0:
        if new_budget > old_budget * 1.02:
            return "scale_up"
        elif new_budget < old_budget * 0.98:
            return "scale_down"
    return "keep"


def get_real_actions(con):
    """Returns {(adset_id, date_str): classified_action} for the SUCCESS'd rule actions and
    buyer actions on the 3 target dates, keyed to the same adset-day granularity as our
    decisions. If an adset has multiple real actions on the same day, the LAST one wins (most
    representative of where things ended up that day)."""
    real = {}

    rule_rows = con.execute("""
        SELECT adset_id, action_date, action_time, action_name, old_budget, new_budget
        FROM rule_exec
        WHERE response = 'SUCCESS' AND action_date IN (DATE '2026-06-10', DATE '2026-06-11', DATE '2026-06-12')
        ORDER BY action_time
    """).fetchall()
    for adset_id, action_date, action_time, action_name, old_b, new_b in rule_rows:
        key = (adset_id, str(action_date))
        real[key] = {"source": "rule", "action": classify_real_action(old_b, new_b, action_name),
                     "detail": f"{action_name} ({old_b}->{new_b})", "time": str(action_time)}

    buyer_rows = con.execute("""
        SELECT adset_id, action_time::DATE AS d, action_time, event_type, old_budget, new_budget
        FROM buyer
        WHERE adset_id IS NOT NULL AND adset_id != ''
          AND action_time::DATE IN (DATE '2026-06-10', DATE '2026-06-11', DATE '2026-06-12')
        ORDER BY action_time
    """).fetchall()
    for adset_id, d, action_time, event_type, old_b, new_b in buyer_rows:
        key = (adset_id, str(d))
        real[key] = {"source": "buyer", "action": classify_real_action(old_b, new_b, event_type),
                      "detail": f"{event_type} ({old_b}->{new_b})", "time": str(action_time)}

    return real


def main():
    con = get_connection()
    decisions = [json.loads(l) for l in open("../out/decisions.jsonl")]
    real_actions = get_real_actions(con)

    print(f"Real (rule/buyer) actions found on target adset-days: {len(real_actions)}")
    print(f"Our decisions: {len(decisions)}")

    matched = []
    for d in decisions:
        key = (d["adset_id"], d["decision_date"])
        if key in real_actions:
            matched.append((d, real_actions[key]))

    print(f"Adset-days where BOTH we and a human/rule took a recorded action: {len(matched)}")
    print()

    # agreement matrix
    matrix = {}
    for d, r in matched:
        matrix.setdefault(d["action"], {}).setdefault(r["action"], 0)
        matrix[d["action"]][r["action"]] += 1
    print("Agreement matrix (rows = our action, cols = real action):")
    actions = ["scale_up", "scale_down", "keep", "pause", "escalate"]
    print("            " + "".join(f"{a:>12}" for a in actions))
    for our_a in actions:
        row = matrix.get(our_a, {})
        print(f"{our_a:>12}" + "".join(f"{row.get(real_a, 0):>12}" for real_a in actions))

    agree = sum(1 for d, r in matched if d["action"] == r["action"])
    print(f"\nExact agreement: {agree}/{len(matched)} ({100*agree/len(matched):.0f}%)" if matched else "no overlap")

    # disagreement cases where we're confident (not escalate) and they differ meaningfully
    print("\n" + "=" * 80)
    print("DISAGREEMENT CASES (our confident action != their action):")
    print("=" * 80)
    disagreements = [(d, r) for d, r in matched if d["action"] != r["action"] and d["action"] != "escalate"]
    for d, r in disagreements:
        print(f"\n{d['adset_id']} {d['decision_date']}: WE={d['action']} (conf {d['confidence']:.2f}) "
              f"vs THEY={r['action']} via {r['source']} ({r['detail']}) at {r['time']}")
        print(f"  Our reasoning: {d['reasoning'][:200]}")

    with open("../out/comparison_matched.jsonl", "w") as f:
        for d, r in matched:
            f.write(json.dumps({"our_decision": d, "real_action": r}) + "\n")
    print(f"\nFull matched set written to out/comparison_matched.jsonl")


if __name__ == "__main__":
    main()
