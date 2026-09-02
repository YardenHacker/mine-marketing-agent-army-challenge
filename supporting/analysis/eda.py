"""
Full EDA pass across all 5 CSVs: missing rows, NAs, and spelling/consistency
errors, with reasons where determinable. Run after the Task A investigation
to double-check nothing was missed the first time around.
"""
import pandas as pd
from db import get_connection

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 80)
pd.set_option("display.max_rows", 200)


def section(title):
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")


def null_counts(con, table, cols):
    q = "SELECT " + ", ".join(f"count(*) - count({c}) AS {c}" for c in cols) + f" FROM {table}"
    return con.execute(q).fetchdf()


def main():
    con = get_connection()

    tables = {
        "perf": "daily_adset_performance.csv",
        "meta": "campaign_adset_metadata.csv",
        "rules": "auto_rules.csv",
        "rule_exec": "rule_executions.csv",
        "buyer": "buyer_actions.csv",
    }

    section("1. NULL / MISSING VALUE COUNTS PER COLUMN")
    for t in tables:
        cols = con.execute(f"SELECT * FROM {t} LIMIT 0").fetchdf().columns.tolist()
        nulls = null_counts(con, t, cols)
        total = con.execute(f"SELECT count(*) FROM {t}").fetchdf().iloc[0, 0]
        print(f"\n--- {t} ({tables[t]}), {total} rows ---")
        nz = nulls.loc[:, (nulls != 0).any(axis=0)]
        if nz.empty:
            print("  no nulls in any column")
        else:
            print(nz.T.rename(columns={0: "null_count"}).to_string())

    section("2. FULLY DUPLICATE ROWS")
    for t in tables:
        cols = con.execute(f"SELECT * FROM {t} LIMIT 0").fetchdf().columns.tolist()
        collist = ", ".join(cols)
        dupes = con.execute(f"""
            SELECT count(*) AS n_excess_dupe_rows FROM (
                SELECT {collist}, count(*) AS n FROM {t} GROUP BY {collist} HAVING count(*) > 1
            )
        """).fetchdf()
        total_dupe_rows = con.execute(f"""
            SELECT coalesce(sum(n - 1), 0) AS total_excess_rows FROM (
                SELECT count(*) AS n FROM {t} GROUP BY {collist} HAVING count(*) > 1
            )
        """).fetchdf()
        print(f"{t}: {dupes.iloc[0,0]} distinct duplicated row-patterns, "
              f"{total_dupe_rows.iloc[0,0]} excess rows")

    section("3. daily_adset_performance.csv -- MISSING DATE ROWS (gaps within an adset's active window)")
    gaps = con.execute("""
        WITH bounds AS (
            SELECT adset_id, min(date) AS first_d, max(date) AS last_d, count(*) AS n_rows
            FROM perf GROUP BY adset_id
        ),
        expected AS (
            SELECT adset_id, first_d, last_d, n_rows,
                   date_diff('day', first_d, last_d) + 1 AS expected_rows
            FROM bounds
        )
        SELECT count(*) AS adsets_with_gaps, sum(expected_rows - n_rows) AS total_missing_day_rows
        FROM expected WHERE expected_rows > n_rows
    """).fetchdf()
    print(gaps.to_string(index=False))
    sample_gaps = con.execute("""
        WITH bounds AS (
            SELECT adset_id, min(date) AS first_d, max(date) AS last_d, count(*) AS n_rows
            FROM perf GROUP BY adset_id
        )
        SELECT adset_id, first_d, last_d, n_rows,
               date_diff('day', first_d, last_d) + 1 AS expected_rows
        FROM bounds
        WHERE date_diff('day', first_d, last_d) + 1 > n_rows
        LIMIT 10
    """).fetchdf()
    print("\nsample adsets with internal date gaps:")
    print(sample_gaps.to_string(index=False))

    section("4. REFERENTIAL INTEGRITY -- ids that appear in one file but not another")
    checks = [
        ("rule_exec.adset_id not in meta", "SELECT count(DISTINCT adset_id) FROM rule_exec WHERE adset_id NOT IN (SELECT adset_id FROM meta)"),
        ("rule_exec.adset_id not in perf", "SELECT count(DISTINCT adset_id) FROM rule_exec WHERE adset_id NOT IN (SELECT adset_id FROM perf)"),
        ("perf.adset_id not in meta", "SELECT count(DISTINCT adset_id) FROM perf WHERE adset_id NOT IN (SELECT adset_id FROM meta)"),
        ("buyer.adset_id (non-empty) not in meta", "SELECT count(DISTINCT adset_id) FROM buyer WHERE adset_id IS NOT NULL AND adset_id != '' AND adset_id NOT IN (SELECT adset_id FROM meta)"),
        ("buyer.adset_id (non-empty) not in perf", "SELECT count(DISTINCT adset_id) FROM buyer WHERE adset_id IS NOT NULL AND adset_id != '' AND adset_id NOT IN (SELECT adset_id FROM perf)"),
        ("rule_exec.rule_id not in rules", "SELECT count(DISTINCT rule_id) FROM rule_exec WHERE rule_id NOT IN (SELECT rule_id FROM rules)"),
    ]
    for label, q in checks:
        r = con.execute(q).fetchdf().iloc[0, 0]
        print(f"  {label}: {r}")

    section("5. CATEGORICAL / TEXT COLUMNS -- distinct values (spelling / casing / whitespace scan)")
    cat_cols = [
        ("perf", "account_name"),
        ("meta", "account_name"),
        ("meta", "effective_status"),
        ("meta", "delivery_status"),
        ("meta", "bid_strategy"),
        ("meta", "budget_optimization"),
        ("meta", "objective"),
        ("meta", "optimization_goal"),
        ("meta", "language"),
        ("rule_exec", "budget_level"),
        ("rules", "action"),
        ("rules", "schedule"),
        ("rules", "scope"),
        ("buyer", "object_type"),
        ("buyer", "event_type"),
    ]
    for table, col in cat_cols:
        vals = con.execute(f"SELECT {col}, count(*) n FROM {table} GROUP BY {col} ORDER BY n DESC").fetchdf()
        print(f"\n--- {table}.{col} ({len(vals)} distinct values) ---")
        print(vals.to_string(index=False))

    section("6. WHITESPACE / CASE ANOMALIES IN KEY TEXT COLUMNS")
    for table, col in cat_cols:
        anomaly = con.execute(f"""
            SELECT {col} FROM {table}
            WHERE {col} IS NOT NULL AND (
                {col} != trim({col}) OR {col} != lower({col}) AND {col} != upper({col})
                  AND lower(trim({col})) IN (SELECT DISTINCT lower(trim({col})) FROM {table} GROUP BY lower(trim({col})) HAVING count(DISTINCT {col}) > 1)
            )
            LIMIT 5
        """).fetchdf()
        if len(anomaly):
            print(f"{table}.{col}: possible whitespace/case variants -> {anomaly[col].tolist()}")

    section("7. NUMERIC SANITY CHECKS")
    numeric_checks = [
        ("perf: negative spend", "SELECT count(*) FROM perf WHERE spend < 0"),
        ("perf: negative revenue", "SELECT count(*) FROM perf WHERE revenue < 0"),
        ("perf: ctr > 1", "SELECT count(*) FROM perf WHERE ctr > 1"),
        ("perf: cr > 1", "SELECT count(*) FROM perf WHERE cr > 1"),
        ("perf: clicks > impressions", "SELECT count(*) FROM perf WHERE clicks > impressions"),
        ("perf: roi != round(profit/spend, 4) beyond rounding (spend>0)",
         "SELECT count(*) FROM perf WHERE spend > 0 AND abs(roi - profit/spend) > 0.01"),
        ("perf: profit != revenue - spend beyond rounding",
         "SELECT count(*) FROM perf WHERE abs(profit - (revenue - spend)) > 0.01"),
        ("meta: negative daily_budget", "SELECT count(*) FROM meta WHERE daily_budget < 0"),
        ("meta: negative bid_amount", "SELECT count(*) FROM meta WHERE bid_amount < 0"),
        ("rule_exec: negative old_budget/new_budget", "SELECT count(*) FROM rule_exec WHERE old_budget < 0 OR new_budget < 0"),
        ("buyer: negative old_budget/new_budget", "SELECT count(*) FROM buyer WHERE old_budget < 0 OR new_budget < 0"),
    ]
    for label, q in numeric_checks:
        r = con.execute(q).fetchdf().iloc[0, 0]
        print(f"  {label}: {r}")

    section("8. DATE RANGE SANITY")
    date_checks = [
        ("perf date range", "SELECT min(date), max(date) FROM perf"),
        ("rule_exec action_date range", "SELECT min(action_date), max(action_date) FROM rule_exec"),
        ("buyer action_time range", "SELECT min(action_time), max(action_time) FROM buyer"),
        ("meta creation_date range", "SELECT min(creation_date), max(creation_date) FROM meta"),
        ("meta rows created AFTER the perf window ends (06-12)", "SELECT count(*) FROM meta WHERE creation_date::DATE > DATE '2026-06-12'"),
        ("rule_exec rows where action_date != date(action_time)", "SELECT count(*) FROM rule_exec WHERE action_date != action_time::DATE"),
    ]
    for label, q in date_checks:
        r = con.execute(q).fetchdf()
        print(f"  {label}: {r.iloc[0].tolist()}")

    section("9. adset_id / campaign_id LENGTH + FORMAT ANOMALIES")
    for table in ["perf", "meta", "rule_exec", "buyer"]:
        try:
            lens = con.execute(f"""
                SELECT length(adset_id) AS len, count(*) n
                FROM {table} WHERE adset_id IS NOT NULL AND adset_id != ''
                GROUP BY len ORDER BY len
            """).fetchdf()
            print(f"\n{table}.adset_id length distribution:")
            print(lens.to_string(index=False))
        except Exception as e:
            print(f"{table}: {e}")

    section("10. NON-NUMERIC adset_id VALUES (should always be digit strings)")
    for table in ["perf", "meta", "rule_exec", "buyer"]:
        bad = con.execute(f"""
            SELECT adset_id, count(*) n FROM {table}
            WHERE adset_id IS NOT NULL AND adset_id != '' AND NOT regexp_matches(adset_id, '^[0-9]+$')
            GROUP BY adset_id LIMIT 10
        """).fetchdf()
        if len(bad):
            print(f"{table}: non-numeric adset_id values found:")
            print(bad.to_string(index=False))
        else:
            print(f"{table}: all adset_id values are pure digit strings")


if __name__ == "__main__":
    main()
