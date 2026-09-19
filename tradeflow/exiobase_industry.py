"""
Exiobase sector -> BEA Sector (~21-category) industry aggregation, used to
produce the small, git-committable primary output files (trade.csv,
trade_factor.csv, interstate.csv, interstate_factor.csv, ...) alongside the
full-detail "-lg" files. See PLAN.md for the full design.

Chains three concordance files:
  Exiobase sector -> USEEIO Detail  (exio_to_useeio2_commodity_concordance.csv)
  USEEIO Detail   -> BEA Summary    (useeio_internal_concordance.csv)
  BEA Summary     -> BEA Sector     (bea_summary_to_sector_concordance.csv)

The first two are EPA-published files we already auto-fetch (see
bea/main.py's _ensure_concordance_file). The third is derived directly from
BEA's own government publication (not separately published anywhere we could
fetch as a plain file):
  https://apps.bea.gov/industry/release/zip/SUPPLY-USE.zip
  -> Use_SUT_Detail.xlsx, sheet "NAICS Codes"
confirmed as the authoritative source by reading useeior's own build scripts
(cornerstone-data/useeior, data-raw/MasterCrosswalk.R / BEAData.R), which
derive useeior's own Sector/Summary/Detail crosswalk from the same file.

Both concordance hops are many-to-many (a single Exiobase sector can chain to
more than one BEA Sector code). Checked empirically: 184/200 (92%) Exiobase
sectors chain to exactly one Sector; the other 16 are genuinely ambiguous
(e.g. "Natural gas..." splits across Mining/Utilities, "Other business
services" spans 7 Sectors) — a real many-to-many relationship, not resolved
here by picking one winner. trade.py/bea/main.py's Sector-level aggregation
instead splits each ambiguous industry's amount proportionally across all of
its candidate sectors, weighted by how many of that industry's Detail codes
land in each one (the same vote count previously used for a single
majority-vote pick). This mirrors EPA's own `generate_import_factors.py` in
spirit — `get_weighted_average()` there also splits proportionally across
multiple MRIO sectors folding into one BEA sector, though weighted by real
import/export quantity, which we don't have (see PLAN.md's open
weighting question); Detail-code-count is a documented approximation of
that, not a substitute for it.

For the database relationship (not just CSV aggregation), the same
many-to-many nature argues for a sector_industry join table rather than a
single industry.sector_id column — see PLAN.md.
"""

import csv
from pathlib import Path
from collections import Counter


def lg_path(path):
    """
    Given a primary output path (e.g. .../trade.csv), return its full-detail
    "-lg" sibling path (.../trade-lg.csv). Distinct from the pre-existing
    "_lg" convention (trade_factor_lg.csv/interstate_factor_lg.csv, meaning
    "all 721 raw unaggregated factors") — this "-lg" means "full Exiobase
    industry detail, not aggregated to BEA Sector level." See
    PLAN.md.
    """
    p = Path(path)
    return p.with_name(f"{p.stem}-lg{p.suffix}")

CONCORDANCE_DIR = Path(__file__).parent.parent.parent / 'trade-data' / 'concordance'

BEA_SECTOR_NAMES = {
    '11': 'Agriculture, forestry, fishing, and hunting',
    '21': 'Mining',
    '22': 'Utilities',
    '23': 'Construction',
    '31ND': 'Nondurable goods manufacturing',
    '33DG': 'Durable goods manufacturing',
    '42': 'Wholesale trade',
    '44RT': 'Retail trade',
    '48TW': 'Transportation and warehousing',
    '51': 'Information',
    '52': 'Finance and insurance',
    '53': 'Real estate and rental and leasing',
    '54': 'Professional and technical services',
    '55': 'Management of companies and enterprises',
    '56': 'Administrative and waste services',
    '61': 'Educational services',
    '62': 'Health care and social assistance',
    '71': 'Arts, entertainment, and recreation',
    '72': 'Accommodation and food services',
    '81': 'Other services, except government',
    'G': 'Government',
    'Used': 'Scrap, used and secondhand goods',
    'Other': 'Noncomparable imports and rest-of-the-world adjustment',
}


def load_exiobase_to_sector_weights():
    """
    Returns dict: Exiobase sector name -> list of (BEA Sector code, fraction)
    pairs, fractions summing to 1.0, chaining the three concordance files
    described in the module docstring. A sector with exactly one candidate
    gets a single (code, 1.0) pair; an ambiguous one gets multiple pairs
    proportional to how many of its Detail codes land in each candidate
    Sector. Raises FileNotFoundError if any concordance file is missing
    locally — callers should route through bea/main.py's
    _ensure_concordance_file first for the two EPA-published files;
    bea_summary_to_sector_concordance.csv has no auto-fetch source yet (see
    PLAN.md) and must exist locally.
    """
    exio_to_detail = {}
    with open(CONCORDANCE_DIR / 'exio_to_useeio2_commodity_concordance.csv') as f:
        for r in csv.DictReader(f):
            exio_to_detail.setdefault(r['Exiobase_Sector'], []).append(r['USEEIO_Detail_2017'])

    detail_to_summary = {}
    with open(CONCORDANCE_DIR / 'useeio_internal_concordance.csv') as f:
        for r in csv.DictReader(f):
            detail_to_summary[r['USEEIO_Detail_2017']] = r['BEA_Summary']

    summary_to_sector = {}
    with open(CONCORDANCE_DIR / 'bea_summary_to_sector_concordance.csv') as f:
        for r in csv.DictReader(f):
            summary_to_sector[r['BEA_Summary']] = r['BEA_Sector']

    mapping = {}
    for exio_sector, detail_codes in exio_to_detail.items():
        sector_votes = Counter()
        for detail in detail_codes:
            summary = detail_to_summary.get(detail)
            sector = summary_to_sector.get(summary) if summary else None
            if sector:
                sector_votes[sector] += 1
        total = sum(sector_votes.values())
        if total:
            mapping[exio_sector] = [(sector, count / total) for sector, count in sector_votes.items()]
    return mapping


def industry_id_to_sector_weights(industry_csv_path):
    """
    Returns dict: our 5-character industry_id -> list of (BEA Sector code,
    fraction) pairs (see load_exiobase_to_sector_weights), by joining
    industry.csv's industry_id<->name mapping with the Exiobase-name-keyed
    mapping above.
    """
    exio_to_sector = load_exiobase_to_sector_weights()
    result = {}
    with open(industry_csv_path) as f:
        for r in csv.DictReader(f):
            weights = exio_to_sector.get(r['name'])
            if weights:
                result[r['industry_id']] = weights
    return result
