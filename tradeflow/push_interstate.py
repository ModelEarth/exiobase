#!/usr/bin/env python3
"""
Push US interstate/interstate_factor data (bea/main.py's local CSV output)
into whichever Azure database this year's comprehensive run targeted --
industrydb_{year} (target='year_db', default) or the shared industrydb
(target='industrydb'). See PLAN-comprehensive.md's "Database write path".

bea/main.py only ever writes local CSVs (year/{year}/US/domestic/
interstate.csv + interstate_factor.csv) -- it has no Azure-push code of its
own, matching trade.py's own scope (extraction only). For the curated
14-country pipeline, that push happens through the admin panel's "Send
Trade Data to Azure" button instead (team's insert_interstate_rows/
insert_interstate_factor_rows, reading CSVs back out of GitHub). A
comprehensive-target database hides that panel once it looks comprehensive
(db-admin.js's COMPREHENSIVE_SIZE_MB_THRESHOLD), so this script is
comprehensive mode's equivalent -- reusing industrydb.py's direct-psycopg2
COPY-then-upsert pattern instead of a Rust/HTTP round trip, for consistency
with how trade_comprehensive.py already pushes trade/trade_factor.

Run standalone: `YEAR=2018 python3 push_interstate.py` (also accepts
DB_TARGET/COMPREHENSIVE.target the same way main.py's comprehensive mode
does). main.py's run_interstate_step calls this automatically right after
bea/main.py, for any year run with COUNTRY.list=comprehensive and
--interstate US.
"""

import os
import sys

import pandas as pd

from config_loader import load_config, get_comprehensive_target

import industrydb


def push_interstate(year, target=None):
    config = load_config()
    if target is None:
        target = get_comprehensive_target(config)

    domestic_folder = config['FOLDERS']['domestic'].format(year=year, country='US')
    interstate_path = os.path.join(domestic_folder, 'interstate.csv')
    interstate_factor_path = os.path.join(domestic_folder, 'interstate_factor.csv')

    if not os.path.exists(interstate_path):
        sys.exit(f"No interstate.csv found at {interstate_path} -- run bea/main.py for {year} first.")

    interstate_df = pd.read_csv(interstate_path)
    interstate_factor_df = (
        pd.read_csv(interstate_factor_path) if os.path.exists(interstate_factor_path) else pd.DataFrame()
    )

    conn = industrydb.get_connection(year, target=target)
    try:
        n_interstate = industrydb.push_interstate_rows(conn, interstate_df, year=year, target=target)
        n_factor = industrydb.push_interstate_factor_rows(conn, interstate_factor_df, year=year, target=target)
    finally:
        conn.close()

    target_name = (
        industrydb.year_database_name(year) if target == industrydb.TARGET_YEAR_DB
        else os.environ.get('EXIOBASE_NAME', '(EXIOBASE_NAME not set)')
    )
    print(
        f"[INTERSTATE-PUSH] {year}: pushed {n_interstate}/{len(interstate_df)} interstate rows and "
        f"{n_factor}/{len(interstate_factor_df)} interstate_factor rows to {target_name} "
        f"(a gap below the total means those rows already existed from a previous run)"
    )
    return n_interstate, n_factor


if __name__ == '__main__':
    config = load_config()
    year = int(os.environ.get('EXIOBASE_YEAR') or os.environ.get('YEAR') or config['YEAR'])
    push_interstate(year)
