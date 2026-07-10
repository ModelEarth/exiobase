#!/usr/bin/env python3
"""
Fetches trade CSVs from GitHub and batch-inserts them into Azure industrydb.

Insert order respects FK constraints:
  factor -> industry -> trade -> trade_factor -> trade_impact

Run directly:
  python insert_pipeline.py --year 2019 --country US --flow_type exports

Or import and call insert_trade_data() from api.py.
"""

import argparse
import io
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras
import requests

GITHUB_BASE = "https://raw.githubusercontent.com/ModelEarth/trade-data/refs/heads/main/year"
BATCH_SIZE = 500
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _get_conn():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            conn = psycopg2.connect(
                host=os.environ["EXIOBASE_HOST"],
                port=int(os.environ.get("EXIOBASE_PORT", 5432)),
                dbname=os.environ["EXIOBASE_NAME"],
                user=os.environ["EXIOBASE_USER"],
                password=os.environ["EXIOBASE_PASSWORD"],
                sslmode=os.environ.get("EXIOBASE_SSL_MODE", "require"),
            )
            return conn
        except psycopg2.OperationalError as e:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** attempt)


# ---------------------------------------------------------------------------
# CSV fetching
# ---------------------------------------------------------------------------

def _fetch_csv(url: str) -> Optional[pd.DataFrame]:
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return pd.read_csv(io.StringIO(r.text), low_memory=False)
    except Exception as e:
        print(f"  Warning: could not fetch {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Batch insert helpers
# ---------------------------------------------------------------------------

def _batch_insert(cur, sql: str, rows: list):
    for i in range(0, len(rows), BATCH_SIZE):
        psycopg2.extras.execute_values(cur, sql, rows[i : i + BATCH_SIZE], page_size=BATCH_SIZE)


# ---------------------------------------------------------------------------
# Per-table insert functions
# ---------------------------------------------------------------------------

def _insert_factors(cur, df: pd.DataFrame) -> int:
    if "factor_id" not in df.columns:
        print("  factor.csv missing factor_id column, skipping")
        return 0
    # CSV uses stressor/extension; DB uses name/context
    name_col = "name" if "name" in df.columns else "stressor"
    context_col = "context" if "context" in df.columns else "extension"
    rows = []
    for _, r in df.iterrows():
        try:
            fid = int(r["factor_id"])
            if fid <= 0:
                continue
        except (ValueError, TypeError):
            continue
        rows.append((fid, str(r.get("unit", "")), str(r.get(name_col, "")), str(r.get(context_col, ""))))
    if not rows:
        return 0
    sql = """
        INSERT INTO factor (factor_id, unit, stressor, extension)
        VALUES %s
        ON CONFLICT (factor_id) DO NOTHING
    """
    _batch_insert(cur, sql, rows)
    return len(rows)


def _insert_industries(cur, df: pd.DataFrame) -> int:
    required = {"industry_id", "name"}
    if not required.issubset(df.columns):
        print(f"  industry.csv missing columns {required - set(df.columns)}, skipping")
        return 0
    rows = []
    for _, r in df.iterrows():
        iid = str(r["industry_id"]).strip()
        name = str(r["name"]).strip()
        if not iid or not name:
            continue
        rows.append((iid, name))
    if not rows:
        return 0
    sql = """
        INSERT INTO industry (industry_id, name)
        VALUES %s
        ON CONFLICT (industry_id) DO NOTHING
    """
    _batch_insert(cur, sql, rows)
    return len(rows)


def _delete_flow(cur, year: int, country: str, flow_type: str):
    cur.execute(
        "DELETE FROM trade_factor WHERE year=%s AND country=%s AND flow_type=%s",
        (year, country, flow_type),
    )
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'trade_impact'
        )
    """)
    if cur.fetchone()[0]:
        cur.execute(
            "DELETE FROM trade_impact WHERE year=%s AND country=%s AND flow_type=%s",
            (year, country, flow_type),
        )
    cur.execute(
        "DELETE FROM trade WHERE year=%s AND country=%s AND flow_type=%s",
        (year, country, flow_type),
    )


def _insert_trade(cur, df: pd.DataFrame, flow_type: str, country: str) -> tuple[int, int]:
    required = {"trade_id", "year", "region1", "region2", "industry1", "industry2", "amount"}
    if not required.issubset(df.columns):
        print(f"  trade.csv missing columns {required - set(df.columns)}, skipping")
        return 0, 0
    rows = []
    skipped = 0
    for _, r in df.iterrows():
        try:
            tid = int(r["trade_id"])
            year = int(r["year"])
            amount = float(r["amount"])
            if tid <= 0 or not (amount == amount):  # NaN check
                skipped += 1
                continue
        except (ValueError, TypeError):
            skipped += 1
            continue
        industry1 = str(r["industry1"]).strip()
        industry2 = str(r["industry2"]).strip()
        if not industry1 or not industry2:
            skipped += 1
            continue
        rows.append((
            tid, year, str(r["region1"]), str(r["region2"]),
            industry1, industry2, amount, flow_type, country,
        ))
    if not rows:
        return 0, skipped
    sql = """
        INSERT INTO trade (trade_id, year, region1, region2, industry1, industry2, amount, flow_type, country)
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    _batch_insert(cur, sql, rows)
    return len(rows), skipped


