#!/usr/bin/env python3
"""
Validates our own employment/energy/land/material/water import factors
(trade_factor.csv factor_id 906-910) against Cornerstone/USEEIO's own
pre-compiled, BLS/EIA/USDA/USGS-derived indicator data (JOBS/ENRG/LAND/MNRL/
WATR) — instead of only comparing our Exiobase-derived approximation against
itself. See bea/README.md's "Beyond GHGs" section for why 906-910 are a scope
match (not a value match) against Exiobase alone, and PLAN.md (in this repo's
profile/footprint/) for how this same pre-compiled data was located.

Source of the pre-compiled indicators: io/build/api/USEEIOv2.0.1-411/ (a local
vendored copy of ModelEarth/useeio-json's national model already used by
profile/footprint, io/charts/inflow-outflow and io/charts/bubble). No network
fetch needed — it's already a sibling directory in this checkout.

Mirrors the join/aggregation methodology of profile/footprint/index.html's
loadBeaFactorData() (the already-validated CO2/CH4/N2O comparison against
EPA's 2019 import factors file): industry1 (the exporting country's Exiobase
industry — what's actually being imported) joins via its Exiobase name to
every matching USEEIO_Detail_2012 BEA code (full fan-out, no fractional
split — 86 of 200 Exiobase sectors genuinely map to more than one BEA Detail
code, and there's no weight column to split by), and each BEA Detail's
"ours" rate is our own summed kg (or equivalent) divided by our own summed
USD imports for that code.

Usage:
    python3 bea/useeio_indicator_alignment.py [--year 2019]
"""

import argparse
import csv
import json
import sys
from pathlib import Path

WEBROOT = Path(__file__).resolve().parents[3]
CONCORDANCE_DIR = WEBROOT / 'trade-data' / 'concordance'
TRADE_YEAR_DIR = WEBROOT / 'trade-data' / 'year'
USEEIO_MODEL_DIR = WEBROOT / 'io' / 'build' / 'api' / 'USEEIOv2.0.1-411'

EUR_TO_USD_2019 = 1.1194  # ECB 2019 average reference rate — matches profile/footprint/index.html

# factor_id (ours, trade_factor.csv) -> (label, our unit, USEEIO indicator code,
# USEEIO's unit, conversion divisor to turn USEEIO's per-2012-USD rate into our unit)
FACTOR_MAP = {
    906: {
        'label': 'employment', 'our_unit': '1000 persons',
        'useeio_code': 'JOBS', 'useeio_unit': 'jobs',
        'divisor': 1_000,  # jobs -> 1000 persons
    },
    907: {
        'label': 'energy', 'our_unit': 'terajoules',
        'useeio_code': 'ENRG', 'useeio_unit': 'MJ',
        'divisor': 1_000_000,  # MJ -> TJ
    },
    908: {
        'label': 'land', 'our_unit': 'km2',
        'useeio_code': 'LAND', 'useeio_unit': 'm2*yr',
        'divisor': 1_000_000,  # m2 -> km2 (unit-*type* mismatch too: m2*yr flow vs our static km2 -- approximate)
    },
    909: {
        'label': 'material', 'our_unit': 'kilotonnes',
        'useeio_code': 'MNRL', 'useeio_unit': 'kg',
        'divisor': 1_000_000,  # kg -> kilotonnes
    },
    910: {
        'label': 'water', 'our_unit': 'Mm3',
        'useeio_code': 'WATR', 'useeio_unit': 'kg',
        # kg -> m3 (freshwater density ~1000 kg/m3) -> Mm3
        'divisor': 1000 * 1_000_000,
    },
}


def load_useeio_model():
    """Loads the local USEEIOv2.0.1-411 indicators.json/sectors.json/matrix/N.json
    (already vendored in the io submodule — see module docstring)."""
    if not USEEIO_MODEL_DIR.exists():
        sys.exit(f"Missing {USEEIO_MODEL_DIR} -- is the io submodule checked out?")

    with open(USEEIO_MODEL_DIR / 'indicators.json') as f:
        indicators = json.load(f)
    with open(USEEIO_MODEL_DIR / 'sectors.json') as f:
        sectors = json.load(f)
    with open(USEEIO_MODEL_DIR / 'matrix' / 'N.json') as f:
        n_matrix = json.load(f)  # [indicator_index][sector_index], per 2012 USD of output

    indicator_index = {row['code']: row['index'] for row in indicators}
    sector_index = {row['code']: row['index'] for row in sectors}
    return indicator_index, sector_index, n_matrix


def load_exio_name_to_bea_details():
    """Exiobase sector name -> list of USEEIO_Detail_2012 codes (full fan-out,
    duplicates removed but NOT fractionally weighted -- see module docstring)."""
    mapping = {}
    with open(CONCORDANCE_DIR / 'exio_to_useeio2_commodity_concordance.csv') as f:
        for row in csv.DictReader(f):
            name = row['Exiobase_Sector']
            detail = row['USEEIO_Detail_2012']
            if not name or not detail:
                continue
            details = mapping.setdefault(name, [])
            if detail not in details:
                details.append(detail)
    return mapping


def load_industry_id_to_name(year):
    industry_csv = TRADE_YEAR_DIR / str(year) / 'industry.csv'
    id_to_name = {}
    with open(industry_csv) as f:
        for row in csv.DictReader(f):
            id_to_name[row['industry_id']] = row['name']
    return id_to_name


