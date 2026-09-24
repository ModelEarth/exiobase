"""
Census International Trade API Client

Fetches US goods-import values by NAICS commodity from the Census Bureau's
international trade API, mirroring the BEA API client's caching pattern
(see main_api_client.py) so both sit side by side the same way EPA's own
import_emission_factors pipeline combines the two sources.

USEPA/USEEIO's own API/Census_API.yml says `api_key_required: False`, but
that's out of date -- a real request against this endpoint with no key
redirects (302) to https://api.census.gov/data/missing_key.html with header
`X-DataWebAPI-KeyError: 1` (confirmed 2026-09-24, not from documentation).
A free key is required now: register at
https://api.census.gov/data/key_signup.html and add CENSUS_API_KEY to your
.env file (see census_key.py for where that's looked up from).

Endpoint/params otherwise match USEPA/USEEIO's
import_emission_factors/API/Census_API.yml exactly (confirmed by reading
that file in a local clone of USEPA/USEEIO) -- this is the same request
EPA's own generate_import_shares.py makes, just with a key appended.
"""

import sys
import pandas as pd
import requests
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
import hashlib

sys.path.insert(0, str(Path(__file__).parent.parent))
from census_key import find_census_api_key

CENSUS_API_KEY_MISSING_NOTICE = (
    "\n" + "!" * 60 +
    "\nNo CENSUS_API_KEY found.\n"
    "Register (free, instant) at https://api.census.gov/data/key_signup.html\n"
    "then add CENSUS_API_KEY=your_key to your .env file (see\n"
    "webroot/automation/paths.yaml for its location, or webroot/docker/.env\n"
    "/ webroot/.env as a fallback).\n"
    "Unlike a missing BEA_API_KEY, nothing degrades gracefully here -- every\n"
    "request returns 0 rows without a key, so census_imports.py has nothing\n"
    "to compute import shares from.\n" +
    "!" * 60
)


class CensusAPIClient:
    def __init__(self, api_key=None, base_url="https://api.census.gov/data/timeseries/intltrade/imports/naics"):
        self.base_url = base_url
        self.call_delay = 0.3  # polite spacing; no published rate limit
        self.cache_dir = Path(__file__).parent / 'census_cache'
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_duration_hours = 24

        self.api_calls_made = 0
        self.session = requests.Session()

        self.api_key = find_census_api_key(api_key, start_dir=Path(__file__).parent.parent)
        if not self.api_key:
            print(CENSUS_API_KEY_MISSING_NOTICE)
            if sys.stdin.isatty():
                typed = input("Paste a CENSUS_API_KEY to use for this run (or press Enter to continue without one): ").strip()
                if typed:
                    self.api_key = typed
                    print("Using the key you entered for this run only -- add it to your .env file "
                          "to skip this prompt next time.")

    def get_imports_by_country(self, year, census_code):
        """
        Fetches one exporting country's US goods imports by NAICS-6 commodity
        for `year` (MONTH=12 -- EPA's own YAML uses this too, giving the
        cumulative year-to-date total through December).

        Returns a DataFrame with columns: naics, import_value_usd (from
        GEN_CIF_YR -- General Imports, CIF value, year-to-date).
        """
        if not self.api_key:
            print("    ⛔ No CENSUS_API_KEY -- skipping (see notice printed at startup)")
            return pd.DataFrame(columns=['naics', 'import_value_usd'])

        params = {
            'get': 'NAICS,GEN_CIF_YR,CTY_CODE',
            'COMM_LVL': 'NA6',
            'CTY_CODE': str(census_code),
            'YEAR': str(year),
            'MONTH': '12',
            'key': self.api_key,
        }
        data = self._make_cached_request(f'imports_{year}_{census_code}', params)
        if not data or len(data) < 2:
            return pd.DataFrame(columns=['naics', 'import_value_usd'])

        header, rows = data[0], data[1:]
        df = pd.DataFrame(rows, columns=header)
        df = df[['NAICS', 'GEN_CIF_YR']].rename(
            columns={'NAICS': 'naics', 'GEN_CIF_YR': 'import_value_usd'}
        )
        df['import_value_usd'] = pd.to_numeric(df['import_value_usd'], errors='coerce').fillna(0.0)
        return df

    def _make_cached_request(self, cache_key_label, params):
        cache_key = self._generate_cache_key(cache_key_label, params)
        cache_file = self.cache_dir / f"{cache_key}.json"

        if self._is_cache_valid(cache_file):
            with open(cache_file, 'r') as f:
                return json.load(f)

        try:
            time.sleep(self.call_delay)
            response = self.session.get(self.base_url, params=params)
            response.raise_for_status()

            # A country/year with literally no import rows returns a 204 (no
            # content), not an empty JSON body -- treat that as "no data",
            # same as EPA's own make_reqs() does.
            if response.status_code == 204 or not response.text.strip():
                data = []
            else:
                data = response.json()

            self.api_calls_made += 1

            with open(cache_file, 'w') as f:
                json.dump(data, f)

            return data

        except requests.RequestException as e:
            print(f"    ❌ Census API request failed for {cache_key_label}: {e}")
            raise
        except ValueError as e:
            print(f"    ❌ Invalid Census API response for {cache_key_label}: {e}")
            raise

    def _generate_cache_key(self, label, params):
        # Exclude the key itself, same as main_api_client.py excludes
        # UserID -- a rotated key shouldn't invalidate an otherwise-identical
        # cached response.
        param_str = json.dumps({k: v for k, v in sorted(params.items()) if k != 'key'}, sort_keys=True)
        return hashlib.md5(f"{label}_{param_str}".encode()).hexdigest()

    def _is_cache_valid(self, cache_file):
        if not cache_file.exists():
            return False
        file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        return file_age < timedelta(hours=self.cache_duration_hours)
