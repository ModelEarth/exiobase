# Annual trade data processing

The following provides guidance to our AI Agents when working with code in this repository.

## Project Overview

This is an Exiobase data processing project that extracts and transforms multiregional input-output (MRIO) data for economic and environmental analysis. The project processes trade flows, industry factors, and environmental impacts from the Industry Database.

## Architecture

### Core Components

- **config.yaml**: Central configuration for countries, trade flows, processing parameters
- **config_loader.py**: Smart configuration handling with domestic/non-domestic file selection
- **main.py**: Automated batch processing with progress tracking

### Data Flow Architecture

1. **Data Source**: Exiobase v3 database files (parsed using pymrio library)
2. **Core Matrices**:
   - **Z matrix**: Inter-industry flows between regions/sectors
   - **Y matrix**: Final demand  
   - **F matrix**: Environmental extension factors
3. **Processing**: Transform matrices into relational format for database storage
4. **Output**: Structured CSV files with comprehensive environmental impact data

## Development Environment

### Python Environment Setup
```bash
# Create a virtual environment (one-time setup)
python -m venv ~/env

# Activate it
source ~/env/bin/activate        # macOS/Linux
~/env/Scripts/activate.bat       # Windows

# Install all required dependencies from requirements.txt
pip install --prefer-binary -r requirements.txt
```

The virtual environment lives at `~/env` (outside the project). Always use the full path
or activate the env before running scripts:

```bash
# Without activation — use full path to python:
~/env/bin/python3 bea/main.py

# With activation — plain python3 works:
source ~/env/bin/activate
python3 bea/main.py
```


#### Automated Batch Processing:
```bash
# Process multiple countries automatically
python main.py

# Override YEAR/TRADEFLOW/COUNTRY.list without editing config.yaml — safe
# to run alongside another process using the same config.yaml. YEAR accepts
# a comma-separated list (e.g. "2019,2021"), looping each year in turn.
EXIOBASE_YEAR=2019,2021 EXIOBASE_COUNTRY_LIST=default python main.py

# Also persist the resolved settings back to config.yaml, once, before
# any processing starts
python main.py --saveconfig

# Also run bea/main.py (interstate/BEA data) right after each year's trade
# data finishes — checks BEA_API_KEY exists before starting anything
python main.py --interstate US

# Update current country manually
python update_current_country.py CN
```

## Processing Pipeline (CSV Generation Order)

The scripts are run in this specific order to ensure proper data dependencies:

### 0. **exiobase_download.py** - Guided Exiobase Year File Download

Run this first, on its own, before `main.py` or `trade.py`:

```bash
python3 exiobase_download.py            # uses YEAR from config.yaml
python3 exiobase_download.py --year 2021
```

`trade.py` calls the same `ensure_exiobase_file()` automatically and silently
as part of its own run, but a multi-GB download with no visible starting
point is easy to mistake for a hang — running this script by itself first
makes the download an explicit, visible step with progress reporting.

