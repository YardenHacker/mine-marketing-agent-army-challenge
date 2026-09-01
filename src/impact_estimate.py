"""
Task A2: quantify how much money rule-driven actions saved or burned.

METHODOLOGY (stated explicitly, per the brief's instruction -- there is no
single correct way to do this):

Only SUCCESS'd executions are counted (see 01_join_coverage_and_response_split.sql --
30 of 214 logged executions never took effect due to API errors, 20 more were
no-ops). Counting the full log as "what happened" would overstate impact in
both directions.

Two action families need two different counterfactual methods, because the
data available differs:

1. TURN OFF (R01, R03, R04, R05, R06, R08, R11): the adset stops spending
   entirely, so there's no post-action observation of "what it would have
   done" for that adset. We extrapolate from its performance around the
   moment of action.

   IMPORTANT METHOD NOTE, found while building this: the obvious first
   choice -- last_3_days_roi_at_action / last_3_days_spend_at_action, both
   already in rule_exec -- turns out to be NULL for 100% of R04's 109 rows
   (0/109 have a value; see sql/09_r04_null_check.sql). This isn't a data
   error: R04 fires on "Total Days = 1" adsets, which by construction have
   no 3-day trailing window yet. R04 is 51% of all successful executions,
   so a method that goes silent on R04 isn't a usable method. We use the
   adset's own SETTLED same-day performance instead (perf.spend / perf.roi
   for that adset_id + action_date), which is available for effectively
   every row (perf join coverage is 100%, see sql/01), and is also a
   *more accurate* read than today_roi_at_action: A1.5 (sql/06_revenue_delay.sql)
   found today_roi_at_action understates final same-day ROI by 0.07 on
   average, worse earlier in the day -- so perf.roi corrects for exactly
   the bias that makes rule decisions look more justified than they were.

   forgone_daily_profit_rate = perf.roi for (adset_id, action_date)
   forgone_daily_spend_rate  = perf.spend for (adset_id, action_date)
   forgone_profit = forgone_daily_spend_rate * forgone_daily_profit_rate * remaining_days_in_dataset
   (remaining_days = days from action_date+1 through 2026-06-12, the last
   date in the snapshot -- we cannot extrapolate past what we can see).

   Two caveats we are stating rather than hiding:
   (a) perf.spend on the kill date is itself likely reduced by the kill
       having happened mid-day (the adset couldn't spend its full daily
       budget after being paused), so forgone_daily_spend_rate is probably
       an UNDERestimate of the adset's true spend capacity -- meaning our
       central/optimistic numbers below are still conservative relative to
       reality, not inflated.
   (b) using a single day's ROI to project forward several days assumes
       performance is stable, which is a strong assumption for young adsets.

   We report three scenarios by varying which ROI figure stands in for
   "what would have kept happening". All three scenarios are on the SAME
   net scale (harm minus savings) -- an earlier version floored the
   conservative rate at 0, which zeroed out every case where the kill
   looked justified instead of crediting it as a saving. That made
   conservative structurally incomparable to central/optimistic (it could
   only ever show "burned", never "saved"), which is why it produced a
   result ($17.68 burned) that wasn't even between the other two -- caught
   during review and fixed:
     - conservative: min(settled same-day ROI, last_3_days_roi_at_action)
       when the trailing figure is available (worst of the two readings --
       skeptical of the kill only where we have two independent data
       points and both matter); falls back to the settled same-day ROI
       alone when no trailing figure exists (R04's day-1 adsets), since
       there's nothing to be "more skeptical" against
     - central: use the settled same-day ROI as-is (can be negative,
       producing a negative "forgone profit" i.e. money saved)
     - optimistic: max(settled same-day ROI, last_3_days_roi_at_action)
       when available (benefit of the doubt for an adset with an
       improving trailing trend); otherwise same as central
   By construction conservative <= central <= optimistic for every row,
   so the three totals now sit on one real spectrum instead of conservative
   answering a different question than the other two.

   This will not perfectly reconstruct reality for any single adset. It is
   a directional estimate, not an audited number -- exactly what the brief
   asks for ("state your assumptions explicitly").

2. BUDGET DECREASE (R02, R07, R10, R12): the adset keeps running, so we CAN
   use real observed post-action performance instead of pure extrapolation.
   For each cut, we look at the adset's perf rows on dates after action_date
   (up to and including 2026-06-12), while no other rule/buyer action moved
   the budget again in between (first cut's effect window ends at the next
   action on that adset, if any, else end of dataset).
   forgone_profit = sum over that window of:
       (budget_before/budget_after - 1) * actual_daily_spend * actual_daily_profit_per_dollar_spent
   i.e. "how much MORE would this adset likely have spent at the old budget,
   valued at the profit rate it actually realized at the new budget." This
   assumes profit-per-dollar-spent is roughly constant across that small a
   budget change (stated assumption -- real diminishing returns exist but
   aren't observable in this snapshot).

Money BURNED = positive forgone_profit (rules cut/killed something that was
actually fine). Money SAVED = negative forgone_profit (rules correctly
avoided losses).
"""
import pandas as pd
from db import get_connection

