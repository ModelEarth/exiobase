#!/usr/bin/env python3
"""
Create export_competitiveness.csv and import_dependency.csv
from real Exiobase trade flow data (trade.csv).

Runs as part of the main.py pipeline:
  exports tradeflow  → export_competitiveness.csv
  imports tradeflow  → import_dependency.csv
  domestic tradeflow → skipped (no cross-country flows)

All metrics are derived from trade.csv amounts (M EUR).
No placeholder or random values.

Metrics — export_competitiveness.csv (one row per trade_id):
  industry_exports_total   : M EUR exported by this industry to all destinations
  destination_share        : this row's amount / industry total (0–1)
  export_intensity         : industry total / country total exports (0–1)
  destination_count        : distinct destination regions for this industry
  export_concentration_hhi : Herfindahl-Hirschman Index of destinations (0=dispersed, 1=one buyer)

Metrics — import_dependency.csv (one row per trade_id):
  industry_imports_total   : M EUR imported for this industry from all sources
  source_share             : this row's amount / industry total (0–1)
  import_intensity         : industry total / country total imports (0–1)
  supplier_count           : distinct source regions for this industry
  import_concentration_hhi : HHI of source regions (higher = more dependent on fewer suppliers)
"""

import pandas as pd
from pathlib import Path
from config_loader import load_config, get_file_path


def _hhi(amounts):
    """Herfindahl-Hirschman Index: sum of squared shares. Range 0–1."""
    total = amounts.sum()
    if total == 0:
        return 0.0
    shares = amounts / total
    return round(float((shares ** 2).sum()), 6)


def create_export_competitiveness(trade_df):
    total_exports = trade_df['amount'].sum()

    industry_stats = trade_df.groupby('industry1').agg(
        industry_exports_total=('amount', 'sum'),
        destination_count=('region2', 'nunique'),
    )
    industry_hhi = (
        trade_df.groupby('industry1')['amount']
        .apply(_hhi)
        .rename('export_concentration_hhi')
    )
    industry_stats = industry_stats.join(industry_hhi)

    result = trade_df[['trade_id', 'industry1', 'amount']].merge(
        industry_stats.reset_index(), on='industry1'
    )
    result['destination_share'] = (result['amount'] / result['industry_exports_total']).round(6)
    result['export_intensity'] = (result['industry_exports_total'] / total_exports).round(6)
    result['industry_exports_total'] = result['industry_exports_total'].round(2)

    return result[['trade_id', 'industry_exports_total', 'destination_share',
                   'export_intensity', 'destination_count', 'export_concentration_hhi']]


def create_import_dependency(trade_df):
    total_imports = trade_df['amount'].sum()

    industry_stats = trade_df.groupby('industry2').agg(
        industry_imports_total=('amount', 'sum'),
        supplier_count=('region1', 'nunique'),
    )
    industry_hhi = (
        trade_df.groupby('industry2')['amount']
        .apply(_hhi)
        .rename('import_concentration_hhi')
    )
    industry_stats = industry_stats.join(industry_hhi)

    result = trade_df[['trade_id', 'industry2', 'amount']].merge(
        industry_stats.reset_index(), on='industry2'
    )
    result['source_share'] = (result['amount'] / result['industry_imports_total']).round(6)
    result['import_intensity'] = (result['industry_imports_total'] / total_imports).round(6)
    result['industry_imports_total'] = result['industry_imports_total'].round(2)

    return result[['trade_id', 'industry_imports_total', 'source_share',
                   'import_intensity', 'supplier_count', 'import_concentration_hhi']]


def main():
    config = load_config()
    tradeflow = config.get('TRADEFLOW', '').lower()

    if tradeflow not in ('exports', 'imports'):
        print(f"trade_competitiveness.py: skipping for {tradeflow} tradeflow")
        return

    trade_file = Path(get_file_path(config, 'industryflow'))
    if not trade_file.exists():
        print(f"trade.csv not found at {trade_file} — skipping")
        return

    trade_df = pd.read_csv(trade_file)
    output_dir = trade_file.parent

    if tradeflow == 'exports':
        print("Creating export_competitiveness.csv...")
        result = create_export_competitiveness(trade_df)
        out = output_dir / 'export_competitiveness.csv'
        result.to_csv(out, index=False)
        print(f"Created {out} ({len(result)} rows, {result['destination_count'].max()} max destinations)")

    elif tradeflow == 'imports':
        print("Creating import_dependency.csv...")
        result = create_import_dependency(trade_df)
        out = output_dir / 'import_dependency.csv'
        result.to_csv(out, index=False)
        print(f"Created {out} ({len(result)} rows, {result['supplier_count'].max()} max suppliers)")


if __name__ == '__main__':
    main()
