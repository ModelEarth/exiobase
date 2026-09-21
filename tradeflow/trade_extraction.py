#!/usr/bin/env python3
"""
Shared Exiobase extraction helpers used by both the per-country pipeline
(trade.py) and the comprehensive all-region pipeline (trade_comprehensive.py
and export_country_csvs.py). Pulled out of trade.py's ExiobaseTradeFlow
class per PLAN-comprehensive.md's "Memory management" section, so
trade_comprehensive.py's per-region loop doesn't duplicate the
factor-aggregation/merge logic -- and, further down, the local `.csv`/
`runnote.md` writers both trade_comprehensive.py and export_country_csvs.py
need, so they don't each keep their own copy of that format either.
"""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config_loader import get_file_path, get_output_folder, get_reference_file_path
from exiobase_factors import (
    EPA_GHG_FLOWS, AGGREGATE_FACTOR_IDS,
    EXTENSION_AGGREGATE_FACTOR_IDS, EXTENSION_STRESSOR_PREFIXES,
)

TRADE_COLUMNS = ['trade_id', 'region1', 'region2', 'industry1', 'industry2', 'amount']
TRADE_FACTOR_COLUMNS = ['trade_id', 'factor_id', 'level']

# Exiobase's own region order, confirmed by reading unit.txt/Z.txt directly
# out of a downloaded IOT_*_pxp.zip (see PLAN-comprehensive.md's "Confirmed:
# Exiobase's regions have a fixed, discoverable order") -- EU-27 first, then
# non-EU OECD-ish countries, then 5 Rest-of-World aggregates last. Stable
# across at least the 2019-2023 files already downloaded; pymrio's
# parse_exiobase3 always yields this column order, since it comes straight
# from Exiobase's own file format, not something this loader controls.
EXIOBASE_REGIONS = [
    'AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR',
    'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'RO',
    'SE', 'SI', 'SK', 'GB', 'US', 'JP', 'CN', 'CA', 'KR', 'BR', 'IN', 'MX',
    'RU', 'AU', 'CH', 'TR', 'TW', 'NO', 'ID', 'ZA', 'WA', 'WL', 'WE', 'WF',
    'WM',
]

# Same thresholds trade.py's extract_m_matrix_data already uses (domestic
# gets a lower bar than international flows).
DOMESTIC_FLOW_THRESHOLD = 0.001
INTERNATIONAL_FLOW_THRESHOLD = 0.01

FACTOR_EXTENSIONS = ['air_emissions', 'employment', 'energy', 'land', 'material', 'water']


def aggregate_factors(F_stacked, ext_name):
    """
    Collapse raw per-stressor coefficients into a small set of aggregated
    flows for the default trade_factor.csv (see exiobase_factors.py for the
    per-extension scoping rules). Moved out of trade.py's
    ExiobaseTradeFlow._aggregate_factors unchanged -- a module-level
    function now, since it never touched `self`.
    """
    if ext_name == 'air_emissions':
        prefix = F_stacked['stressor'].astype(str).str.split(' - ', n=1).str[0]
        flow = prefix.map(EPA_GHG_FLOWS)
        matched = F_stacked[flow.notna()].copy()
        if matched.empty:
            return matched.assign(factor_id=[])[['region', 'sector', 'industry_id', 'factor_id', 'coefficient']]
        matched['factor_id'] = flow[flow.notna()].map(AGGREGATE_FACTOR_IDS).values
        result = (
            matched.groupby(['region', 'industry_id', 'factor_id'], as_index=False)['coefficient']
            .sum()
        )
    elif ext_name in EXTENSION_AGGREGATE_FACTOR_IDS:
        prefixes = EXTENSION_STRESSOR_PREFIXES.get(ext_name)
        scoped = F_stacked
        if prefixes:
            scoped = F_stacked[F_stacked['stressor'].astype(str).str.startswith(tuple(prefixes))]
        result = scoped.groupby(['region', 'industry_id'], as_index=False)['coefficient'].sum()
        result['factor_id'] = EXTENSION_AGGREGATE_FACTOR_IDS[ext_name]
    else:
        result = F_stacked.iloc[0:0][['region', 'industry_id', 'coefficient']].copy()
        result['factor_id'] = []

    return result[['region', 'industry_id', 'factor_id', 'coefficient']]


