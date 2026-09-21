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
Creates trade_factor_lg.csv (~1.5GB, causes Node.js memory errors) 

Creates 4 files

  1. Reference Files (created if they don't exist) - used for trade factor generation process:
  - industry.csv - Sector mapping with 5-character industry codes (calls create_sector_mapping())
  - factor.csv - Environmental factor definitions from Exiobase extensions (calls create_factors_csv())

  2. Primary Output:
  - trade.csv - The main trade flow data with columns: trade_id, region1, region2, industry1, industry2,
  amount

  3. Trade Factors (your focus):
  - trade_factor.csv (default, small 50 to 120 factors)
  - trade_factor_lg.csv (with -lag flag, large ~721 factors)

"""

import pandas as pd
import numpy as np
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
        _, self.year = ensure_exiobase_file(self.model_path, self.year, self.model_type)

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
        management" section); this method keeps the factor-mapping setup,
        file I/O, and error/fallback handling that are specific to the
        single-country CSV pipeline.
        """
        print("Creating trade_factor.csv with real Exiobase factor data...")

        try:
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
                if not output_file.endswith('_lg.csv'):
                    output_file = output_file.replace('.csv', '_lg.csv')
                file_type = "large"
                if not trade_factor_df.empty:
                    print(f"⚠️  WARNING: Creating large trade_factor_lg.csv (~1.5GB) - this may cause memory issues in trade_resource.py")
            else:
                output_file = get_file_path(self.config, 'trade_factor')
                if output_file.endswith('_lg.csv'):
                    output_file = output_file.replace('_lg.csv', '.csv')
                file_type = "small"

            if not trade_factor_df.empty:
                trade_factor_df.to_csv(output_file, index=False)
                print(f"Created {file_type} trade_factor file with {len(trade_factor_df)} factor-trade relationships")
                print(f"File: {output_file}")
            else:
                print("No trade-factor relationships found, creating empty trade_factor.csv")
                trade_factor_df.to_csv(output_file, index=False)

        except Exception as e:
            print(f"Error creating trade_factor.csv: {e}")
            self.create_trade_factor_fallback(trade_df)

    def create_trade_factor_fallback(self, trade_df):
        """
        Create a simplified trade_factor.csv for fallback data
        """
        print("Creating simplified trade_factor.csv with sample data...")
        
        try:
            # Create sample factor relationships for major flows
            sample_factors = []
            
            # Sample some common factors
            common_factor_ids = [1, 5, 7, 15]  # As, CH4, CO2, N2O
            
            # For each trade flow, create sample factor relationships
            for _, trade_row in trade_df.head(100).iterrows():  # Limit to first 100 for performance
                for factor_id in common_factor_ids:
                    # Create realistic sample coefficients
                    if factor_id == 7:  # CO2
                        coefficient = np.random.uniform(0.1, 2.0)
                    elif factor_id == 5:  # CH4  
                        coefficient = np.random.uniform(0.01, 0.1)
                    else:
                        coefficient = np.random.uniform(0.001, 0.05)
                    
                    sample_factors.append({
                        'trade_id': trade_row['trade_id'],
                        'factor_id': factor_id,
                        'level': trade_row['amount'] * coefficient
                    })
            
            trade_factor_df = pd.DataFrame(sample_factors)
            output_file = get_file_path(self.config, 'trade_factor')
            trade_factor_df.to_csv(output_file, index=False)
            print(f"Created sample trade_factor.csv with {len(trade_factor_df)} relationships")
            
        except Exception as e:
            print(f"Error creating fallback trade_factor.csv: {e}")

    def download_and_process_exiobase(self):
        """
        Download (if needed) and parse Exiobase data using pymrio library.
        """
        print(f"Loading Exiobase data for {self.year}...")

        # Shared with exiobase_download.py's standalone --year guide so a
        # multi-GB download run this way behaves identically either way.
        exio_file, actual_year = ensure_exiobase_file(self.model_path, self.year, self.model_type)
        self.year = actual_year

        if exio_file is None:
            return self.load_fallback_data()

        # Parse the downloaded Exiobase data
        try:
            print(f"Parsing Exiobase file: {exio_file}")
            exio_model = pymrio.parse_exiobase3(exio_file).calc_all()
            return exio_model
        except Exception as e:
            print(f"Parsing failed: {e}")
            print("Using fallback method with simulated data...")
            return self.load_fallback_data()

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

    def load_fallback_data(self):
        """
        Fallback method to generate realistic trade flow data when Exiobase download fails
        """
        print("Using fallback data generation...")
        
        # Simplified region and sector lists based on typical Exiobase structure
        regions = ['AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR',
                  'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'RO',
                  'SE', 'SI', 'SK', 'GB', 'JP', 'CN', 'CA', 'KR', 'BR', 'IN', 'MX', 'RU',
                  'AU', 'CH', 'TR', 'TW', 'NO', 'ID', 'ZA', 'WA', 'WL', 'WE', 'WF', 'WM']
        
        # Use the same 5-character IDs from the mapping if available
        if hasattr(self, 'sector_mapping') and self.sector_mapping:
            sectors = list(set(self.sector_mapping.values()))[:50]  # Use actual IDs
        else:
            # Fallback 5-character sector codes
            sectors = ['PADDY', 'WHEAT', 'CEREA', 'VEGET', 'OILSE', 'SUGAR', 'PLANT', 'CROPS',
                      'CATTL', 'PIGS9', 'POULT', 'MEATA', 'ANIMA', 'RAWMI', 'WOOLS', 'MANUR',
                      'FORES', 'FISHF', 'ANTHR', 'COKIN', 'OTHER', 'SUBBI', 'PATEN', 'LIGNI',
                      'CRUDE', 'NATUR', 'IRON1', 'IRON2', 'ALUMI', 'COPPE', 'NICKE', 'ZINC1',
                      'LEAD1', 'TIN12', 'OTHER', 'GOLD1', 'SILVE', 'PLATI', 'OTHER', 'URANI',
                      'STONE', 'SAND1', 'CLAY1', 'CHEMI', 'SALT1', 'OTHER', 'PETRE', 'NATUR',
                      'OTHER', 'MEAT1', 'MEAT2']
        
        np.random.seed(42)  # For reproducible results
        
        data = []
        for region1 in regions:
            for region2 in regions:
                # Apply filtering based on tradeflow type
                if self.tradeflow_type == 'imports':
                    if region2 != self.country or region1 == self.country:
                        continue
                elif self.tradeflow_type == 'exports':
                    if region1 != self.country or region2 == self.country:
                        continue
                elif self.tradeflow_type == 'domestic':
                    if region1 != self.country or region2 != self.country:
                        continue
                
                for exp_sector in sectors[:31]:  # Limit to first 31 sectors
                    for imp_sector in sectors[:31]:
                        # Generate realistic trade amounts
                        base_amount = np.random.lognormal(8, 2.5)
                        
                        # Sector-specific adjustments
                        if any(x in exp_sector for x in ['Coke_', 'Comin', 'Basic']):
                            base_amount *= 3.0  # Raw materials
                        elif any(x in exp_sector for x in ['Chemi', 'Mach_', 'Elec_']):
                            base_amount *= 2.0  # Manufacturing
                        elif any(x in exp_sector for x in ['Finan', 'Legal', 'Educa']):
                            base_amount *= 0.2  # Services
                        
                        # Region-specific adjustments
                        if region1 in ['CN', 'DE', 'JP']:
                            base_amount *= 1.8
                        elif region1 in ['CA', 'MX']:
                            base_amount *= 1.3
                        
                        # Only include significant flows
                        if base_amount > 0.1:
                            data.append({
                                'region1': region1,
                                'region2': region2,
                                'industry1': exp_sector,
                                'industry2': imp_sector,
                                'amount': round(base_amount, 2)
                            })

        df = pd.DataFrame(data)
        # Add trade_id for fallback data
        df['trade_id'] = df.index + 1
        # Reorder columns (no 'year' column — one database per year makes it redundant)
        df = df[['trade_id', 'region1', 'region2', 'industry1', 'industry2', 'amount']]

        return df

    def process_trade_flows(self):
        """
        Process and format the trade flow data
        """
        print(f"Processing {self.tradeflow_type} flows for {self.year} with {self.country}...")

        # Try to download and process real Exiobase data
        exio_model = self.download_and_process_exiobase()

        if isinstance(exio_model, pd.DataFrame):
            # Fallback data was returned
            df = exio_model
            # For fallback data, create trade_factor with dummy data
            self.create_trade_factor_fallback(df)
        else:
            # Real Exiobase model was returned
            df = self.extract_m_matrix_data(exio_model)
            # Create trade_factor with real data
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
                       help='Generate large trade_factor_lg.csv with all factors (WARNING: ~1.5GB file, may cause memory issues)')
    
    args = parser.parse_args()
    
    if args.large:
        print("🚀 Large factors mode enabled - generating comprehensive trade_factor_lg.csv")
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
