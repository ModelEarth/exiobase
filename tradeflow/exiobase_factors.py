"""
Shared environmental-factor aggregation used by both the international
(trade.py) and US state-level (bea/main_trade_analyzer.py) pipelines for
the default (non "_lg") trade_factor.csv / interstate_factor.csv files.

Replaces the earlier "top N raw stressors ranked by |M-matrix coefficient|
magnitude" selection with EPA USEEIO's own approach, for the one extension
where EPA publishes a directly comparable product (air_emissions/GHGs): map
a small, curated set of raw Exiobase stressor prefixes onto named flows and
SUM every raw stressor that maps to each one, rather than picking the
largest raw values. The mapping below is copied verbatim from EPA's own
config for the Exiobase model:
https://github.com/USEPA/USEEIO/blob/master/import_emission_factors/data/mrio_config.yml
(the `exiobase: flows:` block), and the aggregation itself mirrors
`clean_exiobase_M_matrix()` in that repo's `exiobase_helpers.py` (split each
stressor name on its first " - ", map the prefix, drop anything that
doesn't map, then group by flow and sum).

EPA's own published import-factor product only covers these GHGs — it
doesn't include employment, energy, land, material, or water at all, so
there's no equivalent curated stressor-to-flow mapping to copy for those
five extensions (see bea/README.md's "Beyond GHGs" section). USEPA's USEEIO
work now continues at https://github.com/cornerstone-data (its `useeior`
package, successor to https://github.com/USEPA/useeior); its indicator list
(inst/extdata/USEEIO_LCIA_Indicators.csv) does define matching target
categories — Jobs Supported (JOBS), Energy Use (ENRG), Land Use (LAND),
Water Use (WATR), Minerals and Metals Use (MNRL) — but computes them from
separate US-specific government inventories (BLS, EIA, USDA, USGS) joined
to BEA/NAICS sectors, not by characterizing MRIO stressor flows. There's no
external source to copy a stressor mapping from, so EXTENSION_STRESSOR_SELECTION
below is our own selection of which raw Exiobase stressors fall within each
indicator's scope — chosen to avoid two failure modes visible in Exiobase's
own stressor list once you look at it (see bea/README.md): mixing
incompatible units in one sum (employment: "people" in 1000 persons vs
"hours" in M.hr), and double/triple-counting different measurement bases of
the same underlying quantity (energy: Gross/Net/Final/Emission-relevant are
4 definitions of one thing, not 4 additive components; water: Withdrawal
and Consumption are different measures of the same water use). This keeps
our own extension names (employment/energy/land/material/water — not
renamed to USEEIO's indicator names, since the computation still isn't
USEEIO's) while matching USEEIO's indicator *scope* as closely as
Exiobase's own categories allow. It will not reproduce USEEIO's published
*values* for these five — different source data, not just a different
selection — only closer conceptual alignment.
"""

EPA_GHG_FLOWS = {
    'CO2': 'Carbon dioxide',
    'CH4': 'Methane',
    'HFC': 'HFCs and PFCs, unspecified',
    'N2O': 'Nitrous oxide',
    'PFC': 'HFCs and PFCs, unspecified',
    'SF6': 'Sulfur hexafluoride',
}

# NOTE: as of Exiobase v3.8.2 (confirmed 2019 and 2021 pxp downloads), the
# SF6/HFC/PFC raw stressor rows each have substantial real nonzero data in
# ext.air_emissions.F, but ext.air_emissions.M (the Leontief-inverse total
# requirement) is 100% NaN for all three, across every region — a single
# poisoned cell somewhere in the global S matrix corrupts each row's entire
# M output (see trade.py's/main_trade_analyzer.py's fillna(0) comments).
# fillna(0) turns that into a real 0 here, silently discarding real
# emissions data rather than confirming a genuine absence like 'energy'
# below. Not fixed here — would need finding/correcting the poisoned cell.

# Fixed factor_id block for every aggregated flow this module produces,
# separate from the 1-721 raw per-stressor IDs in factor.csv (still used by
# trade_factor_lg.csv/interstate_factor_lg.csv) so both can coexist in the
# same factor.csv without collision, regardless of a given year's exact
# Exiobase stressor count.
AGGREGATE_FACTOR_IDS = {
    'Carbon dioxide': 901,
    'Methane': 902,
    'Nitrous oxide': 903,
    'Sulfur hexafluoride': 904,
    'HFCs and PFCs, unspecified': 905,
}

EXTENSION_AGGREGATE_FACTOR_IDS = {
    'employment': 906,
    'energy': 907,
    'land': 908,
    'material': 909,
    'water': 910,
}

EXTENSION_AGGREGATE_NAMES = {
    'employment': 'Employment (people, jobs-scope — see exiobase_factors.py)',
    'energy': 'Energy (gross use, ENRG-scope — see exiobase_factors.py)',
    'land': 'Land (total, LAND-scope — see exiobase_factors.py)',
    'material': 'Material (metals and minerals, MNRL-scope — see exiobase_factors.py)',
    'water': 'Water (blue withdrawal, WATR-scope — see exiobase_factors.py)',
}