def build_factor_mapping(factors_df):
    """
    Exact stressor-name -> factor_id mapping, plus formatting-variant
    aliases (PM2_5/PM2.5, '_'<->'.'). Moved out of trade.py's
    create_trade_factor unchanged.
    """
    factor_mapping = dict(zip(factors_df['stressor'], factors_df['factor_id']))
    robust_mapping = factor_mapping.copy()
    for name, factor_id in factor_mapping.items():
        if 'PM2_5' in name:
            robust_mapping['PM2.5'] = factor_id
        elif 'PM2.5' in name:
            robust_mapping['PM2_5'] = factor_id
        robust_mapping[name.replace('_', '.')] = factor_id
        robust_mapping[name.replace('.', '_')] = factor_id
    return robust_mapping


def compute_trade_factor(trade_df, exio_model, sector_mapping, factor_mapping, use_large_factors=False, log=None):
    """
    Compute trade_factor rows (trade_id, factor_id, level) for trade_df
    against exio_model's per-extension M matrices. Same computation as
    trade.py's ExiobaseTradeFlow.create_trade_factor, minus the file I/O and
    minus `self` -- the caller decides where the result goes (a local .csv
    for trade.py, an industrydb COPY for trade_comprehensive.py) and
    supplies its own sector_mapping/factor_mapping instead of reading
    self.sector_mapping / re-reading factor.csv from disk each call.

    Returns a DataFrame with columns trade_id, factor_id, level (empty with
    those columns if trade_df is empty or nothing matched).
    """
    def _log(msg):
        if log is not None:
            log(msg)

    if trade_df.empty:
        return pd.DataFrame(columns=['trade_id', 'factor_id', 'level'])

    all_trade_factor = []

    for ext_name in FACTOR_EXTENSIONS:
        if not hasattr(exio_model, ext_name):
            continue
        ext = getattr(exio_model, ext_name)
        if not hasattr(ext, 'M'):
            continue

        _log(f"Processing {ext_name} factors for trade flows...")

        # A handful of raw Exiobase cells are NaN (typically a 0/0 from a
        # sector with zero output in some region) rather than 0 -- fillna(0)
        # here before any aggregation, or a single poisoned cell silently
        # NaNs out an aggregated flow that has real data from its other
        # contributing stressors (see trade.py's original comment on this).
        M_matrix = ext.M.fillna(0)
        F_stacked = M_matrix.stack(level=['region', 'sector'], future_stack=True).reset_index()
        F_stacked.columns = ['stressor', 'region', 'sector', 'coefficient']
        F_stacked = F_stacked[F_stacked['coefficient'] != 0].copy()

        F_stacked['industry_id'] = F_stacked['sector'].map(sector_mapping)
        F_stacked = F_stacked.dropna(subset=['industry_id'])

        F_stacked['factor_id'] = F_stacked['stressor'].map(factor_mapping)
        F_stacked = F_stacked.dropna(subset=['factor_id'])

        if not use_large_factors:
            F_stacked = aggregate_factors(F_stacked, ext_name)

        if F_stacked.empty:
            continue

        F_stacked = F_stacked.set_index(['region', 'industry_id'])

        chunk_size = 10000
        trade_factor_chunks = []
        for i in range(0, len(trade_df), chunk_size):
            chunk_df = trade_df.iloc[i:i + chunk_size]
            trade_factor_chunk = chunk_df.merge(
                F_stacked.reset_index(),
                left_on=['region1', 'industry1'],
                right_on=['region', 'industry_id'],
                how='inner',
            )
            if not trade_factor_chunk.empty:
                trade_factor_chunks.append(trade_factor_chunk)

        if not trade_factor_chunks:
            continue
        trade_factor_merge = pd.concat(trade_factor_chunks, ignore_index=True)

        trade_factor_merge['level'] = trade_factor_merge['amount'] * trade_factor_merge['coefficient']
        if ext_name in ('water', 'air_emissions'):
            trade_factor_merge['level'] = trade_factor_merge['level'].round(3)
        else:
            trade_factor_merge['level'] = trade_factor_merge['level'].round(0).astype(int)

        trade_factor_merge = trade_factor_merge[abs(trade_factor_merge['level']) > 0.001]
        if trade_factor_merge.empty:
            continue

        trade_factor_subset = trade_factor_merge[['trade_id', 'factor_id', 'level']].dropna(subset=['factor_id'])
        if trade_factor_subset.empty:
            continue

        trade_factor_subset = trade_factor_subset.copy()
        trade_factor_subset['factor_id'] = trade_factor_subset['factor_id'].astype(int)
        all_trade_factor.extend(trade_factor_subset.to_dict('records'))

    if all_trade_factor:
        return pd.DataFrame(all_trade_factor)
    return pd.DataFrame(columns=['trade_id', 'factor_id', 'level'])


