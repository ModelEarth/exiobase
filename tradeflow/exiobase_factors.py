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

TODO: EPA's own published import-factor product only covers these GHGs —
it doesn't include employment, energy, land, material, or water at all, so
there's no equivalent curated list to copy for those five extensions. Until
an external source (EPA, USEEIO, or otherwise) defines one, each of those
extensions is aggregated into a single placeholder flow (every raw stressor
in the extension, summed) rather than a real substance-specific breakdown —
dimensionally consistent (each extension uses one unit, per
bea/README.md's Units table) but not a considered selection like the GHGs
are. Replace EXTENSION_PLACEHOLDER_* once a real source is found.
"""

EPA_GHG_FLOWS = {
    'CO2': 'Carbon dioxide',
    'CH4': 'Methane',
    'HFC': 'HFCs and PFCs, unspecified',
    'N2O': 'Nitrous oxide',
    'PFC': 'HFCs and PFCs, unspecified',
    'SF6': 'Sulfur hexafluoride',
}

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

EXTENSION_PLACEHOLDER_FACTOR_IDS = {
    'employment': 906,
    'energy': 907,
    'land': 908,
    'material': 909,
    'water': 910,
}

EXTENSION_PLACEHOLDER_NAMES = {
    'employment': 'Employment (aggregate placeholder — see exiobase_factors.py TODO)',
    'energy': 'Energy (aggregate placeholder — see exiobase_factors.py TODO)',
    'land': 'Land (aggregate placeholder — see exiobase_factors.py TODO)',
    'material': 'Material (aggregate placeholder — see exiobase_factors.py TODO)',
    'water': 'Water (aggregate placeholder — see exiobase_factors.py TODO)',
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
    for ext_name, factor_id in EXTENSION_PLACEHOLDER_FACTOR_IDS.items():
        rows.append((factor_id, EXTENSION_UNITS[ext_name], EXTENSION_PLACEHOLDER_NAMES[ext_name], ext_name))
    return rows


def aggregate_coefficients(stressor_coefficient_pairs, ext_name):
    """
    Collapse (stressor_name, coefficient) pairs for one Exiobase extension
    into aggregate (factor_id, coefficient) pairs, summing coefficients that
    map to the same flow.

    air_emissions: keeps only the 6 EPA GHG-mapped prefixes, summed into up
    to 5 flows (rows with no matching prefix are dropped, same as EPA's own
    filter). All other extensions: every stressor summed into that
    extension's single placeholder flow (see module docstring TODO).
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

    if ext_name not in EXTENSION_PLACEHOLDER_FACTOR_IDS:
        return []
    if not stressor_coefficient_pairs:
        return []
    total = sum(coefficient for _, coefficient in stressor_coefficient_pairs)
    return [(EXTENSION_PLACEHOLDER_FACTOR_IDS[ext_name], total)]
