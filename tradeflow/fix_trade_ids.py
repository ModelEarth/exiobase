#!/usr/bin/env python3
"""
One-off cleanup: fixes interstate_id in already-published 2019/2021 CSV
files in trade-data (see webroot/team/PLAN-merge.md's "Two-stage ID
design").

interstate_id: replaces the old {trade_id}-US-{state1}-US-{state2}-
{sector1}-{sector2} composite string with a fresh 1-based integer,
preserving existing row order. interstate.csv's trade_id column needs no
change (it only ever references domestic). interstate_factor.csv/
interstate_estimate.csv's interstate_id is remapped through the same
mapping built while rewriting interstate.csv.

Only touches the primary interstate.csv/interstate_factor.csv — not the
-lg full-detail siblings (gitignored, never loaded into Postgres, out of
scope for this fix).

Does NOT touch trade_id in trade.csv/trade_factor.csv. An earlier version
of this script added a fixed per-flow_type offset there directly, but the
Postgres loader (team/src/main.rs's insert_trade_rows/
insert_trade_factor_rows) already applies that same offset at insert
time — trade.py itself is unchanged and will keep producing un-offset
per-file trade_id for every future year, so the loader has to apply the
offset uniformly for historical and future years alike. Baking it into
the CSV too double-applied it (caught and reverted — see
webroot/trade-data commit history around 2026-09-20). The offset now
lives solely in the loader.

Usage (from exiobase/tradeflow/):
    python fix_trade_ids.py 2019 2021
"""
import csv
import sys
from pathlib import Path

TRADE_DATA_ROOT = Path(__file__).resolve().parents[2] / "trade-data" / "year"


def _read_rows(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    return fieldnames, rows


def _write_rows(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def renumber_interstate_id(path):
    """Replaces interstate_id with a fresh 1-based sequence in existing row
    order. Returns {old_id: new_id} for interstate_factor.csv/
    interstate_estimate.csv to remap through."""
    fieldnames, rows = _read_rows(path)
    id_map = {}
    for i, row in enumerate(rows, start=1):
        old_id = row["interstate_id"]
        new_id = str(i)
        id_map[old_id] = new_id
        row["interstate_id"] = new_id
    _write_rows(path, fieldnames, rows)
    return id_map


def remap_interstate_id_column(path, id_map):
    fieldnames, rows = _read_rows(path)
    for row in rows:
        old_id = row["interstate_id"]
        if old_id not in id_map:
            raise ValueError(f"{path}: interstate_id {old_id!r} has no entry in interstate.csv's mapping")
        row["interstate_id"] = id_map[old_id]
    _write_rows(path, fieldnames, rows)
    return len(rows)


def fix_year(year):
    year_dir = TRADE_DATA_ROOT / str(year) / "US"
    print(f"=== {year} ===")

    domestic_dir = year_dir / "domestic"
    id_map = renumber_interstate_id(domestic_dir / "interstate.csv")
    print(f"  domestic/interstate.csv: interstate_id renumbered 1..{len(id_map)}")

    factor_csv = domestic_dir / "interstate_factor.csv"
    if factor_csv.exists():
        n = remap_interstate_id_column(factor_csv, id_map)
        print(f"  domestic/interstate_factor.csv: {n} rows remapped")

    estimate_csv = domestic_dir / "interstate_estimate.csv"
    if estimate_csv.exists():
        n = remap_interstate_id_column(estimate_csv, id_map)
        print(f"  domestic/interstate_estimate.csv: {n} rows remapped")


if __name__ == "__main__":
    years = sys.argv[1:] or ["2019", "2021"]
    for year in years:
        fix_year(year)