def extract_region_chunk(Z, region, sector_mapping):
    """
    One region's own outbound flows (exports + domestic together), sliced
    out of the full Z matrix *before* reshaping to long format -- the one
    non-negotiable mechanism change from trade.py's extract_m_matrix_data
    (which stacks the whole 9,800 x 9,800 matrix first, then filters by a
    boolean mask). `Z.loc[region]` -- this region's ~200 rows x 9,800
    columns -- is reshaped on its own, never the full matrix. See
    PLAN-comprehensive.md's "Extraction" and "Memory management" sections
    for the measured ~40x memory difference this makes (a full-matrix stack
    is ~10GB peak RSS; a per-region slice stays within ~50MB of the
    ~4.3GB baseline of just having the model parsed).

    Reshaped with numpy (repeat/tile/ravel), not `DataFrame.stack()`:
    verified against the real 2021 file that `.stack(future_stack=True)`
    unconditionally re-sorts its output alphabetically by region (no way to
    opt out -- `sort=False` raises `ValueError` under `future_stack=True`),
    which would silently throw away Exiobase's own row order even though
    `Z.loc[region]` itself is confirmed already in that native order (see
    README.md's "Exiobase trade record order" section). The old,
    non-future stack implementation does support `sort=False` and preserves
    order correctly, but is deprecated and slated for removal. The numpy
    reshape sidesteps the whole question -- and, measured, is also ~10x
    faster than either stack variant for one region.

    Domestic (region2 == region) keeps a lower amount threshold than
    international rows, same as trade.py. `flow_type` is 'domestic' or
    'international' -- there's no imports/exports distinction any more,
    since that was only ever about *whose file* a row came from (see
    PLAN-comprehensive.md's "Extraction" section) and there's only one
    file/push per region now.

    Returns a DataFrame with columns trade_id, region1, region2, industry1,
    industry2, amount, flow_type. trade_id is 1-based *within this chunk
    only* -- the caller offsets it into the running whole-year counter
    before writing/pushing anywhere.
    """
    region_slice = Z.loc[region]
    from_sectors = region_slice.index.to_numpy()
    to_regions = region_slice.columns.get_level_values('to_region').to_numpy()
    to_sectors = region_slice.columns.get_level_values('to_sector').to_numpy()
    n_from, n_to = len(from_sectors), len(to_regions)

    chunk = pd.DataFrame({
        'from_sector': np.repeat(from_sectors, n_to),
        'to_region': np.tile(to_regions, n_from),
        'to_sector': np.tile(to_sectors, n_from),
        'flow': region_slice.to_numpy().ravel(),
    })

    # industry_order: each industry_id's position, in Exiobase's own fixed
    # sector order (from_sectors -- the same 200-sector list/order for every
    # region), of its *first* constituent raw sector -- computed once here,
    # entirely independent of `region` or the amount threshold below.
    # Deliberately NOT based on "the first surviving cell after filtering":
    # confirmed against real 2021 data that the threshold removes cells
    # unevenly across destinations (e.g. Malta's very first raw sector has
    # zero measured flow to Austria specifically, but not to Italy), so a
    # survival-based order would just reflect which regions/industries
    # happen to trade early in the sector list that particular year, not
    # Exiobase's actual, fixed column position.
    industry_order = {}
    for pos, raw_sector in enumerate(from_sectors):
        industry_id = sector_mapping.get(raw_sector)
        if industry_id is not None and industry_id not in industry_order:
            industry_order[industry_id] = pos

    is_domestic = chunk['to_region'] == region
    keep = (
        (is_domestic & (chunk['flow'] > DOMESTIC_FLOW_THRESHOLD)) |
        (~is_domestic & (chunk['flow'] > INTERNATIONAL_FLOW_THRESHOLD))
    )
    chunk = chunk[keep].copy()

    # Categorical dtype immediately, before the frame grows any further --
    # see PLAN-comprehensive.md's measured ~19x reduction from this alone
    # (492MB -> 25.5MB for a single region's stacked chunk).
    for col in ('from_sector', 'to_region', 'to_sector'):
        chunk[col] = chunk[col].astype('category')

    chunk['industry1'] = chunk['from_sector'].map(sector_mapping)
    chunk['industry2'] = chunk['to_sector'].map(sector_mapping)
    chunk = chunk.dropna(subset=['industry1', 'industry2'])
    # .map() on a Categorical Series (from_sector/to_sector) returns a
    # Categorical result too -- cast to plain str now that the real NaNs are
    # gone (matters for the merge against F_stacked's plain-str industry_id
    # in compute_trade_factor).
    chunk['industry1'] = chunk['industry1'].astype(str)
    chunk['industry2'] = chunk['industry2'].astype(str)
    chunk['region2'] = chunk['to_region'].astype(str)

    if chunk.empty:
        return pd.DataFrame(columns=[
            'trade_id', 'region1', 'region2', 'industry1', 'industry2', 'amount', 'flow_type',
        ])

    trade_data = chunk.groupby(['region2', 'industry1', 'industry2'], as_index=False).agg(
        amount=('flow', 'sum'),
    )
    trade_data['region1'] = region

    # Keep the historical 2dp trade.csv format, but do not carry rows that
    # would be written as 0.00 into trade_factor.csv or BEA interstate data
    # -- same rule trade.py's extract_m_matrix_data applies.
    rounded_zero_rows = trade_data['amount'].round(2) <= 0
    if rounded_zero_rows.any():
        trade_data = trade_data[~rounded_zero_rows].copy()

    # trade_id order follows Exiobase's own row order (README.md's "Exiobase
    # trade record order" section), not an alphabetical re-sort: region2 by
    # its fixed block position in EXIOBASE_REGIONS, then industry1/industry2
    # by their fixed sector position (industry_order, above) -- entirely
    # structural, so a resumed/retried run always reproduces the same order
    # regardless of which rows happened to survive this particular
    # threshold pass.
    region_rank = {r: i for i, r in enumerate(EXIOBASE_REGIONS)}
    trade_data = trade_data.sort_values(
        by=['region2', 'industry1', 'industry2'],
        key=lambda col: (
            col.map(region_rank) if col.name == 'region2' else col.map(industry_order)
        ),
    ).reset_index(drop=True)
    trade_data['trade_id'] = trade_data.index + 1
    trade_data['flow_type'] = np.where(trade_data['region2'] == region, 'domestic', 'international')

    return trade_data[[
        'trade_id', 'region1', 'region2', 'industry1', 'industry2', 'amount', 'flow_type',
    ]]


