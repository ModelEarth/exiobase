#!/usr/bin/env python3
"""
Industry Trade Flow Analysis for Exiobase Data
Extracts trade flow data based on config settings for imports, exports, or domestic flows
Outputs trade.csv with columns: trade_id, region1, region2, industry1, industry2, amount

Default (Recommended):
python trade.py
Creates small trade_factor.csv (50 to 120 factors, manageable size)

Large File (Not Recommended):
python trade.py -lag
Creates trade_factor-max.csv (~1.5GB, causes Node.js memory errors) 

Creates 4 files

  1. Reference Files (created if they don't exist) - used for trade factor generation process:
  - industry.csv - Sector mapping with 5-character industry codes (calls create_sector_mapping())
  - factor.csv - Environmental factor definitions from Exiobase extensions (calls create_factors_csv())

  2. Primary Output:
  - trade.csv - The main trade flow data with columns: trade_id, region1, region2, industry1, industry2,
  amount

  3. Trade Factors (your focus):
  - trade_factor.csv (default, small 50 to 120 factors)
  - trade_factor-max.csv (with -lag flag, large ~721 factors)

"""

import pandas as pd
import pymrio
import csv
from datetime import datetime
import os
from pathlib import Path
import pickle as pkl
import argparse
from config_loader import load_config, get_file_path, get_reference_file_path, print_config_summary
from exiobase_download import ensure_exiobase_file
from trade_extraction import (
    aggregate_factors, build_factor_mapping, compute_trade_factor,
    ensure_industry_mapping, ensure_sector_tables, ensure_factors_export,
)

