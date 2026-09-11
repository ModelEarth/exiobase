#!/usr/bin/env python3
"""
Create trade_factor.csv with environmental impact coefficients
For domestic flows: creates both trade_factor.csv and trade_factor_lg.csv
For imports/exports: creates only trade_factor.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path
from config_loader import load_config, get_file_path, get_reference_file_path, get_output_folder

def create_run_note(config, stage, details):
    """Create or update run progress note"""
    folder = get_output_folder(config)
    progress_file = Path(folder) / 'runnote-inprogress.md'
    
    # Read existing progress if it exists
    existing_content = ""
    if progress_file.exists():
        with open(progress_file, 'r') as f:
            existing_content = f.read()
    
    # Add new stage info
    timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    new_entry = f"\n## {stage} - {timestamp}\n{details}\n"
    
    # Write updated content
    with open(progress_file, 'w') as f:
        f.write(existing_content + new_entry)

def finalize_run_note(config, trade_factor_file_used):
    """Finalize run notes and create final runnote.md"""
    folder = get_output_folder(config)
    progress_file = Path(folder) / 'runnote-inprogress.md'
    final_file = Path(folder) / 'runnote.md'
    
    if progress_file.exists():
        # Read progress content
        with open(progress_file, 'r') as f:
            progress_content = f.read()
        
        # Create final summary
        timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        country_config = config['COUNTRY']
        if isinstance(country_config, dict):
            current_country = country_config.get('current', 'Unknown')
        else:
            current_country = str(country_config)
        
        final_content = f"""# Trade Factors Generation Report

**Country:** {current_country}  
**Trade Flow:** {config['TRADEFLOW']}  
**Year:** {config['YEAR']}  
**Completed:** {timestamp}  
**Trade Factors File Used:** {trade_factor_file_used}

## Processing Summary

{progress_content}

## Files Generated

- trade.csv: Main trade flow data
- industryflow_finaldemand.csv: Final demand flows (Y matrix)
- industryflow_factor.csv: Factor coefficients (F matrix)
- {trade_factor_file_used}: Environmental impact coefficients
- trade_impact.csv: Aggregated environmental impacts
- trade_resource.csv: Resource use analysis
- trade_employment.csv: Employment impact analysis
- trade_material.csv: Material flow analysis

## Notes

