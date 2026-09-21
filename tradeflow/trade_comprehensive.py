#!/usr/bin/env python3
"""
Comprehensive trade push: every Exiobase region, direct to Azure industrydb,
local folders for all 49 by default. See PLAN-comprehensive.md.

Run via `EXIOBASE_YEAR=<year> python3 trade_comprehensive.py` (main.py's
run_comprehensive_processing() invokes it this way as a subprocess, the same
pattern trade.py's per-country invocation already uses). Reads
COMPREHENSIVE.folders from config.yaml ("all" or "default"), overridable via
EXIOBASE_COMPREHENSIVE_FOLDERS or its short alias SCOPE -- "default" limits
both the Azure push and local .csv output to the 14 default-list countries
(added for the 2024 run; 2018 used "all").

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
    TRADE_COLUMNS, TRADE_FACTOR_COLUMNS,
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
    Azure. Non-interactive runs (cron, main.py's automated NODES pipeline)
    have no stdin to read a reply from, so they instead require
    EXIOBASE_COMPREHENSIVE_CONFIRM=yes to already be set -- failing fast
    with an explicit message rather than hanging on input() forever.

    folder_regions is also the push scope as of the 2024 run (see
    run_comprehensive's region loop and PLAN-comprehensive.md's "Database
    write path" -- COMPREHENSIVE.folders="default" now limits the Azure
    push to those regions too, not just local .csv output; 2018 used
    folders="all", pushing and writing every region).
    """
    db_name, db_note = describe_comprehensive_target(year, target)
    host = os.environ.get('EXIOBASE_HOST', '(EXIOBASE_HOST not set)')

    print(f"\n{'='*80}")
    print(f"COMPREHENSIVE MODE -- {year}")
    print(f"{'='*80}")
    print(f"  Target database : {db_name}  (Azure PostgreSQL @ {host})")
    print(f"                    {db_note}")
    print(f"  Regions pushed  : {len(folder_regions)}/49 Exiobase regions -> trade + trade_factor")
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