def run(year):
    print(f"Loading USEEIO N matrix (pre-compiled BLS/EIA/USDA/USGS-derived indicators) from {USEEIO_MODEL_DIR.relative_to(WEBROOT)}")
    indicator_index, sector_index, n_matrix = load_useeio_model()
    for fid, meta in FACTOR_MAP.items():
        if meta['useeio_code'] not in indicator_index:
            sys.exit(f"USEEIO model is missing indicator {meta['useeio_code']} (factor_id {fid})")

    exio_name_to_details = load_exio_name_to_bea_details()
    id_to_name = load_industry_id_to_name(year)

    imports_dir = TRADE_YEAR_DIR / str(year) / 'US' / 'imports'
    trade_csv = imports_dir / 'trade.csv'
    factor_csv = imports_dir / 'trade_factor.csv'
    if not trade_csv.exists() or not factor_csv.exists():
        sys.exit(f"Missing {trade_csv} or {factor_csv} -- generate {year} US imports data first")

    # trade_id -> BEA Detail codes it counts toward; usd imports summed per BEA Detail
    trade_id_to_details = {}
    usd_by_detail = {}
    with open(trade_csv) as f:
        for row in csv.DictReader(f):
            name = id_to_name.get(row['industry1'])
            details = exio_name_to_details.get(name) if name else None
            if not details:
                continue
            trade_id_to_details[row['trade_id']] = details
            usd = float(row['amount']) * 1_000_000 * EUR_TO_USD_2019
            for detail in details:
                usd_by_detail[detail] = usd_by_detail.get(detail, 0.0) + usd

    # our own summed level by (BEA Detail, factor_id)
    ours_by_detail_factor = {}
    with open(factor_csv) as f:
        for row in csv.DictReader(f):
            fid = int(row['factor_id'])
            if fid not in FACTOR_MAP:
                continue
            details = trade_id_to_details.get(row['trade_id'])
            if not details:
                continue
            level = float(row['level'])
            for detail in details:
                key = (detail, fid)
                ours_by_detail_factor[key] = ours_by_detail_factor.get(key, 0.0) + level

    # Per-factor comparison stats
    rows = []
    for detail, usd in usd_by_detail.items():
        if usd <= 0:
            continue
        s_idx = sector_index.get(detail)
        if s_idx is None:
            continue  # BEA Detail code not in this USEEIO model's 411 sectors
        row = {'bea_detail': detail, 'usd_imports': usd}
        for fid, meta in FACTOR_MAP.items():
            ours_level = ours_by_detail_factor.get((detail, fid), 0.0)
            ours_rate = ours_level / usd
            epa_raw = n_matrix[indicator_index[meta['useeio_code']]][s_idx]
            epa_rate = epa_raw / meta['divisor']
            ratio = (ours_rate / epa_rate) if epa_rate else None
            row[f"{meta['label']}_ours"] = ours_rate
            row[f"{meta['label']}_epa"] = epa_rate
            row[f"{meta['label']}_ratio"] = ratio
        rows.append(row)

    rows.sort(key=lambda r: -r['usd_imports'])

    out_csv = Path(__file__).parent / f'useeio_indicator_alignment_{year}.csv'
    fieldnames = ['bea_detail', 'usd_imports'] + [
        f"{meta['label']}_{suffix}" for meta in FACTOR_MAP.values() for suffix in ('ours', 'epa', 'ratio')
    ]
    with open(out_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} BEA Detail rows to {out_csv.relative_to(WEBROOT)}")

    print(f"\n{'Extension':<12} {'unit (ours)':<14} {'matched':>8} {'median ratio':>13} {'% within 2x':>12}")
    for fid, meta in FACTOR_MAP.items():
        ratios = [r[f"{meta['label']}_ratio"] for r in rows if r[f"{meta['label']}_ratio"] not in (None, 0)]
        if not ratios:
            print(f"{meta['label']:<12} {meta['our_unit']:<14} {0:>8} {'n/a':>13} {'n/a':>12}  (ours is 0 for every row)")
            continue
        ratios.sort()
        median = ratios[len(ratios) // 2] if len(ratios) % 2 else (ratios[len(ratios) // 2 - 1] + ratios[len(ratios) // 2]) / 2
        within_2x = sum(1 for r in ratios if 0.5 <= r <= 2.0) / len(ratios) * 100
        print(f"{meta['label']:<12} {meta['our_unit']:<14} {len(ratios):>8} {median:>12.3f}x {within_2x:>11.1f}%")

    print(
        "\nCaveats: USEEIOv2.0.1-411's N matrix is fixed at 2012-USD-of-output basis; "
        f"our USD imports above are {year} trade converted at the {EUR_TO_USD_2019} "
        "EUR/USD rate with no inflation adjustment back to 2012 dollars -- ratios include "
        "that uncorrected ~15-20% CPI drift on top of any real methodology difference. "
        "'energy' (907) is expected to show 0 matched rows: Exiobase's own energy "
        "extension is entirely zero in the raw source data (see bea/README.md's "
        "'Beyond GHGs' section), so 'ours' is always 0 regardless of this comparison."
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=2019)
    args = parser.parse_args()
    run(args.year)