LAST_DATE = pd.Timestamp("2026-06-12")

TURN_OFF_RULES = {"R01", "R03", "R04", "R05", "R06", "R08", "R11"}
BUDGET_DECREASE_RULES = {"R02", "R07", "R10", "R12"}


def load_data(con):
    rule_exec = con.execute("""
        SELECT rule_id, action_date, action_time, adset_id, account_id,
               old_budget, new_budget, response,
               spend_at_action, today_roi_at_action,
               last_3_days_spend_at_action, last_3_days_roi_at_action
        FROM rule_exec
        WHERE response = 'SUCCESS'
    """).fetchdf()
    perf = con.execute("""
        SELECT adset_id, date, spend, revenue, profit, roi
        FROM perf
    """).fetchdf()
    return rule_exec, perf


def estimate_turn_off_impact(rule_exec: pd.DataFrame, perf: pd.DataFrame) -> pd.DataFrame:
    rows = rule_exec[rule_exec["rule_id"].isin(TURN_OFF_RULES)].copy()
    rows["action_date"] = pd.to_datetime(rows["action_date"])
    rows["remaining_days"] = (LAST_DATE - rows["action_date"]).dt.days  # days AFTER action_date through 06-12

    perf_same_day = perf.copy()
    perf_same_day["date"] = pd.to_datetime(perf_same_day["date"])
    perf_same_day = perf_same_day.rename(
        columns={"spend": "settled_spend", "roi": "settled_roi", "profit": "settled_profit"}
    )[["adset_id", "date", "settled_spend", "settled_roi", "settled_profit"]]

    rows = rows.merge(
        perf_same_day, left_on=["adset_id", "action_date"], right_on=["adset_id", "date"], how="left"
    )

    daily_spend_rate = rows["settled_spend"].fillna(0)
    settled_roi = rows["settled_roi"]
    trailing_roi = rows["last_3_days_roi_at_action"]  # available for non-R04 rows; NaN for R04

    # skipna=True (pandas default) means min/max fall back to the settled
    # rate alone when trailing_roi is NaN (R04's day-1 adsets) -- there's
    # only one reading to use, so conservative == central == optimistic
    # for those rows specifically. That's correct: we can't be "more
    # skeptical" than the only data point we have.
    rows["conservative_rate"] = pd.concat([settled_roi, trailing_roi], axis=1).min(axis=1)
    rows["central_rate"] = settled_roi
    rows["optimistic_rate"] = pd.concat([settled_roi, trailing_roi], axis=1).max(axis=1)

    for scenario in ["conservative", "central", "optimistic"]:
        rate_col = f"{scenario}_rate"
        rows[f"{scenario}_forgone_profit"] = (
            daily_spend_rate * rows[rate_col].fillna(0) * rows["remaining_days"]
        )

    return rows


