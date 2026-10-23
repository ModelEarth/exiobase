#!/usr/bin/env python3
"""
Shared BEA_API_KEY lookup, used by bea/main.py and bea/category_state.py (to
call the BEA API) and main.py (to fail fast, before a long trade-data run,
when --interstate is requested even though main.py itself never uses the
key). See env_key.py for where the key is looked up.
"""

from env_key import find_env_key


def find_bea_api_key(provided_key=None, start_dir=None):
    """BEA_API_KEY from env_key.find_env_key(), or None if not found anywhere."""
    return find_env_key('BEA_API_KEY', 'BEA API key', provided_key, start_dir)
