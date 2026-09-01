"""
Task C, C2: builds the compact, decision-ready context object per (adset_id, decision_date),
matching the shape designed in ARCHITECTURE.md §5 -- adapted in three places where the live
design assumed data this snapshot doesn't have. Each adaptation is a real, measured finding,
not a guess -- see DECISIONS.md for how each was checked before this was written.

Deviations from the ARCHITECTURE.md §5 design, and why:
1. No `today_partial` field. The live design assumes intraday snapshots (spend_so_far at a
   given time of day). Only 75 of 1,000 adsets in the full dataset ever have an intraday
   snapshot (via rule_exec); the other ~2,000 target adset-days only have one settled row per
   day. Fabricating a partial-day figure we don't have would be worse than omitting it.
2. `current_budget` is the adset's own trailing observed spend (not `meta.daily_budget`
   directly), because `meta.daily_budget` is at least 10x its own observed spend for 58.4% of
   the actual target set (measured directly against this run's population, not assumed from the
   smaller rule-touched subset in INVESTIGATION.md). `meta.daily_budget` is still surfaced,
   separately, as `declared_budget_meta`, flagged when inconsistent -- informational, never used
   for the budget-step math.
3. `cohort_percentile_roi` is only computed when the vertical+account cohort has >=5 members
   (22.2% of the real target set) -- most parsed "verticals" are unique to 1-2 adsets in this
   data (avg cohort size 1.6), so a percentile computed against a cohort of 1 isn't a real
   statistic. Below that size: null, flagged `cohort_too_small`.
"""
import re
from datetime import date, timedelta
from db import get_connection

DATASET_LAST_DATE = date(2026, 6, 12)
MIN_DATA_FLOOR_DAYS = 2
MIN_DATA_FLOOR_SPEND = 5.0
MIN_COHORT_SIZE = 5
BUDGET_SCALE_RATIO_FLAG = 10.0
NEAR_EDGE_DAYS = 1  # decision_date within this many days of the dataset's last date

VERTICAL_RE = re.compile(r"slg:([a-z0-9-]+?)-[0-9]+_", re.IGNORECASE)


def parse_vertical(adset_name):
    if not adset_name:
        return "unknown"
    m = VERTICAL_RE.search(adset_name)
    return m.group(1) if m else "unknown"