def capture_imports_for_others(trade_chunk, trade_factor_chunk, region, folder_regions,
                                exio_model, sector_mapping, factor_mapping):
    """
    A region's own chunk (region1 == region) already contains every OTHER
    in-scope country's imports FROM this region, as its rows where region2
    is one of folder_regions -- captured here instead of a separate Azure
    pull, so imports.csv can be assembled purely from this run's in-memory
    Z matrix (see PLAN-comprehensive.md's "Local .csv output for country
    folders"). This runs for every one of the 49 regions, in scope or not:
    an out-of-scope exporter can still trade with an in-scope importer, and
    that flow has to reach the importer's imports.csv even though the
    exporter's own domestic/exports never get pushed or written anywhere.

    trade_id is already the correct, globally-ordered value from the
    caller's running_trade_id offset -- untouched here, so an importer's
    imports.csv naturally ends up with ids scattered across the full
    49-region range (grouped by exporter, not sequential), exactly
    reflecting each flow's true position in Exiobase's own row order.

    trade_factor_chunk: pass the already-computed whole-chunk result (an
    in-scope region computes it anyway, for its own push) to reuse via a
    trade_id filter instead of recomputing; pass None to compute it fresh,
    scoped to just the matched rows (cheaper for an out-of-scope region,
    which has no other reason to run compute_trade_factor at all --
    row-independent since it only merges on region1/industry1, the
    exporter's own side, so a subset computes identically to the same rows
    inside a full-chunk pass).

    Returns {country: (trade_df, factor_df)} for every folder_regions
    country this chunk contributes anything to.
    """
    others = trade_chunk[(trade_chunk['region2'] != region) & trade_chunk['region2'].isin(folder_regions)]
    if others.empty:
        return {}

    if trade_factor_chunk is not None:
        others_factor = trade_factor_chunk[trade_factor_chunk['trade_id'].isin(set(others['trade_id']))]
    else:
        others_factor = compute_trade_factor(
            others, exio_model, sector_mapping, factor_mapping,
            use_large_factors=False, log=None,
        )

    result = {}
    for dest, group in others.groupby('region2', observed=True):
        dest_factor = others_factor[others_factor['trade_id'].isin(set(group['trade_id']))]
        result[dest] = (group, dest_factor)
    return result


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
    # folder_regions is also the Azure push scope, as of the 2024 run (see
    # the region loop below) -- "default" now means only these regions'
    # trade/trade_factor rows reach Azure at all, not just local .csv
    # output. trade_id numbering still runs across all 49 regions in
    # Exiobase's own fixed order regardless (see running_trade_id below),
    # so an excluded region's rows leave a gap in the sequence rather than
    # shifting later regions' ids -- a later "all" run for the same year
    # would assign the exact same ids to the already-pushed regions.
    folder_regions = set(EXIOBASE_REGIONS) if folders_scope == 'all' else default_countries
    print(f"[COMPREHENSIVE] COMPREHENSIVE.folders={folders_scope} -> local folders + Azure push for {len(folder_regions)}/{len(EXIOBASE_REGIONS)} regions")
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

    # Every in-scope country's imports are assembled here, straight from
    # this run's own in-memory extraction (see capture_imports_for_others) --
    # no Azure round-trip, and correct regardless of push scope: an
    # out-of-scope exporter's flows to an in-scope importer still get
    # captured even though that exporter's own domestic/exports never reach
    # Azure or disk anywhere else.
    imports_trade_acc = {r: [] for r in folder_regions}
    imports_factor_acc = {r: [] for r in folder_regions}

    # One connection for the whole run (factor.csv re-export and the
    # 49-region push loop) instead of separate open/close cycles -- there's
    # no gap between these phases that would justify releasing the
    # connection in between.
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

            # Out-of-scope region (COMPREHENSIVE.folders="default"): trade_id
            # still advances past its rows -- preserving the same numbering a
            # full "all" run would assign -- but nothing is pushed/written
            # for its own domestic/exports. Its exports TO an in-scope
            # country still count as that country's imports, though (see
            # capture_imports_for_others) -- trade_factor_chunk=None so this
            # only computes factors for whichever rows actually match,
            # instead of the whole (otherwise-unused) chunk.
            if region not in folder_regions:
                captured = capture_imports_for_others(
                    trade_chunk, None, region, folder_regions,
                    exio_model, sector_mapping, factor_mapping,
                )
                for dest, (t, f) in captured.items():
                    imports_trade_acc[dest].append(t)
                    imports_factor_acc[dest].append(f)

                elapsed = time.time() - region_start
                print(f"  {region}: out of scope (COMPREHENSIVE.folders={folders_scope}) -- "
                      f"{n} row(s) reserved (ids {base+1}-{running_trade_id}), nothing pushed, "
                      f"{len(captured)} in-scope countries' imports captured, in {elapsed:.1f}s")
                continue

            trade_factor_chunk = compute_trade_factor(
                trade_chunk, exio_model, sector_mapping, factor_mapping,
                use_large_factors=False, log=None,
            )

            trade_id_flow_type = dict(zip(trade_chunk['trade_id'], trade_chunk['flow_type']))
            inserted_trade = industrydb.push_trade_rows(conn, trade_chunk, year=year, target=target)
            inserted_factor = industrydb.push_trade_factor_rows(
                conn, trade_factor_chunk, region, trade_id_flow_type, year=year, target=target,
            )

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

            # This region's own exports_rows already contains every OTHER
            # in-scope country's imports from it -- reuses trade_factor_chunk
            # (already computed above for the push) via a trade_id filter
            # instead of recomputing.
            captured = capture_imports_for_others(
                trade_chunk, trade_factor_chunk, region, folder_regions,
                exio_model, sector_mapping, factor_mapping,
            )
            for dest, (t, f) in captured.items():
                imports_trade_acc[dest].append(t)
                imports_factor_acc[dest].append(f)

            elapsed = time.time() - region_start
            print(f"  {region}: pushed {inserted_trade}/{n} trade rows (ids {base+1}-{running_trade_id}) and "
                  f"{inserted_factor}/{len(trade_factor_chunk)} trade_factor rows to {target_db_name} "
                  f"(a gap below the total means those rows already existed from a previous run) in {elapsed:.1f}s")

        total_elapsed = time.time() - total_start
        print(f"\n[COMPREHENSIVE] {len(folder_regions)}/{len(EXIOBASE_REGIONS)} regions pushed to {target_db_name} "
              f"(trade_id 1-{running_trade_id} reserved across all 49, per Exiobase's own row order): "
              f"{total_elapsed/60:.1f} minutes")
    finally:
        conn.close()

    print(f"\n[COMPREHENSIVE] Assembling imports for {len(folder_regions)} in-scope region(s) "
          f"from this run's in-memory extraction (no Azure pull needed)...")
    for region in sorted(folder_regions):
        imports_trade = (
            pd.concat(imports_trade_acc[region], ignore_index=True) if imports_trade_acc[region]
            else pd.DataFrame(columns=TRADE_COLUMNS)
        )
        imports_factor = (
            pd.concat(imports_factor_acc[region], ignore_index=True) if imports_factor_acc[region]
            else pd.DataFrame(columns=TRADE_FACTOR_COLUMNS)
        )

        write_flow_csv(config, region, 'imports', imports_trade, imports_factor)

        if region not in default_countries:
            write_comprehensive_runnote(
                config, year, region, 'imports',
                source="trade_comprehensive.py (assembled in-memory during the region loop)",
            )

        print(f"  {region}: {len(imports_trade)} imports rows assembled from "
              f"{len(imports_trade_acc[region])} contributing region(s)")

    print(f"\n[COMPREHENSIVE] Done. {len(folder_regions)} region folder(s) written under year/{year}/.")


if __name__ == "__main__":
    import os
    run_comprehensive(int(os.environ.get('EXIOBASE_YEAR', load_config()['YEAR'])))
