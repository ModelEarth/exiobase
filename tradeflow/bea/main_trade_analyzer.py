"""
State Trade Analyzer for US Trade Flow Disaggregation

Splits national US-to-US trade flows among state pairs with BEA GDP-by-state
weights, and derives state export and import shares.
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
import json
import re

# Allow imports from parent tradeflow directory (exiobase_factors, etc.)
sys.path.insert(0, str(Path(__file__).parent.parent))
from exiobase_factors import aggregate_coefficients

# BEA Sector (sector.csv) to the broad category whose GDP by state allocates a flow.
# Sectors not listed (trade, information, finance and other services) are services.
SECTOR_ALLOCATION_CATEGORY = {
    '11': 'agriculture',
    '21': 'mining',
    '22': 'utilities',
    '23': 'construction',
    '31ND': 'manufacturing',
    '33DG': 'manufacturing',
    '48TW': 'transportation',
}

class StateTradeAnalyzer:
    def __init__(self, config):
        self.config = config
        self.year = config['YEAR']
        
        # Load state reference data
        self.state_codes = self._load_state_codes()
        self.industry_category_by_id = self._load_industry_categories()
        self._bea_allocation_source_id = None
        self._bea_allocation_weight_lookup = {}
        self._bea_allocation_ranked_states = {}
        

    def _load_state_codes(self):
        """Load US state codes and names"""
        # Standard US state codes
        states = {
            'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
            'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
            'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
            'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
            'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
            'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
            'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
            'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
            'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
            'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
            'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
            'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
            'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
        }
        
        return pd.DataFrame([
            {'state_code': code, 'state_name': name} 
            for code, name in states.items()
        ])
    
    def _load_industry_categories(self):
        """Load Exiobase 5-character industry IDs from industry.csv."""
        year = self.config.get('YEAR')
        filename = self.config.get('FILES', {}).get('industries', 'industry.csv')
        base_template = self.config.get('FOLDERS', {}).get('base', '')
        tradeflow_dir = Path(__file__).parents[1]
        repo_root = Path(__file__).parents[3]

        candidates = []
        if base_template:
            base_path = Path(str(base_template).format(year=year))
            candidates.extend([
                Path.cwd() / base_path / filename,
                tradeflow_dir / base_path / filename,
            ])
        candidates.append(repo_root / 'trade-data' / 'year' / str(year) / filename)

        seen = set()
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if not path.exists():
                continue

            try:
                industry_df = pd.read_csv(path)
            except Exception as exc:
                print(f"    Could not load industry categories from {path}: {exc}")
                continue

            required = {'industry_id', 'name', 'category'}
            if not required.issubset(industry_df.columns):
                print(f"    industry.csv missing columns {required - set(industry_df.columns)} at {path}")
                continue

            # BEA Sector from sector_industry.csv beside industry.csv (the Sector with the
            # largest weight), else a match on the industry's category and name
            sector_by_id = self._load_industry_sectors(path.parent / 'sector_industry.csv')
            category_by_id = {}
            for _, row in industry_df.iterrows():
                industry_id = str(row['industry_id']).strip().upper()
                sector = sector_by_id.get(industry_id)
                category_by_id[industry_id] = (
                    SECTOR_ALLOCATION_CATEGORY.get(sector, 'services') if sector
                    else self._normalize_industry_category(row.get('category', ''), row.get('name', ''))
                )

            from_sectors = sum(1 for industry_id in category_by_id if industry_id in sector_by_id)
            print(f"    Loaded {len(category_by_id)} industry categories from {path} "
                  f"({from_sectors} from sector_industry.csv)")
            return category_by_id

        print("    industry.csv not found - falling back to NAICS-prefix industry categorization")
        return {}

    def _load_industry_sectors(self, path):
        """Each industry's BEA Sector with the largest weight in sector_industry.csv."""
        if not path.exists():
            return {}
        try:
            sector_df = pd.read_csv(path, dtype={'sector_id': str, 'industry_id': str})
        except Exception as exc:
            print(f"    Could not load industry sectors from {path}: {exc}")
            return {}
        if not {'sector_id', 'industry_id', 'weight'}.issubset(sector_df.columns):
            return {}
        sector_df['industry_id'] = sector_df['industry_id'].str.strip().str.upper()
        top = sector_df.sort_values('weight', ascending=False).drop_duplicates('industry_id')
        return dict(zip(top['industry_id'], top['sector_id'].str.strip()))

    def _normalize_industry_category(self, category, name=''):
        """Map detailed Exiobase categories to the broad state-allocation buckets."""
        category_text = str(category).lower()
        name_text = str(name).lower()
        text = f"{category_text} {name_text}"

        if self._text_has_any(name_text, [
            'sewerage', 'sewage', 'waste collection', 'waste treatment',
            'water collection', 'water treatment'
        ]):
            return 'utilities'
        if self._text_has_any(text, [
            'agriculture', 'crop', 'rice', 'wheat', 'cereal', 'vegetable', 'fruit',
            'nut', 'oil seed', 'sugar cane', 'sugar beet', 'cattle', 'pig',
            'poultry', 'meat animal', 'raw milk', 'wool', 'manure', 'forestry',
            'logging', 'fish', 'fishing'
        ]):
            return 'agriculture'
        if self._text_has_any(text, [
            'mining', 'coal', 'petroleum', 'crude', 'natural gas', 'ore',
            'lignite', 'uranium', 'quarry'
        ]):
            return 'mining'
        if 'construction' in text or 'building' in text:
            return 'construction'
        if self._text_has_any(text, [
            'electricity', 'gas supply', 'water supply', 'steam', 'utility',
            'utilities', 'sewerage', 'sewage', 'waste collection',
            'waste treatment', 'water collection', 'water treatment'
        ]):
            return 'utilities'
        if self._text_has_any(text, ['transportation services', 'transport by', 'land transport', 'water transport', 'air transport', 'pipeline']):
            return 'transportation'
        if self._text_has_any(text, [
            'manufacturing', 'food', 'beverage', 'tobacco', 'textile', 'clothing',
            'leather', 'chemical', 'pharmaceutical', 'plastic', 'rubber', 'metal',
            'steel', 'iron', 'aluminum', 'machinery', 'equipment', 'motor vehicle',
            'aircraft', 'ship', 'paper', 'cement', 'glass', 'wood products'
        ]):
            return 'manufacturing'
        return 'services'

    def _text_has_any(self, text, terms):
        """Return true when any term appears as a word or phrase."""
        return any(
            re.search(rf'(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])', text)
            for term in terms
        )
    
    def load_exiobase_satellite(self, exiobase_zip_path):
        """
        Load Exiobase M matrix (total — direct + upstream supply chain, via the
        Leontief inverse — environmental multiplier per unit output) for US
        sectors. This matches EPA USEEIO's import_emission_factors methodology
        (see exiobase_helpers.py in https://github.com/USEPA/USEEIO/tree/master/import_emission_factors),
        which builds import factors from M, not the direct-only S matrix — S
        would omit everything embodied in a sector's own inputs.
        Populates self._satellite_data: dict of industry_id -> list of (factor_id, coefficient).
        Factor IDs are assigned by row position across extensions (same as factors.py).
        """
        # No fallback: without the factors, interstate.csv would be written without a
        # matching interstate_factor.csv (bea/main.py checks for pymrio before starting)
        import pymrio

        exiobase_zip_path = Path(exiobase_zip_path)
        if not exiobase_zip_path.exists():
            raise FileNotFoundError(f"Exiobase zip not found: {exiobase_zip_path}")

        print(f"    Loading Exiobase satellite matrix from {exiobase_zip_path.name}...")
        exio_model = pymrio.parse_exiobase3(str(exiobase_zip_path)).calc_all()

        # Build stressor → factor_id mapping (same extension order and row order as factors.py)
        extensions = ['air_emissions', 'employment', 'energy', 'land', 'material', 'water']
        stressor_to_fid = {}
        fid = 1
        for ext_name in extensions:
            if hasattr(exio_model, ext_name):
                ext = getattr(exio_model, ext_name)
                if hasattr(ext, 'F'):
                    for stressor in ext.F.index.tolist():
                        stressor_to_fid[stressor] = fid
                        fid += 1

        # Build sector_name → industry_id mapping (same algorithm as create_sector_mapping.py)
        sectors = exio_model.Z.index.get_level_values('sector').unique()
        used_ids = set()
        sector_to_iid = {}
        for i, sector in enumerate(sectors):
            iid = self._make_industry_id(str(sector), i, used_ids)
            sector_to_iid[str(sector)] = iid

        threshold = self.config.get('PROCESSING', {}).get('min_impact_threshold', 0.001)

        satellite_data = {}      # industry_id → list of (factor_id, coefficient), all raw factors meeting threshold — feeds interstate_factor-max.csv only
        satellite_aggregate = {}  # industry_id → list of (factor_id, coefficient), EPA-style aggregated flows — feeds the default interstate_factor.csv (see exiobase_factors.py)

        for ext_name in extensions:
            if hasattr(exio_model, ext_name):
                ext = getattr(exio_model, ext_name)
                if not hasattr(ext, 'M'):
                    continue
                try:
                    # fillna(0): a handful of raw Exiobase cells are NaN
                    # (typically a 0/0 from a sector with zero output in some
                    # region) rather than 0. Since M is a global
                    # Leontief-inverse product, a single NaN anywhere poisons
                    # that entire stressor's M row for every region — treat
                    # it as a real "no reported value" before summing raw
                    # stressors into an aggregated flow, or a single poisoned
                    # cell silently NaNs out a flow that has real data from
                    # its other contributing stressors.
                    us_M = ext.M.xs('US', level='region', axis=1).fillna(0)
                except KeyError:
                    continue

                for sector in us_M.columns:
                    iid = sector_to_iid.get(str(sector))
                    if not iid:
                        continue
                    entries = [
                        (stressor_to_fid[stressor], float(us_M.loc[stressor, sector]))
                        for stressor in us_M.index
                        if stressor in stressor_to_fid and abs(float(us_M.loc[stressor, sector])) >= threshold
                    ]
                    if entries:
                        if iid not in satellite_data:
                            satellite_data[iid] = []
                        satellite_data[iid].extend(entries)

                    # Aggregated entries for the default file — every stressor
                    # in this extension for this sector, not threshold-filtered
                    # (EPA's own GHG selection doesn't apply a magnitude cutoff
                    # either; the aggregation itself is the reduction).
                    stressor_pairs = [(stressor, float(us_M.loc[stressor, sector])) for stressor in us_M.index]
                    agg_entries = aggregate_coefficients(stressor_pairs, ext_name)
                    if agg_entries:
                        satellite_aggregate.setdefault(iid, []).extend(agg_entries)

        # Sort each industry's full factor list globally by magnitude (descending).
        # This allows callers to slice [:N] to get the top-N selected factors.
        for iid in satellite_data:
            satellite_data[iid].sort(key=lambda x: abs(x[1]), reverse=True)

        self._satellite_data = satellite_data
        self._satellite_data_aggregate = satellite_aggregate
        print(f"    Satellite data loaded: {len(satellite_data)} US industries with factor coefficients")
        return satellite_data

    def get_satellite_aggregate_entries(self, industry_id):
        """
        Return the EPA-style aggregated (factor_id, coefficient) entries for
        a 5-character industry ID — used by the default interstate_factor.csv
        instead of a top-N-by-magnitude slice of get_satellite_factor_entries.
        See exiobase_factors.py.
        """
        satellite = getattr(self, '_satellite_data_aggregate', None)
        if not satellite:
            return []
        return satellite.get(str(industry_id), [])

    def _make_industry_id(self, sector_str, index, used_ids):
        """Generate 5-char industry ID from sector name (mirrors create_sector_mapping.py logic)."""
        clean = re.sub(r'\b(and|of|related|to|services|products|nec|other)\b', '', sector_str, flags=re.IGNORECASE)
        clean = re.sub(r'[^\w\s]', '', clean).strip()
        words = clean.split()
        cid = clean.replace(' ', '')[:5].upper()
        if len(cid) < 5 and len(words) > 1:
            acr = ''.join(w[0] for w in words if w)[:3].upper()
            cid = (acr + clean.replace(' ', '')[len(acr):])[:5].upper()
        if len(cid) < 5:
            cid = (cid + str(index).zfill(5 - len(cid)))[:5]
        orig = cid
        c = 1
        while cid in used_ids:
            cid = (orig[:4] + str(c)) if c < 10 else (orig[:3] + str(c).zfill(2))
            c += 1
        used_ids.add(cid)
        return cid

    def disaggregate_domestic_flows(self, base_trade_df, bea_state_data=None):
        print("    🗺️ Disaggregating domestic flows to state level...")

        if self._prepare_bea_allocation_cache(bea_state_data):
            print("      Using BEA Regional state allocation weights")
        else:
            print("      Using built-in proxy state allocation weights")

        CHUNK_SIZE = 100_000  # tune if needed
        chunks = []
        buffer = []

        for _, trade_row in base_trade_df.iterrows():
            state_disagg = self._disaggregate_single_flow(trade_row, bea_state_data)
            buffer.extend(state_disagg)

            # Flush to chunk when buffer gets large
            if len(buffer) >= CHUNK_SIZE:
                chunks.append(pd.DataFrame(buffer))
                buffer = []

        # Flush remaining
        if buffer:
            chunks.append(pd.DataFrame(buffer))

        if not chunks:
            return pd.DataFrame()

        # Concatenate efficiently
        state_df = pd.concat(chunks, ignore_index=True, copy=False)

        print(f"      ✅ Created {len(state_df)} state-to-state flow records")
        return state_df
    
    def _disaggregate_single_flow(self, trade_row, bea_data=None):
        """Disaggregate a single trade flow to state level.

        Emits one aggregate row per state-pair. Interstate factor rows are
        streamed later from these rows and the Exiobase S-matrix coefficients.
        """
        flows = []

        # Broad industry category used for state allocation weights
        industry1_cat = self._categorize_industry(trade_row.get('industry1', ''))
        industry2_cat = self._categorize_industry(trade_row.get('industry2', ''))
        producing_states = self._get_producing_states(industry1_cat, bea_data)
        consuming_states = self._get_consuming_states(industry2_cat, bea_data)
        total_value = float(trade_row.get('amount', 0))

        industry_id = str(trade_row.get('industry1', ''))
        industry2_id = str(trade_row.get('industry2', ''))

        trade_id = trade_row.get('trade_id', '')

        industry = industry1_cat

        # First collect all candidate state-pair shares. Same-state pairs
        # (origin == destination) are kept, not skipped: excluding them and
        # then renormalizing the rest to sum to 1.0 would silently reallocate
        # genuine intra-state consumption onto cross-state pairs, inflating
        # them. Keeping same-state pairs in the normalization means the
        # total across all resulting rows still equals trade.amount, but now
        # correctly split between real interstate and intrastate flow.
        state_pairs = []
        for origin_state in producing_states:
            for dest_state in consuming_states:
                raw_share = self._calculate_state_flow_share(
                    origin_state, dest_state, industry1_cat, industry2_cat, bea_data
                )

                if raw_share > 0:
                    state_pairs.append((origin_state, dest_state, raw_share))

        if not state_pairs:
            return flows

        total_share = sum(share for _, _, share in state_pairs)
        if total_share <= 0:
            return flows

        for origin_state, dest_state, raw_share in state_pairs:
            normalized_share = raw_share / total_share
            level = total_value * normalized_share

            interstate_id = (
                f"{self.year}-{trade_id}-US-{origin_state}-US-{dest_state}-{industry}"
            )

            flows.append({
                'interstate_id': interstate_id,
                'trade_id': trade_id,
                'factor_id': -1,
                'coefficient': 1.0,
                'state_industry_code': industry,
                'level': level,
                'flow_type': 'intra_state' if origin_state == dest_state else 'inter_state',
                '_origin_state': origin_state,
                '_destination_state': dest_state,
                '_industry1': industry_id,
                '_industry2': industry2_id,
            })

        return flows

    def get_satellite_factor_entries(self, industry_id, limit=None):
        """Return sorted Exiobase factor coefficients for a 5-character industry ID."""
        satellite = getattr(self, '_satellite_data', None)
        if not satellite:
            return []

        entries = satellite.get(str(industry_id), [])
        if limit is None:
            return entries
        return entries[:limit]
 
    
    def _categorize_industry(self, industry_code):
        """Categorize industry code into broad category"""
        if not industry_code:
            return 'services'

        industry_code = str(industry_code).strip().upper()
        if industry_code in self.industry_category_by_id:
            return self.industry_category_by_id[industry_code]

        # Map industry codes to categories (simplified)
        if industry_code.startswith('31') or industry_code.startswith('32') or industry_code.startswith('33'):
            return 'manufacturing'
        elif industry_code.startswith('11'):
            return 'agriculture'
        elif industry_code.startswith('21'):
            return 'mining'
        elif industry_code.startswith('22'):
            return 'utilities'
        elif industry_code.startswith('23'):
            return 'construction'
        elif industry_code.startswith('48') or industry_code.startswith('49'):
            return 'transportation'
        else:
            return 'services'
    
    def _prepare_bea_allocation_cache(self, bea_data):
        """Prepare fast lookups for BEA Regional allocation weights."""
        if not isinstance(bea_data, pd.DataFrame) or bea_data.empty:
            self._bea_allocation_source_id = None
            self._bea_allocation_weight_lookup = {}
            self._bea_allocation_ranked_states = {}
            return False

        source_id = id(bea_data)
        if self._bea_allocation_source_id == source_id:
            return bool(self._bea_allocation_weight_lookup)

        data = bea_data.copy()
        if 'state_industry_code' not in data.columns and 'allocation_category' in data.columns:
            data = data.rename(columns={'allocation_category': 'state_industry_code'})

        required_cols = {'state_industry_code', 'weight_type', 'state', 'weight'}
        if not required_cols.issubset(data.columns):
            self._bea_allocation_source_id = None
            self._bea_allocation_weight_lookup = {}
            self._bea_allocation_ranked_states = {}
            return False

        data = data[list(required_cols)].dropna()
        data['state_industry_code'] = data['state_industry_code'].astype(str).str.lower().str.strip()
        data['weight_type'] = data['weight_type'].astype(str).str.lower().str.strip()
        data['state'] = data['state'].astype(str).str.upper().str.strip()
        data['weight'] = pd.to_numeric(data['weight'], errors='coerce')
        data = data[data['weight'] > 0]

        if data.empty:
            self._bea_allocation_source_id = None
            self._bea_allocation_weight_lookup = {}
            self._bea_allocation_ranked_states = {}
            return False

        data = data.groupby(
            ['state_industry_code', 'weight_type', 'state'],
            as_index=False,
        )['weight'].sum()

        weight_lookup = {
            (row.state_industry_code, row.weight_type, row.state): float(row.weight)
            for row in data.itertuples(index=False)
        }

        ranked_states = {}
        for (category, weight_type), group in data.groupby(['state_industry_code', 'weight_type']):
            ranked_states[(category, weight_type)] = (
                group.sort_values('weight', ascending=False)['state'].tolist()
            )

        self._bea_allocation_source_id = source_id
        self._bea_allocation_weight_lookup = weight_lookup
        self._bea_allocation_ranked_states = ranked_states
        return bool(weight_lookup)

    def _get_bea_ranked_states(self, industry, weight_type, bea_data):
        if not self._prepare_bea_allocation_cache(bea_data):
            return []
        return self._bea_allocation_ranked_states.get((industry, weight_type), [])

    def _get_bea_weight(self, industry, weight_type, state, bea_data):
        if not self._prepare_bea_allocation_cache(bea_data):
            return None
        return self._bea_allocation_weight_lookup.get(
            (industry, weight_type, str(state).upper().strip())
        )

    def _get_producing_states(self, industry, bea_data=None):
        """The 8 states with the largest BEA origin weights for this category"""
        return self._get_bea_ranked_states(industry, 'origin', bea_data)[:8]

    def _get_consuming_states(self, industry, bea_data=None):
        """The 20 states with the largest BEA destination weights for this category"""
        return self._get_bea_ranked_states(industry, 'destination', bea_data)[:20]

    def _calculate_state_flow_share(self, origin, destination, industry1_cat, industry2_cat, bea_data):
        """Origin weight of the supplying category times destination weight of the buying one"""
        origin_weight = self._get_bea_weight(industry1_cat, 'origin', origin, bea_data)
        dest_weight = self._get_bea_weight(industry2_cat, 'destination', destination, bea_data)
        if origin_weight is None or dest_weight is None:
            return 0.0
        return origin_weight * dest_weight

    def analyze_export_competitiveness(self, interstate_df):
        """
        State-level export competitiveness from interstate.csv.

        interstate_df columns: interstate_id, state1 (origin state), state2 (destination state),
                               sector1/industry1 (BEA Sector for the primary interstate.csv, raw
                               Exiobase industry for the full-detail interstate-lg.csv), amount (M EUR)

        Metrics per interstate_id:
          state_industry_exports_total : M EUR sent by this state+industry to all destination states
          state_destination_share      : this row's amount / state+industry total (0–1)
          state_export_intensity       : state+industry total / all interstate exports (0–1)
          state_destination_count      : distinct destination states for this state+industry
          state_export_concentration   : HHI of destinations for this state+industry (0=dispersed, 1=one)
        """
        print("    📈 Analyzing state export competitiveness from interstate data...")

        if interstate_df.empty:
            return pd.DataFrame()

        # interstate.csv (primary) has sector1/2 (BEA Sector level); interstate-lg.csv
        # (full detail) has industry1/2 (raw Exiobase industry) — see ../PLAN.md.
        col1 = 'sector1' if 'sector1' in interstate_df.columns else 'industry1'

        total = interstate_df['amount'].sum()

        def _hhi(amounts):
            t = amounts.sum()
            if t == 0:
                return 0.0
            s = amounts / t
            return round(float((s ** 2).sum()), 6)

        state_industry_stats = interstate_df.groupby(['state1', col1]).agg(
            state_industry_exports_total=('amount', 'sum'),
            state_destination_count=('state2', 'nunique'),
        )
        state_industry_hhi = (
            interstate_df.groupby(['state1', col1])['amount']
            .apply(_hhi)
            .rename('state_export_concentration')
        )
        state_industry_stats = state_industry_stats.join(state_industry_hhi).reset_index()

        result = interstate_df[['interstate_id', 'state1', col1, 'amount']].merge(
            state_industry_stats, on=['state1', col1]
        )
        result['state_destination_share'] = (result['amount'] / result['state_industry_exports_total']).round(6)
        result['state_export_intensity'] = (result['state_industry_exports_total'] / total).round(6)
        result['state_industry_exports_total'] = result['state_industry_exports_total'].round(2)

        out = result[['interstate_id', 'state_industry_exports_total', 'state_destination_share',
                      'state_export_intensity', 'state_destination_count', 'state_export_concentration']]
        print(f"      ✅ State export competitiveness: {len(out)} rows, {interstate_df['state1'].nunique()} states")
        return out

    def analyze_import_dependency(self, interstate_df):
        """
        State-level import dependency from interstate.csv.

        Treats inbound interstate flows (state2 = destination state) as state imports.

        Metrics per interstate_id:
          state_industry_imports_total : M EUR received by this state+industry from all origin states
          state_source_share           : this row's amount / state+industry total (0–1)
          state_import_intensity       : state+industry total / all interstate imports (0–1)
          state_supplier_count         : distinct origin states supplying this state+industry
          state_import_concentration   : HHI of origins (higher = more dependent on fewer states)
        """
        print("    🔗 Analyzing state import dependency from interstate data...")

        if interstate_df.empty:
            return pd.DataFrame()

        # interstate.csv (primary) has sector1/2 (BEA Sector level); interstate-lg.csv
        # (full detail) has industry1/2 (raw Exiobase industry) — see ../PLAN.md.
        col2 = 'sector2' if 'sector2' in interstate_df.columns else 'industry2'

        total = interstate_df['amount'].sum()

        def _hhi(amounts):
            t = amounts.sum()
            if t == 0:
                return 0.0
            s = amounts / t
            return round(float((s ** 2).sum()), 6)

        state_industry_stats = interstate_df.groupby(['state2', col2]).agg(
            state_industry_imports_total=('amount', 'sum'),
            state_supplier_count=('state1', 'nunique'),
        )
        state_industry_hhi = (
            interstate_df.groupby(['state2', col2])['amount']
            .apply(_hhi)
            .rename('state_import_concentration')
        )
        state_industry_stats = state_industry_stats.join(state_industry_hhi).reset_index()

        result = interstate_df[['interstate_id', 'state2', col2, 'amount']].merge(
            state_industry_stats, on=['state2', col2]
        )
        result['state_source_share'] = (result['amount'] / result['state_industry_imports_total']).round(6)
        result['state_import_intensity'] = (result['state_industry_imports_total'] / total).round(6)
        result['state_industry_imports_total'] = result['state_industry_imports_total'].round(2)

        out = result[['interstate_id', 'state_industry_imports_total', 'state_source_share',
                      'state_import_intensity', 'state_supplier_count', 'state_import_concentration']]
        print(f"      ✅ State import dependency: {len(out)} rows, {interstate_df['state2'].nunique()} states")
        return out
    
    def create_state_reference_data(self, output_path):
        """Create state reference data files"""
        print("  📋 Creating state reference data...")
        output_path.mkdir(parents=True, exist_ok=True)

        self.state_codes.to_csv(output_path / 'state_codes.csv', index=False)
        print("    ✅ Created state_codes.csv")