def ensure_industry_mapping(config):
    """
    Load the sector -> 5-char industry_id mapping from industry.csv, or
    create it if it doesn't exist yet. Moved out of trade.py's
    ExiobaseTradeFlow.load_sector_mapping unchanged -- the underlying
    create_sector_mapping() call re-reads config itself (via
    config_loader.load_config()), so this only needs `config` for the
    existence check.
    """
    industries_file = get_reference_file_path(config, 'industries')

    if Path(industries_file).exists():
        print("Loading existing sector mapping from industry.csv")
        mapping_df = pd.read_csv(industries_file)
        return dict(zip(mapping_df['name'], mapping_df['industry_id']))

    print("Creating new sector mapping...")
    from create_sector_mapping import create_sector_mapping
    mapping_df = create_sector_mapping()
    if mapping_df is None:
        print("Warning: Could not create sector mapping (Exiobase zip unavailable). Using empty mapping.")
        return {}
    return dict(zip(mapping_df['name'], mapping_df['industry_id']))


def ensure_sector_tables(config):
    """
    Create sector.csv and sector_industry.csv if they don't exist yet
    (requires industry.csv, written by ensure_industry_mapping, to exist).
    Moved out of trade.py's ExiobaseTradeFlow.create_sector_tables unchanged.
    """
    sectors_file = get_reference_file_path(config, 'sectors')
    sector_industry_file = get_reference_file_path(config, 'sector_industry')

    if Path(sectors_file).exists() and Path(sector_industry_file).exists():
        print("sector.csv and sector_industry.csv already exist")
        return

    print("Creating sector.csv / sector_industry.csv...")
    from create_sector_mapping import create_sector_table, create_sector_industry_table
    create_sector_table()
    create_sector_industry_table()


