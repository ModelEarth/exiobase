#!/usr/bin/env python3
"""
Create a mapping of Exiobase sectors to 5-character industry IDs
"""

import pandas as pd
import pymrio
from pathlib import Path
import re
from config_loader import load_config, get_reference_file_path
from exiobase_industry import BEA_SECTOR_NAMES, industry_id_to_sector_weights

def create_sector_mapping():
    """
    Create a standardized 5-character ID mapping for Exiobase sectors
    """
    # Load configuration
    config = load_config()
    
    model_path = Path(__file__).parent / 'exiobase_data'
    year = config['YEAR']
    model_type = 'pxp'
    
    exio_file = model_path / f'IOT_{year}_{model_type}.zip'
    
    if not exio_file.exists():
        print(f"Exiobase file not found for {year}: {exio_file}")
        # Only fallback to a prior year that doesn't yet have downloaded data
        # If the year prior to the missing year already has a download, then exit the process
        fallback_year = year - 1
        fallback_file = model_path / f'IOT_{fallback_year}_{model_type}.zip'
        
        if fallback_file.exists():
            print(f"Found existing data for {fallback_year}, using that for sector mapping")
            exio_file = fallback_file
            year = fallback_year
        else:
            print(f"No Exiobase data files found for sector mapping (requested: {year}, checked: {fallback_year})")
            return
    
    print(f"Loading Exiobase data from: {exio_file}")
    exio_model = pymrio.parse_exiobase3(exio_file)
    
    # Get all unique sectors
    sectors = exio_model.Z.index.get_level_values('sector').unique()
    
    sector_mapping = []
    used_ids = set()
    
    for i, sector in enumerate(sectors):
        sector_str = str(sector)
        
        # Create a 5-character ID based on the sector name
        # First, try to extract meaningful characters
        # Remove common words and get key terms
        clean_name = re.sub(r'\b(and|of|related|to|services|products|nec|other)\b', '', sector_str, flags=re.IGNORECASE)
        clean_name = re.sub(r'[^\w\s]', '', clean_name)  # Remove punctuation
        clean_name = clean_name.strip()
        
        # Split into words and take first letters of important words
        words = clean_name.split()
        
        # Strategy 1: Use first 5 characters of cleaned name
        candidate_id = clean_name.replace(' ', '')[:5].upper()
        
        # Strategy 2: If too short, use acronym approach
        if len(candidate_id) < 5 and len(words) > 1:
            # Create acronym from first letters of words
            acronym = ''.join([word[0] for word in words if word])[:3].upper()
            # Add numbers or partial words to reach 5 chars
            candidate_id = (acronym + clean_name.replace(' ', '')[len(acronym):])[:5].upper()
        
        # Strategy 3: If still too short, pad with numbers
        if len(candidate_id) < 5:
            candidate_id = (candidate_id + str(i).zfill(5 - len(candidate_id)))[:5]
        
        # Ensure uniqueness
        original_candidate = candidate_id
        counter = 1
        while candidate_id in used_ids:
            if counter < 10:
                candidate_id = original_candidate[:4] + str(counter)
            else:
                candidate_id = original_candidate[:3] + str(counter).zfill(2)
            counter += 1
        
        used_ids.add(candidate_id)
        
        # Determine sector category for additional metadata
        sector_lower = sector_str.lower()
        if any(term in sector_lower for term in ['crop', 'plant', 'agriculture', 'cattle', 'pig', 'poultry', 'meat', 'milk', 'wool', 'manure']):
            category = 'Agriculture'
        elif any(term in sector_lower for term in ['forestry', 'logging', 'wood', 'timber']):
            category = 'Forestry'
        elif any(term in sector_lower for term in ['fish', 'fishing']):
            category = 'Fishing'
        elif any(term in sector_lower for term in ['coal', 'petroleum', 'crude', 'gas', 'mining', 'ore', 'anthracite', 'lignite']):
            category = 'Mining'
        elif any(term in sector_lower for term in ['food', 'beverage', 'tobacco', 'dairy']):
            category = 'Food Manufacturing'
        elif any(term in sector_lower for term in ['textile', 'clothing', 'leather', 'wearing']):
            category = 'Textiles'
        elif any(term in sector_lower for term in ['chemical', 'pharmaceutical', 'plastic', 'rubber']):
            category = 'Chemicals'
        elif any(term in sector_lower for term in ['metal', 'steel', 'iron', 'aluminum', 'fabricated']):
            category = 'Metals'
        elif any(term in sector_lower for term in ['machinery', 'equipment', 'computer', 'electronic']):
            category = 'Machinery'
        elif any(term in sector_lower for term in ['transport', 'motor', 'vehicle', 'aircraft', 'ship']):
            category = 'Transportation Equipment'
        elif any(term in sector_lower for term in ['construction', 'building']):
            category = 'Construction'
        elif any(term in sector_lower for term in ['electricity', 'gas supply', 'water', 'steam']):
            category = 'Utilities'
        elif any(term in sector_lower for term in ['wholesale', 'retail', 'trade', 'repair']):
            category = 'Trade'
        elif any(term in sector_lower for term in ['transport', 'land', 'water', 'air', 'pipeline']):
            category = 'Transportation Services'
        elif any(term in sector_lower for term in ['accommodation', 'hotel', 'restaurant', 'food service']):
            category = 'Accommodation & Food'
        elif any(term in sector_lower for term in ['information', 'telecommunication', 'publishing', 'media']):
            category = 'Information'
        elif any(term in sector_lower for term in ['financial', 'insurance', 'bank']):
            category = 'Finance & Insurance'
        elif any(term in sector_lower for term in ['real estate', 'rental', 'leasing']):
            category = 'Real Estate'
        elif any(term in sector_lower for term in ['professional', 'technical', 'scientific', 'legal']):
            category = 'Professional Services'
        elif any(term in sector_lower for term in ['administrative', 'support', 'waste', 'management']):
            category = 'Administrative Services'
        elif any(term in sector_lower for term in ['public', 'administration', 'defence', 'government']):
            category = 'Public Administration'
        elif any(term in sector_lower for term in ['education', 'teaching']):
            category = 'Education'
        elif any(term in sector_lower for term in ['health', 'medical', 'social', 'care']):
            category = 'Health & Social'
        elif any(term in sector_lower for term in ['arts', 'entertainment', 'recreation', 'sport']):
            category = 'Arts & Recreation'
        else:
            category = 'Other Services'
        
        sector_mapping.append({
            'industry_id': candidate_id,
            'name': sector_str,
            'category': category,
        })

    # Create DataFrame
    df = pd.DataFrame(sector_mapping)

    # Save to CSV
    output_file = get_reference_file_path(config, 'industries')
    df.to_csv(output_file, index=False)
    print(f"\nCreated {output_file} with {len(df)} sectors")
    
    # Display summary
    print(f"\nSector mapping summary:")
    print(f"Total sectors: {len(df)}")
    print(f"Categories: {df['category'].nunique()}")
    print(f"\nCategory breakdown:")
    print(df['category'].value_counts().head(10))
    
    print(f"\nFirst 20 sector mappings:")
    print(df[['industry_id', 'name', 'category']].head(20).to_string(index=False))
    
    return df


