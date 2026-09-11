#!/usr/bin/env python3
"""
Create split resource files: trade_employment.csv, trade_resource.csv (includes crops), trade_material.csv
Uses configuration-driven approach for imports/exports/domestic analysis
"""

import pandas as pd
import numpy as np
from pathlib import Path
from config_loader import load_config, get_file_path, get_reference_file_path, print_config_summary

def create_split_resources():
    """
    Create split resource CSV files based on configuration
    """
    
    # Load configuration
    config = load_config()
    print_config_summary(config)
    
    print("Reading input files...")
    
    # Read the trade flows using config paths
    trade_df = pd.read_csv(get_file_path(config, 'industryflow'))
    print(f"Loaded {len(trade_df)} trade flows")
    
    # Read the trade factors - use small optimized version by default
    try:
        # Use the small optimized trade_factor.csv (50 selected factors)
        trade_factor_file = get_file_path(config, 'trade_factor')
        if trade_factor_file.endswith('_lg.csv'):
            trade_factor_file = trade_factor_file.replace('_lg.csv', '.csv')
        
        trade_factor_df = pd.read_csv(trade_factor_file)
        print(f"Loaded {len(trade_factor_df)} trade-factor relationships (optimized small dataset)")
        print(f"File: {trade_factor_file}")
        
        # Check if large file exists and warn about potential issues
        large_file = trade_factor_file.replace('.csv', '_lg.csv')
        if Path(large_file).exists():
            print(f"\n💡 Note: Large file {large_file} exists but using optimized version")
            print(f"   Large file (~1.5GB) causes FATAL ERROR: v8::ToLocalChecked Empty MaybeLocal")
            print(f"   after ~10 minutes due to memory limitations")
        
    except FileNotFoundError:
        print(f"\n⚠️  WARNING: trade_factor.csv not found at {trade_factor_file}")
        print(f"Run 'python trade.py' to generate the optimized trade factors file")
        print(f"Or run 'python trade.py -lag' for the large version (not recommended)")
        return
    
    # Read the factors metadata
    factors_df = pd.read_csv(get_reference_file_path(config, 'factors'))
    print(f"Loaded {len(factors_df)} factor definitions")
    
    # Merge trade_factor with factor metadata
    print("Merging trade factors with metadata...")
    # Adapt to actual factor.csv column names: factor_id,unit,stressor,extension
    enhanced_factors = trade_factor_df.merge(
        factors_df[['factor_id', 'unit', 'stressor', 'extension']], 
        on='factor_id', 
        how='left'
    )
    
    # Map stressor names to context (since we don't have context column)
    enhanced_factors['context'] = enhanced_factors['extension'].map({
        'air_emissions': 'emission/air',
        'employment': 'economic/employment', 
        'energy': 'natural_resource/energy',
        'land': 'natural_resource/land',
        'material': 'natural_resource/in_ground',
        'water': 'natural_resource/water'
    })
    
    # Create name and fullname from stressor
    enhanced_factors['name'] = enhanced_factors['stressor'].str.split(' - ').str[0]
    enhanced_factors['fullname'] = enhanced_factors['stressor']
    
    # Define resource categories for splitting
    employment_contexts = ['economic/employment']
    resources_contexts = ['emission/water', 'natural_resource/water', 'natural_resource/land', 'natural_resource/energy']
    materials_contexts = ['natural_resource/in_ground']
    
    # Additional criteria for resources vs materials
    crops_keywords = ['Crops', 'Primary Crops', 'Agriculture', 'Forestry', 'Fishery']
    
    print("Splitting factors into categories...")
    
    # 1. EMPLOYMENT FACTORS
    employment_factors = enhanced_factors[
        enhanced_factors['context'].isin(employment_contexts)
    ].copy()
    
    # 2. RESOURCES FACTORS (water, land, energy + crops/agriculture)
    resources_factors = enhanced_factors[
        (enhanced_factors['context'].isin(resources_contexts)) |
        (enhanced_factors['fullname'].str.contains('|'.join(crops_keywords), case=False, na=False))
    ].copy()
    
    # 3. MATERIALS FACTORS (remaining in_ground materials, excluding crops)
    materials_factors = enhanced_factors[
        (enhanced_factors['context'].isin(materials_contexts)) &
        (~enhanced_factors['fullname'].str.contains('|'.join(crops_keywords), case=False, na=False))
    ].copy()
    
    print(f"Factor split summary:")
    print(f"  Employment factors: {len(employment_factors)}")
    print(f"  Resources factors: {len(resources_factors)}")
    print(f"  Materials factors: {len(materials_factors)}")
    
    # Create summary data for each category
    datasets = {
        'employment': employment_factors,
        'resources': resources_factors,
        'materials': materials_factors
    }
    
    output_files = {}
    
    for category, factors_data in datasets.items():
        if factors_data.empty:
            print(f"No {category} factors found, creating empty file")
            empty_df = trade_df.copy()
            empty_df[f'total_{category}_value'] = 0
            empty_df[f'{category}_count'] = 0
            output_files[category] = empty_df
            continue
        
        print(f"Processing {category} factors...")
        
        # Calculate summary statistics
        summary = factors_data.groupby('trade_id').agg({
            'level': ['sum', 'count'],
            'factor_id': 'nunique'
        }).round(3)
        
        # Flatten column names
        summary.columns = [f'total_{category}_value', f'{category}_count', f'unique_{category}_factors']
        summary = summary.reset_index()
        
        # Calculate impact by context within this category
        context_impacts = factors_data.groupby(['trade_id', 'context'])['level'].sum().unstack(fill_value=0)
        context_impacts = context_impacts.round(3)
        
        # Calculate specific subcategories
        if category == 'employment':
            subcategories = {
                'People': ['Employment people:'],
                'Hours': ['Employment hours:']
            }
        elif category == 'resources':
            subcategories = {
                'Water_Consumption': ['Water Consumption'],
                'Water_Withdrawal': ['Water Withdrawal'], 
                'Energy': ['Energy use'],
                'Land_Crops': ['Cropland'],
                'Land_Forest': ['Forest'],
                'Land_Other': ['Artificial', 'meadows', 'pastures'],
                'Crops': ['Primary Crops', 'Agriculture']
            }
        else:  # materials
            subcategories = {
                'Metals': ['Metal Ores'],
                'Minerals': ['Non-Metallic Minerals'],
                'Fossil': ['Fossil Fuels'],
                'Other_Materials': ['Extraction']
            }
        
        subcategory_impacts = pd.DataFrame(index=factors_data['trade_id'].unique())
        
        for subcat_name, keywords in subcategories.items():
            matching_factors = factors_data[
                factors_data['fullname'].str.contains('|'.join(keywords), case=False, na=False)
            ]
            
            if not matching_factors.empty:
                subcat_impact = matching_factors.groupby('trade_id')['level'].sum()
                subcategory_impacts[f'{category}_{subcat_name}'] = subcat_impact
        
        subcategory_impacts = subcategory_impacts.fillna(0).round(3)
        
        # Merge all data with original trade information
        result_df = trade_df.merge(summary, on='trade_id', how='left')
        
        # Add context-based impacts
        if not context_impacts.empty:
            result_df = result_df.merge(
                context_impacts.reset_index(), 
                on='trade_id', 
                how='left'
            )
        
        # Add subcategory impacts
        if not subcategory_impacts.empty:
            subcategory_reset = subcategory_impacts.reset_index()
            subcategory_reset = subcategory_reset.rename(columns={'index': 'trade_id'})
            result_df = result_df.merge(
                subcategory_reset, 
                on='trade_id', 
                how='left'
            )
        
        # Fill NaN values with 0
        impact_columns = [col for col in result_df.columns if col not in ['trade_id', 'year', 'region1', 'region2', 'industry1', 'industry2', 'amount']]
        result_df[impact_columns] = result_df[impact_columns].fillna(0)
        
        # Calculate intensity
        result_df[f'{category}_intensity'] = (result_df[f'total_{category}_value'] / result_df['amount']).round(6)
        result_df[f'{category}_intensity'] = result_df[f'{category}_intensity'].replace([np.inf, -np.inf], 0)
        
        # Sort by total value descending
        result_df = result_df.sort_values(f'total_{category}_value', ascending=False)
        
        output_files[category] = result_df
    
    # Save all files
    file_mapping = {
        'employment': 'trade_employment',
        'resources': 'trade_resource', 
        'materials': 'trade_material'
    }
    
    for category, df in output_files.items():
        file_key = file_mapping[category]
        output_path = get_file_path(config, file_key)
        df.to_csv(output_path, index=False)
        
        # Display summary
        total_impact = df[f'total_{category}_value'].sum()
        flows_with_data = len(df[df[f'{category}_count'] > 0])
        
        print(f"\nCreated {output_path}")
        print(f"  Total {category} impact: {total_impact:,.0f}")
        print(f"  Flows with {category} data: {flows_with_data}")
        print(f"  Columns: {len(df.columns)}")
        
        if flows_with_data > 0:
            print(f"  Top {category} flows:")
            top_flows = df[df[f'{category}_count'] > 0].head(3)
            for _, row in top_flows.iterrows():
                print(f"    {row['region1']} {row['industry1']} -> {row['region2']}: {row[f'total_{category}_value']:,.0f}")
    
    return output_files

if __name__ == "__main__":
    create_split_resources()