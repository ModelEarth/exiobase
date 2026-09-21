#!/usr/bin/env python3
"""
Ad-hoc [year]/[country] folder export straight from industrydb -- for a
region a comprehensive run's COMPREHENSIVE.folders excluded, or any other
country/year already loaded into industrydb that needs a local folder. See
PLAN-comprehensive.md's `Answering "add a [year]/[country] folder later"`
section: for a year already comprehensively loaded, always export from
Azure, never re-derive from the raw Exiobase file -- re-parsing/re-stacking
is slower and, unlike a straight export, can silently drift from what's
actually stored if extraction logic ever changes.

Assumes that year's reference files (industry.csv/sector.csv/factor.csv/
sector_industry.csv) already exist locally -- they're written once by
trade_comprehensive.py (or trade.py) and don't vary per country, so there's
nothing to re-export here.

Set EXIOBASE_COMPREHENSIVE_TARGET=industrydb to pull from the shared,
multi-year database instead of the default per-year industrydb_[year] --
must match whichever COMPREHENSIVE.target that year was originally pushed
with (see config.yaml's NOTES).

Usage: EXIOBASE_YEAR=<year> EXIOBASE_COUNTRY=NL python3 export_country_csvs.py
"""
import os
import sys

from config_loader import load_config, get_comprehensive_target
from trade_extraction import write_flow_csv, write_comprehensive_runnote
import industrydb


def export_country(year, country):
    config = load_config()
    target = get_comprehensive_target(config)

    conn = industrydb.get_connection(year, target=target)
    try:
        for kind in ('domestic', 'exports', 'imports'):
            trade_rows, trade_factor_rows = industrydb.pull_flow(conn, country, kind, year=year, target=target)
            write_flow_csv(config, country, kind, trade_rows, trade_factor_rows)
            write_comprehensive_runnote(
                config, year, country, kind,
                source="export_country_csvs.py (pulled from industrydb)",
            )
            print(f"{kind}: {len(trade_rows)} trade rows, {len(trade_factor_rows)} trade_factor rows")
    finally:
        conn.close()


if __name__ == "__main__":
    year_env = os.environ.get('EXIOBASE_YEAR')
    country_env = os.environ.get('EXIOBASE_COUNTRY')
    if not year_env or not country_env:
        sys.exit("Usage: EXIOBASE_YEAR=<year> EXIOBASE_COUNTRY=<code> python3 export_country_csvs.py")
    export_country(int(year_env), country_env.strip().upper())
