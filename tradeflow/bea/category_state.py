#!/usr/bin/env python3
"""
State allocation weights and state supply-chain inputs for US trade-data.

bea/main.py splits each national US-to-US flow among state pairs with BEA
Regional weights: GDP by state for the supplying industry's broad category
(origin) times GDP by state for the buying industry's category (destination).
Because a state pair's share is that product, the weights alone describe the
whole split, for all 50 states and DC. This module writes them, and the files
profile/item (the product label's Top 10 Industries Supplying Production, UN
option) reads, into year/{year}/US/:

- domestic/category_state.csv: each state's share of each category's US GDP, as
  origin and destination weights (state_industry_code, weight_type, state,
  weight, value, source_table, line_code). Weights sum to 1 per category and
  weight_type.
- domestic/industry_category.csv: each Exiobase industry's category
  (state_industry_code), as main_trade_analyzer.py assigns it.
- domestic/trade-us.csv: the national purchases of each Exiobase industry
  (industry2), by supplying industry1 and origin ("us" for US producers,
  "foreign" for imports summed over countries), with amount (M EUR) and
  factor_id 901-910 from trade_factor.csv. It's the trade_us SQL view in
  bea/README.md, written out for visualizations that read .csv files.

For a buying state ST, with o = origin weight of industry1's category and
d = destination weight of industry2's category in ST, a US flow splits into
amount * o * d bought in-state and amount * (1 - o) * d from other states, and
imports of the same industry pair place amount * d in ST.

bea/main.py runs this after its trade flows. To rebuild from existing trade.csv
files, using cached BEA responses of any age and fetching only missing ones
with BEA_API_KEY (found as bea/main.py finds it, via automation/paths.yaml):

    python bea/category_state.py 2019      (run from exiobase/tradeflow, like main.py)
"""

from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd


FACTOR_IDS = ("901", "902", "903", "904", "905", "906", "907", "908", "909", "910")
SIGNIFICANT_DIGITS = 6
CATEGORY_STATE_FILE = "category_state.csv"
CATEGORY_STATE_COLUMNS = ["state_industry_code", "weight_type", "state", "weight", "value", "source_table", "line_code"]

BEA_ORIGIN_ALLOCATION_LINES = {
    'agriculture': ('SAGDP2', 3, 'GDP by state: Agriculture, forestry, fishing and hunting'),
    'mining': ('SAGDP2', 6, 'GDP by state: Mining, quarrying, oil, and gas extraction'),
    'utilities': ('SAGDP2', 10, 'GDP by state: Utilities'),
    'construction': ('SAGDP2', 11, 'GDP by state: Construction'),
    'manufacturing': ('SAGDP2', 12, 'GDP by state: Manufacturing'),
    'transportation': ('SAGDP2', 36, 'GDP by state: Transportation and warehousing'),
    'services': ('SAGDP2', 92, 'GDP by state: Private services-providing industries'),
}

BEA_DESTINATION_ALLOCATION_LINES = {
    'agriculture':    ('SAGDP2', 3,  'GDP by state: Agriculture, forestry, fishing and hunting'),
    'mining':         ('SAGDP2', 6,  'GDP by state: Mining, quarrying, oil, and gas extraction'),
    'utilities':      ('SAGDP2', 10, 'GDP by state: Utilities'),
    'construction':   ('SAGDP2', 11, 'GDP by state: Construction'),
    'manufacturing':  ('SAGDP2', 12, 'GDP by state: Manufacturing'),
    'transportation': ('SAGDP2', 36, 'GDP by state: Transportation and warehousing'),
    'services':       ('SAGDP2', 92, 'GDP by state: Private services-providing industries'),
}


def compact(value: float) -> str:
    """A number at 6 significant digits, without a trailing .0"""
    if value == 0:
        return "0"
    text = f"{value:.{SIGNIFICANT_DIGITS}g}"
    return text[:-2] if text.endswith(".0") else text


def state_allocation_weights(regional_df, state_codes, year, category, weight_type,
                             table_name, line_code, description):
    """Convert a BEA Regional response into normalized state allocation weights."""
    required_cols = {'state_name', 'value'}
    if regional_df.empty or not required_cols.issubset(regional_df.columns):
        return pd.DataFrame()

    state_lookup = dict(zip(state_codes['state_name'], state_codes['state_code']))

    weights = regional_df.copy()
    weights['state_name'] = (
        weights['state_name']
        .astype(str)
        .str.replace('*', '', regex=False)
        .str.strip()
    )
    weights['state'] = weights['state_name'].map(state_lookup)
    weights['value'] = pd.to_numeric(weights['value'], errors='coerce')
    weights = weights[weights['state'].notna() & (weights['value'] > 0)]

    if weights.empty:
        return pd.DataFrame()

    weights = weights.groupby(['state', 'state_name'], as_index=False)['value'].sum()
    total_value = weights['value'].sum()
    if total_value <= 0:
        return pd.DataFrame()

    weights['weight'] = weights['value'] / total_value
    weights['year'] = year
    weights['state_industry_code'] = category
    weights['weight_type'] = weight_type
    weights['source_table'] = table_name
    weights['line_code'] = line_code
    weights['source_description'] = description

    return weights[
        [
            'year',
            'state_industry_code',
            'state',
            'state_name',
            'weight_type',
            'weight',
            'value',
            'source_table',
            'line_code',
            'source_description',
        ]
    ]


