"""
Runs every statement in a .sql file against the loaded views, printing each
result set. Statements are split on ';' at top level -- fine for this
project's queries (no stored procedures, no semicolons inside string
literals in these queries).

Usage: python src/run_sql.py sql/01_join_coverage_and_response_split.sql
"""
import sys
import pandas as pd
from db import get_connection

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 60)


def split_statements(sql_text: str):
    # strip full-line comments, then split on ';'
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def main(path: str):
    with open(path, "r", encoding="utf-8") as f:
        sql_text = f.read()

    con = get_connection()
    statements = split_statements(sql_text)
    for i, stmt in enumerate(statements, 1):
        print(f"\n{'=' * 80}\n[{i}/{len(statements)}] {stmt[:120]}\n{'=' * 80}")
        df = con.execute(stmt).fetchdf()
        print(df.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
