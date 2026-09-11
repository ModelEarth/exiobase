"""
FEDEFL Integration Module

Integrates Federal LCA Commons Elementary Flow List (FEDEFL) data
to provide comprehensive flow metadata and environmental impact details.
"""

import pandas as pd
import requests
import json
from pathlib import Path
import uuid
import os
import re
from io import BytesIO

DEFAULT_FEDEFL_FLOWLIST_URL = (
    # Reference:https://flcac-admin.github.io/FLCAC-docs/flowmappinginstructions/
    "https://dmap-data-commons-ord.s3.amazonaws.com/fedelemflowlist/FedElemFlowList_1.3.0_all.xlsx"
)

class FEDEFLIntegrator:
    def __init__(self):
        self.fedefl_flowlist_url = os.getenv(
            'FEDEFL_FLOWLIST_URL',
            DEFAULT_FEDEFL_FLOWLIST_URL,
        ).strip()
        self.fedefl_base_url = os.getenv('FEDEFL_BASE_URL', '').strip().rstrip('/')
        self.flows_cache = None
        self.contexts_cache = None
        self.mapped_flow_uuids = set()
        self.factor_flow_mapping = pd.DataFrame()
        
        # Common flow categories for trade analysis
        self.priority_contexts = [
            'emission/air',
            'emission/water',
            'emission/soil',
            'resource/air',
            'resource/water', 
            'resource/biotic',
            'resource/fossil fuel',
            'resource/land',
            'waste'
        ]
    
    def load_fedefl_flows(self):
        """Load FEDEFL flows from a configured source or built-in seed list."""
        print("  Loading FEDEFL flow data...")

        if self.fedefl_flowlist_url:
            try:
                flows_df = self._fetch_fedefl_workbook()
                if not flows_df.empty:
                    print(f"    Loaded {len(flows_df)} FEDEFL flows from workbook")
                    self.flows_cache = flows_df
                    return flows_df
            except Exception as e:
                print(f"    FEDEFL workbook unavailable: {e}")

        if self.fedefl_base_url:
            try:
                flows_df = self._fetch_fedefl_online()
                if not flows_df.empty:
                    print(f"    Loaded {len(flows_df)} FEDEFL flows from online source")
                    self.flows_cache = flows_df
                    return flows_df
                
            except Exception as e:
                print(f"    Configured FEDEFL online source unavailable: {e}")
        else:
            print("    Using built-in FEDEFL-compatible flow list")
        
        # Fallback to local flow creation
        flows_df = self._create_local_flows()
        print(f"    Created {len(flows_df)} built-in environmental flows")
        self.flows_cache = flows_df
        return flows_df
    
    def _fetch_fedefl_online(self):
        """Fetch FEDEFL data from online source"""
        if not self.fedefl_base_url:
            raise ValueError("FEDEFL_BASE_URL is not configured")

        flows_url = f"{self.fedefl_base_url}/flows.json"
        contexts_url = f"{self.fedefl_base_url}/contexts.json"
        
        # Fetch flows
        flows_response = requests.get(flows_url, timeout=10)
        flows_response.raise_for_status()
        flows_data = flows_response.json()
        
        # Fetch contexts
        contexts_response = requests.get(contexts_url, timeout=10)
        contexts_response.raise_for_status()
        contexts_data = contexts_response.json()
        
        # Process into DataFrame
        flows_df = self._process_fedefl_data(flows_data, contexts_data)
        return flows_df

    def _fetch_fedefl_workbook(self):
        """Fetch and parse the official FEDEFL workbook export."""
        source = self.fedefl_flowlist_url
        if source.lower().startswith(('http://', 'https://')):
            response = requests.get(source, timeout=30)
            response.raise_for_status()
            workbook = BytesIO(response.content)
        else:
            workbook = Path(source)
            if not workbook.exists():
                raise FileNotFoundError(workbook)

        flows_df = pd.read_excel(workbook, sheet_name=0)
        return self._process_fedefl_workbook(flows_df)

    def _process_fedefl_workbook(self, flows_df):
        """Normalize the FEDEFL workbook columns into flow.csv columns."""
        required_columns = {'Flowable', 'Context', 'Unit', 'Flow UUID'}
        missing_columns = required_columns - set(flows_df.columns)
        if missing_columns:
            raise ValueError(
                f"FEDEFL workbook missing columns: {sorted(missing_columns)}"
            )

        def clean(value):
            if pd.isna(value):
                return ''
            return str(value).strip()

        def preferred(value):
            if pd.isna(value):
                return True
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() not in ('0', 'false', 'no')

        flows = []
        for _, flow in flows_df.iterrows():
            flowable = clean(flow.get('Flowable'))
            context = clean(flow.get('Context'))
            unit = clean(flow.get('Unit'))
            if not flowable or not context or not unit:
                continue

            flow_uuid = clean(flow.get('Flow UUID'))
            try:
                flow_uuid = str(uuid.UUID(flow_uuid))
            except (TypeError, ValueError):
                uuid_basis = f"model-earth:fedefl-workbook:{flowable}:{context}:{unit}"
                flow_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, uuid_basis))

            flows.append({
                'flow_uuid': flow_uuid,
                'flowable': flowable,
                'context': context,
                'unit': unit,
                'compartment': self._extract_compartment(context),
                'flow_class': clean(flow.get('Class')) or 'environmental',
                'preferred': preferred(flow.get('Preferred')),
                'external_reference': clean(flow.get('External Reference')),
                'cas_number': clean(flow.get('CAS No')),
                'formula': clean(flow.get('Formula')),
                'synonyms': clean(flow.get('Synonyms')),
            })

        return pd.DataFrame(flows)
    
    def _process_fedefl_data(self, flows_data, contexts_data):
        """Process raw FEDEFL data into standardized DataFrame"""
        flows = []
        
        for flow in flows_data:
            flow_record = {
                'flow_uuid': flow.get('uuid', str(uuid.uuid4())),
                'flowable': flow.get('flowable', ''),
                'context': flow.get('context', ''),
                'unit': flow.get('unit', ''),
                'compartment': self._extract_compartment(flow.get('context', '')),
                'flow_class': flow.get('class', 'environmental'),
                'preferred': flow.get('preferred', True),
                'external_reference': flow.get('external_reference', ''),
                'cas_number': flow.get('cas_number', ''),
                'formula': flow.get('formula', ''),
                'synonyms': '; '.join(flow.get('synonyms', [])),
            }
            flows.append(flow_record)
        
        return pd.DataFrame(flows)
    
    def _create_local_flows(self):
        """Create local environmental flows based on common trade impacts"""
        flows = []

        def stable_uuid(uuid_str, flowable, context, unit):
            try:
                uuid.UUID(str(uuid_str))
                return uuid_str
            except (TypeError, ValueError):
                uuid_basis = f"model-earth:local-flow:{flowable}:{context}:{unit}"
                return str(uuid.uuid5(uuid.NAMESPACE_URL, uuid_basis))
        
        # Air emissions
        air_emissions = [
            ('Carbon dioxide', 'kg', 'b6f010fb-a764-3063-af2d-bcb8309a97b7'),
            ('Methane', 'kg', '7b8b7b8b-a764-3063-af2d-bcb8309a97b8'),
            ('Nitrous oxide', 'kg', '8c9c8c9c-a764-3063-af2d-bcb8309a97b9'),
            ('Sulfur dioxide', 'kg', '9d0d9d0d-a764-3063-af2d-bcb8309a97c0'),
            ('Nitrogen oxides', 'kg', 'a1e1a1e1-a764-3063-af2d-bcb8309a97c1'),
            ('Particulate matter', 'kg', 'b2f2b2f2-a764-3063-af2d-bcb8309a97c2'),
            ('Carbon monoxide', 'kg', 'c3g3c3g3-a764-3063-af2d-bcb8309a97c3'),
            ('Volatile organic compounds', 'kg', 'd4h4d4h4-a764-3063-af2d-bcb8309a97c4'),
            ('Ammonia', 'kg', 'e5i5e5i5-a764-3063-af2d-bcb8309a97c5'),
            ('Benzene', 'kg', 'f6j6f6j6-a764-3063-af2d-bcb8309a97c6')
        ]
        
        for flowable, unit, uuid_str in air_emissions:
            flows.append({
                'flow_uuid': stable_uuid(uuid_str, flowable, 'emission/air', unit),
                'flowable': flowable,
                'context': 'emission/air',
                'unit': unit,
                'compartment': 'air',
                'flow_class': 'environmental',
                'preferred': True,
                'external_reference': 'EPA',
                'cas_number': '',
                'formula': '',
                'synonyms': '',
            })
        
        # Water emissions
        water_emissions = [
            ('Biological oxygen demand', 'kg', '10a10a10-a764-3063-af2d-bcb8309a97c7'),
            ('Chemical oxygen demand', 'kg', '11b11b11-a764-3063-af2d-bcb8309a97c8'),
            ('Suspended solids', 'kg', '12c12c12-a764-3063-af2d-bcb8309a97c9'),
            ('Nitrogen total', 'kg', '13d13d13-a764-3063-af2d-bcb8309a97d0'),
            ('Phosphorus total', 'kg', '14e14e14-a764-3063-af2d-bcb8309a97d1'),
            ('Heavy metals', 'kg', '15f15f15-a764-3063-af2d-bcb8309a97d2')
        ]
        
        for flowable, unit, uuid_str in water_emissions:
            flows.append({
                'flow_uuid': stable_uuid(uuid_str, flowable, 'emission/water', unit),
                'flowable': flowable,
                'context': 'emission/water',
                'unit': unit,
                'compartment': 'water',
                'flow_class': 'environmental',
                'preferred': True,
                'external_reference': 'EPA',
                'cas_number': '',
                'formula': '',
                'synonyms': '',
            })
        
        # Resource use
        resources = [
            ('Water use', 'L', '16g16g16-a764-3063-af2d-bcb8309a97d3'),
            ('Energy use', 'MJ', '17h17h17-a764-3063-af2d-bcb8309a97d4'),
            ('Land use', 'm2', '18i18i18-a764-3063-af2d-bcb8309a97d5'),
            ('Fossil fuel depletion', 'MJ surplus', '19j19j19-a764-3063-af2d-bcb8309a97d6'),
            ('Mineral depletion', 'kg Fe equiv', '20k20k20-a764-3063-af2d-bcb8309a97d7')
        ]
        
        for flowable, unit, uuid_str in resources:
            flows.append({
                'flow_uuid': stable_uuid(uuid_str, flowable, 'resource/natural', unit),
                'flowable': flowable,
                'context': 'resource/natural',
                'unit': unit,
                'compartment': 'natural resources',
                'flow_class': 'resource',
                'preferred': True,
                'external_reference': 'EPA',
                'cas_number': '',
                'formula': '',
                'synonyms': '',
            })
        
        # Employment and economic flows
        economic_flows = [
            ('Employment', 'person*year', '21l21l21-a764-3063-af2d-bcb8309a97d8'),
            ('Value added', 'USD', '22m22m22-a764-3063-af2d-bcb8309a97d9'),
            ('Tax revenue', 'USD', '23n23n23-a764-3063-af2d-bcb8309a97e0')
        ]
        
        for flowable, unit, uuid_str in economic_flows:
            flows.append({
                'flow_uuid': stable_uuid(uuid_str, flowable, 'economic', unit),
                'flowable': flowable,
                'context': 'economic',
                'unit': unit,
                'compartment': 'economic',
                'flow_class': 'economic',
                'preferred': True,
                'external_reference': 'BEA',
                'cas_number': '',
                'formula': '',
                'synonyms': '',
            })
        
        return pd.DataFrame(flows)
    
    def _extract_compartment(self, context):
        """Extract compartment from context string"""
        if '/' in context:
            return context.split('/')[1]
        return context
    
    def map_factors_to_flows(self, factors_df):
        """Map trade factors to FEDEFL flows"""
        print("  Mapping trade factors to FEDEFL flows...")
        
        if self.flows_cache is None:
            self.load_fedefl_flows()
        
        mapped_factors = []
        
        for _, factor in factors_df.iterrows():
            factor_record = self._get_factor_record(factor)
            factor_name = factor_record['factor_name']
            
            # Try to find matching flow
            matching_flow = self._find_matching_flow(factor_record)
            
            if matching_flow is not None:
                target_flowable = self._target_flowable_for_factor(factor_record)
                target_context = self._target_context_for_factor(factor_record)
                matched_flowable = str(matching_flow['flowable']).lower().strip()
                matched_context = str(matching_flow['context']).lower().strip()

                matching_reference = str(
                    matching_flow.get('external_reference', '')
                ).strip().lower()

                if matching_reference == 'exiobase':
                    match_quality = 'created'
                elif (
                    target_flowable.lower().strip() == matched_flowable
                    and (
                        not target_context
                        or target_context.lower().strip() == matched_context
                    )
                ):
                    match_quality = 'high'
                else:
                    match_quality = 'medium'

                self.mapped_flow_uuids.add(matching_flow['flow_uuid'])
                mapped_factors.append({
                    'factor_id': factor_record['factor_id'],
                    'factor_name': factor_name,
                    'flow_uuid': matching_flow['flow_uuid'],
                    'flowable': matching_flow['flowable'],
                    'context': matching_flow['context'],
                    'unit': matching_flow['unit'],
                    'match_quality': match_quality,
                })
            else:
                # Create new flow for unmapped factors
                new_flow = self._create_flow_for_factor(
                    factor_name,
                    unit=factor_record['unit'],
                    extension=factor_record['extension'],
                    factor_id=factor_record['factor_id'],
                )
                self.mapped_flow_uuids.add(new_flow['flow_uuid'])
                mapped_factors.append({
                    'factor_id': factor_record['factor_id'],
                    'factor_name': factor_name,
                    'flow_uuid': new_flow['flow_uuid'],
                    'flowable': new_flow['flowable'],
                    'context': new_flow['context'],
                    'unit': new_flow['unit'],
                    'match_quality': 'created',
                })
        
        mapping_df = pd.DataFrame(mapped_factors)
        self.factor_flow_mapping = mapping_df.copy()
        print(f"    Mapped {len(mapping_df)} factors to flows")
        
        return mapping_df

    def _get_factor_record(self, factor):
        """Normalize factor.csv rows for FEDEFL matching."""
        def first_present(columns, default=''):
            for col in columns:
                if col in factor.index and pd.notna(factor[col]) and str(factor[col]).strip():
                    return str(factor[col]).strip()
            return default

        factor_id = first_present(['factor_id', 'id'], str(factor.name))
        factor_name = first_present(
            ['factor_name', 'stressor', 'flowable', 'name'],
            factor_id,
        )

        return {
            'factor_id': factor_id,
            'factor_name': factor_name,
            'unit': first_present(['unit'], ''),
            'extension': first_present(['extension'], ''),
        }
    
    def _find_matching_flow(self, factor_record):
        """Find matching FEDEFL flow for a factor"""
        if self.flows_cache is None or factor_record is None:
            return None

        factor_name = factor_record.get('factor_name')
        if factor_name is None:
            return None

        factor_lower = str(factor_name).lower().strip()
        target_flowable = self._target_flowable_for_factor(factor_record)
        target_lower = target_flowable.lower().strip()
        target_context = self._target_context_for_factor(factor_record)
        extension = str(factor_record.get('extension', '')).lower().strip()

        if target_lower in ('hfc', 'pfc'):
            return None

        flowable_lower = self.flows_cache['flowable'].astype(str).str.lower().str.strip()
        
        # Exact FEDEFL flowable match first, ranked by the expected context.
        exact_matches = self.flows_cache[
            flowable_lower == target_lower
        ]
        if not exact_matches.empty:
            return self._rank_flow_matches(exact_matches, target_context).iloc[0].to_dict()
        
        # For non-air extensions, avoid fuzzy matching because broad FEDEFL rows
        # such as "Land use" can collapse detailed Exiobase land/water/material
        # factors into misleading generic rows.
        if extension != 'air_emissions':
            return None

        # Match against FEDEFL synonyms where available.
        if 'synonyms' in self.flows_cache.columns:
            synonyms_lower = self.flows_cache['synonyms'].fillna('').astype(str).str.lower()
            synonym_matches = self.flows_cache[
                synonyms_lower.str.contains(target_lower, na=False, regex=False)
            ]
            if not synonym_matches.empty:
                return self._rank_flow_matches(synonym_matches, target_context).iloc[0].to_dict()

        # Partial match, ranked by the expected context.
        partial_matches = self.flows_cache[
            flowable_lower.str.contains(
                target_lower,
                na=False,
                regex=False,
            )
        ]
        if not partial_matches.empty:
            return self._rank_flow_matches(partial_matches, target_context).iloc[0].to_dict()
        
        # Keyword matching for common cases
        keywords = {
            'co2': 'carbon dioxide',
            'ch4': 'methane', 
            'n2o': 'nitrous oxide',
            'so2': 'sulfur dioxide',
            'nox': 'nitrogen oxides',
            'pm10': 'Particulate matter, \u2264 10\u03bcm',
            'pm2.5': 'Particulate matter, \u2264 2.5\u03bcm',
            'pm': 'particulate matter',
        }
        
        for keyword, flowable in keywords.items():
            if keyword in factor_lower:
                keyword_matches = self.flows_cache[
                    (flowable_lower == flowable)
                    | flowable_lower.str.contains(flowable, na=False, regex=False)
                ]
                if not keyword_matches.empty:
                    return self._rank_flow_matches(keyword_matches, target_context).iloc[0].to_dict()
        
        return None

    def _target_flowable_for_factor(self, factor_record):
        """Convert common Exiobase stressor labels into FEDEFL flowable names."""
        factor_name = str(factor_record.get('factor_name', '')).strip()
        base_name = re.split(r'\s+-\s+', factor_name, maxsplit=1)[0].strip()
        key = base_name.lower().replace('_', '.')

        aliases = {
            'as': 'Arsenic',
            'b(a)p': 'Benzo[a]pyrene',
            'b(b)f': 'Benzo[b]fluoranthene',
            'b(k)f': 'Benzo[k]fluoranthene',
            'cd': 'Cadmium',
            'ch4': 'Methane',
            'co': 'Carbon monoxide',
            'co2': 'Carbon dioxide',
            'co2.bio': 'Carbon dioxide',
            'cr': 'Chromium',
            'cu': 'Copper',
            'hcb': 'Hexachlorobenzene',
            'hg': 'Mercury',
            'indeno': 'Indeno[1,2,3-cd]pyrene',
            'n2o': 'Nitrous oxide',
            'nh3': 'Ammonia',
            'nmvoc': 'Non-methane volatile organic compounds',
            'nox': 'Nitrogen oxides',
            'ni': 'Nickel',
            'pb': 'Lead',
            'pcb': 'Polychlorinated biphenyls',
            'pm10': 'Particulate matter, \u2264 10\u03bcm',
            'pm2.5': 'Particulate matter, \u2264 2.5\u03bcm',
            'se': 'Selenium',
            'so2': 'Sulfur dioxide',
            'sox': 'Sulfur oxides',
            'tsp': 'Particulate matter',
            'zn': 'Zinc',
        }

        return aliases.get(key, base_name or factor_name)

    def _target_context_for_factor(self, factor_record):
        """Infer the broad FEDEFL context expected for an Exiobase factor."""
        extension = str(factor_record.get('extension', '')).lower().strip()
        factor_name = str(factor_record.get('factor_name', '')).lower()

        if extension == 'air_emissions' or factor_name.endswith('- air'):
            return 'emission/air'
        if extension == 'water':
            return 'resource/water'
        if extension == 'land':
            return 'resource/ground'
        if extension == 'energy':
            return 'resource/energy'
        if extension == 'material':
            return 'resource/natural'
        if extension == 'employment':
            return 'economic'
        return ''

    def _rank_flow_matches(self, matches, target_context):
        """Rank candidate FEDEFL rows so broad expected contexts win first."""
        ranked = matches.copy()
        context_lower = ranked['context'].fillna('').astype(str).str.lower().str.strip()
        target_context = str(target_context).lower().strip()

        ranked['_context_score'] = 0
        if target_context:
            ranked.loc[context_lower == target_context, '_context_score'] = 100
            ranked.loc[
                context_lower.str.startswith(f"{target_context}/"),
                '_context_score',
            ] = ranked['_context_score'].where(ranked['_context_score'] > 0, 70)
            ranked.loc[
                context_lower.str.contains(target_context, regex=False, na=False),
                '_context_score',
            ] = ranked['_context_score'].where(ranked['_context_score'] > 0, 30)

        if 'preferred' in ranked.columns:
            preferred = ranked['preferred'].fillna(False).astype(bool)
        else:
            preferred = pd.Series(False, index=ranked.index)
        ranked['_preferred_score'] = preferred.astype(int)
        ranked['_context_length'] = context_lower.str.len()

        ranked = ranked.sort_values(
            ['_context_score', '_preferred_score', '_context_length'],
            ascending=[False, False, True],
        )
        return ranked.drop(columns=['_context_score', '_preferred_score', '_context_length'])
    
    def _create_flow_for_factor(self, factor_name, unit='', extension='', factor_id=''):
        """Create new flow for unmapped factor"""
        # Determine likely context based on factor name
        factor_lower = str(factor_name).lower()

        extension_defaults = {
            'air_emissions': ('emission/air', 'air', 'environmental'),
            'water': ('resource/water', 'water', 'resource'),
            'energy': ('resource/energy', 'energy', 'resource'),
            'land': ('resource/land', 'land', 'resource'),
            'material': ('resource/natural', 'natural resources', 'resource'),
            'employment': ('economic', 'economic', 'economic'),
        }

        extension_key = str(extension).lower().strip()
        if extension_key in extension_defaults:
            context, compartment, flow_class = extension_defaults[extension_key]
        elif any(word in factor_lower for word in ['emission', 'co2', 'ch4', 'pollut']):
            context = 'emission/air'
            compartment = 'air'
            flow_class = 'environmental'
        elif any(word in factor_lower for word in ['water', 'aquatic']):
            context = 'resource/water'
            compartment = 'water'
            flow_class = 'resource'
        elif any(word in factor_lower for word in ['employ', 'job', 'worker']):
            context = 'economic'
            compartment = 'economic'
            flow_class = 'economic'
        elif any(word in factor_lower for word in ['energy', 'mj', 'kwh']):
            context = 'resource/energy'
            compartment = 'energy'
            flow_class = 'resource'
        else:
            context = 'environmental'
            compartment = 'environmental'
            flow_class = 'environmental'

        if not unit:
            if flow_class == 'economic':
                unit = 'person*year'
            elif context == 'resource/energy':
                unit = 'MJ'
            else:
                unit = 'kg'

        uuid_basis = f"model-earth:exiobase-factor:{factor_id}:{factor_name}:{unit}:{extension_key}"
        synonyms = '; '.join(
            part for part in [
                f"factor_id:{factor_id}" if factor_id != '' else '',
                f"extension:{extension}" if extension != '' else '',
            ]
            if part
        )
        
        new_flow = {
            'flow_uuid': str(uuid.uuid5(uuid.NAMESPACE_URL, uuid_basis)),
            'flowable': factor_name,
            'context': context,
            'unit': unit,
            'compartment': compartment,
            'flow_class': flow_class,
            'preferred': True,
            'external_reference': 'Exiobase',
            'cas_number': '',
            'formula': '',
            'synonyms': synonyms,
        }
        
        # Add to cache
        if self.flows_cache is not None:
            new_flow_df = pd.DataFrame([new_flow])
            self.flows_cache = pd.concat([self.flows_cache, new_flow_df], ignore_index=True)
        
        return new_flow
    
    def create_comprehensive_flow_table(self, output_path):
        """Create comprehensive flow.csv table"""
        print("  Creating comprehensive flow table...")
        
        if self.flows_cache is None:
            self.load_fedefl_flows()
        
        # Enhance flows with additional metadata
        enhanced_flows = self.flows_cache.copy()
        if self.mapped_flow_uuids:
            enhanced_flows = enhanced_flows[
                enhanced_flows['flow_uuid'].isin(self.mapped_flow_uuids)
            ].copy()

        enhanced_flows = enhanced_flows.drop_duplicates(
            subset=['flowable', 'context', 'unit'],
            keep='first',
        ).drop_duplicates(
            subset=['flow_uuid'],
            keep='first',
        )
        
        # Add trade relevance scoring
        enhanced_flows['trade_relevance'] = enhanced_flows.apply(
            self._calculate_trade_relevance, axis=1
        )

        output_columns = [
            'flow_uuid',
            'flowable',
            'context',
            'unit',
            'compartment',
            'flow_class',
            'preferred',
            'external_reference',
            'cas_number',
            'formula',
            'synonyms',
            'trade_relevance',
        ]
        for column in output_columns:
            if column not in enhanced_flows.columns:
                enhanced_flows[column] = ''
        enhanced_flows = enhanced_flows[output_columns]
        
        # Sort by relevance and preferred status
        enhanced_flows = enhanced_flows.sort_values([
            'trade_relevance', 'preferred', 'flowable'
        ], ascending=[False, False, True])
        
        # Save comprehensive flow table
        output_file = output_path / 'flow.csv'
        enhanced_flows.to_csv(output_file, index=False)
        
        print(f"    Created comprehensive flow table with {len(enhanced_flows)} flows")
        
        # Create summary statistics
        self._create_flow_summary(enhanced_flows, output_path)
        
        return enhanced_flows
    
    def _calculate_trade_relevance(self, flow_row):
        """Calculate relevance score for trade analysis"""
        flowable = str(flow_row['flowable']).lower()
        context = str(flow_row['context']).lower()
        
        # High relevance flows
        high_relevance_terms = [
            'carbon dioxide', 'co2', 'methane', 'ch4', 'employment', 
            'energy', 'water', 'land use', 'gdp', 'value added'
        ]
        
        # Medium relevance flows
        medium_relevance_terms = [
            'nitrogen', 'sulfur', 'particulate', 'pollution', 
            'waste', 'resource', 'mineral', 'fossil'
        ]
        
        score = 0
        
        # Check flowable name
        for term in high_relevance_terms:
            if term in flowable:
                score += 10
                break
        else:
            for term in medium_relevance_terms:
                if term in flowable:
                    score += 5
                    break
        
        # Context bonuses
        if 'emission' in context:
            score += 3
        elif 'resource' in context:
            score += 2
        elif 'economic' in context:
            score += 8
        
        # Preferred flows get bonus
        if flow_row.get('preferred', False):
            score += 2
        
        return score
    
    def _create_flow_summary(self, flows_df, output_path):
        """Create flow summary statistics"""
        summary_stats = {
            'total_flows': len(flows_df),
            'by_context': flows_df['context'].value_counts().to_dict(),
            'by_compartment': flows_df['compartment'].value_counts().to_dict(),
            'by_flow_class': flows_df['flow_class'].value_counts().to_dict(),
            'high_relevance_flows': len(flows_df[flows_df['trade_relevance'] >= 10]),
            'preferred_flows': len(flows_df[flows_df['preferred'] == True])
        }
        
        # Save summary as JSON
        with open(output_path / 'flow_summary.json', 'w') as f:
            json.dump(summary_stats, f, indent=2)
        
        print(f"    Flow summary: {summary_stats['total_flows']} total, "
              f"{summary_stats['high_relevance_flows']} high-relevance flows")
    
    def validate_flow_completeness(self, trade_factors_df, output_path):
        """Validate that all trade factors have corresponding flows"""
        print("  Validating flow completeness...")
        
        if trade_factors_df.empty:
            print("    No trade factors to validate")
            return
        
        # Reuse the first-pass mapping so generated Exiobase rows do not get
        # remapped as exact matches after they are added to the local cache.
        if not self.factor_flow_mapping.empty:
            mapping = self.factor_flow_mapping.copy()
        else:
            mapping = self.map_factors_to_flows(trade_factors_df)

        match_quality = mapping.get(
            'match_quality',
            pd.Series('', index=mapping.index),
        ).fillna('')
        
        created = mapping[match_quality == 'created']

        created_factor_ids = []
        if not created.empty and 'factor_id' in created.columns:
            created_factor_ids = [
                int(factor_id) if str(factor_id).isdigit() else factor_id
                for factor_id in created['factor_id'].tolist()
            ]
        
        validation_report = {
            'total_factors': len(trade_factors_df),
            'mapped_factors': len(mapping),
            'exact_matches': int((match_quality == 'high').sum()),
            'partial_matches': int((match_quality == 'medium').sum()),
            'created_flows': len(created),
            'unmapped_factors': created_factor_ids
        }
        
        # Save validation report
        with open(output_path / 'flow_validation.json', 'w') as f:
            json.dump(validation_report, f, indent=2)
        
        print(f"    Validation complete: {validation_report['mapped_factors']}/{validation_report['total_factors']} factors mapped")