class ExiobaseTradeFlow:
    def __init__(self, use_large_factors=False):
        # Load configuration
        self.config = load_config()
        self.use_large_factors = use_large_factors
        print_config_summary(self.config)
        
        self.year = self.config['YEAR']
        
        # Handle COUNTRY as either string or dict with current sub-parameter
        country_config = self.config['COUNTRY']
        if isinstance(country_config, dict):
            if 'current' in country_config:
                self.country = country_config['current']
            elif 'list' in country_config:
                # If no current is set, use first from list
                country_list = country_config['list'].split(',')
                self.country = country_list[0].strip()
            else:
                self.country = str(country_config)
        elif isinstance(country_config, str):
            if ',' in country_config:
                self.country = country_config.split(',')[0].strip()
            else:
                self.country = country_config
        else:
            self.country = str(country_config)
            
        self.tradeflow_type = self.config['TRADEFLOW']
        self.output_file = get_file_path(self.config, 'industryflow')
        self.model_type = 'pxp'  # product by product matrix
        
        # Set up paths for Exiobase data storage
        self.model_path = Path(__file__).parent / 'exiobase_data'
        self.model_path.mkdir(exist_ok=True)

        # Ensure the Exiobase zip is downloaded before sector mapping needs it
        ensure_exiobase_file(self.model_path, self.year, self.model_type)

        # Load or create sector mapping
        self.sector_mapping = self.load_sector_mapping()

        # Create the BEA Sector table + its many-to-many join to industry.csv
        self.create_sector_tables()

        # Create factors export
        self.create_factors_export()

    def load_sector_mapping(self):
        """Delegates to trade_extraction.ensure_industry_mapping — shared with trade_comprehensive.py."""
        return ensure_industry_mapping(self.config)

    def create_sector_tables(self):
        """Delegates to trade_extraction.ensure_sector_tables — shared with trade_comprehensive.py."""
        ensure_sector_tables(self.config)

    def create_factors_export(self):
        """Delegates to trade_extraction.ensure_factors_export — shared with trade_comprehensive.py."""
        ensure_factors_export(self.config)

    def _aggregate_factors(self, F_stacked, ext_name):
        """
        Collapse raw per-stressor coefficients into a small set of aggregated
        flows for the default trade_factor.csv. Delegates to
        trade_extraction.aggregate_factors (shared with trade_comprehensive.py
        — see PLAN-comprehensive.md's "Memory management" section); this
        method now just adds the progress print.
        """
        result = aggregate_factors(F_stacked, ext_name)
        print(f"    Aggregated {ext_name} into {len(result)} flow rows (region x industry x flow)")
        return result

    def create_trade_factor(self, trade_df, exio_model):
        """
        Create trade_factor.csv that links each trade flow to environmental
        factors. The per-extension M-matrix merge itself now lives in
        trade_extraction.compute_trade_factor (shared with
        trade_comprehensive.py — see PLAN-comprehensive.md's "Memory
        management" section); this method keeps the factor-mapping setup
        and file I/O that are specific to the single-country CSV pipeline.
        """
        print("Creating trade_factor.csv with real Exiobase factor data...")

        # Load the factors mapping. Prefix-only names like "CO2" are
        # ambiguous across multiple factors, so build_factor_mapping
        # keys on the exact stressor name (plus formatting variants).
        factors_file = get_reference_file_path(self.config, 'factors')
        factors_df = pd.read_csv(factors_file)
        factor_mapping = build_factor_mapping(factors_df)
        print(f"Created factor mapping with {len(factor_mapping)} entries")

        trade_factor_df = compute_trade_factor(
            trade_df, exio_model, self.sector_mapping, factor_mapping,
            use_large_factors=self.use_large_factors, log=print,
        )

        # Determine output file based on mode
        if self.use_large_factors:
            output_file = get_file_path(self.config, 'trade_factor')
            if not output_file.endswith('-max.csv'):
                output_file = output_file.replace('.csv', '-max.csv')
            file_type = "large"
            if not trade_factor_df.empty:
                print(f"⚠️  WARNING: Creating large trade_factor-max.csv (~1.5GB) - this may cause memory issues in trade_resource.py")
        else:
            output_file = get_file_path(self.config, 'trade_factor')
            if output_file.endswith('-max.csv'):
                output_file = output_file.replace('-max.csv', '.csv')
            file_type = "small"

        if not trade_factor_df.empty:
            trade_factor_df.to_csv(output_file, index=False)
            print(f"Created {file_type} trade_factor file with {len(trade_factor_df)} factor-trade relationships")
            print(f"File: {output_file}")
        else:
            print("No trade-factor relationships found, creating empty trade_factor.csv")
            trade_factor_df.to_csv(output_file, index=False)

    def download_and_process_exiobase(self):
        """
        Download (if needed) and parse Exiobase data using pymrio library.
        """
        print(f"Loading Exiobase data for {self.year}...")

        # Shared with exiobase_download.py's standalone --year guide so a
        # multi-GB download run this way behaves identically either way.
        exio_file = ensure_exiobase_file(self.model_path, self.year, self.model_type)
        if exio_file is None:
            raise RuntimeError(
                f"Could not obtain the Exiobase {self.year} file. "
                f"Download it with: python3 exiobase_download.py --year {self.year}"
            )

        print(f"Parsing Exiobase file: {exio_file}")
        return pymrio.parse_exiobase3(exio_file).calc_all()

    def extract_m_matrix_data(self, exio_model):
        """
        Extract trade flow data from Exiobase model based on tradeflow type
        """
        print(f"Extracting {self.tradeflow_type} trade flow data...")
        
        # Get the Z matrix (inter-industry flows)
        Z = exio_model.Z.copy()
        
        # Set proper index and column names
        Z.index.names = ['from_region', 'from_sector']
        Z.columns.names = ['to_region', 'to_sector']
        
        # Stack the matrix to create a long format DataFrame
        Z_stacked = Z.stack(level=['to_region', 'to_sector'], future_stack=True).reset_index()
        Z_stacked.columns = ['from_region', 'from_sector', 'to_region', 'to_sector', 'flow']
        
        # Filter based on tradeflow type
        if self.tradeflow_type == 'imports':
            # Filter for flows to the country (imports)
            Z_filtered = Z_stacked[Z_stacked['to_region'] == self.country].copy()
            # Remove domestic flows
            Z_filtered = Z_filtered[Z_filtered['from_region'] != self.country].copy()
            print(f"Processing imports to {self.country}")
        elif self.tradeflow_type == 'exports':
            # Filter for flows from the country (exports)
            Z_filtered = Z_stacked[Z_stacked['from_region'] == self.country].copy()
            # Remove domestic flows
            Z_filtered = Z_filtered[Z_filtered['to_region'] != self.country].copy()
            print(f"Processing exports from {self.country}")
        elif self.tradeflow_type == 'domestic':
            # Filter for flows within the country (domestic)
            domestic_candidates = Z_stacked[
                (Z_stacked['from_region'] == self.country) & 
                (Z_stacked['to_region'] == self.country)
            ].copy()
            
            print(f"Processing domestic flows within {self.country}")
            print(f"Found {len(domestic_candidates)} potential domestic flows")
            print(f"Non-zero flows: {len(domestic_candidates[domestic_candidates['flow'] > 0])}")
            print(f"Flows > 0.001: {len(domestic_candidates[domestic_candidates['flow'] > 0.001])}")
            print(f"Flows > 0.01: {len(domestic_candidates[domestic_candidates['flow'] > 0.01])}")
            
            if len(domestic_candidates) > 0:
                print(f"Flow range: {domestic_candidates['flow'].min():.6f} to {domestic_candidates['flow'].max():.2f}")
            
            Z_filtered = domestic_candidates
        else:
            raise ValueError(f"Invalid tradeflow type: {self.tradeflow_type}")
        
        # Filter out zero or very small flows (lowered threshold for domestic)
        initial_count = len(Z_filtered)
        if self.tradeflow_type == 'domestic':
            # Use lower threshold for domestic flows
            Z_filtered = Z_filtered[Z_filtered['flow'] > 0.001].copy()
            print(f"After filtering flows > 0.001: {len(Z_filtered)} flows (removed {initial_count - len(Z_filtered)})")
        else:
            Z_filtered = Z_filtered[Z_filtered['flow'] > 0.01].copy()
        
        # Map sector names to 5-character industry IDs
        Z_filtered['industry1'] = Z_filtered['from_sector'].map(self.sector_mapping)
        Z_filtered['industry2'] = Z_filtered['to_sector'].map(self.sector_mapping)
        
        # Remove rows where mapping failed (should be rare)
        Z_filtered = Z_filtered.dropna(subset=['industry1', 'industry2'])
        
        # Aggregate by 5-character industry IDs
        trade_data = Z_filtered.groupby(['from_region', 'to_region', 'industry1', 'industry2']).agg({
            'flow': 'sum'
        }).reset_index()
        
        # Format the final output
        trade_data = trade_data.rename(columns={
            'from_region': 'region1',
            'to_region': 'region2',
            'flow': 'amount'
        })

        # Keep the historical 2dp trade.csv format, but do not carry rows that
        # would be written as 0.00 into trade_factor.csv or BEA interstate data.
        rounded_zero_rows = trade_data['amount'].round(2) <= 0
        if rounded_zero_rows.any():
            removed_count = int(rounded_zero_rows.sum())
            trade_data = trade_data[~rounded_zero_rows].copy()
            print(f"Removed {removed_count} flows that round to 0.00 at 2 decimals")
        
        # Add trade_id column (1-based sequential ID)
        trade_data = trade_data.reset_index(drop=True)
        trade_data['trade_id'] = trade_data.index + 1

        # Reorder columns (no 'year' column — one database per year makes it redundant)
        trade_data = trade_data[['trade_id', 'region1', 'region2', 'industry1', 'industry2', 'amount']]
        
        return trade_data

    def process_trade_flows(self):
        """
        Process and format the trade flow data
        """
        print(f"Processing {self.tradeflow_type} flows for {self.year} with {self.country}...")

        exio_model = self.download_and_process_exiobase()
        df = self.extract_m_matrix_data(exio_model)
        self.create_trade_factor(df, exio_model)

        # Sort by amount descending to show largest flows first
        df = df.sort_values('amount', ascending=False)

        return df

    def export_to_csv(self, df):
        """
        Export the processed data to CSV
        """
        columns_with_id = ['trade_id', 'region1', 'region2', 'industry1', 'industry2', 'amount']
        columns_no_id = ['region1', 'region2', 'industry1', 'industry2', 'amount']

        print(f"Exporting trade.csv data to {self.output_file}...")
        columns = columns_with_id if 'trade_id' in df.columns else columns_no_id
        df = df[columns]
        df.to_csv(self.output_file, index=False, float_format='%.2f')
        return len(df)

    def run_analysis(self):
        """
        Main analysis runner with timing and logging
        """
        start_time = datetime.now()
        print(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"For year: {self.year}")
        print(f"For country: {self.country}")
        print(f"Trade flow type: {self.tradeflow_type}")
        print(f"Output: {self.output_file}")
        print()
        
        try:
            # Process the trade flows
            df = self.process_trade_flows()

            # Export to CSV
            total_rows = self.export_to_csv(df)
            
            # Calculate timing
            end_time = datetime.now()
            run_time = end_time - start_time
            run_time_minutes = round(run_time.total_seconds() / 60, 1)
            
            # Display summary
            print()
            print(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Total run time: {run_time_minutes} minutes")
            print(f"Total rows output: {total_rows}")
            print()
            print("Data source in Exiobase: Inter-industry flows matrix (Z) - Trade flows from exporting regions/industries")
            print("to importing industries in the United States. Data extracted from Exiobase v3.8.2")
            print("multiregional input-output database covering 163 industries across 44 countries and 5 RoW regions.")
            print("Downloaded using pymrio.download_exiobase3() and processed via pymrio.parse_exiobase3().")
            print("Additional exports: industry.csv (200 sectors), factor.csv (721 factors), trade_factor.csv (factor impacts)")
            
            return True
            
        except Exception as e:
            end_time = datetime.now()
            run_time = end_time - start_time
            run_time_minutes = round(run_time.total_seconds() / 60, 1)
            
            print(f"Error occurred: {str(e)}")
            print(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Total run time: {run_time_minutes} minutes")
            return False

def main():
    """
    Main execution function
    """
    parser = argparse.ArgumentParser(description='Generate trade factors for Exiobase data')
    parser.add_argument('-lag', '--large', action='store_true', 
                       help='Generate large trade_factor-max.csv with all factors (WARNING: ~1.5GB file, may cause memory issues)')
    
    args = parser.parse_args()
    
    if args.large:
        print("🚀 Large factors mode enabled - generating comprehensive trade_factor-max.csv")
        print("⚠️  WARNING: This will create a ~1.5GB file that may cause FATAL ERROR in trade_resource.py")
        print("   Node.js v8::ToLocalChecked Empty MaybeLocal error after ~10 minutes")
        print("   Consider using the default small file mode instead")
        print()
    
    analyzer = ExiobaseTradeFlow(use_large_factors=args.large)
    success = analyzer.run_analysis()
    
    if not success:
        exit(1)

if __name__ == "__main__":
    main()
