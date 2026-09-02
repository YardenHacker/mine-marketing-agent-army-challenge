from db import get_connection

con = get_connection()


def section(t):
    print(f"\n{'=' * 100}\n{t}\n{'=' * 100}")


section("A. perf duplicate rows -- are they TRUE full-row duplicates, or near-duplicates?")
print(con.execute("""
    SELECT adset_id, date, spend, revenue, count(*) n
    FROM perf GROUP BY adset_id, date, spend, revenue
    HAVING count(*) > 1 ORDER BY n DESC LIMIT 10
""").fetchdf().to_string(index=False))

print("\nWould deduping change adset-day counts? (adset_id+date combos with >1 row at all)")
print(con.execute("""
    SELECT count(*) FROM (
        SELECT adset_id, date, count(*) n FROM perf GROUP BY adset_id, date HAVING count(*) > 1
    )
""").fetchdf().to_string(index=False))

section("B. Did the duplicate perf rows affect the Task A impact numbers? (were any dupe adsets in rule_exec)")
print(con.execute("""
    SELECT DISTINCT p.adset_id FROM perf p
    JOIN (SELECT adset_id, date, count(*) n FROM perf GROUP BY adset_id, date HAVING count(*) > 1) d
      ON d.adset_id = p.adset_id
    WHERE p.adset_id IN (SELECT DISTINCT adset_id FROM rule_exec)
""").fetchdf().to_string(index=False))

section("C. perf: are the ~2700 null revenue/profit/ctr/cr rows explained by zero spend or zero clicks?")
print(con.execute("""
    SELECT
        count(*) FILTER (WHERE revenue IS NULL) AS revenue_null,
        count(*) FILTER (WHERE revenue IS NULL AND spend = 0) AS revenue_null_and_zero_spend,
        count(*) FILTER (WHERE revenue IS NULL AND spend > 0) AS revenue_null_but_spend_gt_0,
        count(*) FILTER (WHERE ctr IS NULL) AS ctr_null,
        count(*) FILTER (WHERE ctr IS NULL AND impressions = 0) AS ctr_null_and_zero_impr,
        count(*) FILTER (WHERE cr IS NULL) AS cr_null,
        count(*) FILTER (WHERE cr IS NULL AND clicks = 0) AS cr_null_and_zero_clicks,
        count(*) FILTER (WHERE first_spend_date IS NULL) AS fsd_null,
        count(*) FILTER (WHERE first_spend_date IS NULL AND spend = 0) AS fsd_null_and_zero_spend
    FROM perf
""").fetchdf().T.rename(columns={0: "count"}).to_string())

print("\nsample rows where revenue is null but spend > 0 (the unexplained ones, if any):")
print(con.execute("SELECT adset_id, date, spend, impressions, clicks, fb_conversions, estimated_conversions, revenue FROM perf WHERE revenue IS NULL AND spend > 0 LIMIT 10").fetchdf().to_string(index=False))

section("D. perf: the 13 rows where cr > 1 -- what do they look like?")
print(con.execute("""
    SELECT adset_id, date, clicks, fb_conversions, estimated_conversions, cr
    FROM perf WHERE cr > 1 ORDER BY cr DESC LIMIT 13
""").fetchdf().to_string(index=False))

section("E. meta: is adset_name null correlated with status (e.g. DELETED)?")
print(con.execute("""
    SELECT effective_status, delivery_status,
           count(*) AS n, count(*) FILTER (WHERE adset_name IS NULL) AS name_null
    FROM meta GROUP BY effective_status, delivery_status ORDER BY name_null DESC LIMIT 10
""").fetchdf().to_string(index=False))

section("F. meta: bid_amount / roas_target nulls -- correlated with bid_strategy?")
print(con.execute("""
    SELECT bid_strategy,
           count(*) AS n,
           count(*) FILTER (WHERE bid_amount IS NULL) AS bid_amount_null,
           count(*) FILTER (WHERE roas_target IS NULL) AS roas_target_null
    FROM meta GROUP BY bid_strategy
""").fetchdf().to_string(index=False))

section("G. rule_exec: why does last_3_days_revenue_at_action have fewer nulls (68) than last_3_days_spend/roi (114)?")
print(con.execute("""
    SELECT
        count(*) FILTER (WHERE last_3_days_spend_at_action IS NULL AND last_3_days_revenue_at_action IS NOT NULL) AS spend_null_rev_present,
        count(*) FILTER (WHERE last_3_days_spend_at_action IS NOT NULL AND last_3_days_revenue_at_action IS NULL) AS spend_present_rev_null,
        count(*) FILTER (WHERE last_3_days_spend_at_action IS NULL AND last_3_days_revenue_at_action IS NULL) AS both_null
    FROM rule_exec
""").fetchdf().to_string(index=False))
print("\nsample of rows where spend is null but revenue is present:")
print(con.execute("""
    SELECT rule_id, action_date, adset_id, total_days_at_action,
           last_3_days_spend_at_action, last_3_days_revenue_at_action, last_3_days_roi_at_action
    FROM rule_exec
    WHERE last_3_days_spend_at_action IS NULL AND last_3_days_revenue_at_action IS NOT NULL
    LIMIT 10
""").fetchdf().to_string(index=False))

section("H. rule_exec: budget_level null (45) and current_budget_from_fb null (45) -- same 45 rows?")
print(con.execute("""
    SELECT
        count(*) FILTER (WHERE budget_level IS NULL AND current_budget_from_fb IS NULL) AS both_null,
        count(*) FILTER (WHERE budget_level IS NULL AND current_budget_from_fb IS NOT NULL) AS level_null_only,
        count(*) FILTER (WHERE budget_level IS NOT NULL AND current_budget_from_fb IS NULL) AS fb_null_only
    FROM rule_exec
""").fetchdf().to_string(index=False))

section("I. meta.language: full distinct list with byte-level inspection (leading/trailing space, case)")
print(con.execute("""
    SELECT '[' || language || ']' AS bracketed, length(language) AS len, count(*) n
    FROM meta GROUP BY language ORDER BY lower(trim(language)), language
""").fetchdf().to_string(index=False))
