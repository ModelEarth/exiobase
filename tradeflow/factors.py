#!/usr/bin/env python3
"""
Extract all factors/flows from Exiobase extensions and create factor.csv
"""

import pandas as pd
import pymrio
from pathlib import Path
import uuid
from config_loader import load_config, get_reference_file_path
from exiobase_factors import aggregate_definitions

def create_factors_csv():
    """
    Extract all factors from Exiobase extensions and create factor.csv
    """
    # Load configuration
    config = load_config()
    
    model_path = Path(__file__).parent / 'exiobase_data'
    year = config['YEAR']
    model_type = 'pxp'
    
    exio_file = model_path / f'IOT_{year}_{model_type}.zip'
    
    if not exio_file.exists():
        print(f"Exiobase file not found: {exio_file}")
        return
    
    print(f"Loading Exiobase data from: {exio_file}")
    exio_model = pymrio.parse_exiobase3(exio_file)
    
    # List of extension names to process
    extensions = ['air_emissions', 'employment', 'energy', 'land', 'material', 'water']
    
    all_factors = []
    factor_id = 1  # 1-based index
    
    for ext_name in extensions:
        if hasattr(exio_model, ext_name):
            print(f"Processing {ext_name} extension...")
            ext = getattr(exio_model, ext_name)
            
            if hasattr(ext, 'F'):
                F_matrix = ext.F
                stressors = F_matrix.index.tolist()
                
                # Get units if available
                units_dict = {}
                if hasattr(ext, 'unit'):
                    units_df = ext.unit
                    if isinstance(units_df, pd.DataFrame):
                        units_dict = units_df['unit'].to_dict()
                    elif isinstance(units_df, pd.Series):
                        units_dict = units_df.to_dict()
                
                for stressor in stressors:
                    # Extract context from stressor name
                    context = "emission/air"  # default
                    
                    # Parse context from factor name
                    if " - " in stressor:
                        parts = stressor.split(" - ")
                        if len(parts) >= 2:
                            if "air" in parts[-1].lower():
                                context = "emission/air"
                            elif "water" in parts[-1].lower():
                                context = "emission/water"
                            elif "land" in ext_name.lower() or "land" in stressor.lower():
                                context = "natural_resource/land"
                            elif "energy" in ext_name.lower():
                                context = "natural_resource/energy"
                            elif "material" in ext_name.lower():
                                context = "natural_resource/in_ground"
                            elif "employment" in ext_name.lower():
                                context = "economic/employment"
                            else:
                                context = f"emission/{ext_name}"
                    elif ext_name == "employment":
                        context = "economic/employment"
                    elif ext_name == "energy":
                        context = "natural_resource/energy"
                    elif ext_name == "land":
                        context = "natural_resource/land"
                    elif ext_name == "material":
                        context = "natural_resource/in_ground"
                    elif ext_name == "water":
                        context = "natural_resource/water"
                    
                    # Create flowable name (clean version of stressor name)
                    flowable = stressor
                    
                    # Extract the main substance/flow name for flowable
                    if " - " in stressor:
                        # For formats like "CO2 - combustion - air", take the first part
                        flowable = stressor.split(" - ")[0]
                    
                    # Get unit
                    unit = units_dict.get(stressor, "unknown")
                    
                    # 'name': flowable,
                    # 'context': context,
                    # 'full_stressor_name': stressor,

                    all_factors.append({
                        'factor_id': factor_id,
                        'unit': unit,
                        'stressor': stressor,
                        'extension': ext_name
                    })
                    
                    factor_id += 1
    
    # Append the fixed aggregate-flow rows (factor_id 901+) used by the
    # default trade_factor.csv/interstate_factor.csv — see exiobase_factors.py.
    # trade_factor_lg.csv/interstate_factor_lg.csv keep using the 1-721 raw
    # per-stressor rows above; both live in this same factor.csv since the
    # aggregate ID block is chosen well clear of the raw range.
    for factor_id, unit, stressor, extension in aggregate_definitions():
        all_factors.append({
            'factor_id': factor_id,
            'unit': unit,
            'stressor': stressor,
            'extension': extension
        })

    # Create DataFrame
    factors_df = pd.DataFrame(all_factors)

    # Create the final factor.csv with only required columns
    output_df = factors_df[['factor_id', 'unit', 'stressor', 'extension']].copy()

    # Save to CSV
    output_file = get_reference_file_path(config, 'factors')
    output_df.to_csv(output_file, index=False)
    
    print(f"\nCreated {output_file} with {len(output_df)} factors")
    
    # Display summary
    print(f"\nFactors summary:")
    print(f"Total factors: {len(output_df)}")
    print(f"Extensions: {output_df['extension'].nunique()}")
    print(f"\nExtension breakdown:")
    print(output_df['extension'].value_counts())
    
    print(f"\nFirst 15 factors:")
    print(output_df.head(15).to_string(index=False))
    
    # Also save detailed version for reference
    #detailed_file = get_reference_file_path(config, 'factors').replace('.csv', '_detailed.csv')
    #factors_df.to_csv(detailed_file, index=False)
    #print(f"\nAlso created {detailed_file} with additional metadata")
    
    return output_df

if __name__ == "__main__":
    create_factors_csv()