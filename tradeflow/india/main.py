#!/usr/bin/env python3
"""
India State-Level Trade Flow Allocation

Allocates national trade flows and economic data to Indian states/UTs using:
- State GSDP (Gross State Domestic Product) 2011-12 series
- GSVA/NSVA (Gross/Net State Value Added) by economic activities
- Supply Use Tables (SUT) - national input-output tables
- TradeStat-Eidb Export and Import data (HS codes)
- GSDP_Current_2011-12_State_wise for scaling

Usage (from exiobase/tradeflow/):
    python india/main.py
    python india/main.py --data-dir ../India_data
    python india/main.py --year 2019
"""

import sys
import pandas as pd
import numpy as np
import argparse
import os
import shutil
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Allow imports from parent tradeflow directory (config_loader, etc.)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Try to import openpyxl for Excel support
try:
    import openpyxl
except ImportError:
    print("Warning: openpyxl not installed. Excel file support may be limited.")
    print("Install with: pip install openpyxl")

from config_loader import load_config, get_reference_file_path

class IndiaStateAllocator:
    def __init__(self, data_dir=None, year=None):
        """Initialize India state allocation processor"""
        self.config = load_config()
        
        # Override year if provided
        if year:
            self.year = year
        else:
            self.year = self.config.get('YEAR', 2019)
        
        # Set data directory
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            # Default to India_data folder in exiobase/ root
            self.data_dir = Path(__file__).parent.parent.parent / 'India_data'
        
        if not self.data_dir.exists():
            raise FileNotFoundError(
                f"India data directory not found: {self.data_dir}\n"
                f"Please create the directory and add your data files, or specify with --data-dir"
            )
        
        print(f"India State Allocation for Year {self.year}")
        print(f"Data directory: {self.data_dir}")
        
        # Initialize data containers
        self.gsdp_data = None
        self.gsva_data = None
        self.sut_data = None
        self.export_data = None
        self.import_data = None
        self.hs_exiobase_mapping = None
        self.industry_mapping = None
        self.india_us_crosswalk = None  # Indian GSVA text -> Exiobase industry_id (same IDs as US trade-data)
        self._industry_name_and_id_lookup = {}  # name or id -> industry_id
        
        # Output matrices
        self.state_sector_output = None  # State × Sector output matrix
        self.state_product_export = None  # State × Product export matrix
        self.state_product_import = None  # State × Product import matrix
        self.state_a_matrices = {}  # State-level A-matrices (technical coefficients)
        
        # Scan available files
        self.available_files = self._scan_available_files()
        
        # Load industry mapping from reference files
        self._load_industry_mapping()
        self._load_india_us_crosswalk()
        self._build_industry_id_lookup()
    
    def _scan_available_files(self):
        """Scan the data directory and catalog available files"""
        print("\nScanning India_data directory...")
        files = {
            'gsdp': [],
            'gsva': [],
            'sut': [],
            'export': [],
            'import': [],
            'state_files': [],
            'other': []
        }
        
        for file_path in self.data_dir.iterdir():
            if not file_path.is_file():
                continue
            
            filename_lower = file_path.name.lower()
            
            # GSDP files
            if any(x in filename_lower for x in ['gsdp', 'sdp', 'gdp']) and 'state' in filename_lower:
                files['gsdp'].append(file_path)
            
            # GSVA files
            elif any(x in filename_lower for x in ['gsva', 'nsva', 'value_added']):
                files['gsva'].append(file_path)
            
            # SUT/IOT files
            elif any(x in filename_lower for x in ['sut', 'iot', 'input_output', 'supply_use', 'revision']):
                files['sut'].append(file_path)
            
            # Export files
            elif 'export' in filename_lower and 'tradestat' in filename_lower:
                files['export'].append(file_path)
            
            # Import files
            elif 'import' in filename_lower and 'tradestat' in filename_lower:
                files['import'].append(file_path)
            
            # State-specific files (exclude trade files)
            elif any(x in filename_lower for x in ['andhra', 'assam', 'bihar', 'gujarat', 'karnataka', 
                    'kerala', 'maharashtra', 'tamil', 'delhi', 'punjab', 'rajasthan', 'west', 'uttar',
                    'madhya', 'odisha', 'jharkhand', 'chhatisgarh', 'haryana', 'telengana', 'himachal',
                    'uttarakhand', 'goa', 'manipur', 'meghalaya', 'mizoram', 'nagaland', 'tripura',
                    'sikkim', 'arunachal', 'jammu', 'ladakh', 'chandigarh', 'puducherry', 'andaman']):
                files['state_files'].append(file_path)
            
            else:
                files['other'].append(file_path)
        
        # Print summary
        print(f"  Found {len(files['gsdp'])} GSDP file(s)")
        print(f"  Found {len(files['gsva'])} GSVA file(s)")
        print(f"  Found {len(files['sut'])} SUT file(s)")
        print(f"  Found {len(files['export'])} export file(s)")
        print(f"  Found {len(files['import'])} import file(s)")
        print(f"  Found {len(files['state_files'])} state-specific file(s)")
        
        return files
    
    def _load_industry_mapping(self):
        """Load EXIOBASE industry mapping"""
        try:
            industries_file = get_reference_file_path(self.config, 'industries')
            if Path(industries_file).exists():
                self.industry_mapping = pd.read_csv(industries_file)
                print(f"Loaded industry mapping: {len(self.industry_mapping)} sectors")
            else:
                print("Warning: industry.csv not found, will create mapping from data")
                self.industry_mapping = None
        except Exception as e:
            print(f"Warning: Could not load industry mapping: {e}")
            self.industry_mapping = None

    def _build_industry_id_lookup(self):
        """Map Exiobase industry name and 5-char industry_id -> industry_id (US and IN share this taxonomy in trade-data)."""
        self._industry_name_and_id_lookup = {}
        if self.industry_mapping is None:
            return
        for _, row in self.industry_mapping.iterrows():
            name = str(row["name"]).strip()
            iid = str(row["industry_id"]).strip()
            self._industry_name_and_id_lookup[name.lower()] = iid
            self._industry_name_and_id_lookup[iid.lower()] = iid

    def _load_india_us_crosswalk(self):
        """
        Load India GSVA / national-accounts activity keywords -> Exiobase industry_id.
        The same industry_id values appear in US Exiobase-derived trade outputs, enabling cross-country IO alignment.
        """
        path = Path(__file__).resolve().parent / "india_us_exiobase_crosswalk.csv"
        if not path.exists():
            print(f"Warning: India–US Exiobase crosswalk not found at {path}")
            self.india_us_crosswalk = pd.DataFrame(
                columns=["india_gsva_keyword", "industry_id", "exiobase_industry_name", "alignment_note"]
            )
            self._crosswalk_sorted_keywords = []
            return
        self.india_us_crosswalk = pd.read_csv(path)
        # Longest keywords first so e.g. "public administration" wins over "public"
        kw = self.india_us_crosswalk["india_gsva_keyword"].astype(str).str.strip()
        order = kw.str.len().sort_values(ascending=False).index
        self.india_us_crosswalk = self.india_us_crosswalk.loc[order].reset_index(drop=True)
        self._crosswalk_sorted_keywords = [
            (str(r.india_gsva_keyword).strip().lower(), str(r.industry_id).strip(), str(r.exiobase_industry_name).strip())
            for r in self.india_us_crosswalk.itertuples(index=False)
        ]
        print(f"Loaded India→Exiobase crosswalk: {len(self.india_us_crosswalk)} keyword rows (shared industry_id with US MRIO outputs)")

    def _match_india_sector_to_exiobase(self, sector_label):
        """Return (industry_id, exiobase_industry_name) for an Indian sector label."""
        if sector_label is None or (isinstance(sector_label, float) and np.isnan(sector_label)):
            return "-1", "Unmapped"
        s = str(sector_label).strip().lower()
        if not s:
            return "-1", "Unmapped"
        for kw, iid, ename in self._crosswalk_sorted_keywords:
            if kw and kw in s:
                return iid, ename
        if self._industry_name_and_id_lookup:
            if s in self._industry_name_and_id_lookup:
                iid = self._industry_name_and_id_lookup[s]
                sub = self.industry_mapping[self.industry_mapping["industry_id"] == iid]
                ename = sub["name"].iloc[0] if len(sub) else iid
                return iid, str(ename)
        return "-1", "Unmapped"

    def _resolve_industry_id_from_exiobase_label(self, label):
        """Map HS / pivot product label (name or compact Exiobase code) to 5-char industry_id."""
        if label is None or (isinstance(label, float) and pd.isna(label)):
            return "-1"
        key = str(label).strip().lower()
        if not key or key == "unmapped":
            return "-1"
        if key in self._industry_name_and_id_lookup:
            return self._industry_name_and_id_lookup[key]
        return "-1"

    def load_india_data(self):
        """Load all India data files"""
        print("\n" + "="*60)
        print("Loading India Data Files")
        print("="*60)
        
        # Load GSDP data
        self._load_gsdp_data()
        
        # Load GSVA data
        self._load_gsva_data()
        
        # Load SUT data
        self._load_sut_data()
        
        # Load trade data
        self._load_trade_data()
        
        # Load/create HS to EXIOBASE mapping
        self._load_hs_exiobase_mapping()
        
        print("\n✅ All India data files loaded successfully")
    
    def _load_gsdp_data(self):
        """Load State Domestic Product (GSDP) data - adaptive based on available files"""
        print("\nLoading GSDP data...")
        
        gsdp_file = None
        
        # Use scanned files if available
        if self.available_files['gsdp']:
            # Prefer CSV over Excel
            csv_files = [f for f in self.available_files['gsdp'] if f.suffix.lower() == '.csv']
            if csv_files:
                gsdp_file = csv_files[0]
            else:
                gsdp_file = self.available_files['gsdp'][0]
            print(f"  Using GSDP file: {gsdp_file.name}")
        else:
            # Fallback: try to extract from state files
            print("  No dedicated GSDP file found, will extract from state files")
            self.gsdp_data = self._extract_gsdp_from_state_files()
            if self.gsdp_data is not None:
                print(f"  ✅ Extracted GSDP data: {len(self.gsdp_data)} rows")
                self._standardize_gsdp_columns()
                return
        
        if not gsdp_file:
            raise FileNotFoundError(
                f"GSDP file not found in {self.data_dir}\n"
                f"Please provide a GSDP file or state-specific files with GSDP data"
            )
        
        # Load the file (CSV or Excel)
        try:
            if gsdp_file.suffix.lower() == '.csv':
                self.gsdp_data = pd.read_csv(gsdp_file)
            elif gsdp_file.suffix.lower() in ['.xlsx', '.xls']:
                self.gsdp_data = pd.read_excel(gsdp_file)
                print(f"  Reading Excel GSDP file...")
            
            print(f"  ✅ Loaded GSDP data: {len(self.gsdp_data)} rows")
            print(f"  Columns: {', '.join(self.gsdp_data.columns.tolist()[:5])}...")
            
            # Standardize column names (handle various formats)
            self._standardize_gsdp_columns()
        except Exception as e:
            print(f"  ⚠️ Error loading GSDP file: {e}")
            raise
    
    def _extract_gsdp_from_state_files(self):
        """Extract GSDP data from state-specific Excel files"""
        if not self.available_files['state_files']:
            return None
        
        print("  Extracting GSDP from state files...")
        gsdp_list = []
        
        for state_file in self.available_files['state_files']:
            try:
                state_name = self._extract_state_name(state_file.name)
                
                # Try to read Excel file
                excel_data = pd.read_excel(state_file, sheet_name=None)
                
                # Look for GSDP/SDP data in sheets
                for sheet_name, sheet_df in excel_data.items():
                    # Look for GSDP/SDP columns
                    gsdp_cols = [c for c in sheet_df.columns if any(x in str(c).lower() for x in 
                        ['gsdp', 'sdp', 'gdp', 'total', 'gross state'])]
                    
                    if gsdp_cols and len(sheet_df) > 0:
                        # Try to find year column or use first numeric column
                        year_cols = [c for c in sheet_df.columns if any(x in str(c).lower() for x in 
                            ['year', str(self.year), '2011', '2012'])]
                        
                        for _, row in sheet_df.head(20).iterrows():  # Check first 20 rows
                            gsdp_value = None
                            for col in gsdp_cols:
                                val = pd.to_numeric(row[col], errors='coerce')
                                if pd.notna(val) and val > 0:
                                    gsdp_value = val
                                    break
                            
                            if gsdp_value and gsdp_value > 0:
                                gsdp_list.append({
                                    'state': state_name,
                                    'gsdp_value': gsdp_value
                                })
                                break  # Take first valid value per state
                        break  # Found GSDP, move to next state file
            
            except Exception as e:
                print(f"    ⚠️ Error processing {state_file.name}: {e}")
                continue
        
        if gsdp_list:
            return pd.DataFrame(gsdp_list)
        return None
    
    def _extract_state_name(self, filename):
        """Extract state name from filename"""
        # Remove extension and common prefixes
        name = filename.replace('.xlsx', '').replace('.xls', '').replace('.csv', '')
        name = name.replace('_', ' ').replace('-', ' ')
        
        # Common state name patterns
        state_patterns = {
            'andhra pradesh': 'Andhra Pradesh',
            'arunachal pradesh': 'Arunachal Pradesh',
            'assam': 'Assam',
            'bihar': 'Bihar',
            'chhatisgarh': 'Chhattisgarh',
            'gujarat': 'Gujarat',
            'haryana': 'Haryana',
            'himachal pradesh': 'Himachal Pradesh',
            'jharkhand': 'Jharkhand',
            'karnataka': 'Karnataka',
            'kerala': 'Kerala',
            'madhya pradesh': 'Madhya Pradesh',
            'maharashtra': 'Maharashtra',
            'manipur': 'Manipur',
            'meghalaya': 'Meghalaya',
            'mizoram': 'Mizoram',
            'nagaland': 'Nagaland',
            'odisha': 'Odisha',
            'punjab': 'Punjab',
            'rajasthan': 'Rajasthan',
            'sikkim': 'Sikkim',
            'tamil nadu': 'Tamil Nadu',
            'telengana': 'Telangana',
            'tripura': 'Tripura',
            'uttar pradesh': 'Uttar Pradesh',
            'uttarakhand': 'Uttarakhand',
            'west bengal': 'West Bengal',
            'delhi': 'Delhi',
            'goa': 'Goa',
            'jammu kashmir': 'Jammu and Kashmir',
            'ladakh': 'Ladakh',
            'chandigarh': 'Chandigarh',
            'puducherry': 'Puducherry',
            'andaman nicobar': 'Andaman and Nicobar'
        }
        
        name_lower = name.lower()
        for pattern, state_name in state_patterns.items():
            if pattern in name_lower:
                return state_name
        
        # Return cleaned name if no match
        return name.title()
    
    def _standardize_gsdp_columns(self):
        """Standardize GSDP column names"""
        # Find state column
        state_cols = [c for c in self.gsdp_data.columns if any(x in c.lower() for x in ['state', 'ut', 'region', 'area'])]
        if state_cols:
            self.gsdp_data.rename(columns={state_cols[0]: 'state'}, inplace=True)
        
        # Find year/GSDP value columns
        year_cols = [c for c in self.gsdp_data.columns if str(self.year) in str(c) or '2011-12' in str(c)]
        gsdp_cols = [c for c in self.gsdp_data.columns if any(x in c.lower() for x in ['gsdp', 'value', 'total', 'amount'])]
        
        if year_cols:
            self.gsdp_data['gsdp_value'] = pd.to_numeric(self.gsdp_data[year_cols[0]], errors='coerce')
        elif gsdp_cols:
            self.gsdp_data['gsdp_value'] = pd.to_numeric(self.gsdp_data[gsdp_cols[0]], errors='coerce')
        else:
            # Try to find numeric columns
            numeric_cols = self.gsdp_data.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                self.gsdp_data['gsdp_value'] = self.gsdp_data[numeric_cols[0]]
        
        # Clean state names
        if 'state' in self.gsdp_data.columns:
            self.gsdp_data['state'] = self.gsdp_data['state'].astype(str).str.strip()
            self.gsdp_data = self.gsdp_data[self.gsdp_data['state'].notna()]
            self.gsdp_data = self.gsdp_data[self.gsdp_data['gsdp_value'].notna()]
    
    def _load_gsva_data(self):
        """Load GSVA/NSVA by economic activities - adaptive based on available files"""
        print("\nLoading GSVA/NSVA data...")
        
        gsva_file = None
        
        # Use scanned files if available
        if self.available_files['gsva']:
            csv_files = [f for f in self.available_files['gsva'] if f.suffix.lower() == '.csv']
            if csv_files:
                gsva_file = csv_files[0]
            else:
                gsva_file = self.available_files['gsva'][0]
            print(f"  Using GSVA file: {gsva_file.name}")
        
        # If no dedicated GSVA file, extract from state files
        if not gsva_file:
            print("  No consolidated GSVA file found, extracting from state Excel files...")
            self.gsva_data = self._extract_gsva_from_state_files()
            if self.gsva_data is not None and len(self.gsva_data) > 0:
                print(f"  ✅ Extracted GSVA data from state files: {len(self.gsva_data)} rows")
                self._standardize_gsva_columns()
                return
        
        # Load the file (CSV or Excel)
        if gsva_file:
            try:
                if gsva_file.suffix.lower() == '.csv':
                    self.gsva_data = pd.read_csv(gsva_file)
                elif gsva_file.suffix.lower() in ['.xlsx', '.xls']:
                    self.gsva_data = pd.read_excel(gsva_file)
                
                print(f"  ✅ Loaded GSVA data: {len(self.gsva_data)} rows")
                print(f"  Columns: {', '.join(self.gsva_data.columns.tolist()[:5])}...")
                self._standardize_gsva_columns()
            except Exception as e:
                print(f"  ⚠️ Error reading GSVA file: {e}")
                print(f"  Will extract from state files instead")
                self.gsva_data = self._extract_gsva_from_state_files()
                if self.gsva_data is not None and len(self.gsva_data) > 0:
                    print(f"  ✅ Extracted GSVA data from state files: {len(self.gsva_data)} rows")
                    self._standardize_gsva_columns()
                else:
                    print(f"  ⚠️ Could not load GSVA data, will use fallback method")
                    self.gsva_data = None
        else:
            print(f"  ⚠️ GSVA data not available, will use fallback allocation method")
            self.gsva_data = None
    
    def _extract_gsva_from_state_files(self):
        """Extract GSVA data from individual state Excel files"""
        if not self.available_files['state_files']:
            print(f"  ⚠️ No state Excel files found to extract GSVA data")
            return None
        
        print(f"  Processing {len(self.available_files['state_files'])} state files...")
        all_gsva_data = []
        
        for state_file in self.available_files['state_files']:
            try:
                state_name = self._extract_state_name(state_file.name)
                
                # Try to read Excel file
                excel_data = pd.read_excel(state_file, sheet_name=None)
                
                # Look for sheets with GSVA/NSVA data
                for sheet_name, sheet_df in excel_data.items():
                    if len(sheet_df) == 0:
                        continue
                    
                    # Try to find sector and value columns
                    sector_cols = [c for c in sheet_df.columns if any(x in str(c).lower() for x in 
                        ['sector', 'activity', 'industry', 'economic', 'item', 'description'])]
                    value_cols = [c for c in sheet_df.columns if any(x in str(c).lower() for x in 
                        ['gsva', 'nsva', 'value', 'amount', 'gva', 'gross value'])]
                    
                    # Also check for year-specific columns
                    year_cols = [c for c in sheet_df.columns if str(self.year) in str(c) or 
                                any(x in str(c) for x in ['2011', '2012', '2019', '2020'])]
                    
                    # Use year-specific column if available, otherwise use any value column
                    target_value_cols = year_cols if year_cols else value_cols
                    
                    if sector_cols and target_value_cols:
                        # Extract relevant data
                        for _, row in sheet_df.iterrows():
                            sector = str(row[sector_cols[0]]).strip() if pd.notna(row[sector_cols[0]]) else None
                            
                            # Try each value column
                            value = None
                            for val_col in target_value_cols:
                                val = pd.to_numeric(row[val_col], errors='coerce')
                                if pd.notna(val) and val > 0:
                                    value = val
                                    break
                            
                            # Skip if sector is empty or invalid
                            if not sector or sector.lower() in ['nan', 'none', 'total', 'all', '']:
                                continue
                            
                            if value and value > 0:
                                all_gsva_data.append({
                                    'state': state_name,
                                    'sector': sector,
                                    'value_added': value
                                })
            
            except Exception as e:
                print(f"    ⚠️ Error processing {state_file.name}: {str(e)[:50]}")
                continue
        
        if all_gsva_data:
            df = pd.DataFrame(all_gsva_data)
            print(f"  Extracted {len(df)} GSVA records from {df['state'].nunique()} states")
            return df
        else:
            print(f"  ⚠️ Could not extract GSVA data from state files")
            return None
    
    def _standardize_gsva_columns(self):
        """Standardize GSVA column names"""
        # Find state column
        state_cols = [c for c in self.gsva_data.columns if any(x in c.lower() for x in ['state', 'ut', 'region'])]
        if state_cols:
            self.gsva_data.rename(columns={state_cols[0]: 'state'}, inplace=True)
        
        # Find sector/activity column
        sector_cols = [c for c in self.gsva_data.columns if any(x in c.lower() for x in ['sector', 'activity', 'industry', 'economic'])]
        if sector_cols:
            self.gsva_data.rename(columns={sector_cols[0]: 'sector'}, inplace=True)
        
        # Find value column
        value_cols = [c for c in self.gsva_data.columns if any(x in c.lower() for x in ['gsva', 'nsva', 'value', 'amount'])]
        if value_cols:
            self.gsva_data.rename(columns={value_cols[0]: 'value_added'}, inplace=True)
        
        # Clean data
        if 'state' in self.gsva_data.columns:
            self.gsva_data['state'] = self.gsva_data['state'].astype(str).str.strip()
        if 'sector' in self.gsva_data.columns:
            self.gsva_data['sector'] = self.gsva_data['sector'].astype(str).str.strip()
        if 'value_added' in self.gsva_data.columns:
            self.gsva_data['value_added'] = pd.to_numeric(self.gsva_data['value_added'], errors='coerce')
            self.gsva_data = self.gsva_data[self.gsva_data['value_added'].notna()]
    
    def _load_sut_data(self):
        """Load Supply Use Tables (SUT) - adaptive based on available files"""
        print("\nLoading SUT data...")
        
        sut_file = None
        
        # Use scanned files if available
        if self.available_files['sut']:
            # Prefer files with 'revision' or 'triangle' in name (likely SUT format)
            revision_files = [f for f in self.available_files['sut'] if 
                            any(x in f.name.lower() for x in ['revision', 'triangle', 'sut'])]
            if revision_files:
                sut_file = revision_files[0]
            else:
                sut_file = self.available_files['sut'][0]
            print(f"  Using SUT file: {sut_file.name}")
        
        if not sut_file:
            print(f"  ⚠️ SUT file not found")
            print(f"  SUT data is required for A-matrix calculation")
            print(f"  Available files: {[f.name for f in self.available_files['other']][:5]}...")
            raise FileNotFoundError(
                f"SUT file not found in {self.data_dir}\n"
                f"Please provide a SUT/IOT file or Revision_triangle file"
            )
        
        # Load the file (CSV or Excel)
        try:
            if sut_file.suffix.lower() == '.csv':
                self.sut_data = pd.read_csv(sut_file)
            elif sut_file.suffix.lower() in ['.xlsx', '.xls']:
                self.sut_data = pd.read_excel(sut_file)
                print(f"  Reading Excel SUT file...")
            
            print(f"  ✅ Loaded SUT data: {len(self.sut_data)} rows")
            print(f"  Columns: {', '.join(self.sut_data.columns.tolist()[:5])}...")
        except Exception as e:
            print(f"  ⚠️ Error reading SUT file: {e}")
            raise
    
    def _load_trade_data(self):
        """Load TradeStat-Eidb Export and Import data - adaptive based on available files"""
        print("\nLoading trade data...")
        
        # Export data - use scanned files
        if self.available_files['export']:
            export_file = self.available_files['export'][0]
            print(f"  Using export file: {export_file.name}")
            try:
                if export_file.suffix.lower() == '.csv':
                    self.export_data = pd.read_csv(export_file)
                elif export_file.suffix.lower() in ['.xlsx', '.xls']:
                    # Try reading with different header options
                    self.export_data = self._read_excel_with_flexible_headers(export_file)
                    print(f"  Reading Excel export file...")
                print(f"  ✅ Loaded export data: {len(self.export_data)} rows")
            except Exception as e:
                print(f"  ⚠️ Error loading export file: {e}")
                self.export_data = None
        else:
            print(f"  ⚠️ Export file not found, will skip export allocation")
            self.export_data = None
        
        # Import data - use scanned files
        if self.available_files['import']:
            import_file = self.available_files['import'][0]
            print(f"  Using import file: {import_file.name}")
            try:
                if import_file.suffix.lower() == '.csv':
                    self.import_data = pd.read_csv(import_file)
                elif import_file.suffix.lower() in ['.xlsx', '.xls']:
                    # Try reading with different header options
                    self.import_data = self._read_excel_with_flexible_headers(import_file)
                    print(f"  Reading Excel import file...")
                print(f"  ✅ Loaded import data: {len(self.import_data)} rows")
            except Exception as e:
                print(f"  ⚠️ Error loading import file: {e}")
                self.import_data = None
        else:
            print(f"  ⚠️ Import file not found, will skip import allocation")
            self.import_data = None
    
    def _read_excel_with_flexible_headers(self, excel_file):
        """Read Excel file with flexible header detection"""
        # First, try reading without header to see the structure
        df_no_header = pd.read_excel(excel_file, header=None, nrows=10)
        
        # Look for header row (row with text in first column and numbers in others)
        header_row = None
        for i in range(min(5, len(df_no_header))):  # Check first 5 rows
            row = df_no_header.iloc[i]
            first_col = str(row.iloc[0]).lower() if pd.notna(row.iloc[0]) else ''
            # Check if first column looks like a header (contains text, not just numbers)
            if any(x in first_col for x in ['hs', 'commodity', 'code', 'item', 'tradestat']):
                # Check if other columns have numeric data
                numeric_cols = sum(1 for j in range(1, min(5, len(row))) 
                                 if pd.to_numeric(row.iloc[j], errors='coerce') is not pd.NA)
                if numeric_cols > 0:
                    header_row = i
                    break
        
        # Try reading with detected header row
        if header_row is not None:
            df = pd.read_excel(excel_file, header=header_row)
            print(f"    Detected header at row {header_row + 1}")
        else:
            # Try reading with first row as header
            df = pd.read_excel(excel_file, header=0)
            # If we have unnamed columns, try to use first row as data and infer headers
            if any('Unnamed' in str(c) for c in df.columns):
                # Re-read and use first row as header
                df = pd.read_excel(excel_file, header=0)
                # If still unnamed, try second row
                if any('Unnamed' in str(c) for c in df.columns[:3]):
                    df_temp = pd.read_excel(excel_file, header=None, nrows=2)
                    if len(df_temp) >= 2:
                        # Use second row as column names
                        df = pd.read_excel(excel_file, header=1)
                        print(f"    Using row 2 as header")
        
        # Clean up column names
        df.columns = [str(c).strip() if pd.notna(c) else f'Unnamed_{i}' 
                     for i, c in enumerate(df.columns)]
        
        return df
    
    def _load_hs_exiobase_mapping(self):
        """Load or create HS to EXIOBASE product mapping"""
        print("\nLoading HS to EXIOBASE mapping...")
        
        mapping_file = self.data_dir / 'HS_EXIOBASE_mapping.csv'
        
        if mapping_file.exists():
            self.hs_exiobase_mapping = pd.read_csv(mapping_file)
            print(f"  ✅ Loaded mapping: {len(self.hs_exiobase_mapping)} entries")
            self._attach_industry_ids_to_hs_mapping()
        else:
            print(f"  ⚠️ HS-EXIOBASE mapping not found, will create basic mapping")
            self.hs_exiobase_mapping = self._create_basic_hs_mapping()
            # Save for future use
            mapping_file.parent.mkdir(parents=True, exist_ok=True)
            self.hs_exiobase_mapping.to_csv(mapping_file, index=False)
            print(f"  ✅ Created and saved basic mapping: {mapping_file}")
            self._attach_industry_ids_to_hs_mapping()

    def _attach_industry_ids_to_hs_mapping(self):
        """Add industry_id for each HS row using Exiobase product/sector labels (same codes as US-side trade-data)."""
        if self.hs_exiobase_mapping is None or not len(self.hs_exiobase_mapping):
            return

        def resolve_row(row):
            for col in ("exiobase_product", "exiobase_sector"):
                if col in row.index and pd.notna(row[col]):
                    iid = self._resolve_industry_id_from_exiobase_label(row[col])
                    if iid != "-1":
                        return iid
            return "-1"

        self.hs_exiobase_mapping["industry_id"] = self.hs_exiobase_mapping.apply(resolve_row, axis=1)

    def _create_basic_hs_mapping(self):
        """Create a basic HS to EXIOBASE mapping based on commodity categories"""
        # This is a simplified mapping - should be enhanced with actual concordance
        mapping_data = []
        
        # Basic HS code ranges to EXIOBASE sectors (simplified)
        # Using 2-digit HS chapter codes
        hs_mappings = {
            # Agriculture
            (1, 5): 'Paddy rice',  # Live animals, animal products
            (6, 14): 'Vegetables',  # Vegetable products
            (15, 15): 'OILSE',  # Animal/vegetable fats
            (16, 24): 'FOODS',  # Food products
            # Textiles
            (50, 63): 'TEXTI',  # Textiles and textile articles
            # Chemicals
            (28, 38): 'CHEMI',  # Chemicals
            # Metals
            (72, 83): 'IRON1',  # Base metals
            # Machinery
            (84, 85): 'MACHI',  # Machinery and electrical
            # Vehicles
            (86, 89): 'TRANS',  # Vehicles
        }
        
        # Create mapping entries for 2-digit HS codes (chapters)
        for (hs_start, hs_end), exio_sector in hs_mappings.items():
            for hs_code in range(hs_start, hs_end + 1):
                hs_2digit = f"{hs_code:02d}"
                mapping_data.append({
                    'hs_code': hs_2digit,
                    'hs_code_2digit': hs_2digit,  # 2-digit for matching
                    'hs_code_6digit': f"{hs_code:06d}",  # Padded 6-digit (for reference)
                    'exiobase_sector': exio_sector,
                    'exiobase_product': exio_sector,
                    'confidence': 'low'
                })
        
        print(f"  Created basic mapping with {len(mapping_data)} entries (2-digit HS codes)")
        return pd.DataFrame(mapping_data)
    
    def allocate_state_sector_output(self):
        """
        Allocate state GSDP across sectors using GSVA
        Produces: state × sector output matrix
        """
        print("\n" + "="*60)
        print("Allocating State GSDP Across Sectors")
        print("="*60)
        
        if self.gsdp_data is None:
            raise ValueError("GSDP data must be loaded first")
        
        if self.gsva_data is None:
            print("  ⚠️ GSVA data not available, will use equal distribution across sectors")
            # Create a simple sector list for equal distribution
            # Use common Indian economic sectors if available
            common_sectors = [
                'Agriculture', 'Mining', 'Manufacturing', 'Electricity', 
                'Construction', 'Trade', 'Transport', 'Finance', 
                'Real Estate', 'Public Administration', 'Other Services'
            ]
            # Create dummy GSVA data for equal distribution
            states_list = self.gsdp_data['state'].unique().tolist()
            gsva_list = []
            for state in states_list:
                for sector in common_sectors:
                    gsva_list.append({
                        'state': state,
                        'sector': sector,
                        'value_added': 1.0  # Equal weights
                    })
            self.gsva_data = pd.DataFrame(gsva_list)
        
        # Get unique states
        states = self.gsdp_data['state'].unique()
        print(f"Processing {len(states)} states/UTs")
        
        # Get unique sectors from GSVA
        sectors = self.gsva_data['sector'].unique()
        print(f"Processing {len(sectors)} sectors")
        
        # Create state × sector matrix
        state_sector_list = []
        
        for state in states:
            # Get state GSDP
            state_gsdp = self.gsdp_data[self.gsdp_data['state'] == state]['gsdp_value'].sum()
            
            if state_gsdp == 0 or pd.isna(state_gsdp):
                continue
            
            # Get state GSVA by sector
            state_gsva = self.gsva_data[self.gsva_data['state'] == state].copy()
            
            if len(state_gsva) == 0:
                # If no GSVA data, allocate proportionally based on national averages
                print(f"  ⚠️ No GSVA data for {state}, using national proportions")
                national_gsva = self.gsva_data.groupby('sector')['value_added'].sum()
                national_total = national_gsva.sum()
                
                for sector in sectors:
                    if national_total > 0:
                        sector_share = national_gsva.get(sector, 0) / national_total
                        sector_output = state_gsdp * sector_share
                    else:
                        sector_output = state_gsdp / len(sectors)  # Equal distribution
                    
                    state_sector_list.append({
                        'state': state,
                        'sector': sector,
                        'output': sector_output,
                        'value_added': sector_output * 0.4,  # Approximate VA ratio
                        'allocation_method': 'national_proportion'
                    })
            else:
                # Calculate sector shares from GSVA
                state_gsva_total = state_gsva['value_added'].sum()
                
                if state_gsva_total > 0:
                    for _, row in state_gsva.iterrows():
                        sector = row['sector']
                        value_added = row['value_added']
                        sector_share = value_added / state_gsva_total
                        sector_output = state_gsdp * sector_share
                        
                        state_sector_list.append({
                            'state': state,
                            'sector': sector,
                            'output': sector_output,
                            'value_added': value_added,
                            'allocation_method': 'gsva'
                        })
                else:
                    # Equal distribution if no valid GSVA
                    for sector in sectors:
                        state_sector_list.append({
                            'state': state,
                            'sector': sector,
                            'output': state_gsdp / len(sectors),
                            'value_added': 0,
                            'allocation_method': 'equal'
                        })
        
        self.state_sector_output = pd.DataFrame(state_sector_list)
        matched = self.state_sector_output["sector"].apply(self._match_india_sector_to_exiobase)
        self.state_sector_output["industry_id"] = matched.apply(lambda t: t[0])
        self.state_sector_output["exiobase_industry_name"] = matched.apply(lambda t: t[1])
        
        # Validate: state totals should match GSDP
        validation = self.state_sector_output.groupby('state')['output'].sum()
        gsdp_totals = self.gsdp_data.groupby('state')['gsdp_value'].sum()
        
        print(f"\n✅ Created state × sector output matrix: {len(self.state_sector_output)} entries")
        print(f"   States: {self.state_sector_output['state'].nunique()}")
        print(f"   Sectors: {self.state_sector_output['sector'].nunique()}")
        
        # Show validation summary
        print(f"\nValidation (State totals vs GSDP):")
        for state in validation.index[:5]:  # Show first 5
            gsdp_val = gsdp_totals.get(state, 0)
            output_val = validation[state]
            diff_pct = abs(output_val - gsdp_val) / gsdp_val * 100 if gsdp_val > 0 else 0
            print(f"  {state}: Output={output_val:.2f}, GSDP={gsdp_val:.2f}, Diff={diff_pct:.1f}%")
    
    def allocate_exports_to_states(self):
        """
        Allocate national exports to states using GSDP/sector outputs as proxies
        Maps HS codes → EXIOBASE products
        Produces: state × product export matrix, normalized to national totals
        """
        print("\n" + "="*60)
        print("Allocating National Exports to States")
        print("="*60)
        
        if self.export_data is None:
            print("  ⚠️ No export data available, skipping")
            return
        
        if self.state_sector_output is None:
            raise ValueError("State sector output must be calculated first")
        
        if self.hs_exiobase_mapping is None:
            raise ValueError("HS-EXIOBASE mapping must be loaded")
        
        # Standardize export data columns (returns modified dataframe)
        self.export_data = self._standardize_trade_columns(self.export_data, 'export')
        
        # Verify required columns exist
        if 'value' not in self.export_data.columns:
            raise ValueError(f"Export data missing 'value' column after standardization. Columns: {list(self.export_data.columns)}")
        if 'hs_code' not in self.export_data.columns:
            raise ValueError(f"Export data missing 'hs_code' column after standardization. Columns: {list(self.export_data.columns)}")
        
        # Map HS codes to EXIOBASE products
        export_mapped = self._map_hs_to_exiobase(self.export_data)
        
        # Verify value column still exists after mapping
        if 'value' not in export_mapped.columns:
            raise ValueError(f"Export data missing 'value' column after HS mapping. Columns: {list(export_mapped.columns)}")
        
        # Get national export totals by EXIOBASE product
        national_exports = export_mapped.groupby('exiobase_product')['value'].sum()
        print(f"National exports by product: {len(national_exports)} products")
        
        # Allocate to states based on sector outputs
        state_export_list = []
        
        states = self.state_sector_output['state'].unique()
        products = national_exports.index.unique()
        
        # Map EXIOBASE products to sectors (simplified - should use proper mapping)
        product_sector_map = self._create_product_sector_map()
        
        for product in products:
            national_export_value = national_exports[product]
            
            # industry_id aligns Indian state outputs with US/Exiobase trade-data industry codes
            industry_id = product_sector_map.get(product, None)
            if not industry_id or industry_id == "-1":
                industry_id = self._resolve_industry_id_from_exiobase_label(product)
            use_industry_slice = industry_id and industry_id != "-1"

            if not use_industry_slice:
                state_shares = self.state_sector_output.groupby('state')['output'].sum()
                state_shares = state_shares / state_shares.sum()
            else:
                sector_outputs = self.state_sector_output[
                    self.state_sector_output['industry_id'] == industry_id
                ].groupby('state')['output'].sum()
                
                if sector_outputs.sum() > 0:
                    state_shares = sector_outputs / sector_outputs.sum()
                else:
                    state_shares = self.state_sector_output.groupby('state')['output'].sum()
                    state_shares = state_shares / state_shares.sum()
            
            # Get HS code for this product (if available)
            product_data = export_mapped[export_mapped['exiobase_product'] == product]
            hs_code_value = ''
            if len(product_data) > 0:
                if 'hs_code' in product_data.columns:
                    hs_code_value = str(product_data['hs_code'].iloc[0]) if pd.notna(product_data['hs_code'].iloc[0]) else ''
                elif 'hs_code_mapping' in product_data.columns:
                    hs_code_value = str(product_data['hs_code_mapping'].iloc[0]) if pd.notna(product_data['hs_code_mapping'].iloc[0]) else ''
            
            # Allocate export value to states
            for state, share in state_shares.items():
                state_export_value = national_export_value * share
                
                state_export_list.append({
                    'state': state,
                    'exiobase_product': product,
                    'industry_id': industry_id if use_industry_slice else self._resolve_industry_id_from_exiobase_label(product),
                    'export_value': state_export_value,
                    'hs_code': hs_code_value,
                    'allocation_method': 'industry_id_output' if use_industry_slice else 'gsdp_proportion'
                })
        
        self.state_product_export = pd.DataFrame(state_export_list)
        
        # Normalize to ensure state totals match national totals
        self._normalize_trade_allocation(self.state_product_export, national_exports, 'export_value')
        
        print(f"\n✅ Created state × product export matrix: {len(self.state_product_export)} entries")
        print(f"   States: {self.state_product_export['state'].nunique()}")
        print(f"   Products: {self.state_product_export['exiobase_product'].nunique()}")
        
        # Validation
        state_totals = self.state_product_export.groupby('state')['export_value'].sum()
        national_total = national_exports.sum()
        allocated_total = self.state_product_export['export_value'].sum()
        
        print(f"\nValidation:")
        print(f"  National export total: {national_total:.2f}")
        print(f"  Allocated total: {allocated_total:.2f}")
        print(f"  Difference: {abs(national_total - allocated_total):.2f} ({abs(national_total - allocated_total)/national_total*100:.2f}%)")
    
    def allocate_imports_to_states(self):
        """
        Allocate national imports to states similarly to exports
        Produces: state × product import matrix, normalized to national totals
        """
        print("\n" + "="*60)
        print("Allocating National Imports to States")
        print("="*60)
        
        if self.import_data is None:
            print("  ⚠️ No import data available, skipping")
            return
        
        if self.state_sector_output is None:
            raise ValueError("State sector output must be calculated first")
        
        if self.hs_exiobase_mapping is None:
            raise ValueError("HS-EXIOBASE mapping must be loaded")
        
        # Standardize import data columns (returns modified dataframe)
        self.import_data = self._standardize_trade_columns(self.import_data, 'import')
        
        # Verify required columns exist
        if 'value' not in self.import_data.columns:
            raise ValueError(f"Import data missing 'value' column after standardization. Columns: {list(self.import_data.columns)}")
        if 'hs_code' not in self.import_data.columns:
            raise ValueError(f"Import data missing 'hs_code' column after standardization. Columns: {list(self.import_data.columns)}")
        
        # Map HS codes to EXIOBASE products
        import_mapped = self._map_hs_to_exiobase(self.import_data)
        
        # Verify value column still exists after mapping
        if 'value' not in import_mapped.columns:
            raise ValueError(f"Import data missing 'value' column after HS mapping. Columns: {list(import_mapped.columns)}")
        
        # Get national import totals by EXIOBASE product
        national_imports = import_mapped.groupby('exiobase_product')['value'].sum()
        print(f"National imports by product: {len(national_imports)} products")
        
        # Allocate to states (similar to exports, but can use consumption-based allocation)
        state_import_list = []
        
        states = self.state_sector_output['state'].unique()
        products = national_imports.index.unique()
        
        # Map EXIOBASE products to sectors
        product_sector_map = self._create_product_sector_map()
        
        for product in products:
            national_import_value = national_imports[product]
            industry_id = product_sector_map.get(product, None)
            if not industry_id or industry_id == "-1":
                industry_id = self._resolve_industry_id_from_exiobase_label(product)
            
            # For imports, allocate based on consumption (proxied by total state output/GSDP)
            state_shares = self.state_sector_output.groupby('state')['output'].sum()
            state_shares = state_shares / state_shares.sum()
            
            # Get HS code for this product (if available)
            product_data = import_mapped[import_mapped['exiobase_product'] == product]
            hs_code_value = ''
            if len(product_data) > 0:
                if 'hs_code' in product_data.columns:
                    hs_code_value = str(product_data['hs_code'].iloc[0]) if pd.notna(product_data['hs_code'].iloc[0]) else ''
                elif 'hs_code_mapping' in product_data.columns:
                    hs_code_value = str(product_data['hs_code_mapping'].iloc[0]) if pd.notna(product_data['hs_code_mapping'].iloc[0]) else ''
            
            # Allocate import value to states
            for state, share in state_shares.items():
                state_import_value = national_import_value * share
                
                state_import_list.append({
                    'state': state,
                    'exiobase_product': product,
                    'industry_id': industry_id,
                    'import_value': state_import_value,
                    'hs_code': hs_code_value,
                    'allocation_method': 'gsdp_proportion'
                })
        
        self.state_product_import = pd.DataFrame(state_import_list)
        
        # Normalize to ensure state totals match national totals
        self._normalize_trade_allocation(self.state_product_import, national_imports, 'import_value')
        
        print(f"\n✅ Created state × product import matrix: {len(self.state_product_import)} entries")
        print(f"   States: {self.state_product_import['state'].nunique()}")
        print(f"   Products: {self.state_product_import['exiobase_product'].nunique()}")
        
        # Validation
        state_totals = self.state_product_import.groupby('state')['import_value'].sum()
        national_total = national_imports.sum()
        allocated_total = self.state_product_import['import_value'].sum()
        
        print(f"\nValidation:")
        print(f"  National import total: {national_total:.2f}")
        print(f"  Allocated total: {allocated_total:.2f}")
        print(f"  Difference: {abs(national_total - allocated_total):.2f} ({abs(national_total - allocated_total)/national_total*100:.2f}%)")
    
    def scale_sut_to_states(self):
        """
        Scale national SUT to states using sectoral outputs
        Produces: state-level A-matrices (technical coefficient matrices)
        """
        print("\n" + "="*60)
        print("Scaling SUT to State-Level A-Matrices")
        print("="*60)
        
        if self.sut_data is None:
            raise ValueError("SUT data must be loaded first")
        
        if self.state_sector_output is None:
            raise ValueError("State sector output must be calculated first")
        
        # Parse SUT structure (assuming standard I-O format)
        # SUT typically has: from_sector, to_sector, value
        self._standardize_sut_columns()
        
        # Calculate national technical coefficients (A-matrix)
        national_a_matrix = self._calculate_technical_coefficients(self.sut_data)
        
        print(f"National A-matrix: {national_a_matrix.shape}")
        print(f"  Sectors: {national_a_matrix.index.nunique()} × {national_a_matrix.columns.nunique()}")
        
        # Check sector name matching
        sut_sectors = set(national_a_matrix.index) | set(national_a_matrix.columns)
        state_sectors = set(self.state_sector_output['sector'].unique())
        
        print(f"\nSector matching analysis:")
        print(f"  SUT sectors: {len(sut_sectors)} unique sectors")
        print(f"  State sectors: {len(state_sectors)} unique sectors")
        
        # Find matching sectors
        matching_sectors = sut_sectors & state_sectors
        print(f"  Matching sectors: {len(matching_sectors)}")
        
        if len(matching_sectors) == 0:
            print(f"  ⚠️ WARNING: No sector name matches found between SUT and state sectors!")
            print(f"  SUT sample sectors: {list(sut_sectors)[:5]}")
            print(f"  State sample sectors: {list(state_sectors)[:5]}")
            print(f"  Using national A-matrix directly for all states (no scaling possible)")
            # Use national matrix directly if no matches
            states = self.state_sector_output['state'].unique()
            for state in states:
                self.state_a_matrices[state] = national_a_matrix.copy()
            print(f"\n✅ Created A-matrices for {len(self.state_a_matrices)} states (using national matrix)")
            return
        
        # Create sector mapping if needed (fuzzy matching)
        sector_mapping = self._create_sector_mapping(sut_sectors, state_sectors)
        
        # Scale to each state
        states = self.state_sector_output['state'].unique()
        
        for state in states:
            print(f"\nProcessing state: {state}")
            
            # Get state sector outputs
            state_outputs = self.state_sector_output[
                self.state_sector_output['state'] == state
            ].set_index('sector')['output']
            
            # Scale A-matrix for this state
            # Method: Use national coefficients but adjust for state output structure
            state_a_matrix = national_a_matrix.copy()
            
            # Track if we have any valid scaling
            has_valid_data = False
            
            # Adjust coefficients based on state sector specialization
            for from_sector in state_a_matrix.index:
                for to_sector in state_a_matrix.columns:
                    national_coeff = state_a_matrix.loc[from_sector, to_sector]
                    
                    # Map SUT sectors to state sectors if needed
                    state_from_sector = sector_mapping.get(from_sector, from_sector)
                    state_to_sector = sector_mapping.get(to_sector, to_sector)
                    
                    # Get state outputs (use mapped sector names)
                    state_from_output = state_outputs.get(state_from_sector, 0)
                    state_to_output = state_outputs.get(state_to_sector, 0)
                    
                    # Get national outputs
                    national_from_output = self.state_sector_output[
                        self.state_sector_output['sector'] == state_from_sector
                    ]['output'].sum() if state_from_sector in state_sectors else 0
                    national_to_output = self.state_sector_output[
                        self.state_sector_output['sector'] == state_to_sector
                    ]['output'].sum() if state_to_sector in state_sectors else 0
                    
                    if national_from_output > 0 and national_to_output > 0:
                        # Scale coefficient by state/national output ratios
                        output_ratio = (state_from_output / national_from_output) * (state_to_output / national_to_output)
                        state_a_matrix.loc[from_sector, to_sector] = national_coeff * output_ratio
                        if output_ratio > 0:
                            has_valid_data = True
                    elif national_coeff > 0:
                        # Keep national coefficient if we can't scale
                        has_valid_data = True
            
            # If no valid scaling occurred, use national matrix directly
            if not has_valid_data:
                print(f"  ⚠️ No sector matches for scaling, using national A-matrix directly")
                state_a_matrix = national_a_matrix.copy()
            
            self.state_a_matrices[state] = state_a_matrix
            
            # Validate: row sums should be reasonable (typically < 1 for most sectors)
            row_sums = state_a_matrix.sum(axis=1)
            non_zero_count = (state_a_matrix != 0).sum().sum()
            print(f"  A-matrix: {non_zero_count} non-zero entries")
            print(f"  Row sums: min={row_sums.min():.3f}, max={row_sums.max():.3f}, mean={row_sums.mean():.3f}")
        
        print(f"\n✅ Created A-matrices for {len(self.state_a_matrices)} states")
    
    def _create_sector_mapping(self, sut_sectors, state_sectors):
        """Create mapping between SUT sectors and state sectors"""
        mapping = {}
        
        # Direct matches
        for sut_sector in sut_sectors:
            if sut_sector in state_sectors:
                mapping[sut_sector] = sut_sector
            else:
                # Try fuzzy matching (case-insensitive, partial matches)
                sut_lower = str(sut_sector).lower().strip()
                best_match = None
                best_score = 0
                
                for state_sector in state_sectors:
                    state_lower = str(state_sector).lower().strip()
                    
                    # Exact match (case-insensitive)
                    if sut_lower == state_lower:
                        best_match = state_sector
                        best_score = 1.0
                        break
                    
                    # Check if one contains the other
                    if sut_lower in state_lower or state_lower in sut_lower:
                        score = min(len(sut_lower), len(state_lower)) / max(len(sut_lower), len(state_lower))
                        if score > best_score:
                            best_score = score
                            best_match = state_sector
                
                if best_match and best_score > 0.5:  # At least 50% match
                    mapping[sut_sector] = best_match
        
        if mapping:
            print(f"  Created sector mapping: {len(mapping)} sectors mapped")
            if len(mapping) < len(sut_sectors):
                print(f"  ⚠️ {len(sut_sectors) - len(mapping)} SUT sectors could not be mapped")
        
        return mapping
    
    def _standardize_sut_columns(self):
        """Standardize SUT column names"""
        # Find from/to sector columns
        from_cols = [c for c in self.sut_data.columns if any(x in c.lower() for x in ['from', 'source', 'input', 'sector1'])]
        to_cols = [c for c in self.sut_data.columns if any(x in c.lower() for x in ['to', 'destination', 'output', 'sector2'])]
        value_cols = [c for c in self.sut_data.columns if any(x in c.lower() for x in ['value', 'amount', 'flow', 'transaction'])]
        
        if from_cols and to_cols and value_cols:
            self.sut_data.rename(columns={
                from_cols[0]: 'from_sector',
                to_cols[0]: 'to_sector',
                value_cols[0]: 'value'
            }, inplace=True)
        else:
            # Try to infer from structure
            if len(self.sut_data.columns) >= 3:
                self.sut_data.columns = ['from_sector', 'to_sector', 'value'] + list(self.sut_data.columns[3:])
        
        # Clean data
        if 'from_sector' in self.sut_data.columns:
            self.sut_data['from_sector'] = self.sut_data['from_sector'].astype(str).str.strip()
        if 'to_sector' in self.sut_data.columns:
            self.sut_data['to_sector'] = self.sut_data['to_sector'].astype(str).str.strip()
        if 'value' in self.sut_data.columns:
            self.sut_data['value'] = pd.to_numeric(self.sut_data['value'], errors='coerce')
            self.sut_data = self.sut_data[self.sut_data['value'].notna()]
    
    def _standardize_trade_columns(self, trade_df, trade_type):
        """Standardize trade data column names"""
        print(f"  Standardizing {trade_type} columns...")
        print(f"  Original columns: {list(trade_df.columns)[:10]}")
        
        # Find HS code column - try multiple patterns
        hs_cols = [c for c in trade_df.columns if any(x in str(c).lower() for x in 
            ['hs', 'commodity', 'code', 'product_code', 'item', 'commodity code', 'hs code'])]
        if hs_cols:
            trade_df.rename(columns={hs_cols[0]: 'hs_code'}, inplace=True)
            print(f"  Found HS code column: {hs_cols[0]} -> hs_code")
        else:
            # Try to find first column that looks like a code
            for col in trade_df.columns:
                if trade_df[col].dtype in ['object', 'string']:
                    # Check if values look like codes (numeric strings)
                    sample = trade_df[col].dropna().head(10)
                    if len(sample) > 0 and all(str(v).replace('.', '').isdigit() for v in sample if pd.notna(v)):
                        trade_df.rename(columns={col: 'hs_code'}, inplace=True)
                        print(f"  Using first code-like column as HS code: {col} -> hs_code")
                        break
        
        # Find value column - try multiple patterns
        value_cols = [c for c in trade_df.columns if any(x in str(c).lower() for x in 
            ['value', 'amount', 'export', 'import', 'trade', 'usd', 'rupee', 'rs', 'inr', 'quantity'])]
        
        if not value_cols:
            # Try to find numeric columns (excluding HS code)
            numeric_cols = trade_df.select_dtypes(include=[np.number]).columns.tolist()
            if 'hs_code' in trade_df.columns:
                numeric_cols = [c for c in numeric_cols if c != 'hs_code']
            
            # Also check "Unnamed" columns that might contain numeric data
            unnamed_cols = [c for c in trade_df.columns if 'Unnamed' in str(c)]
            for col in unnamed_cols:
                # Check if column contains numeric data
                sample = trade_df[col].dropna().head(20)
                if len(sample) > 0:
                    numeric_count = sum(1 for v in sample if pd.to_numeric(v, errors='coerce') is not pd.NA)
                    if numeric_count > len(sample) * 0.5:  # More than 50% numeric
                        numeric_cols.append(col)
            
            if numeric_cols:
                # Use the largest numeric column (likely the value)
                max_col = numeric_cols[0]
                max_sum = trade_df[numeric_cols[0]].abs().sum() if pd.api.types.is_numeric_dtype(trade_df[numeric_cols[0]]) else 0
                for col in numeric_cols[1:]:
                    if pd.api.types.is_numeric_dtype(trade_df[col]):
                        col_sum = trade_df[col].abs().sum()
                    else:
                        # Try to convert
                        col_numeric = pd.to_numeric(trade_df[col], errors='coerce')
                        col_sum = col_numeric.abs().sum()
                    if col_sum > max_sum:
                        max_sum = col_sum
                        max_col = col
                value_cols = [max_col]
                print(f"  Using largest numeric column as value: {max_col}")
        
        if value_cols:
            trade_df.rename(columns={value_cols[0]: 'value'}, inplace=True)
            print(f"  Found value column: {value_cols[0]} -> value")
        else:
            raise ValueError(
                f"Could not find value column in {trade_type} data. "
                f"Available columns: {list(trade_df.columns)}. "
                f"Please ensure the data has a column with trade values."
            )
        
        # Clean HS codes
        if 'hs_code' in trade_df.columns:
            # Convert to string first, handling NaN values
            trade_df['hs_code'] = trade_df['hs_code'].apply(lambda x: 
                str(x) if pd.notna(x) else '')
            trade_df['hs_code'] = trade_df['hs_code'].str.strip()
            # Clean HS code (remove dots, dashes, spaces)
            trade_df['hs_code'] = trade_df['hs_code'].apply(lambda x: 
                str(x).replace('.', '').replace('-', '').replace(' ', '') 
                if x and str(x) != 'nan' else '')
            # Normalize to 2-digit format (pad with zeros if needed, but keep original length if longer)
            # This handles both 2-digit and 6-digit codes
            def normalize_hs_code(x):
                if not x or x == 'nan':
                    return ''
                # Remove leading zeros for comparison, but keep original format
                cleaned = x.lstrip('0')
                if not cleaned:
                    return '00'  # All zeros becomes '00'
                # If it's 1-2 digits, pad to 2 digits
                if len(cleaned) <= 2:
                    return cleaned.zfill(2)
                # If it's longer (6-digit), keep first 2 digits
                return cleaned[:2].zfill(2)
            
            trade_df['hs_code'] = trade_df['hs_code'].apply(normalize_hs_code)
            # Remove empty HS codes
            trade_df = trade_df[trade_df['hs_code'] != ''].copy()
            print(f"  HS codes normalized: sample = {trade_df['hs_code'].head(5).tolist()}")
        else:
            raise ValueError(
                f"Could not find HS code column in {trade_type} data. "
                f"Available columns: {list(trade_df.columns)}. "
                f"Please ensure the data has a column with HS/commodity codes."
            )
        
        # Clean values
        if 'value' in trade_df.columns:
            trade_df['value'] = pd.to_numeric(trade_df['value'], errors='coerce')
            # Remove rows with invalid values
            initial_count = len(trade_df)
            trade_df = trade_df[trade_df['value'].notna()].copy()
            trade_df = trade_df[trade_df['value'] > 0].copy()  # Only positive values
            removed = initial_count - len(trade_df)
            if removed > 0:
                print(f"  Removed {removed} rows with invalid values")
            print(f"  Final {trade_type} data: {len(trade_df)} rows")
        else:
            raise ValueError(f"Value column not found after standardization")
        
        return trade_df
    
    def _map_hs_to_exiobase(self, trade_df):
        """Map HS codes to EXIOBASE products"""
        if 'hs_code' not in trade_df.columns:
            raise ValueError("HS code column not found in trade data")
        
        print(f"  Mapping {len(trade_df)} HS codes to EXIOBASE products...")
        
        # Ensure HS codes are strings in both dataframes
        trade_df = trade_df.copy()
        trade_df['hs_code'] = trade_df['hs_code'].astype(str).str.strip()
        
        # Normalize HS codes to 2-digit format for matching
        # If codes are already 2-digit, use them directly; if longer, extract first 2 digits
        trade_df['hs_code_2digit'] = trade_df['hs_code'].apply(
            lambda x: x[:2].zfill(2) if len(x) >= 2 else x.zfill(2) if x else ''
        )
        
        # Preserve original hs_code column name
        trade_hs_code = trade_df['hs_code'].copy()
        
        # Ensure mapping HS codes are also strings
        mapping = self.hs_exiobase_mapping.copy()
        
        # Create 2-digit column in mapping if it doesn't exist
        if 'hs_code_2digit' not in mapping.columns:
            if 'hs_code_6digit' in mapping.columns:
                # Extract 2-digit from 6-digit codes
                mapping['hs_code_2digit'] = mapping['hs_code_6digit'].astype(str).str[:2].str.zfill(2)
            elif 'hs_code' in mapping.columns:
                # Use hs_code directly if it's already 2-digit, or extract first 2 digits
                mapping['hs_code_2digit'] = mapping['hs_code'].astype(str).apply(
                    lambda x: x[:2].zfill(2) if len(x) >= 2 else x.zfill(2) if x else ''
                )
            else:
                print(f"  ⚠️ WARNING: Mapping file has no HS code columns!")
                print(f"  Mapping columns: {list(mapping.columns)}")
                trade_mapped = trade_df.copy()
                trade_mapped['exiobase_product'] = 'Unmapped'
                return trade_mapped
        
        # Convert to string, strip, and ensure 2-digit format
        mapping['hs_code_2digit'] = mapping['hs_code_2digit'].astype(str).str.strip().apply(
            lambda x: x[:2].zfill(2) if len(x) >= 2 else x.zfill(2) if x else ''
        )
        
        # Show sample of what we're matching
        print(f"  Sample trade HS codes: {trade_df['hs_code'].head(5).tolist()}")
        print(f"  Sample trade 2-digit: {trade_df['hs_code_2digit'].head(5).tolist()}")
        print(f"  Sample mapping 2-digit: {mapping['hs_code_2digit'].head(5).tolist()}")
        print(f"  Mapping has {len(mapping)} entries")
        
        # Merge on 2-digit codes
        trade_mapped = trade_df.merge(
            mapping,
            left_on='hs_code_2digit',
            right_on='hs_code_2digit',
            how='left',
            suffixes=('', '_mapping')
        )
        
        # Ensure hs_code column exists (use original if it was dropped)
        if 'hs_code' not in trade_mapped.columns:
            trade_mapped['hs_code'] = trade_hs_code
        
        # Fill missing mappings with 'Unmapped'
        if 'exiobase_product' in trade_mapped.columns:
            unmapped_count = trade_mapped['exiobase_product'].isna().sum()
            mapped_count = len(trade_mapped) - unmapped_count
            print(f"  Mapping results: {mapped_count} mapped, {unmapped_count} unmapped")
            trade_mapped['exiobase_product'] = trade_mapped['exiobase_product'].fillna('Unmapped')
        else:
            # If no mapping found, create default
            print(f"  ⚠️ WARNING: No exiobase_product column after merge!")
            print(f"  Merged columns: {list(trade_mapped.columns)}")
            trade_mapped['exiobase_product'] = 'Unmapped'
        
        # Show sample of mapped products
        if 'exiobase_product' in trade_mapped.columns:
            sample_products = trade_mapped['exiobase_product'].value_counts().head(5)
            print(f"  Top 5 mapped products: {dict(sample_products)}")
        
        return trade_mapped
    
    def _create_product_sector_map(self):
        """Map EXIOBASE product labels (name or 5-char id) to industry_id for state allocation."""
        product_sector_map = {}
        if self.industry_mapping is not None:
            for _, row in self.industry_mapping.iterrows():
                name = row["name"]
                iid = row["industry_id"]
                product_sector_map[name] = iid
                product_sector_map[iid] = iid
        if self.hs_exiobase_mapping is not None:
            for _, row in self.hs_exiobase_mapping.iterrows():
                iid = row["industry_id"] if "industry_id" in row.index else "-1"
                if pd.isna(iid) or str(iid).strip() == "":
                    iid = "-1"
                iid = str(iid).strip()
                for col in ("exiobase_product", "exiobase_sector"):
                    if col in row.index and pd.notna(row[col]) and str(row[col]).strip():
                        product_sector_map[str(row[col]).strip()] = iid
        return product_sector_map
    
    def _calculate_technical_coefficients(self, sut_df):
        """Calculate technical coefficient matrix (A-matrix) from SUT"""
        # A = Z / x, where Z is intermediate flow matrix, x is output vector
        
        # Create Z matrix (from_sector × to_sector)
        z_matrix = sut_df.pivot_table(
            index='from_sector',
            columns='to_sector',
            values='value',
            aggfunc='sum',
            fill_value=0
        )
        
        # Calculate total output by sector (column sums)
        sector_outputs = z_matrix.sum(axis=0)
        
        # Calculate A-matrix: A_ij = Z_ij / x_j
        a_matrix = z_matrix.div(sector_outputs, axis=1).fillna(0)
        
        return a_matrix
    
    def _normalize_trade_allocation(self, state_trade_df, national_totals, value_column):
        """Normalize state allocations to match national totals"""
        # Calculate current allocation totals by product
        allocated_totals = state_trade_df.groupby('exiobase_product')[value_column].sum()
        
        # Calculate normalization factors
        normalization_factors = national_totals / allocated_totals
        normalization_factors = normalization_factors.fillna(1.0)
        
        # Apply normalization
        state_trade_df[value_column] = state_trade_df.apply(
            lambda row: row[value_column] * normalization_factors.get(row['exiobase_product'], 1.0),
            axis=1
        )
    
    def save_outputs(self, output_dir=None):
        """Save all output matrices as CSV files"""
        print("\n" + "="*60)
        print("Saving Output Matrices")
        print("="*60)
        
        if output_dir is None:
            tradeflow_root = Path(__file__).resolve().parent.parent
            rel = self.config["FOLDERS"]["domestic"].format(year=self.year, country="IN")
            output_dir = (tradeflow_root / rel).resolve()
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Output directory: {output_dir}")

        crosswalk_src = Path(__file__).resolve().parent / "india_us_exiobase_crosswalk.csv"
        if crosswalk_src.exists():
            shutil.copy(crosswalk_src, output_dir / "india_us_exiobase_crosswalk.csv")
            print(f"✅ Copied India–US Exiobase crosswalk to: {output_dir / 'india_us_exiobase_crosswalk.csv'}")
        
        # Save state × sector output matrix
        if self.state_sector_output is not None:
            output_file = output_dir / 'state_sector_output.csv'
            self.state_sector_output.to_csv(output_file, index=False)
            print(f"✅ Saved: {output_file}")
        
        # Save state × product export matrix
        if self.state_product_export is not None:
            output_file = output_dir / 'state_product_export.csv'
            self.state_product_export.to_csv(output_file, index=False)
            print(f"✅ Saved: {output_file}")
        
        # Save state × product import matrix
        if self.state_product_import is not None:
            output_file = output_dir / 'state_product_import.csv'
            self.state_product_import.to_csv(output_file, index=False)
            print(f"✅ Saved: {output_file}")
        
        # State A-matrices are calculated but not saved as individual files
        if self.state_a_matrices:
            print(f"  Note: {len(self.state_a_matrices)} state A-matrices were calculated but not saved as individual files")
        
        # Create summary report
        self._create_summary_report(output_dir)
        self.generate_india_states_summary(output_dir)

        print(f"\n✅ All outputs saved to: {output_dir}")
    
    def _sanitize_filename(self, filename):
        """Sanitize filename by removing/replacing invalid characters"""
        # Replace invalid Windows filename characters
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*', '&']
        sanitized = str(filename)
        for char in invalid_chars:
            sanitized = sanitized.replace(char, '_')
        # Remove leading/trailing spaces and dots
        sanitized = sanitized.strip(' .')
        # Replace multiple underscores with single underscore
        while '__' in sanitized:
            sanitized = sanitized.replace('__', '_')
        return sanitized
    
    def _create_summary_report(self, output_dir):
        """Create a summary report of the allocation process"""
        report_file = output_dir / 'allocation_report.md'
        
        with open(report_file, 'w') as f:
            f.write(f"# India State-Level Allocation Report\n\n")
            f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Year**: {self.year}\n\n")
            f.write("## India–US Exiobase alignment\n\n")
            f.write("Indian GSVA activity strings map to Exiobase `industry_id` (5-character codes) via ")
            f.write("`india_us_exiobase_crosswalk.csv` — the same `industry_id` dimension as US `trade-data` outputs.\n\n")
            
            f.write("## Data Sources\n\n")
            f.write(f"- GSDP Data: {len(self.gsdp_data) if self.gsdp_data is not None else 0} records\n")
            f.write(f"- GSVA Data: {len(self.gsva_data) if self.gsva_data is not None else 0} records\n")
            f.write(f"- SUT Data: {len(self.sut_data) if self.sut_data is not None else 0} records\n")
            f.write(f"- Export Data: {len(self.export_data) if self.export_data is not None else 0} records\n")
            f.write(f"- Import Data: {len(self.import_data) if self.import_data is not None else 0} records\n\n")
            
            f.write("## Output Matrices\n\n")
            
            if self.state_sector_output is not None:
                f.write(f"### State × Sector Output Matrix\n")
                f.write(f"- Rows: {len(self.state_sector_output)}\n")
                f.write(f"- States: {self.state_sector_output['state'].nunique()}\n")
                f.write(f"- Sectors: {self.state_sector_output['sector'].nunique()}\n")
                f.write(f"- Total Output: {self.state_sector_output['output'].sum():.2f}\n\n")
            
            if self.state_product_export is not None:
                f.write(f"### State × Product Export Matrix\n")
                f.write(f"- Rows: {len(self.state_product_export)}\n")
                f.write(f"- States: {self.state_product_export['state'].nunique()}\n")
                f.write(f"- Products: {self.state_product_export['exiobase_product'].nunique()}\n")
                f.write(f"- Total Exports: {self.state_product_export['export_value'].sum():.2f}\n\n")
            
            if self.state_product_import is not None:
                f.write(f"### State × Product Import Matrix\n")
                f.write(f"- Rows: {len(self.state_product_import)}\n")
                f.write(f"- States: {self.state_product_import['state'].nunique()}\n")
                f.write(f"- Products: {self.state_product_import['exiobase_product'].nunique()}\n")
                f.write(f"- Total Imports: {self.state_product_import['import_value'].sum():.2f}\n\n")
            
            if self.state_a_matrices:
                f.write(f"### State A-Matrices\n")
                f.write(f"- Number of states: {len(self.state_a_matrices)}\n")
                sample_state = list(self.state_a_matrices.keys())[0]
                sample_matrix = self.state_a_matrices[sample_state]
                f.write(f"- Matrix dimensions: {sample_matrix.shape}\n\n")
        
        print(f"✅ Created summary report: {report_file}")
    
    def run_full_allocation(self, output_dir=None):
        """Run the complete allocation process"""
        print("\n" + "="*80)
        print("INDIA STATE-LEVEL ALLOCATION PROCESS")
        print("="*80)
        
        # Step 1: Load data
        self.load_india_data()
        
        # Step 2: Allocate state sector outputs
        self.allocate_state_sector_output()
        
        # Step 3: Allocate exports
        self.allocate_exports_to_states()
        
        # Step 4: Allocate imports
        self.allocate_imports_to_states()
        
        # Step 5: Scale SUT to states
        self.scale_sut_to_states()
        
        # Step 6: Save outputs
        self.save_outputs(output_dir=output_dir)
        
        print("\n" + "="*80)
        print("✅ ALLOCATION PROCESS COMPLETE")
        print("="*80)

    def generate_india_states_summary(self, output_dir):

        import pandas as pd
        import os

        print("\nGenerating india_states.csv summary file...")

        state_sector_path = os.path.join(output_dir, "state_sector_output.csv")
        if not os.path.exists(state_sector_path):
            print("❌ ERROR: state_sector_output.csv not found — cannot build india_states.csv")
            return

        df = pd.read_csv(state_sector_path)

        # Group totals
        summary = df.groupby("state")["output"].sum().reset_index()

        # Rename to match UI expectations
        summary = summary.rename(columns={
            "state": "State",
            "output": "Output"
        })

        # Placeholder values until India employment/population are added
        summary["Employment"] = 0
        summary["Population"] = 0


        target_path = os.path.join(output_dir, "india_states.csv")
        summary.to_csv(target_path, index=False, sep=",")

        print(f"✅ india_states.csv created at: {target_path}")



def main():
    parser = argparse.ArgumentParser(description='India State-Level Trade Flow Allocation')
    parser.add_argument('--data-dir', help='Directory containing India data files', default=None)
    parser.add_argument('--year', type=int, help='Year for processing', default=None)
    parser.add_argument('--output-dir', help='Output directory for results', default=None)
    
    args = parser.parse_args()
    
    try:
        print("Initializing India State Allocation...")
        allocator = IndiaStateAllocator(data_dir=args.data_dir, year=args.year)
        allocator.run_full_allocation(output_dir=args.output_dir)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())