def _insert_trade_factor(cur, df: pd.DataFrame, year: int, country: str, flow_type: str) -> tuple[int, int]:
    # CSV uses "level" as the amount column name
    amount_col = "level" if "level" in df.columns else "amount"
    required = {"trade_id", "factor_id", amount_col}
    if not required.issubset(df.columns):
        print(f"  trade_factor.csv missing columns {required - set(df.columns)}, skipping")
        return 0, 0
    rows = []
    skipped = 0
    for _, r in df.iterrows():
        try:
            tid = int(r["trade_id"])
            fid = int(r["factor_id"])
            amount = float(r[amount_col])
            if tid <= 0 or fid <= 0 or not (amount == amount):
                skipped += 1
                continue
        except (ValueError, TypeError):
            skipped += 1
            continue
        rows.append((tid, year, country, flow_type, fid, amount))
    if not rows:
        return 0, skipped
    sql = """
        INSERT INTO trade_factor (trade_id, year, country, flow_type, factor_id, level)
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    _batch_insert(cur, sql, rows)
    return len(rows), skipped


def _insert_trade_impact(cur, df: pd.DataFrame, year: int, country: str, flow_type: str) -> int:
    # Skipped until trade_impact DB schema is confirmed
    return 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

@dataclass
class InsertResult:
    year: int
    country: str
    flow_type: str
    rows_inserted: dict = field(default_factory=dict)
    rows_skipped: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


def insert_trade_data(year: int, country: str, flow_type: str) -> InsertResult:
    result = InsertResult(year=year, country=country, flow_type=flow_type)

    # Validate inputs
    if not (1990 <= year <= 2030):
        result.errors.append(f"Invalid year: {year}")
        return result
    country = country.strip().upper()
    if len(country) != 2 or not country.isalpha():
        result.errors.append(f"Invalid country code: {country}")
        return result
    if flow_type not in ("domestic", "imports", "exports"):
        result.errors.append(f"Invalid flow_type: {flow_type}")
        return result

    base = f"{GITHUB_BASE}/{year}"
    flow_base = f"{base}/{country}/{flow_type}"

    print(f"Fetching CSVs for {year}/{country}/{flow_type}...")
    factor_df = _fetch_csv(f"{base}/factor.csv")
    industry_df = _fetch_csv(f"{base}/industry.csv")
    trade_df = _fetch_csv(f"{flow_base}/trade.csv")
    trade_factor_df = _fetch_csv(f"{flow_base}/trade_factor.csv")
    trade_impact_df = _fetch_csv(f"{flow_base}/trade_impact.csv")  # optional

    if trade_df is None:
        result.errors.append(f"trade.csv not found at {flow_base}/trade.csv")
        return result

    print("Connecting to database...")
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Reference tables (idempotent)
                if factor_df is not None:
                    n = _insert_factors(cur, factor_df)
                    result.rows_inserted["factor"] = n
                    print(f"  factor: {n} rows")

                if industry_df is not None:
                    n = _insert_industries(cur, industry_df)
                    result.rows_inserted["industry"] = n
                    print(f"  industry: {n} rows")

                # Clear then re-insert flow-specific tables
                print(f"  Clearing existing {year}/{country}/{flow_type} rows...")
                _delete_flow(cur, year, country, flow_type)

                n, skipped = _insert_trade(cur, trade_df, flow_type, country)
                result.rows_inserted["trade"] = n
                result.rows_skipped["trade"] = skipped
                print(f"  trade: {n} inserted, {skipped} skipped")

                if trade_factor_df is not None:
                    n, skipped = _insert_trade_factor(cur, trade_factor_df, year, country, flow_type)
                    result.rows_inserted["trade_factor"] = n
                    result.rows_skipped["trade_factor"] = skipped
                    print(f"  trade_factor: {n} inserted, {skipped} skipped")

                if trade_impact_df is not None:
                    n = _insert_trade_impact(cur, trade_impact_df, year, country, flow_type)
                    result.rows_inserted["trade_impact"] = n
                    print(f"  trade_impact: {n} inserted")

    finally:
        conn.close()

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Insert trade data into Azure industrydb")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--country", type=str, required=True)
    parser.add_argument("--flow_type", type=str, required=True, choices=["domestic", "imports", "exports"])
    args = parser.parse_args()

    result = insert_trade_data(args.year, args.country, args.flow_type)
    if result.errors:
        print("Errors:", result.errors)
    else:
        print("Done.", result.rows_inserted)


if __name__ == "__main__":
    main()