def ensure_factors_export(config):
    """
    Create the factor.csv export if it doesn't exist. Moved out of trade.py's
    ExiobaseTradeFlow.create_factors_export unchanged.
    """
    factors_file = get_reference_file_path(config, 'factors')

    if Path(factors_file).exists():
        print("factor.csv already exists")
        return

    print("Creating factor.csv from Exiobase extensions...")
    try:
        from factors import create_factors_csv
        create_factors_csv()
    except Exception as e:
        print(f"Failed to create factor.csv: {e}")


def write_flow_csv(config, region, kind, trade_rows, trade_factor_rows):
    """
    Write one region's kind ('domestic'/'exports'/'imports') folder in the
    exact format trade.py already produces, so trade_impact.py/
    trade_resource.py/trade_competitiveness.py/bea/main.py/india/main.py
    keep working unmodified against it -- used by both
    trade_comprehensive.py (during/after its region loop) and
    export_country_csvs.py (the later ad-hoc exporter), so a region's local
    folder always ends up byte-for-byte the same shape regardless of which
    of the two produced it. `config['COUNTRY']` is mutated on a copy
    (cheaper than a fresh load_config() call per region -- get_file_path
    only ever reads the dict it's given).
    """
    config = dict(config)
    config['COUNTRY'] = {'current': region}

    trade_path = get_file_path(config, 'industryflow', tradeflow_type=kind)
    factor_path = get_file_path(config, 'trade_factor', tradeflow_type=kind)

    trade_rows[TRADE_COLUMNS].to_csv(trade_path, index=False, float_format='%.2f')
    trade_factor_rows[TRADE_FACTOR_COLUMNS].to_csv(factor_path, index=False)
    return trade_path, factor_path


def write_comprehensive_runnote(config, year, region, kind, source, seconds=None):
    """
    runnote.md for a region/kind folder derived straight from industrydb --
    no trade_impact.py/trade_resource.py/trade_competitiveness.py chain ran
    for it (that stays scoped to the default-14 via main.py's
    run_comprehensive_processing/run_country_processing, which writes its
    own runnote.md via create_runnote() -- see PLAN-comprehensive.md's
    "Local .csv output for country folders"). Used for every non-default
    region under COMPREHENSIVE.folders: all, and by export_country_csvs.py
    for any later ad-hoc folder (default or not -- nothing runs the
    downstream chain for those after the fact either).
    """
    config = dict(config)
    config['COUNTRY'] = {'current': region}
    folder = Path(get_output_folder(config, kind))
    folder.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# {year} {region} {kind.title()} - Comprehensive Run Note",
        "",
        f"**Processing Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Source:** {source}",
    ]
    if seconds is not None:
        lines.append(f"**Imports export (Azure):** {seconds:.1f}s")
    lines += [
        "",
        "## Processing Notes",
        "Generated from industrydb (see PLAN-comprehensive.md). No per-country analysis scripts "
        "(trade_impact.py/trade_resource.py/trade_competitiveness.py) ran for this folder.",
    ]
    (folder / "runnote.md").write_text("\n".join(lines) + "\n")