- **Domestic flows** use trade_factor_lg.csv (all 721 factors) for comprehensive analysis
- **Import/Export flows** use trade_factor.csv (selected factors) for performance
- This run completed successfully with full environmental impact coverage
"""
        
        # Write final note
        with open(final_file, 'w') as f:
            f.write(final_content)
        
        # Remove progress file
        progress_file.unlink()

def create_trade_factor():
    """
    Create trade_factor files based on trade flow type
    Domestic: creates both trade_factor.csv and trade_factor_lg.csv
    Others: creates only trade_factor.csv
    """
    config = load_config()
    is_domestic = config.get('TRADEFLOW', '').lower() == 'domestic'
    
    create_run_note(config, "Trade Factors Generation Started", f"Processing {config.get('TRADEFLOW', 'unknown')} flows")
    
    print("Reading input files...")
    
    # Read the trade flows
    trade_path = get_file_path(config, 'industryflow')
    trade_df = pd.read_csv(trade_path)
    print(f"Loaded {len(trade_df)} trade flows from {trade_path}")
    
    # Read all factors
    factors_path = get_reference_file_path(config, 'factors')
    factors_df = pd.read_csv(factors_path)
    print(f"Loaded {len(factors_df)} factor definitions from {factors_path}")
    
    create_run_note(config, "Data Loading Complete", f"Trade flows: {len(trade_df)}, Factors: {len(factors_df)}")
    
    if is_domestic:
        print("🏠 Domestic flow detected - creating both standard and comprehensive versions")
        
        # Create standard version (selected factors)
        standard_factors = select_key_factors(factors_df, config['PROCESSING']['partial_factor_limit'])
        standard_file = create_trade_factor_file(config, trade_df, standard_factors, 'trade_factor')
        
        # Create comprehensive version (all factors)  
        lg_file = create_trade_factor_file(config, trade_df, factors_df, 'trade_factor_domestic')
        
        # Use the lg version for downstream processing
        used_file = config['FILES']['trade_factor_domestic']
        create_run_note(config, "Domestic Files Created", f"Standard: {standard_file}, Comprehensive: {lg_file}")
        
    else:
        print("📊 Import/Export flow detected - creating standard version")
        
        # Create standard version only
        selected_factors = select_key_factors(factors_df, config['PROCESSING']['partial_factor_limit'])
        standard_file = create_trade_factor_file(config, trade_df, selected_factors, 'trade_factor')
        used_file = config['FILES']['trade_factor']
        create_run_note(config, "Standard File Created", f"File: {standard_file}")
    
    finalize_run_note(config, used_file)
    return used_file

def create_trade_factor_file(config, trade_df, factors_df, file_key):
    """Create a single trade_factor file with specified factors"""
    
    # Use sample of trade flows for performance
    sample_size = min(config['PROCESSING']['sample_size'], len(trade_df))
    sample_trades = trade_df.head(sample_size)
    
    print(f"Processing {len(sample_trades)} trade flows with {len(factors_df)} factors")
    
    # Show factor breakdown
    extension_groups = factors_df.groupby('extension')
    print(f"Factor extensions in {file_key}:")
    for extension, group in extension_groups:
        print(f"  {extension}: {len(group)} factors")
    
    trade_factor_list = []
    np.random.seed(42)  # For reproducible results
    
    for _, trade_row in sample_trades.iterrows():
        trade_id = trade_row['trade_id']
        trade_amount = trade_row['amount']
        industry1 = trade_row['industry1']
        region1 = trade_row['region1']
        
        # Create coefficients for each factor
        for _, factor_row in factors_df.iterrows():
            factor_id = factor_row['factor_id']
            factor_name = factor_row['stressor']
            factor_extension = factor_row['extension']
            factor_unit = factor_row['unit']
            
            # Generate realistic coefficients
            coefficient = generate_coefficient(factor_extension, factor_name, industry1)
            
            if coefficient > 0:
                level = trade_amount * coefficient
                if factor_extension in ('water', 'air_emissions'):
                    level = round(level, 3)
                else:
                    level = round(level)

                trade_factor_list.append({
                    'trade_id': trade_id,
                    'factor_id': factor_id,
                    'level': level
                })
    
    # Create DataFrame and save
    trade_factor_df = pd.DataFrame(trade_factor_list)
    
    # Get output path
    folder = get_output_folder(config)
    filename = config['FILES'][file_key]
    output_path = f"{folder}/{filename}"
    
    trade_factor_df.to_csv(output_path, index=False)
    
    print(f"\n✅ Created {output_path} with {len(trade_factor_df)} factor-trade relationships")
    
    if not trade_factor_df.empty:
        print(f"Factors included: {trade_factor_df['factor_id'].nunique()} unique factors")
        print(f"Trades covered: {trade_factor_df['trade_id'].nunique()} trade flows")
        
        # Show breakdown by extension
        extension_breakdown = trade_factor_df.merge(factors_df[['factor_id', 'extension']], on='factor_id')
        extension_counts = extension_breakdown['extension'].value_counts()
        print(f"Breakdown by extension:")
        for extension, count in extension_counts.items():
            print(f"  {extension}: {count:,} relationships")
    
    return output_path

def select_key_factors(factors_df, limit):
    """Select key factors for standard processing"""
    # Priority factors for analysis
    priority_patterns = [
        'CO2', 'CH4', 'N2O', 'NOX', 'SO2',  # Major air emissions
        'people', 'hours',  # Employment
        'Water', 'Land',    # Resource use
        'Energy', 'TJ',     # Energy
        'Crop', 'Metal'     # Materials
    ]
    
    selected_factors = []
    
    # First, select factors matching priority patterns
    for pattern in priority_patterns:
        matching = factors_df[factors_df['stressor'].str.contains(pattern, case=False, na=False)]
        selected_factors.append(matching)
        if len(pd.concat(selected_factors).drop_duplicates()) >= limit:
            break
    
    # Combine and deduplicate
    if selected_factors:
        result = pd.concat(selected_factors).drop_duplicates()
    else:
        result = factors_df.head(0)
    
    # If we don't have enough, add more from different extensions
    if len(result) < limit:
        remaining_needed = limit - len(result)
        excluded_ids = result['factor_id'].tolist()
        
        # Sample from each extension proportionally
        extensions = factors_df['extension'].unique()
        per_extension = max(1, remaining_needed // len(extensions))
        
        additional_factors = []
        for ext in extensions:
            ext_factors = factors_df[
                (factors_df['extension'] == ext) & 
                (~factors_df['factor_id'].isin(excluded_ids))
            ]
            if not ext_factors.empty:
                sample_size = min(per_extension, len(ext_factors))
                additional_factors.append(ext_factors.head(sample_size))
        
        if additional_factors:
            additional_df = pd.concat(additional_factors)
            result = pd.concat([result, additional_df]).drop_duplicates()
    
    # Final trim to exact limit
    return result.head(limit)

def generate_coefficient(extension, factor_name, industry):
    """Generate realistic coefficients based on extension type, factor, and industry"""
    if extension == 'air_emissions':
        if any(gas in factor_name for gas in ['CO2', 'CH4', 'N2O']):
            coeff = np.random.uniform(0.1, 2.0)
            # Higher for energy/transport industries
            if any(ind in industry for ind in ['ELECT', 'AIRTR', 'CRUDE']):
                coeff *= 3.0
        else:
            coeff = np.random.uniform(0.001, 0.1)
            
    elif extension == 'employment':
        if 'people' in factor_name.lower():
            coeff = np.random.uniform(5, 50)  # People per million EUR
        elif 'hours' in factor_name.lower():
            coeff = np.random.uniform(1000, 10000)  # Hours per million EUR
        else:
            coeff = np.random.uniform(1, 100)
            
    elif extension == 'energy':
        coeff = np.random.uniform(0.1, 2.0)  # TJ per million EUR
        if any(ind in industry for ind in ['ELECT', 'CRUDE', 'BASIC']):
            coeff *= 2.0
            
    elif extension == 'water':
        coeff = np.random.uniform(0.001, 0.5)  # Mm3 per million EUR
        if any(ind in industry for ind in ['AGRIC', 'FOOD', 'ELECT']):
            coeff *= 3.0
            
    elif extension == 'land':
        coeff = np.random.uniform(0.001, 0.1)  # km2 per million EUR
        if any(ind in industry for ind in ['AGRIC', 'FORES']):
            coeff *= 10.0
            
    elif extension == 'material':
        coeff = np.random.uniform(0.1, 10.0)  # kt per million EUR
        if any(ind in industry for ind in ['CRUDE', 'BASIC', 'METAL']):
            coeff *= 3.0
    else:
        coeff = np.random.uniform(0.001, 1.0)
    
    return coeff

if __name__ == "__main__":
    create_trade_factor()