# Which raw stressors count toward each extension's aggregate, chosen to
# match the scope of the corresponding USEEIO indicator (see module
# docstring) and avoid summing incompatible units or double-counting
# different measures of the same quantity. A stressor counts if its name
# starts with any of these prefixes; 'land' has no entry, meaning every
# stressor in that extension counts (they're genuinely additive distinct
# land-use categories — Exiobase has no overlapping "total" row to avoid
# double-counting against, unlike energy/water).
EXTENSION_STRESSOR_PREFIXES = {
    # USEEIO's Jobs Supported (JOBS) is a headcount; Exiobase's "Employment
    # hours" (a different unit, M.hr) isn't part of that scope.
    'employment': ['Employment people'],
    # Gross/Net/Final/Emission-relevant are 4 different definitions of one
    # quantity, not 4 additive components — Gross is the closest to USEEIO's
    # Energy Use (ENRG), which is a total primary-energy-basis measure.
    # NOTE: as of Exiobase v3.8.2, all four of these are 0 for every
    # region/sector/year (confirmed in both the 2019 and 2021 pxp
    # downloads: ext.energy.F is entirely zero, not NaN) — this extension's
    # source data is simply empty in this Exiobase release, not something
    # our selection logic can work around. Factor 907 will read 0 for every
    # row until Exiobase publishes real energy data or we source it
    # elsewhere (see bea/README.md's "Beyond GHGs" section).
    'energy': ['Energy use - Gross'],
    # USEEIO's Minerals and Metals Use (MNRL) excludes crops, forestry,
    # fishery, and fossil fuels — those aren't minerals or metals, even
    # though Exiobase's "material" extension lumps all of it together as
    # "Domestic Extraction Used".
    'material': [
        'Domestic Extraction Used - Metal Ores',
        'Domestic Extraction Used - Non-Metallic Minerals',
    ],
    # Water Withdrawal and Water Consumption are different measures of the
    # same underlying water use (withdrawal is the larger, more commonly
    # reported figure); Water Consumption Green is a different resource
    # entirely (soil moisture, never withdrawn from a blue-water source).
    'water': ['Water Withdrawal Blue'],
}

# extension -> unit, matching bea/README.md's Units table (one unit per
# extension, applied uniformly to every stressor/flow within it).
EXTENSION_UNITS = {
    'air_emissions': 'kg',
    'employment': '1000 persons',
    'energy': 'terajoules',
    'land': 'km2',
    'material': 'kilotonnes',
    'water': 'Mm3',
}


def aggregate_definitions():
    """
    The fixed set of aggregate factor.csv rows this module produces:
    (factor_id, unit, stressor, extension) tuples, in the same shape as
    factors.py's raw per-stressor rows.
    """
    rows = []
    for flow, factor_id in AGGREGATE_FACTOR_IDS.items():
        rows.append((factor_id, EXTENSION_UNITS['air_emissions'], flow, 'air_emissions'))
    for ext_name, factor_id in EXTENSION_AGGREGATE_FACTOR_IDS.items():
        rows.append((factor_id, EXTENSION_UNITS[ext_name], EXTENSION_AGGREGATE_NAMES[ext_name], ext_name))
    return rows


def _matches_prefix(stressor, prefixes):
    return any(str(stressor).startswith(p) for p in prefixes)


def aggregate_coefficients(stressor_coefficient_pairs, ext_name):
    """
    Collapse (stressor_name, coefficient) pairs for one Exiobase extension
    into aggregate (factor_id, coefficient) pairs, summing coefficients that
    map to the same flow.

    air_emissions: keeps only the 6 EPA GHG-mapped prefixes, summed into up
    to 5 flows (rows with no matching prefix are dropped, same as EPA's own
    filter). All other extensions: stressors matching that extension's
    EXTENSION_STRESSOR_PREFIXES scope (or every stressor, for 'land', which
    has no entry) summed into that extension's single aggregate flow.
    """
    if ext_name == 'air_emissions':
        totals = {}
        for stressor, coefficient in stressor_coefficient_pairs:
            prefix = str(stressor).split(' - ', 1)[0]
            flow = EPA_GHG_FLOWS.get(prefix)
            if flow is None:
                continue
            totals[flow] = totals.get(flow, 0.0) + coefficient
        return [(AGGREGATE_FACTOR_IDS[flow], total) for flow, total in totals.items()]

    if ext_name not in EXTENSION_AGGREGATE_FACTOR_IDS:
        return []
    if not stressor_coefficient_pairs:
        return []
    prefixes = EXTENSION_STRESSOR_PREFIXES.get(ext_name)
    if prefixes:
        pairs = [(s, c) for s, c in stressor_coefficient_pairs if _matches_prefix(s, prefixes)]
    else:
        pairs = stressor_coefficient_pairs
    if not pairs:
        return []
    total = sum(coefficient for _, coefficient in pairs)
    return [(EXTENSION_AGGREGATE_FACTOR_IDS[ext_name], total)]