def build_context(con, adset_id: str, decision_date: date) -> dict:
    meta_row = con.execute(
        "SELECT account_name, adset_name, daily_budget FROM meta WHERE adset_id = ?", [adset_id]
    ).fetchone()
    account_name, adset_name, declared_budget = meta_row
    vertical = parse_vertical(adset_name)

    trailing = con.execute(
        """
        SELECT date, spend, revenue, roi, estimated_conversions, spend_day_no
        FROM perf
        WHERE adset_id = ? AND date <= ? AND date >= ?
        ORDER BY date
        """,
        [adset_id, decision_date, decision_date - timedelta(days=6)],
    ).fetchall()

    trailing_daily = [
        {
            "date": str(d),
            "spend": round(spend, 4) if spend is not None else None,
            "roi": round(roi, 4) if roi is not None else None,
            "conversions": round(conv, 2) if conv is not None else None,
            "settled": True,
        }
        for d, spend, revenue, roi, conv, spend_day_no in trailing
    ]

    age_days = trailing[-1][5] if trailing else None
    total_spend = sum(r[1] for r in trailing if r[1] is not None)
    # trailing observed daily spend rate -- the budget-step anchor (see module docstring #2)
    active_days = [r for r in trailing if r[1] and r[1] > 0]
    observed_daily_spend = (
        sum(r[1] for r in active_days) / len(active_days) if active_days else 0.0
    )

    data_quality_flags = []

    below_floor = (age_days is not None and age_days < MIN_DATA_FLOOR_DAYS) or total_spend < MIN_DATA_FLOOR_SPEND
    if below_floor:
        data_quality_flags.append("insufficient_history")

    budget_ratio = (declared_budget / observed_daily_spend) if observed_daily_spend > 0 else None
    budget_scale_uncertain = budget_ratio is not None and budget_ratio > BUDGET_SCALE_RATIO_FLAG
    if budget_scale_uncertain:
        data_quality_flags.append("budget_scale_uncertain")

    if (DATASET_LAST_DATE - decision_date).days <= NEAR_EDGE_DAYS:
        data_quality_flags.append("near_dataset_edge")

    # recent actions on THIS adset, both sources, labeled by outcome -- failed/no-op attempts
    # are informative (an unreconciled prior failure), not just successes.
    rule_actions = con.execute(
        """
        SELECT action_time, rule_id, action_name, old_budget, new_budget, response
        FROM rule_exec WHERE adset_id = ? AND action_date <= ?
        ORDER BY action_time DESC LIMIT 3
        """,
        [adset_id, decision_date],
    ).fetchall()
    buyer_actions = con.execute(
        """
        SELECT action_time, event_type, old_budget, new_budget, note
        FROM buyer WHERE adset_id = ? AND action_time::DATE <= ?
        ORDER BY action_time DESC LIMIT 3
        """,
        [adset_id, decision_date],
    ).fetchall()

    recent_actions = []
    unreconciled = False
    for t, rule_id, action_name, old_b, new_b, response in rule_actions:
        outcome = "success" if response == "SUCCESS" else ("no_op" if "No budget" in str(response) else "failed")
        if outcome == "failed":
            unreconciled = True
        recent_actions.append({
            "source": f"rule:{rule_id}", "time": str(t), "action": action_name,
            "change": f"{old_b} -> {new_b}" if old_b is not None else None, "outcome": outcome,
        })
    for t, event_type, old_b, new_b, note in buyer_actions:
        recent_actions.append({
            "source": "buyer", "time": str(t), "action": event_type,
            "change": f"{old_b} -> {new_b}" if old_b is not None else None,
            "note": note, "outcome": "success",
        })
    recent_actions.sort(key=lambda a: a["time"], reverse=True)
    recent_actions = recent_actions[:5]
    if unreconciled:
        data_quality_flags.append("unreconciled_prior_action")

    # cohort percentile -- only when the cohort is large enough to mean something (see #3)
    cohort_n_row = con.execute(
        """
        WITH cohort_adsets AS (
            SELECT m.adset_id
            FROM meta m
            WHERE m.account_name = ? AND regexp_extract(m.adset_name, 'slg:([a-z0-9-]+?)-[0-9]+_', 1) = ?
        )
        SELECT count(DISTINCT p.adset_id)
        FROM perf p
        WHERE p.adset_id IN (SELECT adset_id FROM cohort_adsets)
          AND p.date <= ? AND p.date >= ? AND p.roi IS NOT NULL
        """,
        [account_name, vertical, decision_date, decision_date - timedelta(days=6)],
    ).fetchone()
    cohort_n = cohort_n_row[0] if cohort_n_row else 0
    if cohort_n >= MIN_COHORT_SIZE:
        pct_row = con.execute(
            """
            WITH cohort_adsets AS (
                SELECT m.adset_id FROM meta m
                WHERE m.account_name = ? AND regexp_extract(m.adset_name, 'slg:([a-z0-9-]+?)-[0-9]+_', 1) = ?
            ),
            cohort_roi AS (
                SELECT p.adset_id, avg(p.roi) AS avg_roi FROM perf p
                WHERE p.adset_id IN (SELECT adset_id FROM cohort_adsets)
                  AND p.date <= ? AND p.date >= ? AND p.roi IS NOT NULL
                GROUP BY p.adset_id
            )
            SELECT round(100 * percent_rank() OVER (ORDER BY avg_roi))
            FROM cohort_roi ORDER BY (adset_id = ?) DESC LIMIT 1
            """,
            [account_name, vertical, decision_date, decision_date - timedelta(days=6), adset_id],
        ).fetchone()
        cohort_percentile_roi = int(pct_row[0]) if pct_row and pct_row[0] is not None else None
    else:
        cohort_percentile_roi = None
        data_quality_flags.append("cohort_too_small")

    return {
        "adset_id": adset_id,
        "decision_date": str(decision_date),
        "account": account_name,
        "vertical": vertical,
        "age_days": age_days,
        "trailing_daily": trailing_daily,
        "current_budget": round(observed_daily_spend, 4),
        "declared_budget_meta": declared_budget,
        "budget_scale_uncertain": budget_scale_uncertain,
        "recent_actions": recent_actions,
        "cohort_size": cohort_n,
        "cohort_percentile_roi": cohort_percentile_roi,
        "data_quality_flags": data_quality_flags,
        "below_minimum_data_floor": below_floor,
        "mandate_reminder": "grow total spend and profit; do not optimize ROI by shrinking",
    }


if __name__ == "__main__":
    import json
    con = get_connection()
    # find a real example that clears the data floor and has real history -- not a trivial case
    example = con.execute(
        """
        SELECT p.adset_id, p.date FROM perf p
        JOIN meta m ON m.adset_id = p.adset_id
        WHERE m.effective_status = 'ACTIVE' AND p.spend_day_no >= 3
          AND p.date IN (DATE '2026-06-11')
        ORDER BY p.spend DESC LIMIT 1
        """
    ).fetchone()
    adset_id, decision_date = example
    ctx = build_context(con, adset_id, decision_date)
    print(json.dumps(ctx, indent=2))
