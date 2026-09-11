"""
BEA API Client for Enhanced Trade Data Retrieval

Handles Bureau of Economic Analysis API integration with rate limiting,
error handling, data caching, and preprocessing for trade flow analysis.
"""

import pandas as pd
import requests
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
import hashlib

class BEAAPIClient:
    def __init__(self, api_key, base_url="https://apps.bea.gov/api/data"):
        self.api_key = api_key
        self.base_url = base_url
        self.call_delay = 0.5  # 500ms between calls
        self.cache_dir = Path(__file__).parent / 'bea_cache'
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_duration_hours = 24
        
        # Track API usage
        self.api_calls_made = 0
        self.session = requests.Session()
        
    def get_international_trade_data(self, year, trade_direction='All', frequency='A'):
        """
        Get international trade in goods and services data
        
        Args:
            year: Data year (from config.yaml)
            trade_direction: 'Imports', 'Exports', or 'All'
            frequency: 'A' for annual, 'Q' for quarterly
        """
        params = {
            'UserID': self.api_key,
            'Method': 'GetData',
            'DataSetName': 'IntlServTrade',
            'Year': str(year),
            'TradeDirection': trade_direction,
            'Frequency': frequency,
            'ResultFormat': 'JSON'
        }
        
        return self._make_cached_request('international_trade', params)
    
    def get_state_exports_data(self, year, state_code='ALL'):
        """
        Get state-level export data
        
        Args:
            year: Data year
            state_code: State abbreviation or 'ALL' for all states
        """
        params = {
            'UserID': self.api_key,
            'Method': 'GetData',
            'DataSetName': 'IntlServTrade',
            'Year': str(year),
            'TradeDirection': 'Exports',
            'State': state_code,
            'ResultFormat': 'JSON'
        }
        
        return self._make_cached_request('state_exports', params)
    
    def get_input_output_data(self, year, table_id='Summary'):
        """
        Get Input-Output table data
        
        Args:
            year: Data year
            table_id: 'Summary' or 'Detail'
        """
        params = {
            'UserID': self.api_key,
            'Method': 'GetData',
            'DataSetName': 'InputOutput',
            'Year': str(year),
            'TableID': table_id,
            'ResultFormat': 'JSON'
        }
        
        return self._make_cached_request('input_output', params)
    
    def get_gdp_by_industry_data(self, year, industry='ALL'):
        """
        Get GDP by industry data
        
        Args:
            year: Data year
            industry: Industry code or 'ALL'
        """
        params = {
            'UserID': self.api_key,
            'Method': 'GetData',
            'DataSetName': 'GDPbyIndustry',
            'Year': str(year),
            'Industry': industry,
            'ResultFormat': 'JSON'
        }
        
        return self._make_cached_request('gdp_by_industry', params)

    def get_regional_data(self, year, table_name, line_code, geo_fips='STATE'):
        """
        Get BEA Regional data for state allocation weights.

        Examples:
        - SAGDP2: GDP by state and industry
        - SAPCE3: PCE by state and product type
        """
        params = {
            'UserID': self.api_key,
            'Method': 'GetData',
            'DataSetName': 'Regional',
            'TableName': table_name,
            'LineCode': str(line_code),
            'GeoFIPS': geo_fips,
            'Year': str(year),
            'ResultFormat': 'JSON'
        }

        return self._make_cached_request(f'regional_{table_name}_{line_code}', params)
    
    def _make_cached_request(self, data_type, params):
        """Make API request with caching"""
        # Generate cache key
        cache_key = self._generate_cache_key(data_type, params)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        # Check cache
        if self._is_cache_valid(cache_file):
            print(f"  📦 Using cached {data_type} data")
            with open(cache_file, 'r') as f:
                return json.load(f)
        
        # Make API request
        try:
            print(f"  🌐 Fetching {data_type} from BEA API...")
            
            # Rate limiting
            time.sleep(self.call_delay)
            
            response = self.session.get(self.base_url, params=params)
            response.raise_for_status()
            
            data = response.json()
            self.api_calls_made += 1
            
            # Validate response
            if 'BEAAPI' not in data:
                raise ValueError(f"Invalid BEA API response for {data_type}")
            
            # Cache successful response
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            print(f"    ✅ Retrieved and cached {data_type} data")
            return data
            
        except requests.RequestException as e:
            print(f"    ❌ BEA API request failed for {data_type}: {e}")
            raise
        except ValueError as e:
            print(f"    ❌ Invalid BEA API response for {data_type}: {e}")
            raise
    
    def _generate_cache_key(self, data_type, params):
        """Generate cache key from parameters"""
        # Create consistent key from parameters
        param_str = json.dumps(
            {k: v for k, v in sorted(params.items()) if k != 'UserID'}, 
            sort_keys=True
        )
        
        return hashlib.md5(f"{data_type}_{param_str}".encode()).hexdigest()
    
    def _is_cache_valid(self, cache_file):
        """Check if cached file is still valid"""
        if not cache_file.exists():
            return False
        
        # Check age
        file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        return file_age < timedelta(hours=self.cache_duration_hours)
    
    def process_trade_response(self, response_data):
        """Process BEA trade API response into DataFrame"""
        try:
            if 'BEAAPI' in response_data and 'Results' in response_data['BEAAPI']:
                results = response_data['BEAAPI']['Results']
                if 'Data' in results:
                    df = pd.DataFrame(results['Data'])
                    return self._standardize_trade_columns(df)
            
            return pd.DataFrame()
            
        except Exception as e:
            print(f"    ⚠️ Error processing trade response: {e}")
            return pd.DataFrame()
    
    def process_state_response(self, response_data):
        """Process BEA state API response into DataFrame"""
        try:
            if 'BEAAPI' in response_data and 'Results' in response_data['BEAAPI']:
                results = response_data['BEAAPI']['Results']
                if 'Data' in results:
                    df = pd.DataFrame(results['Data'])
                    return self._standardize_state_columns(df)
            
            return pd.DataFrame()
            
        except Exception as e:
            print(f"    ⚠️ Error processing state response: {e}")
            return pd.DataFrame()
    
    def process_io_response(self, response_data):
        """Process BEA Input-Output API response into DataFrame"""
        try:
            results = response_data.get('BEAAPI', {}).get('Results', {})

            if isinstance(results, list):
                results = results[0] if results else {}

            data = results.get('Data', [])
            df = pd.DataFrame(data)

            return self._standardize_io_columns(df)

        except Exception as e:
            print(f"    ⚠️ Error processing I-O response: {e}")
            return pd.DataFrame()
    
    def process_regional_response(self, response_data):
        """Process BEA Regional API response into DataFrame."""
        try:
            results = response_data.get('BEAAPI', {}).get('Results', {})

            if isinstance(results, list):
                results = results[0] if results else {}

            data = results.get('Data', [])
            df = pd.DataFrame(data)

            if df.empty:
                return df

            column_mapping = {
                'TimePeriod': 'year',
                'GeoFips': 'geo_fips',
                'GeoName': 'state_name',
                'DataValue': 'value',
                'Code': 'code',
                'CL_UNIT': 'unit',
                'UNIT_MULT': 'unit_mult'
            }
            df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

            if 'value' in df.columns:
                df['value'] = (
                    df['value']
                    .astype(str)
                    .str.replace(',', '', regex=False)
                    .pipe(pd.to_numeric, errors='coerce')
                )

            return df

        except Exception as e:
            print(f"    ⚠️ Error processing Regional response: {e}")
            return pd.DataFrame()

    def _standardize_trade_columns(self, df):
        """Standardize trade data column names and types"""
        if df.empty:
            return df
        
        # Common column mappings
        column_mapping = {
            'TimePeriod': 'year',
            'CtyCode': 'country_code', 
            'CtyName': 'country_name',
            'SERVCAT': 'service_category',
            'DataValue': 'value',
            'TradeDirection': 'trade_direction'
        }
        
        # Rename columns if they exist
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        
        # Convert numeric columns
        numeric_columns = ['value']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    
    def _standardize_state_columns(self, df):
        """Standardize state data column names and types"""
        if df.empty:
            return df
        
        column_mapping = {
            'TimePeriod': 'year',
            'StateCode': 'state_code',
            'StateName': 'state_name', 
            'DataValue': 'value',
            'NAICS': 'naics_code'
        }
        
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        
        numeric_columns = ['value']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    
    def _standardize_io_columns(self, df):
        """Standardize Input-Output data column names and types"""
        if df.empty:
            return df
        
        column_mapping = {
            'TimePeriod': 'year',
            'RowCode': 'row_code',
            'ColCode': 'col_code',
            'DataValue': 'value'
        }
        
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        
        numeric_columns = ['value']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    
    def get_api_usage_stats(self):
        """Get API usage statistics"""
        return {
            'api_calls_made': self.api_calls_made,
            'cache_dir': str(self.cache_dir),
            'cache_files': len(list(self.cache_dir.glob('*.json')))
        }
    
    def clear_cache(self, older_than_hours=None):
        """Clear API cache"""
        if older_than_hours is None:
            # Clear all cache
            for cache_file in self.cache_dir.glob('*.json'):
                cache_file.unlink()
            print("Cleared all BEA API cache")
        else:
            # Clear old cache files
            cutoff = datetime.now() - timedelta(hours=older_than_hours)
            cleared = 0
            for cache_file in self.cache_dir.glob('*.json'):
                if datetime.fromtimestamp(cache_file.stat().st_mtime) < cutoff:
                    cache_file.unlink()
                    cleared += 1
            print(f"Cleared {cleared} old BEA API cache files")