def create_sector_table():
    """
    Write sector.csv: the ~21-category BEA Sector table (sector_id, name),
    referenced by trade.sector1/2 and interstate.sector1/2 via the
    sector_industry many-to-many join (see PLAN-industry.md,
    exiobase_industry.py).
    """
    config = load_config()
    rows = [{'sector_id': code, 'name': name} for code, name in BEA_SECTOR_NAMES.items()]
    df = pd.DataFrame(rows)
    output_file = get_reference_file_path(config, 'sectors')
    df.to_csv(output_file, index=False)
    print(f"Created {output_file} with {len(df)} sectors")
    return df


def create_sector_industry_table():
    """
    Write sector_industry.csv: the many-to-many join between BEA Sector
    (sector.csv) and Exiobase industry (industry.csv), with a weight column
    (fraction of an industry's amount attributed to that sector — see
    exiobase_industry.industry_id_to_sector_weights). Requires industry.csv
    to already exist (create_sector_mapping must run first).
    """
    config = load_config()
    industry_csv_path = get_reference_file_path(config, 'industries')
    weights = industry_id_to_sector_weights(industry_csv_path)
    rows = [
        {'sector_id': sector_code, 'industry_id': industry_id, 'weight': weight}
        for industry_id, sector_weights in weights.items()
        for sector_code, weight in sector_weights
    ]
    df = pd.DataFrame(rows)
    output_file = get_reference_file_path(config, 'sector_industry')
    df.to_csv(output_file, index=False)
    print(f"Created {output_file} with {len(df)} sector/industry pairs")
    return df


if __name__ == "__main__":
    create_sector_mapping()
    create_sector_table()
    create_sector_industry_table()