def fetch_state_allocation_weights(bea_client, year, state_codes):
    """BEA Regional GDP by state for each category, as origin and destination weights."""
    allocation_frames = []
    for weight_type, line_map in (
        ('origin', BEA_ORIGIN_ALLOCATION_LINES),
        ('destination', BEA_DESTINATION_ALLOCATION_LINES),
    ):
        for category, (table_name, line_code, description) in line_map.items():
            response = bea_client.get_regional_data(
                year=year,
                table_name=table_name,
                line_code=line_code,
            )
            regional_df = bea_client.process_regional_response(response)
            weights = state_allocation_weights(
                regional_df,
                state_codes,
                year,
                category,
                weight_type,
                table_name,
                line_code,
                description,
            )
            if not weights.empty:
                allocation_frames.append(weights)

    if not allocation_frames:
        return pd.DataFrame()

    return pd.concat(
        allocation_frames,
        ignore_index=True,
        copy=False,
    ).sort_values(
        ['state_industry_code', 'weight_type', 'weight'],
        ascending=[True, True, False],
    )


def write_category_state(allocation_df, domestic_dir: Path) -> Path | None:
    """Write domestic/category_state.csv from the BEA allocation weights."""
    if allocation_df is None or allocation_df.empty:
        return None
    weights = allocation_df[CATEGORY_STATE_COLUMNS].copy()
    weights['weight'] = weights['weight'].map(compact)
    weights['value'] = weights['value'].map(compact)
    output_file = Path(domestic_dir) / CATEGORY_STATE_FILE
    weights.to_csv(output_file, index=False)
    print(f"    Wrote {CATEGORY_STATE_FILE} ({len(weights)} rows, {weights['state'].nunique()} states)")
    return output_file


def read_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def national_inputs(us_dir: Path) -> dict:
    """(industry2, industry1, origin) -> [amount, factor 901, ..., factor 910]"""
    totals: dict[tuple, list] = defaultdict(lambda: [0.0] * (1 + len(FACTOR_IDS)))
    factor_column = {factor_id: i + 1 for i, factor_id in enumerate(FACTOR_IDS)}
    for folder, origin in (("domestic", "us"), ("imports", "foreign")):
        trade_file = us_dir / folder / "trade.csv"
        if not trade_file.exists():
            print(f"    No {folder}/trade.csv -- trade-us.csv will have no {origin} purchases")
            continue
        key_of_trade = {}
        for row in read_rows(trade_file):
            if row["region2"] != "US" or (origin == "foreign") == (row["region1"] == "US"):
                continue
            key = (row["industry2"], row["industry1"], origin)
            key_of_trade[row["trade_id"]] = key
            totals[key][0] += float(row["amount"] or 0)
        factor_file = us_dir / folder / "trade_factor.csv"
        if not factor_file.exists():
            continue
        for row in read_rows(factor_file):
            column = factor_column.get(row["factor_id"])
            key = key_of_trade.get(row["trade_id"])
            if column is not None and key is not None:
                totals[key][column] += float(row["level"] or 0)
    return totals


def build_trade_us(us_dir: Path, categorize, industry_ids) -> Path:
    """Write domestic/trade-us.csv and domestic/industry_category.csv."""
    domestic_dir = Path(us_dir) / "domestic"

    by_industry: dict[str, list] = defaultdict(list)
    for (industry2, industry1, origin), values in national_inputs(us_dir).items():
        if any(values):
            by_industry[industry2].append((industry1, origin, values))
    with (domestic_dir / "trade-us.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["industry2", "industry1", "origin", "amount", *FACTOR_IDS])
        for industry2, rows in sorted(by_industry.items()):
            rows.sort(key=lambda item: (item[1] != "us", -item[2][0]))
            for industry1, origin, values in rows:
                writer.writerow([industry2, industry1, origin, *(compact(v) for v in values)])

    suppliers = {industry1 for rows in by_industry.values() for industry1, _, _ in rows}
    codes = sorted(set(industry_ids) | set(by_industry) | suppliers)
    with (domestic_dir / "industry_category.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["industry_id", "state_industry_code"])
        for code in codes:
            writer.writerow([code, categorize(code)])

    print(f"    Wrote trade-us.csv ({sum(len(rows) for rows in by_industry.values())} rows) "
          f"and industry_category.csv ({len(codes)} industries)")
    return domestic_dir


def main(argv) -> int:
    """Rebuild category_state.csv, trade-us.csv and industry_category.csv for a year."""
    from config_loader import load_config, get_file_path
    from bea_key import find_bea_api_key
    from main_api_client import BEAAPIClient
    from main_trade_analyzer import StateTradeAnalyzer

    config = load_config()
    if len(argv) > 1:
        config['YEAR'] = int(argv[1])
    config['TRADEFLOW'] = 'domestic'
    domestic_dir = Path(get_file_path(config, 'industryflow')).parent
    if not (domestic_dir / "trade.csv").exists():
        print(f"No domestic trade.csv in {domestic_dir} -- run main.py for {config['YEAR']} first.")
        return 1
    analyzer = StateTradeAnalyzer(config)

    weights_file = domestic_dir / CATEGORY_STATE_FILE
    if not weights_file.exists():
        # Cached BEA responses of any age; the API is only called for a missing one, with
        # the BEA_API_KEY from the env file automation/paths.yaml points at (see env_key.py)
        client = BEAAPIClient(find_bea_api_key())
        client.cache_duration_hours = 24 * 365 * 100
        weights = fetch_state_allocation_weights(client, config['YEAR'], analyzer.state_codes)
        if write_category_state(weights, domestic_dir) is None:
            print("No BEA Regional weights -- run bea/main.py with a BEA_API_KEY first.")
            return 1

    build_trade_us(domestic_dir.parent, analyzer._categorize_industry, analyzer.industry_category_by_id.keys())
    return 0


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent.parent)  # config.yaml's FOLDERS are relative to tradeflow/
    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main(sys.argv))