It checks `exiobase_data/IOT_{year}_pxp.zip` first and does nothing if that
file already exists. Otherwise it downloads Exiobase v3 (product-by-product,
roughly 0.2-4 GB, depending on year) from Zenodo (https://doi.org/10.5281/zenodo.3583070), trying
`pymrio.download_exiobase3()` first, then falling back to a direct Zenodo API
download (pymrio's URL regex no longer matches Zenodo's current API format),
then falling back to the prior year if the requested year isn't published yet
and no download for that prior year already exists locally. The file lands in
`exiobase/tradeflow/exiobase_data/` (gitignored — never deployed).

### 1. **trade.py** - Primary Data Extraction and Processing
- **Input**: Exiobase Z-matrix (inter-industry flows) and F-matrices (environmental extensions)
- **Output**: 
  - `trade.csv` - Core trade flows, full Exiobase industry detail (trade_id, region1, region2, industry1, industry2, amount) — no `year` column; one database per year makes it redundant. Never had a separate Sector-level primary tier — trade/trade_factor were never the file-size problem (see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md)'s revision note).
  - `industry.csv` - Raw Exiobase industry mapping with 5-character codes (~200 rows)
  - `sector.csv` / `sector_industry.csv` - BEA Sector classification (~21 categories) and its many-to-many join to `industry.csv`, used by `interstate.csv`'s Sector-level aggregation — see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md)
  - `factor.csv` - Environmental factor definitions (721 factors)
  - `trade_factor.csv` - Environmental coefficients (aggregated flows — ~10 per industry, not a top-N slice; see below)
  - `trade_factor_lg.csv` - All environmental coefficients (721 factors for domestic flows)
- **Purpose**: Primary script that extracts trade flows and creates environmental impact coefficients
- **Key Features**: 
  - Handles imports, exports, and domestic flows based on config
  - Creates both small (aggregated flows) and large (721 raw factors) coefficient files
  - For domestic flows, extracts intra-country flows (country→same country)
- **Processing time**: \~2-3 minutes per country

### 2. **trade_impact.py** - Aggregated Environmental Impacts
- **Input**: `trade.csv` + `trade_factor_lg.csv` (domestic) or `trade_factor.csv` (others)
- **Output**: `trade_impact.csv`
- **Purpose**: Comprehensive environmental impact summary per trade transaction
- **Processing time**: \~10-15 seconds per country

### 3. **trade_resource.py** - Specialized Resource Analysis
- **Input**: `trade_factor_lg.csv` or `trade_factor.csv`
- **Output**: 
  - `trade_employment.csv` - Employment impact analysis
  - `trade_resource.csv` - Resource use analysis (water, energy, land)
  - `trade_material.csv` - Material flow analysis
- **Purpose**: Creates three specialized output files optimized for size and processing performance
- **Processing time**: \~5-15 seconds per country


### Running Scripts

#### Individual Script Execution:

Run main.py to invove the following:

```bash
# Create a virtual environment (commands above)
# Run to invoke all 3 scripts
python main.py

# Or run scripts in order
python trade.py # Creates trade.csv, trade_factor.csv, industry.csv, factor.csv
python trade_impact.py
python trade_resource.py
```

## Configuration Management

### Country List Handling
- **Explicit list**: `COUNTRY: {list: "CN,DE,JP", current: "CN"}`
- **All countries**: `COUNTRY: {list: "all"}` - Auto-discovers existing country folders
- **Default set**: `COUNTRY: {list: "default"}` - Uses predefined 12-country set
- **Auto-population**: Missing `current` field automatically populated during processing
- **Auto-cleanup**: `current` field automatically removed when batch processing completes

### Trade Flow Types
- **imports**: Flows TO the country (from other countries)
- **exports**: Flows FROM the country (to other countries)  
- **domestic**: Flows WITHIN the country (intra-country only)

### File Selection Logic
- **Domestic flows**: Automatically uses `trade_factor_lg.csv` (all 721 factors) if available
- **Import/Export flows**: Uses `trade_factor.csv` (aggregated flows, ~10 per industry) for performance
- **Smart fallback**: If `_lg` version doesn't exist, falls back to standard version

## Data Processing Patterns

### Exiobase Data Structure
- **Regions**: 44 countries + 5 rest-of-world regions (AT, BE, CN, US, etc.)
- **Industries**: 163 detailed sectors aggregated to \~200 standardized codes
- **Extensions**: Air emissions, employment, energy, land use, materials, water, etc.

### Trade Factors Strategy: Two-File System

The project uses a dual-file approach to balance comprehensive environmental coverage with processing performance:

#### **trade_factor.csv** (Small File - Aggregated Flows)
- **Used for**: Imports and Exports (international trade flows)
- **Size**: ~50MB, manageable for all processing scripts
- **Factor Selection**: Not a top-N-by-magnitude slice — raw stressors are aggregated (summed) into a small,
  fixed set of flows per industry, mirroring EPA USEEIO's own `import_emission_factors` methodology:
  5 curated GHG flows for `air_emissions` (Carbon dioxide, Methane, Nitrous oxide, Sulfur hexafluoride,
  HFCs and PFCs unspecified — EPA's own mapping, copied verbatim), plus one flow per other
  extension (employment, energy, land, material, water) scoped to match the corresponding USEEIO
  indicator's coverage (see `exiobase_factors.py`'s `EXTENSION_STRESSOR_PREFIXES`). Up to 10 rows
  per industry rather than up to 120/721.
- **Rationale**: International trade volumes are massive - using all 721 raw factors would create files >1.5GB;
  aggregating to a small flow set also matches EPA's published import-factor product for GHGs.
- **Performance**: Fast processing, no memory issues
- **Coverage**: GHG-complete for air_emissions; the other five extensions are single scoped flows matching
  USEEIO indicator coverage (Jobs Supported, Energy Use, Land Use, Minerals and Metals Use, Water Use), but
  computed from Exiobase, not USEEIO's own government-inventory sources. These five won't numerically match
  either the older EPA repo's or cornerstone-data's published values — USEEIO computes them from separate US
  government data (BLS for jobs, EIA for energy, USDA for land, USGS for water and minerals), not from
  Exiobase — so this is a scope match only, not a value match. See `bea/README.md`'s "Beyond GHGs" section.

#### **trade_factor_lg.csv** (Large File - All 721 raw, unaggregated Factors) 
- **Used for**: Domestic flows (intra-country trade only)
- **Size**: ~1.5GB when created with `-lag` flag in trade.py
- **Factor Coverage**: Complete environmental analysis (all extensions: air, water, land, materials, employment, energy)
- **Rationale**: Domestic trade volumes are smaller, so comprehensive analysis is feasible
- **Warning**: May cause Node.js memory errors in trade_resource.py processing
- **Usage**: Only recommended for thorough domestic environmental analysis

#### **Smart File Selection Logic**
- **config_loader.py** automatically selects the appropriate file:
  - **Domestic flows**: Uses `trade_factor_lg.csv` if available, falls back to `trade_factor.csv`
  - **International flows**: Always uses `trade_factor.csv` for performance
- **Processing scripts** (trade_impact.py, trade_resource.py) detect which file to use based on tradeflow type

## File Path Conventions

- **Exiobase data**: `exiobase_data/IOT_{year}_pxp.zip`
- **Country outputs**: `year/{year}/{country}/{tradeflow}/`
- **Reference files**: `year/{year}/industry.csv`, `year/{year}/factor.csv`
- **Run documentation**: `runnote.md` (overwritten after each full run)

## Progress Tracking System

### Run Notes
- **runnote-inprogress.md**: Created during processing, tracks progress and timing
- **runnote.md**: Final summary created after successful completion, overwrites previous
- **Auto-cleanup**: Progress file deleted after creating final summary

### Key Information Tracked
- Trade factors file used (`trade_factor.csv` vs `trade_factor_lg.csv`)
- Processing timestamps and duration
- File generation summary
- Environmental impact coverage details

## Output Files Structure

### Core Trade Data
- **trade.csv**: `trade_id, region1, region2, industry1, industry2, amount` (full Exiobase industry detail) — no `year` column; one database per year makes it redundant.

### Environmental Impact Data  
- **trade_factor.csv**: Aggregated flows for imports/exports (see EPA import factor reduction in bea/README.md)
- **trade_factor_lg.csv**: All raw, unaggregated factors for domestic flows (721 factors)
- **trade_impact.csv**: Comprehensive impact summary per trade transaction
- **trade_employment.csv**: Employment impact analysis
- **trade_resource.csv**: Resource use analysis (water, energy, land)
- **trade_material.csv**: Material flow analysis

### Reference Files
- **industry.csv**: Sector mapping with standardized 5-character codes
- **factor.csv**: Environmental factor definitions with units and contexts

## Key Libraries

- **pymrio**: Primary library for parsing Exiobase data files
- **pandas**: Data manipulation and transformation
- **numpy**: Numerical computations and coefficient generation
- **pathlib**: Modern file path handling
- **yaml**: Configuration file management

## Performance Optimizations

- **Domestic flows**: All 721 factors (comprehensive analysis feasible)
- **International flows**: aggregated flows, ~10 per industry (performance-optimized)
- **Smart file selection**: Automatic `_lg` vs standard file detection
- **Batch processing**: Multi-level timeout protection with automatic progression
- **Memory management**: Chunked processing for large datasets
- **Resume functionality**: Automatically skips already completed countries

## Timeout Configuration

The system implements a three-tier timeout hierarchy for robust processing management in **main.py** (batch processor):

1. **Script timeout**: 20 minutes (1200 seconds) per individual script
   - Prevents any single script from hanging indefinitely
   - Applies to each of the 3 processing scripts per country: `trade.py`, `trade_impact.py`, `trade_resource.py`
   - Most granular level of timeout protection
   - Implementation: `timeout=1200` in subprocess.run() calls

2. **Country timeout**: 60 minutes (3600 seconds) per country total
   - Limits total processing time for all scripts in a single country
   - Provides real-time countdown: "Country time remaining: X.X minutes"
   - Prevents any country from consuming excessive batch time
   - Implementation: `country_timeout = 3600` in main.py

3. **Batch timeout**: 5 hours (18000 seconds) for entire batch
   - Overall time limit for processing all countries in the list
   - Shows remaining batch time: "Batch time remaining: X.X hours"
   - Most restrictive timeout - will stop processing when reached
   - Implementation: `batch_timeout = 18000` in main.py

**Timeout Priority**: The most restrictive timeout wins. If any timeout is exceeded, processing stops gracefully with clear status reporting and automatic resume capability.

## US BEA Pipeline (`bea/main.py`)

### Purpose
Extends the core Exiobase trade data with US Bureau of Economic Analysis API data to produce
state-level domestic trade flows (`interstate.csv`, `interstate_factor.csv`) and supplementary
BEA-enhanced tables. Also loads the Exiobase satellite M matrix (total — direct + upstream supply chain, via the
Leontief inverse) to add `factor_id` to `interstate_factor.csv`. Using M rather than the
direct-only S matrix matches EPA USEEIO's [import_emission_factors](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors)
methodology — S alone would omit everything embodied in a sector's own inputs.

### Prerequisites (must exist before running)
- `exiobase_data/IOT_{year}_pxp.zip` — Exiobase download (generated by `main.py` or `trade.py`)
- `../../trade-data/year/{year}/US/domestic/trade.csv` — generated by `trade.py` for domestic flow
- `../../trade-data/year/{year}/US/imports/trade.csv` — generated by `trade.py` for imports flow
- `../../trade-data/year/{year}/US/exports/trade.csv` — generated by `trade.py` for exports flow
- `BEA_API_KEY=your_key` (register at https://apps.bea.gov/api/signup/) in a local environment file if present, else `webroot/docker/.env` or `webroot/.env`
- `trade-data/concordance/*.csv` — fetched automatically from [ModelEarth/trade-data](https://github.com/ModelEarth/trade-data/tree/main/concordance) if not already present locally; the run stops with a clear message if a needed file isn't found there either

If the `trade.csv` files don't exist yet, pass `--force-regen` to generate them inline.

### Run command (from `exiobase/tradeflow/`)
```bash
# Uses BEA_API_KEY from a local environment file if present, else webroot/docker/.env or webroot/.env
~/env/bin/python3 bea/main.py

# Force regeneration of trade.csv base files
~/env/bin/python3 bea/main.py --force-regen

# Pass API key explicitly
~/env/bin/python3 bea/main.py --bea-key YOUR_API_KEY
```

**Working directory**: Always run from `exiobase/tradeflow/` (not from `bea/`).
CWD doesn't affect file resolution (all paths use `Path(__file__)`), but it is the established convention.

**Combined with trade processing**: `main.py --interstate US` runs this automatically, once per
year, right after that year's trade data finishes — no separate command needed. The key lookup
(`_load_bea_api_key`) delegates to the shared `bea_key.find_bea_api_key()`, which `main.py` also
calls upfront when `--interstate` is passed, so a missing key is caught before any trade
processing starts rather than after.

### Key outputs
- `year/{year}/US/domestic/interstate.csv`
- `year/{year}/US/domestic/interstate_factor.csv` — includes `factor_id` from Exiobase's M matrix (total multipliers); `coefficient` is not stored (derivable as `level / interstate.amount`)
- `year/{year}/US/domestic/state_industry_impacts.csv`
- `year/{year}/US/bea-report.md`

### factor_id in interstate_factor.csv
The M matrix (total environmental multiplier per unit output — direct plus everything embodied
in a sector's own inputs, via the Leontief inverse) is loaded directly from the Exiobase zip
via pymrio — no intermediate CSVs are read. The default file uses the fixed aggregate factor_ids
(901-910, see exiobase_factors.py) rather than raw per-stressor factor_ids: `air_emissions`
collapses to EPA's own 5-flow GHG list, the other five extensions each collapse to a single
flow scoped to match the corresponding USEEIO indicator's coverage. `interstate_factor_lg.csv` (when `use_partial_factors_interstate: false`)
instead uses every raw per-stressor factor_id (1-721, assigned by row position across extensions
in order: `air_emissions`, `employment`, `energy`, `land`, `material`, `water`, same ordering as
`factor.csv`), filtered by `min_impact_threshold` only, no top-N cap. If the zip is unavailable,
the file falls back to one aggregate row per state-pair with no `factor_id`.

---

## Best Practices

1. **Always run scripts in the specified order** (dependencies matter)
2. **Use batch processing** for multiple countries (main.py)
3. **Check runnote.md** for processing details and file usage
4. **Domestic flows**: Expect longer processing times but comprehensive coverage
5. **International flows**: Optimized for performance with key environmental impacts

## Troubleshooting

### Common Processing Failures

#### **Memory Errors (Critical Issue)**
- **Symptom**: `"FATAL ERROR: v8::ToLocalChecked Empty MaybeLocal"` after ~10 minutes
- **Cause**: `trade_factor_lg.csv` files (~1.5GB) exceed Node.js memory limits
- **Solution**: Use default `python trade.py` (not `python trade.py -lag`)
- **Prevention**: Avoid large factor files for international trade processing

#### **Missing Files**
- **Symptom**: `"⚠️ WARNING: trade_factor.csv not found"`
- **Solution**: Run scripts in correct dependency order: `trade.py` → `trade_impact.py` → `trade_resource.py`
- **Check**: Verify previous script completed successfully without errors

#### **Empty Domestic Flows**
- **Symptom**: No trade flows found for domestic processing
- **Solution**: Check country codes match Exiobase regions exactly (CN, DE, JP, US, etc.)
- **Diagnostic**: Look for flow count messages in script output (>0, >0.001, >0.01)

#### **Timeout Errors**
- **Script timeout**: 20 minutes per individual script
- **Country timeout**: 60 minutes per country total  
- **Batch timeout**: 5 hours for entire batch processing
- **Solution**: Processing automatically resumes and skips completed countries

#### **Performance Issues**
- **International flows**: Use optimized 120-factor selection for performance
- **Domestic flows**: Expect longer processing times with comprehensive 721-factor coverage
- **Chunked processing**: Large datasets processed in 10,000-row chunks to manage memory

#### **Configuration Errors**
- **Country structure**: Verify COUNTRY dict format with proper 'current' field population
- **Auto-resolution**: System handles "all", "default", or explicit country lists automatically
- **File paths**: Ensure base directory structure exists before processing

### Error Recovery Mechanisms

- **Automatic fallbacks**: Scripts use simulated data when Exiobase downloads fail
- **Resume functionality**: Batch processing skips countries with existing `runnote.md`
- **Smart file selection**: Automatically chooses appropriate factor file based on trade flow type
- **Progress tracking**: `runnote-inprogress.md` tracks processing stages for debugging