def estimate_budget_decrease_impact(rule_exec: pd.DataFrame, perf: pd.DataFrame) -> pd.DataFrame:
    rows = rule_exec[rule_exec["rule_id"].isin(BUDGET_DECREASE_RULES)].copy()
    rows["action_date"] = pd.to_datetime(rows["action_date"])
    rows = rows[(rows["old_budget"].notna()) & (rows["new_budget"].notna()) & (rows["new_budget"] > 0)]
    rows["budget_ratio"] = rows["old_budget"] / rows["new_budget"] - 1.0  # extra fraction that would have been spent

    perf = perf.copy()
    perf["date"] = pd.to_datetime(perf["date"])

    results = []
    for _, r in rows.iterrows():
        # this cut's effect window: the day AFTER the cut through the next
        # action on this adset (any rule or the last dataset date, whichever
        # is first), so we don't attribute a later, separate cut's effect
        # to this one.
        later_actions = rule_exec[
            (rule_exec["adset_id"] == r["adset_id"])
            & (pd.to_datetime(rule_exec["action_date"]) > r["action_date"])
        ]
        if len(later_actions):
            window_end = pd.to_datetime(later_actions["action_date"]).min() - pd.Timedelta(days=1)
        else:
            window_end = LAST_DATE
        window_end = min(window_end, LAST_DATE)

        window = perf[
            (perf["adset_id"] == r["adset_id"])
            & (perf["date"] > r["action_date"])
            & (perf["date"] <= window_end)
        ]
        forgone = 0.0
        for _, w in window.iterrows():
            if w["spend"] and w["spend"] > 0:
                profit_per_dollar = w["profit"] / w["spend"]
                extra_spend = w["spend"] * r["budget_ratio"]
                forgone += extra_spend * profit_per_dollar

        results.append({**r.to_dict(), "window_days": len(window), "forgone_profit": forgone})

    return pd.DataFrame(results)


def main():
    con = get_connection()
    rule_exec, perf = load_data(con)

    turn_off = estimate_turn_off_impact(rule_exec, perf)
    budget_cut = estimate_budget_decrease_impact(rule_exec, perf)

    print("=" * 90)
    print("TURN-OFF RULES -- forgone profit by scenario (positive = money burned by killing a")
    print("winner; negative = money saved by killing a genuine loser)")
    print("=" * 90)
    by_rule = turn_off.groupby("rule_id").agg(
        n=("adset_id", "count"),
        conservative=("conservative_forgone_profit", "sum"),
        central=("central_forgone_profit", "sum"),
        optimistic=("optimistic_forgone_profit", "sum"),
    ).round(2)
    print(by_rule.to_string())
    print("\nTOTAL turn-off forgone profit (conservative / central / optimistic):")
    print(turn_off[["conservative_forgone_profit", "central_forgone_profit", "optimistic_forgone_profit"]].sum().round(2).to_string())

    print("\n" + "=" * 90)
    print("BUDGET-DECREASE RULES -- forgone profit from realized post-cut performance")
    print("=" * 90)
    by_rule2 = budget_cut.groupby("rule_id").agg(
        n=("adset_id", "count"),
        window_days_total=("window_days", "sum"),
        forgone_profit=("forgone_profit", "sum"),
    ).round(2)
    print(by_rule2.to_string())
    print(f"\nTOTAL budget-decrease forgone profit: {budget_cut['forgone_profit'].sum():.2f}")

    print("\n" + "=" * 90)
    print("GRAND TOTAL (turn-off + budget-decrease), three scenarios")
    print("=" * 90)
    budget_total = budget_cut["forgone_profit"].sum()
    for scenario in ["conservative", "central", "optimistic"]:
        total = turn_off[f"{scenario}_forgone_profit"].sum() + budget_total
        print(f"  {scenario:>12}: ${total:,.2f}")

    # save row-level detail for inspection / appendix
    turn_off.to_csv("../out/turn_off_impact_detail.csv", index=False)
    budget_cut.to_csv("../out/budget_decrease_impact_detail.csv", index=False)
    print("\nRow-level detail written to out/turn_off_impact_detail.csv and out/budget_decrease_impact_detail.csv")


if __name__ == "__main__":
    main()
