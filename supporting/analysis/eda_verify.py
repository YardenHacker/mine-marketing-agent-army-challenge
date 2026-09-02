"""
Independent re-verification of the EDA findings before they go into
INVESTIGATION.md. Each check here is written differently from the original
eda.py/eda_followup.py query that produced the claim, specifically so this
isn't just "run the same query twice and get the same bug twice."
"""
from db import get_connection

con = get_connection()


def section(t):
    print(f"\n{'=' * 100}\n{t}\n{'=' * 100}")


section("V1. 72 duplicate perf rows -- re-derive via row_number() window function instead of GROUP BY")
r = con.execute("""
    SELECT count(*) AS excess_rows FROM (
        SELECT *, row_number() OVER (PARTITION BY adset_id, date ORDER BY spend) AS rn
        FROM perf
    ) WHERE rn > 1
""").fetchdf()
print(r.to_string(index=False))
print("(original claim: 72 excess rows via GROUP BY ... HAVING count(*)>1)")

section("V2. duplicated rows are TRUE duplicates (all columns identical), not just same key+spend/revenue")
r = con.execute("""
    WITH keyed AS (
        SELECT *, row_number() OVER (PARTITION BY adset_id, date ORDER BY spend) AS rn,
               count(*) OVER (PARTITION BY adset_id, date) AS grp_n
        FROM perf
    )
    SELECT count(DISTINCT adset_id || '|' || date::VARCHAR) AS n_dup_keys
    FROM keyed WHERE grp_n > 1
""").fetchdf()
print(f"distinct (adset_id,date) keys with >1 row: {r.iloc[0,0]}")

# check full-row equality for a handful of the duplicated keys
r2 = con.execute("""
    WITH dup_keys AS (
        SELECT adset_id, date FROM perf GROUP BY adset_id, date HAVING count(*) > 1 LIMIT 5
    )
    SELECT p.* FROM perf p JOIN dup_keys d ON d.adset_id = p.adset_id AND d.date = p.date
    ORDER BY p.adset_id, p.date
""").fetchdf()
print("\nfull rows for 5 sample duplicated keys (checking every column matches, not just spend/revenue):")
print(r2.to_string(index=False))

section("V3. Zero overlap between duplicated perf adsets and rule_exec adsets -- re-derive via anti-join count")
r = con.execute("""
    SELECT count(*) AS overlap
    FROM (SELECT DISTINCT adset_id FROM rule_exec) re
    WHERE re.adset_id IN (
        SELECT adset_id FROM perf GROUP BY adset_id, date HAVING count(*) > 1
    )
""").fetchdf()
print(f"rule_exec adsets that are also duplicated-perf adsets: {r.iloc[0,0]} (original claim: 0)")

section("V4. meta.language collapsed-category totals reconcile to 7129 total rows")
r = con.execute("""
    SELECT
        sum(CASE WHEN lower(trim(language)) IN ('en','english') THEN n ELSE 0 END) AS english,
        sum(CASE WHEN lower(trim(language)) = 'es' THEN n ELSE 0 END) AS spanish,
        sum(CASE WHEN lower(trim(language)) = 'de' THEN n ELSE 0 END) AS german,
        sum(CASE WHEN lower(trim(language)) = 'fr' THEN n ELSE 0 END) AS french,
        sum(CASE WHEN lower(trim(language)) = 'pt' THEN n ELSE 0 END) AS portuguese,
        sum(CASE WHEN lower(trim(language)) = 'sv' THEN n ELSE 0 END) AS swedish,
        sum(CASE WHEN lower(trim(language)) = 'ja' THEN n ELSE 0 END) AS japanese,
        sum(CASE WHEN lower(trim(language)) = 'ar' THEN n ELSE 0 END) AS arabic,
        sum(CASE WHEN lower(trim(language)) IN ('no_language') THEN n ELSE 0 END) AS no_language_marker,
        sum(CASE WHEN lower(trim(language)) = 'all' THEN n ELSE 0 END) AS all_marker,
        sum(CASE WHEN trim(language) = '' THEN n ELSE 0 END) AS blank_or_space,
        sum(CASE WHEN language IS NULL THEN n ELSE 0 END) AS true_null,
        sum(CASE WHEN lower(trim(language)) IN ('he','it','nl','pl','ro','cs','fi','hu') THEN n ELSE 0 END) AS other_singletons,
        sum(n) AS grand_total
    FROM (SELECT language, count(*) n FROM meta GROUP BY language) t
""").fetchdf()
print(r.T.rename(columns={0: "count"}).to_string())
print(f"\nsanity: total meta rows = {con.execute('SELECT count(*) FROM meta').fetchdf().iloc[0,0]}")

section("V5. last_3_days_revenue-without-spend rows are ALL R04 / day-1 -- re-derive")
r = con.execute("""
    SELECT rule_id, total_days_at_action, count(*) n
    FROM rule_exec
    WHERE last_3_days_spend_at_action IS NULL AND last_3_days_revenue_at_action IS NOT NULL
    GROUP BY rule_id, total_days_at_action
""").fetchdf()
print(r.to_string(index=False))
print("(original claim: sampled rows were all R04, total_days_at_action=1 -- checking the FULL set, not a sample)")

section("V6. cr > 1 rows -- re-derive count and re-verify all trace to estimated_conversions > clicks")
r = con.execute("""
    SELECT count(*) AS n_cr_over_1,
           count(*) FILTER (WHERE estimated_conversions > clicks) AS n_where_econv_gt_clicks
    FROM perf WHERE cr > 1
""").fetchdf()
print(r.to_string(index=False))

section("V7. bid_amount / roas_target vs bid_strategy -- re-derive as a strict 1:1 rule instead of a crosstab")
r = con.execute("""
    SELECT
        count(*) FILTER (WHERE bid_strategy = 'LOWEST_COST_WITH_MIN_ROAS' AND bid_amount IS NOT NULL) AS violations_min_roas_has_bid,
        count(*) FILTER (WHERE bid_strategy = 'LOWEST_COST_WITHOUT_CAP' AND (bid_amount IS NOT NULL OR roas_target IS NOT NULL)) AS violations_without_cap_has_either,
        count(*) FILTER (WHERE bid_strategy = 'LOWEST_COST_WITH_BID_CAP' AND bid_amount IS NULL) AS violations_bid_cap_missing_bid,
        count(*) FILTER (WHERE bid_strategy = 'COST_CAP' AND bid_amount IS NULL) AS violations_cost_cap_missing_bid
    FROM meta
""").fetchdf()
print(r.to_string(index=False))
print("(all should be 0 if the original 100%-clean claim holds)")

section("V8. adset_name null-rate by status -- re-derive as percentages instead of raw counts")
r = con.execute("""
    SELECT effective_status, delivery_status,
           count(*) n,
           round(100.0 * count(*) FILTER (WHERE adset_name IS NULL) / count(*), 1) AS pct_null
    FROM meta GROUP BY effective_status, delivery_status ORDER BY pct_null DESC
""").fetchdf()
print(r.to_string(index=False))
