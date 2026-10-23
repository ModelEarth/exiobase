#!/usr/bin/env python3
"""
Shared CENSUS_API_KEY lookup, used by bea/census_api_client.py. Census's
own API/Census_API.yml in USEPA/USEEIO says `api_key_required: False`, but that's out of date: as of 2026-09-24 the
Census international trade API redirects keyless requests to
https://api.census.gov/data/missing_key.html (confirmed by a real request,
not documentation) -- a key is required now. Register at
https://api.census.gov/data/key_signup.html. See env_key.py for where
the key is looked up.
"""

from env_key import find_env_key


def find_census_api_key(provided_key=None, start_dir=None):
    """CENSUS_API_KEY from env_key.find_env_key(), or None if not found anywhere."""
    return find_env_key('CENSUS_API_KEY', 'Census API key', provided_key, start_dir)
