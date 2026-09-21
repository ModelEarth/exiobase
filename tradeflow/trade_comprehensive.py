#!/usr/bin/env python3
"""
Comprehensive trade push: every Exiobase region, direct to Azure industrydb,
local folders for all 49 by default. See PLAN-comprehensive.md.

Run via `EXIOBASE_YEAR=<year> python3 trade_comprehensive.py` (main.py's
run_comprehensive_processing() invokes it this way as a subprocess, the same
pattern trade.py's per-country invocation already uses). Reads
COMPREHENSIVE.folders from config.yaml ("all" or "default"), overridable via
EXIOBASE_COMPREHENSIVE_FOLDERS.

What this script does NOT do: run trade_impact.py/trade_resource.py/
trade_competitiveness.py for anything. That downstream analysis chain stays
scoped to the default-14 and is run by main.py's run_comprehensive_processing
afterward, exactly as it would under 'default'/'all' -- this script's job is
only the extraction + database push + local trade.csv/trade_factor.csv
derivation, matching trade.py's own scope for a single country.
"""

import os
import sys
import time
from pathlib import Path

import pandas as pd
import pymrio

from config_loader import (
    load_config, get_reference_file_path, get_comprehensive_folders_scope,
    get_comprehensive_target,
)
from exiobase_download import ensure_exiobase_file
from trade_extraction import (
    EXIOBASE_REGIONS, extract_region_chunk, build_factor_mapping,
    compute_trade_factor, ensure_industry_mapping, ensure_sector_tables,
    ensure_factors_export, write_flow_csv, write_comprehensive_runnote,
    write_timing_sidecar,
)
import industrydb


def describe_comprehensive_target(year, target):
    """(db_name, one-line note) for whichever Azure database this run/target
    combination points at -- shared between the confirmation banner and the
    preflight log line, so they can't drift out of sync with each other."""
    if target == industrydb.TARGET_SHARED:
        db_name = os.environ.get('EXIOBASE_NAME', '(EXIOBASE_NAME not set)')
        db_note = "shared, multi-year database -- year is a column on trade/trade_factor"
    else:
        db_name = industrydb.year_database_name(year)
        db_note = "dedicated per-year database, created if it doesn't already exist"
    return db_name, db_note


def confirm_comprehensive_push(year, target, folder_regions):
    """
    Prints where this run's data is headed and, on a TTY, blocks for a
    literal "y" before continuing -- there's no undo for a real push to
    Azure, and this is the first mode that pushes ALL 49 regions in one
    call rather than one country at a time. Non-interactive runs (cron,
    main.py's automated NODES pipeline) have no stdin to read a reply from,
    so they instead require EXIOBASE_COMPREHENSIVE_CONFIRM=yes to already be
    set -- failing fast with an explicit message rather than hanging on
    input() forever.
    """
    db_name, db_note = describe_comprehensive_target(year, target)
    host = os.environ.get('EXIOBASE_HOST', '(EXIOBASE_HOST not set)')

    print(f"\n{'='*80}")
    print(f"COMPREHENSIVE MODE -- {year}")
    print(f"{'='*80}")
    print(f"  Target database : {db_name}  (Azure PostgreSQL @ {host})")
    print(f"                    {db_note}")
    print(f"  Regions pushed  : all 49 Exiobase regions -> trade + trade_factor")
    print(f"  Local folders   : {len(folder_regions)}/49 written under year/{year}/<region>/")
    print(f"{'='*80}")

    if not sys.stdin.isatty():
        if os.environ.get('EXIOBASE_COMPREHENSIVE_CONFIRM', '').strip().lower() in ('y', 'yes', '1', 'true'):
            print("[COMPREHENSIVE] Non-interactive run, EXIOBASE_COMPREHENSIVE_CONFIRM set -- continuing.")
            return
        sys.exit(
            "No terminal attached to confirm this push -- set "
            "EXIOBASE_COMPREHENSIVE_CONFIRM=yes to run comprehensive mode non-interactively."
        )

    reply = input("Continue? [y/N]: ").strip().lower()
    if reply not in ('y', 'yes'):
        sys.exit("Aborted -- no data was pushed.")


