"""
Loads the 5 assignment CSVs into DuckDB as materialized in-memory TABLES (not views).

adset_id is forced to VARCHAR everywhere on load. This matters: adset_id shows
up in two non-overlapping numeric-string formats (14-digit and 18-digit)
across the files -- confirmed by suffix-matching that these are genuinely
different adsets, not one truncated form of the other. VARCHAR is the
deliberate choice for an identifier we only ever join/compare as a string,
never do arithmetic on -- letting DuckDB's type sniffer pick a numeric type
instead would be a silent footgun (e.g. losing a leading digit, or two ids
comparing equal after an int cast that shouldn't).

TABLE, not VIEW: found the hard way, mid-Task-C, that a VIEW over read_csv_auto()
re-parses the source CSV from disk on every single query against it -- fine for
the handful of ad hoc queries in Task A/B, but Task C's batch run issues
thousands of queries per run (multiple per adset-day x ~2,000 adset-days), and
re-scanning campaign_adset_metadata.csv (7.6MB) that many times made a dry run
that should take seconds hang indefinitely with zero output. Materializing once
at connection time turns "parse this CSV" from O(queries) into O(1).
"""
import os
import duckdb

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "supporting", "dataset")


def get_connection():
    con = duckdb.connect(database=":memory:")
    data_dir = DATA_DIR.replace("\\", "/")

    con.execute(f"""
        CREATE TABLE perf AS
            SELECT * FROM read_csv_auto('{data_dir}/daily_adset_performance.csv',
                types={{'adset_id': 'VARCHAR', 'fb_ad_account_id': 'VARCHAR'}});

        CREATE TABLE meta AS
            SELECT * FROM read_csv_auto('{data_dir}/campaign_adset_metadata.csv',
                types={{'adset_id': 'VARCHAR', 'campaign_id': 'VARCHAR'}});

        CREATE TABLE rules AS
            SELECT * FROM read_csv_auto('{data_dir}/auto_rules.csv');

        CREATE TABLE rule_exec AS
            SELECT * FROM read_csv_auto('{data_dir}/rule_executions.csv',
                types={{'adset_id': 'VARCHAR', 'account_id': 'VARCHAR', 'campaign_id': 'VARCHAR'}});

        CREATE TABLE buyer AS
            SELECT * FROM read_csv_auto('{data_dir}/buyer_actions.csv',
                types={{'adset_id': 'VARCHAR'}});

        CREATE INDEX idx_perf_adset ON perf(adset_id);
        CREATE INDEX idx_perf_date ON perf(date);
        CREATE INDEX idx_meta_adset ON meta(adset_id);
        CREATE INDEX idx_rule_exec_adset ON rule_exec(adset_id);
        CREATE INDEX idx_buyer_adset ON buyer(adset_id);
    """)
    return con


if __name__ == "__main__":
    con = get_connection()
    counts = con.execute("""
        SELECT
            (SELECT count(*) FROM perf) AS perf,
            (SELECT count(*) FROM meta) AS meta,
            (SELECT count(*) FROM rules) AS rules,
            (SELECT count(*) FROM rule_exec) AS rule_exec,
            (SELECT count(*) FROM buyer) AS buyer
    """).fetchdf()
    print("View row counts:")
    print(counts.to_string(index=False))

    id_types = con.execute("""
        (SELECT 'perf' AS src, typeof(adset_id) AS t FROM perf LIMIT 1)
        UNION ALL (SELECT 'meta', typeof(adset_id) FROM meta LIMIT 1)
        UNION ALL (SELECT 'rule_exec', typeof(adset_id) FROM rule_exec LIMIT 1)
        UNION ALL (SELECT 'buyer', typeof(adset_id) FROM buyer LIMIT 1)
    """).fetchdf()
    print("\nadset_id column types:")
    print(id_types.to_string(index=False))
