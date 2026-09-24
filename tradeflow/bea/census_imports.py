#!/usr/bin/env python3
"""
US goods-import shares from the Census Bureau, by BEA Detail sector and
country -- the "independent of the MRIO" weighting EPA's own
generate_import_shares.py computes from Census (goods) + BEA (services) +
EIA (electricity) combined. This script covers the Census/goods half only
(see bea/README.md's "Import shares" section for the rest of that picture
and why goods -- not services -- is the half that matters for MRIO-based
emission factors).

Mirrors USEPA/USEEIO's import_emission_factors/generate_import_shares.py
methodology (confirmed by reading that repo directly, not from memory):
fetch each exporting country's Census imports by NAICS-6, map to BEA Detail
via Census_to_useeio2_sector_concordance.csv, then compute each country's
fractional contribution to a given BEA Detail sector's total imports --
both nationally and within its 7-region bucket (APAC/EU/ROW/etc., or a
single-country "region" for CA/MX/JP/CN, matching EPA's own
single_country_regions special-case).

Usage:
    python3 bea/census_imports.py --year 2019
    python3 bea/census_imports.py --year 2019 --countries AU,DE,JP
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from census_api_client import CensusAPIClient

CONCORDANCE_DIR = Path(__file__).parents[3] / 'trade-data' / 'concordance'

# Matches config.yaml's COUNTRY.list "default" set, minus US (the importer,
# not an exporter in this dataset) and WM (an Exiobase Rest-of-World
# aggregate, not a real country Census tracks on its own).
DEFAULT_COUNTRIES = ['AU', 'BR', 'CA', 'CN', 'DE', 'FR', 'GB', 'IN', 'IT', 'JP', 'KR', 'RU']

# Countries Census/EPA treat as their own single-country "region" rather than
# folding into a broader bucket -- see EPA's single_country_regions.
SINGLE_COUNTRY_REGIONS = {'CA', 'MX', 'JP', 'CN'}


def load_census_country_codes():
    """iso_code -> census_code, from trade-data/concordance/census_country_codes.csv
    (parsed from USEPA/USEEIO's own Census_country_codes.txt -- see that
    file's header comment for provenance)."""
    path = CONCORDANCE_DIR / 'census_country_codes.csv'
    mapping = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            iso = row['iso_code'].strip()
            if iso and iso not in mapping:  # first match wins (a few names repeat, e.g. two Germany rows)
                mapping[iso] = row['census_code'].strip()
    return mapping


def load_naics_to_bea_detail(schema=2017):
    """naics -> BEA Detail code, from Census_to_useeio2_sector_concordance.csv.
    schema=2017 matches EPA's own published 2019 reference file
    (US_detail_import_factors_exiobase_2019_17sch.csv -- the "17sch" in that
    filename), which this data is meant to eventually help us get closer to."""
    path = CONCORDANCE_DIR / 'Census_to_useeio2_sector_concordance.csv'
    mapping = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            mapping[row['NAICS']] = row[f'BEA_Detail_{schema}']
    return mapping


def load_country_regions():
    """iso_code -> region (APAC/EU/ROW/US/or a single-country code like
    CA/MX/JP/CN), from country_to_region_concordance.csv."""
    path = CONCORDANCE_DIR / 'country_to_region_concordance.csv'
    mapping = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            iso = row['ISO Code'].strip()
            region = row['Region'].strip()
            if iso and region:
                mapping.setdefault(iso, region)  # first match wins, same reasoning as above
    return mapping


def fetch_imports_by_detail(year, countries, schema=2017):
    """
    Returns a list of dicts: {bea_detail, country, import_value_usd} --
    one row per (country, BEA Detail) with that country's NAICS-level Census
    imports summed up to BEA Detail.
    """
    client = CensusAPIClient()
    country_codes = load_census_country_codes()
    naics_to_detail = load_naics_to_bea_detail(schema=schema)

    rows_by_detail_country = {}
    for country in countries:
        census_code = country_codes.get(country)
        if not census_code:
            print(f"  ⚠️ No Census country code found for {country}, skipping")
            continue

        print(f"  🌐 Fetching Census imports for {country} ({year})...")
        df = client.get_imports_by_country(year, census_code)
        if df.empty:
            print(f"    No Census data returned for {country}")
            continue

        for _, r in df.iterrows():
            detail = naics_to_detail.get(r['naics'])
            # '#N/A' is a literal string in the concordance CSV itself (NAICS
            # 980000 -- Census's catch-all "not elsewhere classified" code
            # has no BEA Detail equivalent). pandas.read_csv would treat it
            # as a null and drop it from any groupby automatically; csv.
            # DictReader doesn't, so it's filtered explicitly here.
            if not detail or detail == '#N/A':
                continue
            key = (detail, country)
            rows_by_detail_country[key] = rows_by_detail_country.get(key, 0.0) + r['import_value_usd']

    print(f"  ✅ Census API calls made: {client.api_calls_made} (rest served from cache)")
    return [
        {'bea_detail': detail, 'country': country, 'import_value_usd': value}
        for (detail, country), value in rows_by_detail_country.items()
    ]


def add_contribution_coefficients(rows):
    """
    Appends cntry_cntrb_to_national_detail and cntry_cntrb_to_region_detail
    to each row -- each country's fraction of total imports for that BEA
    Detail sector, nationally and within its region. Mirrors EPA's
    calc_coefficients_bea_detail(); Summary-level rollup isn't added here
    (see bea/README.md for why Detail is enough for the current use case).
    """
    regions = load_country_regions()
    for row in rows:
        row['region'] = regions.get(row['country'], 'ROW')

    national_totals = {}
    region_totals = {}
    for row in rows:
        national_totals[row['bea_detail']] = national_totals.get(row['bea_detail'], 0.0) + row['import_value_usd']
        key = (row['region'], row['bea_detail'])
        region_totals[key] = region_totals.get(key, 0.0) + row['import_value_usd']

    for row in rows:
        national_total = national_totals.get(row['bea_detail'], 0.0)
        region_total = region_totals.get((row['region'], row['bea_detail']), 0.0)
        row['cntry_cntrb_to_national_detail'] = (row['import_value_usd'] / national_total) if national_total else 0.0
        row['cntry_cntrb_to_region_detail'] = (row['import_value_usd'] / region_total) if region_total else 0.0

    return rows


def run(year, countries, schema=2017):
    print(f"Fetching Census import data for {len(countries)} countries, {year}...")
    rows = fetch_imports_by_detail(year, countries, schema=schema)
    rows = add_contribution_coefficients(rows)
    rows.sort(key=lambda r: (r['bea_detail'], -r['import_value_usd']))

    out_path = Path(__file__).parents[3] / 'trade-data' / 'year' / str(year) / 'import_shares_census.csv'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['bea_detail', 'country', 'region', 'import_value_usd',
                  'cntry_cntrb_to_national_detail', 'cntry_cntrb_to_region_detail']
    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} (BEA Detail, country) rows to {out_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=2019)
    parser.add_argument('--countries', default=','.join(DEFAULT_COUNTRIES),
                         help='Comma-separated Exiobase ISO country codes (exporters)')
    parser.add_argument('--schema', type=int, default=2017, choices=[2012, 2017])
    args = parser.parse_args()

    countries = [c.strip().upper() for c in args.countries.split(',') if c.strip()]
    run(args.year, countries, schema=args.schema)
