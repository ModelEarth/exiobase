#!/usr/bin/env python3
"""
Push the curated default/all pipeline's already-written local CSVs straight
to Azure, via team's /api/db/insert-trade-data endpoint with
source: "local" -- team reads them directly off this machine's disk
(../trade-data/year/... relative to team's own working directory, a sibling
repo under the same webroot checkout) instead of fetching from GitHub, so
there's no need to commit/push trade-data first. This is the curated-
pipeline equivalent of comprehensive mode's direct industrydb.py push;
unlike that path, the actual insert logic (country block_index/trade_id
offsets, so multiple countries can share one year_db without trade_id
collisions) still runs in team's Rust process, reused unchanged -- this
script only supplies the CSVs from local disk instead of GitHub.

IMPORTANT: only use this against a year whose database has never been
pushed via comprehensive mode. industrydb_{year} databases built by
trade_comprehensive.py (see PLAN-comprehensive.md) use a different,
incompatible trade_id scheme (a single global counter across all 49
regions, no per-country block_index) -- pushing through this script against
one of those (e.g. industrydb_2018) would assign new countries a
block_index that collides with or duplicates already-comprehensive-pushed
trade_id ranges. Safe targets are a year that has only ever gone through
the curated default/all pipeline (e.g. industrydb_2019/2021/2023, or a new
industrydb_2024).

Run standalone, after main.py has produced this year's local CSVs
(YEAR=2024 COUNTRY_LIST=default python main.py --interstate US):

    YEAR=2024 python3 push_default.py

Accepts the same YEAR/DB_TARGET short aliases as main.py's comprehensive
mode (DB_TARGET=industrydb pushes into the shared multi-year database
instead of a dedicated industrydb_{year}). Country list defaults to
config.yaml's COUNTRY.list (or COUNTRY_LIST/EXIOBASE_COUNTRY_LIST) the same
way main.py resolves it -- "default" (14 countries), "all", or an explicit
comma-separated list.
"""

import os
import sys

import requests

from config_loader import load_config, get_comprehensive_target
from main import get_default_countries, get_existing_countries, get_country_list_value

TEAM_API_BASE = os.environ.get('TEAM_API_BASE', 'http://localhost:8081')


def resolve_push_country_list(config):
    """Same resolution as main.py's resolve_country_list, without that
    function's progress printing -- "all" falls back to whichever country
    folders already exist locally for this year, "default" is the fixed
    14-country list, anything else is parsed as an explicit comma-separated
    list."""
    country_list = get_country_list_value(config)
    year = config['YEAR']

    if country_list.lower() == 'all':
        existing = get_existing_countries(year)
        return existing if existing else get_default_countries()
    elif country_list.lower() == 'default':
        return get_default_countries()
    else:
        return [c.strip() for c in country_list.split(',') if c.strip()]


def push_country(year, country, target):
    payload = {'year': str(year), 'country': country, 'source': 'local'}
    if target == 'industrydb':
        payload['target'] = 'industrydb'

    resp = requests.post(f'{TEAM_API_BASE}/api/db/insert-trade-data', json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json()


def push_default(year, countries=None, target=None):
    config = load_config()
    if target is None:
        target = get_comprehensive_target(config)
    if countries is None:
        countries = resolve_push_country_list(config)

    target_name = 'industrydb (shared)' if target == 'industrydb' else f'industrydb_{year}'
    print(f"[PUSH-DEFAULT] {year}: pushing {len(countries)} countries to {target_name} from local disk -- {', '.join(countries)}")

    results = {}
    for country in countries:
        print(f"\n[PUSH-DEFAULT] {country}...")
        try:
            result = push_country(year, country, target)
        except requests.RequestException as e:
            print(f"  [ERROR] {country}: {e}")
            results[country] = {'success': False, 'error': str(e)}
            continue

        results[country] = result
        if result.get('success'):
            for entry in result.get('inserted', []):
                print(f"  {entry['file']}: {entry['rows']} rows")
        else:
            print(f"  [ERROR] {result.get('errors')}")

    failed = [c for c, r in results.items() if not r.get('success')]
    print(f"\n[PUSH-DEFAULT] Done. {len(countries) - len(failed)}/{len(countries)} succeeded.")
    if failed:
        print(f"[PUSH-DEFAULT] Failed: {', '.join(failed)}")
        sys.exit(1)

    return results


if __name__ == '__main__':
    config = load_config()
    year = int(os.environ.get('EXIOBASE_YEAR') or os.environ.get('YEAR') or config['YEAR'])
    push_default(year)