def run_comprehensive(year):
    config = load_config()
    config['YEAR'] = year
    # Not print_config_summary() -- that assumes a single-flow TRADEFLOW
    # value (it calls get_output_folder(config) with no tradeflow_type,
    # defaulting to config['TRADEFLOW']), which comprehensive ignores
    # entirely (see PLAN-comprehensive.md's "config.yaml" section) and may
    # hold a comma-separated value that isn't a valid FOLDERS key at all.
    print("Configuration Summary:")
    print(f"  Mode: comprehensive (all 49 Exiobase regions)")
    print(f"  Year: {year}")

    folders_scope = get_comprehensive_folders_scope(config)
    target = get_comprehensive_target(config)
    from main import get_default_countries
    default_countries = set(get_default_countries())
    folder_regions = set(EXIOBASE_REGIONS) if folders_scope == 'all' else default_countries
    print(f"[COMPREHENSIVE] COMPREHENSIVE.folders={folders_scope} -> local folders for {len(folder_regions)}/{len(EXIOBASE_REGIONS)} regions")
    print(f"[COMPREHENSIVE] COMPREHENSIVE.target={target}")

    confirm_comprehensive_push(year, target, folder_regions)

    model_path = Path(__file__).parent / 'exiobase_data'
    model_path.mkdir(exist_ok=True)

    exio_file, actual_year = ensure_exiobase_file(model_path, year, 'pxp')
    year = actual_year
    if exio_file is None:
        sys.exit(
            f"Could not obtain Exiobase file for {year} -- comprehensive mode has no "
            "fallback-data path (unlike trade.py's single-country mode; see PLAN-comprehensive.md)."
        )

    print("Ensuring local reference files (industry.csv/sector.csv/sector_industry.csv/factor.csv)...")
    sector_mapping = ensure_industry_mapping(config)
    ensure_sector_tables(config)
    ensure_factors_export(config)

    print(f"Parsing Exiobase file: {exio_file}")
    exio_model = pymrio.parse_exiobase3(exio_file).calc_all()

    factors_df = pd.read_csv(get_reference_file_path(config, 'factors'))
    factor_mapping = build_factor_mapping(factors_df)

    print(f"[COMPREHENSIVE] Preflight: pushing reference tables to {describe_comprehensive_target(year, target)[0]}...")
    preflight = industrydb.push_reference_tables(
        year,
        factor_csv_path=get_reference_file_path(config, 'factors'),
        industry_csv_path=get_reference_file_path(config, 'industries'),
        sector_csv_path=get_reference_file_path(config, 'sectors'),
        sector_industry_csv_path=get_reference_file_path(config, 'sector_industry'),
        target=target,
    )
    print(f"[COMPREHENSIVE] Preflight done: region seeded ({preflight.get('region_seeded')} codes), "
          f"reference tables: {preflight.get('inserted')}")

    Z = exio_model.Z.copy()
    Z.index.names = ['from_region', 'from_sector']
    Z.columns.names = ['to_region', 'to_sector']

    running_trade_id = 0
    region_ranges = {}
    total_start = time.time()
    target_db_name = describe_comprehensive_target(year, target)[0]

    # One connection for the whole run (factor.csv re-export, the 49-region
    # push loop, and the imports-pull pass) instead of three separate
    # open/close cycles -- there's no gap between these phases that would
    # justify releasing the connection in between.
    conn = industrydb.get_connection(year, target=target)
    try:
        # Re-export local factor.csv from industrydb's own authoritative
        # table -- not the fresh local 1-based numbering
        # ensure_factors_export() just wrote, which only agrees with
        # industrydb's ids for the very first year ever merged (see
        # PLAN-comprehensive.md's "local factor.csv must also be exported
        # from industrydb.factor" note). factor_mapping was already correct
        # *if* factor.csv on disk was already industrydb's own numbering
        # going in (true for a from-scratch year); re-reading it after this
        # re-export makes disk and industrydb agree for a year merged after
        # others already exist, before any trade_factor row is computed.
        authoritative_factors = industrydb.pull_factor_reference(conn)
        authoritative_factors.to_csv(get_reference_file_path(config, 'factors'), index=False)
        print(f"[COMPREHENSIVE] Re-exported factor.csv from industrydb.factor ({len(authoritative_factors)} rows)")
        factor_mapping = build_factor_mapping(pd.read_csv(get_reference_file_path(config, 'factors')))

        for i, region in enumerate(EXIOBASE_REGIONS, 1):
            print(f"\n{'='*80}")
            print(f"[COMPREHENSIVE] {region} ({i}/{len(EXIOBASE_REGIONS)})")
            print(f"{'='*80}")
            region_start = time.time()

            trade_chunk = extract_region_chunk(Z, region, sector_mapping)
            n = len(trade_chunk)
            if n == 0:
                print(f"  No flows above threshold for {region}, skipping")
                continue

            base = running_trade_id
            trade_chunk = trade_chunk.copy()
            trade_chunk['trade_id'] = trade_chunk['trade_id'] + base
            running_trade_id += n
            region_ranges[region] = (base + 1, running_trade_id)

            trade_factor_chunk = compute_trade_factor(
                trade_chunk, exio_model, sector_mapping, factor_mapping,
                use_large_factors=False, log=None,
            )

            trade_id_flow_type = dict(zip(trade_chunk['trade_id'], trade_chunk['flow_type']))
            inserted_trade = industrydb.push_trade_rows(conn, trade_chunk, year=year, target=target)
            inserted_factor = industrydb.push_trade_factor_rows(
                conn, trade_factor_chunk, region, trade_id_flow_type, year=year, target=target,
            )

            if region in folder_regions:
                domestic_rows = trade_chunk[trade_chunk['region2'] == region]
                exports_rows = trade_chunk[trade_chunk['region2'] != region]
                domestic_ids = set(domestic_rows['trade_id'])
                exports_ids = set(exports_rows['trade_id'])
                domestic_factor = trade_factor_chunk[trade_factor_chunk['trade_id'].isin(domestic_ids)]
                exports_factor = trade_factor_chunk[trade_factor_chunk['trade_id'].isin(exports_ids)]

                write_flow_csv(config, region, 'domestic', domestic_rows, domestic_factor)
                write_flow_csv(config, region, 'exports', exports_rows, exports_factor)

                if region not in default_countries:
                    write_comprehensive_runnote(
                        config, year, region, 'domestic',
                        source="trade_comprehensive.py (sliced from in-memory region chunk)",
                    )
                    write_comprehensive_runnote(
                        config, year, region, 'exports',
                        source="trade_comprehensive.py (sliced from in-memory region chunk)",
                    )

            elapsed = time.time() - region_start
            print(f"  {region}: pushed {inserted_trade}/{n} trade rows (ids {base+1}-{running_trade_id}) and "
                  f"{inserted_factor}/{len(trade_factor_chunk)} trade_factor rows to {target_db_name} "
                  f"(a gap below the total means those rows already existed from a previous run) in {elapsed:.1f}s")

        total_elapsed = time.time() - total_start
        print(f"\n[COMPREHENSIVE] All 49 regions pushed to {target_db_name}: "
              f"{running_trade_id} trade rows total, {total_elapsed/60:.1f} minutes")

        print(f"\n[COMPREHENSIVE] Pulling imports for {len(folder_regions)} in-scope region(s) from {target_db_name}...")
        for region in sorted(folder_regions):
            pull_start = time.time()
            imports_trade, imports_factor = industrydb.pull_flow(conn, region, 'imports', year=year, target=target)
            pull_seconds = time.time() - pull_start

            write_flow_csv(config, region, 'imports', imports_trade, imports_factor)

            if region in default_countries:
                write_timing_sidecar(config, region, pull_seconds)
            else:
                write_comprehensive_runnote(
                    config, year, region, 'imports',
                    source="trade_comprehensive.py (pulled from industrydb)",
                    seconds=pull_seconds,
                )

            print(f"  {region}: {len(imports_trade)} imports rows pulled in {pull_seconds:.1f}s")
    finally:
        conn.close()

    print(f"\n[COMPREHENSIVE] Done. {len(folder_regions)} region folder(s) written under year/{year}/.")


if __name__ == "__main__":
    import os
    run_comprehensive(int(os.environ.get('EXIOBASE_YEAR', load_config()['YEAR'])))
